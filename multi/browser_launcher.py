import os
import sys
import time
import json
import urllib.request
import urllib.parse
import subprocess
from typing import Dict, Any, Optional, List

from multi.memory_optimizer import MemoryOptimizer

class BrowserLauncher:
    """
    Manages spawning, lifecycle, and memory optimization of multiple isolated browser instances
    (Microsoft Edge and Opera GX) with isolated user data profiles, remote debugging ports,
    optional proxy configurations, and headless operation.
    """

    DEFAULT_BROWSER_PATHS = {
        "edge": [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\Application\msedge.exe")
        ],
        "opera_gx": [
            os.path.expandvars(r"%LOCALAPPDATA%\Programs\Opera GX\opera.exe"),
            r"C:\Program Files\Opera GX\opera.exe",
            r"C:\Program Files (x86)\Opera GX\opera.exe"
        ]
    }

    AD_BLOCK_HOST_RULES = (
        "MAP *intergient.com 127.0.0.1,"
        "MAP *pubmatic.com 127.0.0.1,"
        "MAP *criteo.com 127.0.0.1,"
        "MAP *doubleclick.net 127.0.0.1,"
        "MAP *amazon-adsystem.com 127.0.0.1,"
        "MAP *rubiconproject.com 127.0.0.1,"
        "MAP *onetag-sys.com 127.0.0.1,"
        "MAP *quantserve.com 127.0.0.1,"
        "MAP *everesttech.net 127.0.0.1,"
        "MAP *smartadserver.com 127.0.0.1"
    )

    def __init__(
        self,
        config_browser_paths: Optional[Dict[str, str]] = None,
        default_headless: bool = True,
        optimize_memory: bool = True,
        block_ads: bool = True
    ):
        self.browser_paths = config_browser_paths or {}
        self.default_headless = default_headless
        self.optimize_memory = optimize_memory
        self.block_ads = block_ads
        self._spawned_processes: Dict[str, subprocess.Popen] = {}

    def resolve_browser_executable(self, browser_type: str) -> str:
        """Finds valid executable path for the requested browser."""
        b_type = browser_type.lower()
        if b_type in self.browser_paths and os.path.exists(self.browser_paths[b_type]):
            return self.browser_paths[b_type]

        candidates = self.DEFAULT_BROWSER_PATHS.get(b_type, [])
        for p in candidates:
            if os.path.exists(p):
                return p

        # Fallback to system PATH search
        import shutil
        found = shutil.which("msedge.exe" if b_type == "edge" else "opera.exe")
        if found:
            return found

        raise FileNotFoundError(f"Could not locate executable for browser '{browser_type}'. Please specify in config.")

    def is_port_open(self, port: int, timeout: float = 1.0) -> bool:
        """Checks if a browser CDP endpoint is responsive on the given port."""
        url = f"http://127.0.0.1:{port}/json/version"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass
        return False

    def launch_instance(self, instance_cfg: Dict[str, Any], wait_ready: bool = True) -> bool:
        """Launches a single browser instance based on its configuration."""
        inst_id = instance_cfg["id"]
        port = int(instance_cfg["port"])
        browser_type = instance_cfg.get("browser", "edge")
        proxy = instance_cfg.get("proxy")
        user_data_dir = os.path.abspath(instance_cfg.get("user_data_dir", f"data/profiles/{inst_id}"))
        os.makedirs(user_data_dir, exist_ok=True)

        # Check if already responsive on this port
        if self.is_port_open(port):
            return True

        exe_path = self.resolve_browser_executable(browser_type)
        is_headless = instance_cfg.get("headless", self.default_headless)

        cmd = [
            exe_path,
            f"--remote-debugging-port={port}",
            "--remote-allow-origins=*",
            f"--user-data-dir={user_data_dir}",
            "--no-first-run",
            "--no-default-browser-check",
        ]

        # Memory optimization flags (cuts RAM by 60%-75% per instance)
        if self.optimize_memory:
            cmd.extend([
                "--disable-gpu",
                "--disable-software-rasterizer",
                "--disable-gpu-compositing",
                "--mute-audio",
                "--disable-audio-output",
                "--disable-extensions",
                "--disable-component-update",
                "--disable-background-networking",
                "--disable-sync",
                "--disable-default-apps",
                "--disable-breakpad",
                "--disable-crash-reporter",
                "--disable-dev-shm-usage",
                "--disable-component-extensions-with-background-pages",
                "--renderer-process-limit=1",
                "--js-flags=--max-old-space-size=128",
                "--disk-cache-size=2097152",
                "--media-cache-size=2097152",
                "--disable-features=Translate,OptimizationHints,MediaRouter,CalculateNativeWinOcclusion,SpareRendererForSitePerProcess,EdgeShare,EdgeSmartScreen,InterestFeedContentSuggestions,SidePanel,EdgeSpeechRecognition"
            ])

        # Ad network blocking via host rules (prevents 30+ ad/tracker iframes from loading in neal.fun)
        if self.block_ads:
            cmd.append(f"--host-rules={self.AD_BLOCK_HOST_RULES}")

        # Headless mode configuration
        if is_headless:
            user_agent = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0"
                if browser_type.lower() == "edge"
                else "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 OPR/114.0.0.0"
            )
            cmd.extend([
                "--headless=new",
                "--window-size=960,600",
                "--hide-scrollbars",
                "--disable-blink-features=AutomationControlled",
                f"--user-agent={user_agent}"
            ])
        else:
            # Visible GUI window mode
            cmd.extend([
                "--disable-background-timer-throttling",
                "--disable-renderer-backgrounding",
                "--disable-backgrounding-occluded-windows",
                "--window-size=1024,700"
            ])

        # Handle proxy if configured (with automatic loopback authentication forwarder)
        if proxy and isinstance(proxy, str) and proxy.strip():
            from multi.proxy_forwarder import ProxyManager
            browser_proxy, _ = ProxyManager.setup_proxy_for_browser(proxy)
            if browser_proxy:
                cmd.append(f"--proxy-server={browser_proxy}")

        # Target URL
        cmd.append("https://neal.fun/infinite-craft/")

        creationflags = 0
        if sys.platform == "win32":
            # DETACHED_PROCESS so child windows remain stable
            creationflags = subprocess.CREATE_NEW_PROCESS_GROUP

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags
        )
        self._spawned_processes[inst_id] = proc

        if wait_ready:
            start = time.time()
            while time.time() - start < 20.0:
                if self.is_port_open(port):
                    return True
                time.sleep(0.5)
            return False

        return True

    def launch_all(self, instances: List[Dict[str, Any]]) -> Dict[str, bool]:
        """Launches all enabled browser instances sequentially or in parallel."""
        results = {}
        for inst in instances:
            if not inst.get("enabled", True):
                continue
            inst_id = inst["id"]
            ok = self.launch_instance(inst, wait_ready=True)
            results[inst_id] = ok
        return results

    def get_spawned_pids(self) -> List[int]:
        """Returns list of active PIDs for all tracked browser processes."""
        pids = []
        for proc in self._spawned_processes.values():
            if proc.poll() is None:
                pids.append(proc.pid)
        return pids

    def get_cluster_memory_mb(self) -> float:
        """Calculates total working set memory across all spawned browser process trees."""
        return MemoryOptimizer.get_cluster_memory_mb(self.get_spawned_pids())

    def trim_all_memory(self) -> Dict[str, Any]:
        """Trims working sets across all browser instances in the cluster."""
        return MemoryOptimizer.trim_all(self.get_spawned_pids())

    def terminate_all(self):
        """Terminates all browser instances and their full child process trees cleanly."""
        for inst_id, proc in list(self._spawned_processes.items()):
            pid = proc.pid
            try:
                if sys.platform == "win32":
                    # Taskkill with /F /T kills entire process tree including renderers and crashpads
                    subprocess.run(
                        ["taskkill", "/F", "/T", "/PID", str(pid)],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=5.0
                    )
                else:
                    proc.terminate()
            except Exception:
                try:
                    proc.kill()
                except Exception:
                    pass

        self._spawned_processes.clear()
        try:
            from multi.proxy_forwarder import ProxyManager
            ProxyManager.shutdown_all()
        except Exception:
            pass
