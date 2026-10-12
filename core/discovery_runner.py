import os
import sys
import time
import signal
from typing import Optional, List, Dict, Any

from core.engine_wrapper import RecipeEngine
from bridge.opera_cdp import OperaCDPClient
from discoveries.logger import DiscoveriesLogger

class DiscoveryRunner:
    def __init__(
        self,
        port: int = 9223,
        batch_size: int = 35,
        concurrency: int = 25,
        delay_between_batches: float = 0.05,
        strategy: int = RecipeEngine.STRATEGY_SMART_HEURISTIC,
        max_depth_delta: int = 2,
        catalyst_cap: int = 24,
        cache_path: str = "data/recipes_cache.bin",
        discoveries_dir: str = "discoveries",
        rate_limit_cooldown: float = 60.0,
        query_interval_ms: int = 300
    ):
        self.port = port
        self.batch_size = batch_size
        self.concurrency = concurrency
        self.delay_between_batches = delay_between_batches
        self.strategy = strategy
        self.max_depth_delta = max_depth_delta
        self.catalyst_cap = catalyst_cap
        self.cache_path = os.path.abspath(cache_path)
        self.discoveries_dir = os.path.abspath(discoveries_dir)
        self.rate_limit_cooldown = rate_limit_cooldown
        self.query_interval_ms = query_interval_ms

        self.engine = RecipeEngine()
        self.engine.set_strategy(self.strategy)
        self.engine.set_max_depth_delta(self.max_depth_delta)
        self.engine.set_catalyst_cap(self.catalyst_cap)
        self.client = OperaCDPClient(port=self.port, concurrency=self.concurrency, query_interval_ms=self.query_interval_ms)
        self.logger = DiscoveriesLogger(discoveries_dir=self.discoveries_dir)

        self._running = False
        self._consecutive_errors = 0
        self._consecutive_rate_limits = 0
        self._total_session_discoveries = 0
        self._total_session_tested = 0
        self._start_time = 0.0

    def setup(self):
        """Initializes components, restores state, and synchronizes with Opera."""
        print("==================================================")
        print("🚀 INFINITE CRAFT HYPER-DISCOVERY ENGINE v3")
        print("   • C Backend: Depth-Bounded BFS & Catalyst Hub Topology")
        print(f"   • Static Reusable Iframe Pool ({self.concurrency} workers, zero DOM thrashing)")
        print(f"   • Depth Delta Limit: {self.max_depth_delta} | Catalyst Hub Cap: {self.catalyst_cap}")
        print("==================================================")

        # 1. Load persistent recipe cache if available
        if os.path.exists(self.cache_path):
            print(f"📦 Loading cached recipe graph from: {self.cache_path}")
            if self.engine.load_cache(self.cache_path):
                stats = self.engine.get_stats()
                print(f"   Loaded {stats['total_elements']} elements, {stats['total_tested_pairs']} tested recipes.")
            else:
                print("   ⚠️ Cache file exists but could not be parsed. Starting fresh.")
        else:
            print("📦 No previous recipe cache found. Starting fresh session.")

        # 2. Connect to Opera CDP
        print(f"🌐 Connecting to Opera debug port {self.port}...")
        self.client.connect()
        print("   ✅ Connected to Opera and attached to Infinite Craft.")

        # 3. Synchronize inventory from Opera
        print("🔄 Synchronizing save inventory from browser...")
        inventory = self.client.get_browser_inventory()
        print(f"   Browser has {len(inventory)} unlocked elements.")

        if not inventory and self.engine.get_element_count() == 0:
            initial = [("Water", "💧"), ("Fire", "🔥"), ("Wind", "🌬️"), ("Earth", "🌍")]
            for name, emoji in initial:
                self.engine.add_element(name, emoji, False, 0)
        else:
            for item in inventory:
                name = item.get("text", "")
                emoji = item.get("emoji", "")
                is_first = item.get("discovered", False)
                if name:
                    self.engine.add_element(name, emoji, is_first, 0)

        stats = self.engine.get_stats()
        print(f"📊 Engine active with {stats['total_elements']} elements.")
        print(f"📁 Discoveries log: {self.logger.filepath}")
        print("==================================================\n")

    def run(self, max_recipes: Optional[int] = None):
        """Runs the high-speed autonomous discovery loop."""
        self._running = True
        self._start_time = time.time()
        last_save_time = time.time()

        def sig_handler(sig, frame):
            print("\n🛑 Interrupt received! Gracefully terminating...")
            self._running = False

        signal.signal(signal.SIGINT, sig_handler)
        signal.signal(signal.SIGTERM, sig_handler)

        print(f"⚡ Launching sliding discovery pipeline (Batch: {self.batch_size}, Concurrency: {self.concurrency}).")

        while self._running:
            if max_recipes and self._total_session_tested >= max_recipes:
                print(f"\n🎯 Target of {max_recipes} tested recipes reached.")
                break

            # 1. Fetch next batch of untested pairs from C engine
            pairs_batch = self.engine.get_untested_batch(self.batch_size)
            if not pairs_batch:
                print("\n🏁 All high-priority pairings explored. Waiting 3s for new combinations...")
                time.sleep(3.0)
                continue

            query_list = [(p[0]["name"], p[1]["name"]) for p in pairs_batch]

            # 2. Concurrently stream pairs in sliding window inside Opera browser
            try:
                results = self.client.batch_query_pairs(query_list, timeout=25.0)
                self._consecutive_errors = 0
            except Exception as e:
                print(f"\n⚠️ Query error: {e}")
                self._consecutive_errors += 1
                for el_a, el_b in pairs_batch:
                    self.engine.revert_in_flight(el_a["id"], el_b["id"])

                if self._consecutive_errors >= 2:
                    print("🛡️ Checking Cloudflare security status...")
                    self.client.handle_cloudflare_if_needed()
                    time.sleep(3.0)
                continue

            # Check for Cloudflare rate limit (Error 1015) in responses
            rate_limited_count = sum(1 for res in results if res and res.get("error") == "rate_limit_1015")
            if rate_limited_count > 0:
                self._handle_rate_limit(pairs_batch, rate_limited_count)
                continue

            # Check for Cloudflare Turnstile verification challenge
            challenge_count = sum(1 for res in results if res and res.get("error") == "cloudflare_challenge")
            if challenge_count > 0:
                print("\n🛡️ Cloudflare verification challenge detected. Resolving...")
                for el_a, el_b in pairs_batch:
                    self.engine.revert_in_flight(el_a["id"], el_b["id"])
                self.client.handle_cloudflare_if_needed()
                time.sleep(3.0)
                continue

            # Query succeeded without rate limit: reset consecutive rate limits counter
            self._consecutive_rate_limits = 0

            # 3. Process results
            for idx, res in enumerate(results):
                el_a, el_b = pairs_batch[idx]
                if not res or "error" in res:
                    self.engine.revert_in_flight(el_a["id"], el_b["id"])
                    continue

                self._total_session_tested += 1
                result_name = res.get("result", "").strip()
                result_emoji = res.get("emoji", "")
                is_first_discovery = bool(res.get("isNew", False))

                if not result_name or result_name.lower() == "nothing":
                    self.engine.record_result(el_a["id"], el_b["id"], RecipeEngine.RESULT_NOTHING, False)
                else:
                    existing_id = self.engine.find_element(result_name)
                    if existing_id >= 0:
                        self.engine.record_result(el_a["id"], el_b["id"], existing_id, False)
                    else:
                        # NEW ELEMENT DISCOVERED!
                        new_depth = max(el_a["depth"], el_b["depth"]) + 1
                        new_id = self.engine.add_element(result_name, result_emoji, is_first_discovery, new_depth)
                        self.engine.record_result(el_a["id"], el_b["id"], new_id, True)

                        self._total_session_discoveries += 1

                        stats = self.engine.get_stats()
                        self.logger.log_discovery(
                            result_name=result_name,
                            result_emoji=result_emoji,
                            elem_a=el_a["name"],
                            elem_a_emoji=el_a["emoji"],
                            elem_b=el_b["name"],
                            elem_b_emoji=el_b["emoji"],
                            is_first_discovery=is_first_discovery,
                            total_recipes_tested=stats["total_tested_pairs"]
                        )

                        self.client.sync_new_item(result_name, result_emoji, is_first_discovery, [el_a["id"], el_b["id"]])

                        badge = "\n⭐ [FIRST DISCOVERY]" if is_first_discovery else "\n✨ [NEW]"
                        print(f"{badge} {el_a['emoji']} {el_a['name']} + {el_b['emoji']} {el_b['name']} => {result_emoji} {result_name}")

            # 4. Progress status display
            self._print_status()

            # 5. Periodic auto-save cache
            if time.time() - last_save_time >= 25.0:
                self.engine.save_cache(self.cache_path)
                last_save_time = time.time()

            # 6. Minimal pacing delay
            if self.delay_between_batches > 0:
                time.sleep(self.delay_between_batches)

        self._shutdown()

    def _print_status(self):
        stats = self.engine.get_stats()
        elapsed = time.time() - self._start_time
        rate = (self._total_session_tested / elapsed) if elapsed > 0 else 0.0
        pruned = stats.get("total_pruned_pairs", 0)
        sys.stdout.write(
            f"\r🧪 Tested: {stats['total_tested_pairs']} | ✂️ Pruned: {pruned} | 🌟 Elements: {stats['total_elements']} "
            f"| 🆕 Session: +{self._total_session_discoveries} | 🚀 Rate: {rate:.1f} pairs/s   "
        )
        sys.stdout.flush()

    def _handle_rate_limit(self, pairs_batch: List[Any], rate_limited_count: int):
        self._consecutive_rate_limits += 1
        # 1. Revert in-flight pairs in the engine immediately so no combinations are lost
        for el_a, el_b in pairs_batch:
            self.engine.revert_in_flight(el_a["id"], el_b["id"])

        # 2. Progressive exponential backoff (attempt 1: base_cd, attempt 2: base_cd * 2, max 300s)
        attempt = self._consecutive_rate_limits
        cooldown = min(self.rate_limit_cooldown * attempt, 300.0)

        print(f"\n🛑 Cloudflare Error 1015 (Rate limit) triggered ({rate_limited_count} queries blocked).")
        print(f"   Entering IP cooldown for {int(cooldown)}s to let Cloudflare quota reset (Attempt {attempt})...")

        # 3. Live countdown timer in console
        start_cd = time.time()
        while time.time() - start_cd < cooldown and self._running:
            rem = int(cooldown - (time.time() - start_cd))
            mins, secs = divmod(rem, 60)
            sys.stdout.write(f"\r   ⏳ Cooldown active... [{mins:02d}:{secs:02d} remaining]   ")
            sys.stdout.flush()
            time.sleep(1.0)
        print("\n   🔄 Cooldown complete. Restoring connection to server...")

        if not self._running:
            return

        # 4. Clean up browser state: reset worker pool, reload tab to refresh clearance cookies
        print("   🌐 Reloading Infinite Craft tab in Opera to refresh session cookies...")
        self.client.reset_worker_pool()
        self.client.reload_page(wait_sec=3.0)
        self.client.handle_cloudflare_if_needed()

        # 5. Adaptively increase inter-query spacing
        current_interval = getattr(self.client, "query_interval_ms", 300)
        new_interval = min(current_interval + 150 * attempt, 900)
        self.client.set_pacing(new_interval)
        print(f"   ⏱️ Adapted inter-query spacing to {new_interval}ms to prevent re-trigger.")

        # 6. CANARY PROBE: Send a single lightweight query before resuming full batch processing
        print("   🔍 Dispatching single canary probe (Water + Fire) to test connection...")
        try:
            probe_res = self.client.probe_query("Water", "Fire", timeout=12.0)
            if probe_res and probe_res.get("error") == "rate_limit_1015":
                print("   ⚠️ Canary probe was still blocked by Error 1015. Cloudflare quota not yet clear.")
                # We do NOT blast a batch, preserving IP quota. Next loop will continue cooldown with higher attempt!
                return
            elif probe_res and "result" in probe_res:
                print(f"   ✅ Canary probe SUCCESS: Water + Fire => {probe_res.get('emoji', '')} {probe_res.get('result', '')}!")
                print("   🎉 Connection restored! Resuming discovery pipeline.\n")
                self._consecutive_rate_limits = 0
                return
            elif probe_res and probe_res.get("error") == "cloudflare_challenge":
                print("   🛡️ Cloudflare challenge detected on probe. Attempting to solve...")
                self.client.handle_cloudflare_if_needed()
                return
            else:
                print(f"   ℹ️ Probe response: {probe_res}. Resuming pipeline...")
                self._consecutive_rate_limits = 0
                return
        except Exception as e:
            print(f"   ⚠️ Canary probe error: {e}. Will retry on next cycle.")

    def _shutdown(self):
        print("\n\n💾 Saving recipe cache to disk...")
        self.engine.save_cache(self.cache_path)
        stats = self.engine.get_stats()
        print("==================================================")
        print("🏁 SESSION SUMMARY:")
        print(f"   • Total Elements in Engine: {stats['total_elements']}")
        print(f"   • Total Tested Recipes: {stats['total_tested_pairs']}")
        print(f"   • Total Obsolete Pairs Pruned: {stats.get('total_pruned_pairs', 0)}")
        print(f"   • Global First Discoveries: {stats['total_first_discoveries']}")
        print(f"   • Session New Discoveries: {self._total_session_discoveries}")
        print(f"   • Discoveries Document: {self.logger.filepath}")
        print("==================================================")
        
        try:
            from core.config_manager import ConfigManager
            ConfigManager().update_lifetime_stats(self._total_session_discoveries)
        except Exception:
            pass

        self.client.close()
        self.engine.cleanup()
