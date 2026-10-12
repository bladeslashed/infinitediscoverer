import os
import sys
import time
import io
from typing import List, Dict, Any, Optional

from multi.memory_optimizer import MemoryOptimizer

# ANSI Color Codes
RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
RED = "\033[31m"
GREEN = "\033[32m"
YELLOW = "\033[33m"
BLUE = "\033[34m"
MAGENTA = "\033[35m"
CYAN = "\033[36m"
WHITE = "\033[37m"
BG_BLUE = "\033[44m"
BG_DARK = "\033[40m"

class CLIDashboard:
    """
    Rich real-time terminal dashboard displaying global discovery statistics,
    per-instance health, IPs, throughput, memory metrics, and a live discovery feed.
    """

    def __init__(self, shared_engine, workers: list, launcher=None, headless: bool = True):
        self.shared_engine = shared_engine
        self.workers = workers
        self.launcher = launcher
        self.headless = headless
        self._last_render = 0.0
        self.flash_message: Optional[str] = None
        self.flash_message_time = 0.0

        # Enable ANSI escape sequences on Windows consoles if needed
        if sys.platform == "win32":
            os.system("")

    def set_flash_message(self, msg: str):
        """Sets a temporary banner message to be displayed at the bottom of the dashboard."""
        self.flash_message = msg
        self.flash_message_time = time.time()

    def _format_time(self, seconds: float) -> str:
        s = int(seconds)
        h, rem = divmod(s, 3600)
        m, sec = divmod(rem, 60)
        return f"{h:02d}:{m:02d}:{sec:02d}"

    def _status_badge(self, status: str, detail: str) -> str:
        st = status.upper()
        if st == "ACTIVE":
            return f"{GREEN}🟢 ACTIVE{RESET} {DIM}({detail}){RESET}"
        elif st == "COOLDOWN":
            return f"{YELLOW}⏳ {detail}{RESET}"
        elif st == "SOLVING_CF":
            return f"{MAGENTA}🛡️ SOLVING CF{RESET}"
        elif st == "SYNCING":
            return f"{CYAN}🔄 SYNCING{RESET}"
        elif st == "RETRYING":
            return f"{YELLOW}⚠️ RETRYING{RESET}"
        elif st in ("CONNECTING", "INITIALIZING"):
            return f"{BLUE}⚙️ {detail}{RESET}"
        elif st == "ERROR":
            return f"{RED}🔴 ERROR{RESET} {DIM}({detail}){RESET}"
        elif st == "IDLE":
            return f"{WHITE}💤 IDLE{RESET}"
        return f"{WHITE}{status}{RESET} {DIM}({detail}){RESET}"

    def render(self):
        """Renders full dashboard frame directly to console."""
        stats = self.shared_engine.get_stats()
        uptime_str = self._format_time(stats["elapsed_sec"])
        total_elements = stats.get("total_elements", 0)
        tested_pairs = stats.get("total_tested_pairs", 0)
        pruned_pairs = stats.get("total_pruned_pairs", 0)
        first_discoveries = stats.get("total_first_discoveries", 0)
        session_tested = stats.get("session_tested", 0)
        session_disc = stats.get("session_discoveries", 0)
        overall_rate = stats.get("overall_rate", 0.0)

        # Calculate combined current rate across active workers
        combined_rate = sum(w.current_rate for w in self.workers if w.running)
        active_count = sum(1 for w in self.workers if w.status == "ACTIVE")
        total_workers = len(self.workers)

        # Memory statistics
        sys_mem = MemoryOptimizer.get_system_memory()
        cluster_mb = self.launcher.get_cluster_memory_mb() if self.launcher else 0.0
        mode_badge = f"{GREEN}[HEADLESS]{RESET}" if self.headless else f"{YELLOW}[GUI]{RESET}"

        # Count occurrences of each public IP
        ip_counts = {}
        for w in self.workers:
            ip = w.public_ip
            if ip and ip not in ("Detecting...", "Direct / Local", "Unknown"):
                ip_counts[ip] = ip_counts.get(ip, 0) + 1

        lines = []

        # Cursor Home (flicker-free redraw)
        lines.append("\033[H")

        # 1. Header Banner
        lines.append(f"{BOLD}{CYAN}══════════════════════════════════════════════════════════════════════════════════════════════{RESET}")
        lines.append(f"{BOLD}{WHITE} 🌌 INFINITE CRAFT MULTI-INSTANCE DISCOVERY AGENT v4 {RESET}{DIM}│ C DLL + CDP │ {mode_badge} {DIM}Opt Mode{RESET}")
        lines.append(f"{BOLD}{CYAN}══════════════════════════════════════════════════════════════════════════════════════════════{RESET}")

        # 2. Global Metric Cards
        lines.append(
            f" ⏱️  {BOLD}Uptime:{RESET} {uptime_str}   "
            f"💻 {BOLD}Browsers:{RESET} {active_count}/{total_workers} active   "
            f"🚀 {BOLD}Combined Speed:{RESET} {BOLD}{GREEN}{combined_rate:.1f}{RESET} req/s   "
            f"💾 {BOLD}Last Save:{RESET} {int(time.time() - self.shared_engine.last_cache_save)}s ago"
        )
        lines.append(
            f" 🧪 {BOLD}Tested Recipes:{RESET} {tested_pairs:,} {DIM}(+{session_tested:,} session){RESET}   "
            f"🌟 {BOLD}Elements:{RESET} {BOLD}{total_elements:,}{RESET} {DIM}(+{session_disc:,} session){RESET}   "
            f"✂️  {BOLD}Pruned:{RESET} {pruned_pairs:,}   "
            f"⭐ {BOLD}Global First:{RESET} {BOLD}{YELLOW}{first_discoveries}{RESET}"
        )
        lines.append(
            f" 🧠 {BOLD}Physical RAM:{RESET} {sys_mem['avail_gb']:.1f} GB Free / {sys_mem['total_gb']:.1f} GB ({sys_mem['load_percent']}% Load)   "
            f"🌐 {BOLD}Cluster RAM:{RESET} {BOLD}{GREEN}{cluster_mb:.0f} MB{RESET} {DIM}(Avg {cluster_mb/max(1, total_workers):.0f} MB/inst){RESET}"
        )
        lines.append(f"{CYAN}──────────────────────────────────────────────────────────────────────────────────────────────{RESET}")

        # 3. Instance Table Header
        lines.append(
            f"{BOLD}{'ID & Name':<24} {'Browser':<10} {'Port':<6} {'Public IP / Proxy':<20} {'Status':<28} {'Tested':<12} {'New':<5}{RESET}"
        )
        lines.append(f"{DIM}──────────────────────────────────────────────────────────────────────────────────────────────{RESET}")

        # 4. Instance Table Rows
        for w in self.workers:
            snap = w.get_snapshot()
            inst_name = f"{snap['name'][:22]}"
            browser_label = snap['browser'].replace('_', ' ').title()[:9]
            port_str = str(snap['port'])
            raw_ip = snap['public_ip']
            if raw_ip and raw_ip not in ("Detecting...", "Direct / Local", "Unknown"):
                if ip_counts.get(raw_ip, 0) > 1:
                    ip_display = f"{YELLOW}{raw_ip[:13]} ⚠️{RESET}"
                else:
                    ip_display = f"{GREEN}{raw_ip[:13]} 🛡️{RESET}"
            else:
                ip_display = f"{DIM}{raw_ip[:15]}{RESET}"

            status_badge = self._status_badge(snap['status'], snap['status_detail'])
            tested_str = f"{snap['tested_count']:,} ({snap['current_rate']:.1f}/s)"
            disc_str = f"+{snap['discoveries_count']}"

            line = f" {inst_name:<23} {browser_label:<10} {port_str:<6} {ip_display:<28} {status_badge}"
            lines.append(line)

        lines.append(f"{CYAN}──────────────────────────────────────────────────────────────────────────────────────────────{RESET}")

        # 5. Live Discovery Chronicle Feed
        lines.append(f"{BOLD}{YELLOW}📜 LIVE DISCOVERIES STREAM (All Sessions):{RESET}")
        recent = list(self.shared_engine.recent_discoveries)[:6]
        if not recent:
            lines.append(f"  {DIM}Listening for new elemental combinations across all browser instances...{RESET}")
        else:
            for item in recent:
                badge = f"{YELLOW}⭐ [FIRST DISCOVERY]{RESET}" if item.get("discovered") else f"{CYAN}✨ [NEW]{RESET}"
                inst_tag = f"{DIM}[{item.get('instance_id', 'multi')}]{RESET}"
                time_tag = f"{DIM}{item.get('timestamp', '')}{RESET}"
                formula = item.get("recipe_str", "")
                result_str = f"{BOLD}{item.get('emoji', '')} {item.get('name', '')}{RESET}"
                lines.append(f"  {time_tag} {inst_tag} {badge} {formula} => {result_str}")

        lines.append(f"{CYAN}══════════════════════════════════════════════════════════════════════════════════════════════{RESET}")

        # 6. Flash Notification Banner
        if self.flash_message and (time.time() - self.flash_message_time < 4.0):
            lines.append(f" {BOLD}{GREEN}⚡ {self.flash_message}{RESET}")
        else:
            lines.append(f" {DIM}Controls: [Q] Quit │ [S] Save Cache │ [M] Trim RAM (Wise Optimizer) │ [R] Redraw{RESET}")

        # Output to console in single atomic write
        output_buffer = "\n".join(lines)
        sys.stdout.write(output_buffer)
        sys.stdout.flush()
