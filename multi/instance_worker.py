import time
import threading
from typing import Dict, Any, Optional, List, Tuple
from collections import deque

from multi.browser_client import BrowserClient
from multi.shared_engine import SharedEngine

class InstanceWorker(threading.Thread):
    """
    Autonomous discovery worker running inside its own thread,
    interfacing with an isolated browser window (Edge or Opera GX) over CDP.
    """

    def __init__(self, instance_cfg: Dict[str, Any], shared_engine: SharedEngine):
        super().__init__(daemon=True, name=f"Worker-{instance_cfg['id']}")
        self.cfg = instance_cfg
        self.id: str = instance_cfg["id"]
        self.name: str = instance_cfg.get("name", self.id)
        self.browser_type: str = instance_cfg.get("browser", "edge")
        self.port: int = int(instance_cfg["port"])
        self.proxy: Optional[str] = instance_cfg.get("proxy")
        self.concurrency: int = int(instance_cfg.get("concurrency", 12))
        self.batch_size: int = int(instance_cfg.get("batch_size", 12))
        self.query_interval_ms: int = int(instance_cfg.get("query_interval_ms", 300))
        self.rate_limit_cooldown: float = float(instance_cfg.get("rate_limit_cooldown", 60.0))

        self.shared_engine = shared_engine
        self.client = BrowserClient(
            port=self.port,
            concurrency=self.concurrency,
            query_interval_ms=self.query_interval_ms,
            proxy=self.proxy
        )

        # Worker status metrics for CLI dashboard
        self.running = False
        self.status = "INITIALIZING"
        self.status_detail = "Starting up..."
        self.public_ip = "Detecting..."
        self.tested_count = 0
        self.discoveries_count = 0
        self.rate_limits_count = 0
        self.consecutive_rate_limits = 0
        self.errors_count = 0
        self.current_rate = 0.0

        # Rate tracking sliding window
        self._history = deque(maxlen=10)
        self._last_sync_time = 0.0

    def get_snapshot(self) -> Dict[str, Any]:
        """Returns instantaneous snapshot of worker state for CLI dashboard."""
        return {
            "id": self.id,
            "name": self.name,
            "browser": self.browser_type,
            "port": self.port,
            "proxy": self.proxy,
            "public_ip": self.public_ip,
            "status": self.status,
            "status_detail": self.status_detail,
            "tested_count": self.tested_count,
            "discoveries_count": self.discoveries_count,
            "rate_limits_count": self.rate_limits_count,
            "current_rate": self.current_rate,
            "errors_count": self.errors_count
        }

    def run(self):
        self.running = True
        
        # 1. Connect to Browser CDP endpoint
        self.status = "CONNECTING"
        self.status_detail = f"Connecting to 127.0.0.1:{self.port}..."
        
        connected = False
        for attempt in range(1, 15):
            if not self.running:
                return
            try:
                self.client.connect()
                connected = True
                break
            except Exception as e:
                self.status_detail = f"Waiting for browser (attempt {attempt}/15)..."
                time.sleep(1.5)

        if not connected:
            self.status = "ERROR"
            self.status_detail = f"Failed to connect on port {self.port}"
            return

        # 2. Detect public IP address via page context
        self.status_detail = "Detecting public IP..."
        self.public_ip = self.client.detect_public_ip()

        # 3. Initial Inventory Synchronization
        self.status = "SYNCING"
        self.status_detail = "Synchronizing initial save state..."
        try:
            browser_inv = self.client.get_browser_inventory()
            missing_items = self.shared_engine.register_instance(self.id, browser_inv)
            if missing_items:
                self.status_detail = f"Injecting {len(missing_items)} missing items..."
                self.client.sync_inventory_bulk(missing_items)
                self.shared_engine.mark_elements_synced(self.id, [m["name"] for m in missing_items])
        except Exception as e:
            self.errors_count += 1

        self.status = "ACTIVE"
        self.status_detail = "Ready to discover"
        self._last_sync_time = time.time()

        # 4. Main Autonomous Loop
        while self.running:
            now = time.time()

            # Periodic cross-browser inventory sync
            if now - self._last_sync_time >= 4.0:
                self._sync_pending_discoveries()
                self._last_sync_time = now

            # Fetch next batch of untested pairs from shared engine
            pairs_batch = self.shared_engine.get_untested_batch(self.id, self.batch_size)
            if not pairs_batch:
                self.status = "IDLE"
                self.status_detail = "Waiting for new combinations..."
                time.sleep(1.0)
                continue

            self.status = "ACTIVE"
            self.status_detail = f"Testing {len(pairs_batch)} pairs"

            query_list = [(p[0]["name"], p[1]["name"]) for p in pairs_batch]
            batch_start = time.time()

            # Execute batch query in browser via persistent iframe pool
            try:
                results = self.client.batch_query_pairs(query_list, timeout=25.0)
            except Exception as e:
                self.errors_count += 1
                self.status = "RETRYING"
                self.status_detail = f"Query error: {e}"
                self.shared_engine.revert_in_flight(self.id, pairs_batch)
                self.client.handle_cloudflare_if_needed()
                time.sleep(2.0)
                continue

            # Check for Cloudflare Rate Limit (Error 1015)
            rate_limited_count = sum(1 for res in results if res and res.get("error") == "rate_limit_1015")
            if rate_limited_count > 0:
                self._handle_rate_limit(pairs_batch, rate_limited_count)
                continue

            # Check for Cloudflare Turnstile Verification
            challenge_count = sum(1 for res in results if res and res.get("error") == "cloudflare_challenge")
            if challenge_count > 0:
                self.status = "SOLVING_CF"
                self.status_detail = "Solving Turnstile challenge..."
                self.shared_engine.revert_in_flight(self.id, pairs_batch)
                self.client.handle_cloudflare_if_needed()
                time.sleep(2.0)
                continue

            # Success: reset consecutive rate limits counter
            self.consecutive_rate_limits = 0

            # Process results into shared engine
            new_discoveries = self.shared_engine.process_results(self.id, pairs_batch, results)
            
            # Update metrics
            batch_size_tested = len(results)
            self.tested_count += batch_size_tested
            if new_discoveries:
                self.discoveries_count += len(new_discoveries)

            duration = time.time() - batch_start
            rate = (batch_size_tested / duration) if duration > 0 else 0.0
            self._history.append((time.time(), batch_size_tested))
            self._calculate_sliding_rate()

            self.status = "ACTIVE"
            self.status_detail = f"Running ({self.current_rate:.1f} req/s)"

        self._shutdown()

    def _sync_pending_discoveries(self):
        """Pulls any new elements found by other instances and syncs them into this browser."""
        try:
            pending = self.shared_engine.get_pending_sync_for_instance(self.id)
            if pending:
                self.client.sync_inventory_bulk(pending)
                self.shared_engine.mark_elements_synced(self.id, [p["name"] for p in pending])
        except Exception:
            pass

    def _calculate_sliding_rate(self):
        """Calculates rolling pairs/second rate over recent cycles."""
        if len(self._history) < 2:
            return
        total_items = sum(count for _, count in self._history)
        time_span = self._history[-1][0] - self._history[0][0]
        if time_span > 0:
            self.current_rate = total_items / time_span

    def _handle_rate_limit(self, pairs_batch: List[Any], count: int):
        """Handles Cloudflare Error 1015 with progressive cooldown on this isolated IP."""
        self.rate_limits_count += 1
        self.consecutive_rate_limits += 1
        self.shared_engine.revert_in_flight(self.id, pairs_batch)

        attempt = self.consecutive_rate_limits
        cooldown = min(self.rate_limit_cooldown * attempt, 300.0)
        self.status = "COOLDOWN"

        start_cd = time.time()
        while time.time() - start_cd < cooldown and self.running:
            rem = int(cooldown - (time.time() - start_cd))
            mins, secs = divmod(rem, 60)
            self.status_detail = f"IP Cooldown [{mins:02d}:{secs:02d}] (Attempt {attempt})"
            time.sleep(1.0)

        if not self.running:
            return

        # Restore browser state
        self.status = "RECONNECTING"
        self.status_detail = "Refreshing clearance session..."
        try:
            self.client.reset_worker_pool()
            self.client.reload_page(wait_sec=3.0)
            self.client.handle_cloudflare_if_needed()

            # Adapt query interval
            current_interval = getattr(self.client, "query_interval_ms", 300)
            new_interval = min(current_interval + 150 * attempt, 900)
            self.client.set_pacing(new_interval)

            # Canary probe
            self.status_detail = "Sending canary probe (Water + Fire)..."
            probe = self.client.probe_query("Water", "Fire", timeout=12.0)
            if probe and probe.get("error") == "rate_limit_1015":
                self.status_detail = "Canary probe blocked; extending cooldown..."
                return
            elif probe and "result" in probe:
                self.consecutive_rate_limits = 0
                self.status = "ACTIVE"
                self.status_detail = "Connection restored!"
        except Exception as e:
            self.status_detail = f"Probe error: {e}"

    def stop(self):
        self.running = False

    def _shutdown(self):
        self.status = "STOPPED"
        self.status_detail = "Terminated gracefully"
        try:
            self.client.close()
        except Exception:
            pass
