"""
Infinite Discoverer - Modern Dark-Themed Tkinter GUI Application
Provides full control over multi-instance autonomous discovery cluster,
real-time performance monitoring, instance health tracking, and discovery chronicle.
"""

import os
import sys
import io
import time
import json
import threading
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from typing import Dict, Any, List, Optional, Set

# Guard against NoneType stdout/stderr in Windows PyInstaller --noconsole builds
if sys.stdout is None:
    try:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")
    except Exception:
        sys.stdout = io.StringIO()

if sys.stderr is None:
    try:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")
    except Exception:
        sys.stderr = io.StringIO()

# Ensure project root is on sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from core.engine_wrapper import RecipeEngine
from multi.shared_engine import SharedEngine
from multi.browser_launcher import BrowserLauncher
from multi.instance_worker import InstanceWorker
from multi.memory_optimizer import MemoryOptimizer, MemoryOptimizerDaemon


class ClusterController:
    """
    Manages background execution of the multi-instance discovery cluster
    in a thread-safe manner for the GUI application.
    """

    def __init__(self, config_path: str = "instances_config.json"):
        self.config_path = config_path
        self.raw_config: Dict[str, Any] = {}
        self.shared_engine: Optional[SharedEngine] = None
        self.launcher: Optional[BrowserLauncher] = None
        self.workers: List[InstanceWorker] = []
        self.mem_daemon: Optional[MemoryOptimizerDaemon] = None
        self.is_running = False
        self._thread: Optional[threading.Thread] = None
        self.active_instances_cfg: List[Dict[str, Any]] = []
        self.last_stats: Dict[str, Any] = {}
        self.lock = threading.Lock()
        self.load_config()

    def _resolve_path(self, target_path: str) -> str:
        """Resolves relative file paths against cwd, exe dir, and project base."""
        if os.path.isabs(target_path) and os.path.exists(target_path):
            return target_path

        candidates = [
            os.path.join(os.getcwd(), target_path),
            os.path.join(BASE_DIR, target_path),
        ]
        if getattr(sys, "frozen", False):
            candidates.insert(0, os.path.join(os.path.dirname(sys.executable), target_path))
        if hasattr(sys, "_MEIPASS"):
            candidates.append(os.path.join(sys._MEIPASS, target_path))

        for c in candidates:
            if os.path.exists(c):
                return os.path.abspath(c)
        return os.path.abspath(candidates[0])

    def load_config(self):
        resolved = self._resolve_path(self.config_path)
        if not os.path.exists(resolved):
            raise FileNotFoundError(f"Configuration file not found: {self.config_path}")
        self.config_path = resolved
        with open(resolved, "r", encoding="utf-8") as f:
            self.raw_config = json.load(f)

    def save_config(self):
        with open(self.config_path, "w", encoding="utf-8") as f:
            json.dump(self.raw_config, f, indent=2)

    def start_cluster(
        self,
        instance_ids: Optional[List[str]] = None,
        is_headless: bool = True,
        opt_memory: bool = True,
        auto_trim: bool = True,
        trim_interval: float = 30.0,
        strategy_name: str = "smart",
        concurrency_override: Optional[int] = None,
        batch_size_override: Optional[int] = None,
        max_recipes: Optional[int] = None
    ):
        if self.is_running:
            return

        self.is_running = True
        self._thread = threading.Thread(
            target=self._run_cluster,
            args=(
                instance_ids,
                is_headless,
                opt_memory,
                auto_trim,
                trim_interval,
                strategy_name,
                concurrency_override,
                batch_size_override,
                max_recipes
            ),
            daemon=True
        )
        self._thread.start()

    def _run_cluster(
        self,
        instance_ids: Optional[List[str]],
        is_headless: bool,
        opt_memory: bool,
        auto_trim: bool,
        trim_interval: float,
        strategy_name: str,
        concurrency_override: Optional[int],
        batch_size_override: Optional[int],
        max_recipes: Optional[int]
    ):
        general_cfg = self.raw_config.get("general", {})
        all_instances = self.raw_config.get("instances", [])
        browser_paths = self.raw_config.get("browser_paths", {})

        # Select target instances
        if instance_ids is not None:
            active = [inst for inst in all_instances if inst["id"] in instance_ids]
        else:
            active = [inst for inst in all_instances if inst.get("enabled", True)]

        if not active:
            active = all_instances[:3]

        self.active_instances_cfg = active

        # Apply overrides
        for inst in active:
            if concurrency_override is not None:
                inst["concurrency"] = concurrency_override
            if batch_size_override is not None:
                inst["batch_size"] = batch_size_override

        strat_code = (
            RecipeEngine.STRATEGY_SMART_HEURISTIC
            if strategy_name == "smart"
            else RecipeEngine.STRATEGY_EXHAUSTIVE
        )

        master_cache_path = self._resolve_path(general_cfg.get("master_cache_path", "data/recipes_cache.bin"))
        os.makedirs(os.path.dirname(master_cache_path), exist_ok=True)

        discoveries_dir = self._resolve_path(general_cfg.get("discoveries_dir", "discoveries"))
        os.makedirs(discoveries_dir, exist_ok=True)

        with self.lock:
            # 1. Initialize Shared Engine
            self.shared_engine = SharedEngine(
                cache_path=master_cache_path,
                discoveries_dir=discoveries_dir,
                strategy=strat_code,
                max_depth_delta=general_cfg.get("max_depth_delta", 2),
                catalyst_cap=general_cfg.get("catalyst_cap", 24),
                prune_threshold=general_cfg.get("prune_threshold", 0.04)
            )

            # 2. Initialize Browser Launcher
            self.launcher = BrowserLauncher(
                config_browser_paths=browser_paths,
                default_headless=is_headless,
                optimize_memory=opt_memory,
                block_ads=general_cfg.get("memory_optimization", {}).get("block_ad_networks", True)
            )

            self.workers = []

        # 3. Launch Browsers if enabled
        if general_cfg.get("auto_launch_browsers", True):
            for inst in active:
                if not self.is_running:
                    break
                self.launcher.launch_instance(inst, wait_ready=True)

        if not self.is_running:
            return

        # 4. Start Memory Daemon
        if auto_trim:
            self.mem_daemon = MemoryOptimizerDaemon(
                get_parent_pids_func=self.launcher.get_spawned_pids,
                interval_sec=trim_interval
            )
            self.mem_daemon.start()

        # 5. Start Workers
        with self.lock:
            for inst in active:
                w = InstanceWorker(instance_cfg=inst, shared_engine=self.shared_engine)
                self.workers.append(w)
                w.start()

        # 6. Main Background Maintenance Loop
        save_interval = general_cfg.get("cache_auto_save_interval_sec", 20.0)
        while self.is_running:
            if max_recipes and self.shared_engine and self.shared_engine.session_tested >= max_recipes:
                break
            if self.shared_engine:
                self.shared_engine.save_cache_if_due(interval_sec=save_interval)
            time.sleep(1.0)

        # Cleanup on stop
        self._shutdown()

    def stop_cluster(self):
        self.is_running = False

    def _shutdown(self):
        if self.mem_daemon:
            try:
                self.mem_daemon.stop()
            except Exception:
                pass

        with self.lock:
            for w in self.workers:
                try:
                    w.stop()
                except Exception:
                    pass

            for w in self.workers:
                try:
                    w.join(timeout=1.5)
                except Exception:
                    pass

            if self.raw_config.get("general", {}).get("auto_close_browsers_on_exit", True):
                if self.launcher:
                    try:
                        self.launcher.terminate_all()
                    except Exception:
                        pass

            if self.shared_engine:
                try:
                    self.last_stats = self.shared_engine.get_stats()
                    self.shared_engine.cleanup()
                except Exception:
                    pass

    def trim_ram_now(self) -> Dict[str, Any]:
        if self.launcher:
            return self.launcher.trim_all_memory()
        return {"trimmed_processes": 0, "before_mb": 0.0, "after_mb": 0.0, "saved_mb": 0.0}

    def save_cache_now(self) -> bool:
        if self.shared_engine:
            return self.shared_engine.save_cache()
        return False

    def get_stats(self) -> Dict[str, Any]:
        if self.shared_engine and self.is_running:
            try:
                stats = self.shared_engine.get_stats()
                self.last_stats = stats
                return stats
            except Exception:
                pass
        return self.last_stats or {
            "total_tested_pairs": 0,
            "session_tested": 0,
            "total_elements": 0,
            "session_discoveries": 0,
            "total_first_discoveries": 0,
            "overall_rate": 0.0
        }


class SettingsModal(tk.Toplevel):
    """Configuration dialog for tuning cluster parameters."""

    def __init__(self, parent, current_settings: Dict[str, Any], on_save_callback):
        super().__init__(parent)
        self.title("⚙ Cluster Advanced Settings")
        self.geometry("450x380")
        self.resizable(False, False)
        self.configure(bg="#161b22")
        self.transient(parent)
        self.grab_set()

        self.on_save = on_save_callback
        self.settings = dict(current_settings)

        self._build_ui()

    def _build_ui(self):
        lbl_h = tk.Label(
            self,
            text="Cluster Tuning & Performance",
            font=("Segoe UI", 12, "bold"),
            fg="#58a6ff",
            bg="#161b22"
        )
        lbl_h.pack(pady=(16, 12))

        form = tk.Frame(self, bg="#161b22")
        form.pack(fill="x", padx=24)

        # Concurrency
        self.ent_concurrency = self._add_row(form, 0, "Worker Concurrency:", str(self.settings.get("concurrency", 12)))
        # Batch Size
        self.ent_batch = self._add_row(form, 1, "Batch Size per Instance:", str(self.settings.get("batch_size", 12)))
        # Auto-Trim Interval
        self.ent_trim = self._add_row(form, 2, "RAM Trim Interval (sec):", str(self.settings.get("trim_interval", 30.0)))
        # Max Recipes
        self.ent_max = self._add_row(form, 3, "Max Recipes (0 = unlimited):", str(self.settings.get("max_recipes", 0)))
        # Auto-Save Interval
        self.ent_save = self._add_row(form, 4, "Cache Auto-Save (sec):", str(self.settings.get("save_interval", 20.0)))

        btn_box = tk.Frame(self, bg="#161b22")
        btn_box.pack(pady=24)

        btn_cancel = tk.Button(
            btn_box,
            text="Cancel",
            font=("Segoe UI", 9),
            bg="#21262d",
            fg="#c9d1d9",
            activebackground="#30363d",
            bd=0,
            padx=14,
            pady=5,
            cursor="hand2",
            command=self.destroy
        )
        btn_cancel.pack(side="left", padx=8)

        btn_save = tk.Button(
            btn_box,
            text="Save Settings",
            font=("Segoe UI", 9, "bold"),
            bg="#238636",
            fg="#ffffff",
            activebackground="#2ea043",
            bd=0,
            padx=16,
            pady=5,
            cursor="hand2",
            command=self._on_save
        )
        btn_save.pack(side="left", padx=8)

    def _add_row(self, parent, row_idx: int, label_text: str, default_val: str) -> tk.Entry:
        lbl = tk.Label(parent, text=label_text, font=("Segoe UI", 9), fg="#c9d1d9", bg="#161b22", anchor="w")
        lbl.grid(row=row_idx, column=0, sticky="w", pady=8)

        ent = tk.Entry(
            parent,
            font=("Consolas", 10),
            bg="#0d1117",
            fg="#ffffff",
            insertbackground="#58a6ff",
            bd=1,
            relief="solid",
            width=14
        )
        ent.insert(0, default_val)
        ent.grid(row=row_idx, column=1, sticky="e", pady=8, padx=(16, 0))
        return ent

    def _on_save(self):
        try:
            c = int(self.ent_concurrency.get().strip())
            b = int(self.ent_batch.get().strip())
            t = float(self.ent_trim.get().strip())
            m = int(self.ent_max.get().strip())
            s = float(self.ent_save.get().strip())

            self.settings["concurrency"] = max(1, c)
            self.settings["batch_size"] = max(1, b)
            self.settings["trim_interval"] = max(5.0, t)
            self.settings["max_recipes"] = max(0, m)
            self.settings["save_interval"] = max(5.0, s)

            self.on_save(self.settings)
            self.destroy()
        except ValueError as err:
            messagebox.showerror("Invalid Input", f"Please check all fields have valid numeric values.\n{err}", parent=self)


class InfiniteDiscovererGUI:
    """
    Modern Dark Theme Tkinter GUI for Infinite Craft Multi-Instance Discovery Cluster.
    """

    COLOR_BG = "#0d1117"
    COLOR_CARD = "#161b22"
    COLOR_INPUT = "#21262d"
    COLOR_BORDER = "#30363d"
    COLOR_CYAN = "#58a6ff"
    COLOR_GREEN = "#3fb950"
    COLOR_YELLOW = "#d29922"
    COLOR_RED = "#f85149"
    COLOR_PURPLE = "#bc8cff"
    COLOR_TEXT = "#c9d1d9"
    COLOR_TEXT_BRIGHT = "#ffffff"
    COLOR_TEXT_DIM = "#8b949e"

    def __init__(self, root: tk.Tk, initial_args=None):
        self.root = root
        self.initial_args = initial_args
        self.root.title("🌌 Infinite Discoverer — Multi-Instance Autonomous Cluster v4")
        self.root.geometry("1340x880")
        self.root.minsize(1100, 720)
        self.root.configure(bg=self.COLOR_BG)

        self.controller = ClusterController()
        self.seen_discoveries: Set[Any] = set()

        # Instance enabled state map: {instance_id: bool}
        all_inst = self.controller.raw_config.get("instances", [])
        self.inst_state = {inst["id"]: inst.get("enabled", True) for inst in all_inst}

        # Advanced settings defaults
        gen_cfg = self.controller.raw_config.get("general", {})
        mem_cfg = gen_cfg.get("memory_optimization", {})
        self.settings = {
            "concurrency": 12,
            "batch_size": 12,
            "trim_interval": mem_cfg.get("trim_interval_sec", 30.0),
            "max_recipes": 0,
            "save_interval": gen_cfg.get("cache_auto_save_interval_sec", 20.0)
        }

        # Apply initial arguments from CLI if provided
        if initial_args:
            if getattr(initial_args, "concurrency", None):
                self.settings["concurrency"] = initial_args.concurrency
            if getattr(initial_args, "batch_size", None):
                self.settings["batch_size"] = initial_args.batch_size
            if getattr(initial_args, "trim_interval", None):
                self.settings["trim_interval"] = initial_args.trim_interval
            if getattr(initial_args, "max_recipes", None):
                self.settings["max_recipes"] = initial_args.max_recipes

        self._setup_styles()
        self._build_ui()
        self._apply_initial_args()
        self._start_poll_timer()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _apply_initial_args(self):
        if not self.initial_args:
            return
        if getattr(self.initial_args, "headless", None):
            self.var_headless.set(True)
        elif getattr(self.initial_args, "headed", False):
            self.var_headless.set(False)

        if getattr(self.initial_args, "strategy", None):
            self.var_strategy.set(self.initial_args.strategy)

        if getattr(self.initial_args, "instances", None):
            inst_arg = str(self.initial_args.instances)
            if inst_arg.isdigit():
                self._apply_instance_count_preset(int(inst_arg))
            else:
                target_ids = {x.strip().lower() for x in inst_arg.split(",")}
                for k in self.inst_state:
                    self.inst_state[k] = (k.lower() in target_ids)
                self.var_inst_preset.set("Custom Selection")
                self._populate_instances_table()

    def _setup_styles(self):
        style = ttk.Style()
        style.theme_use("clam")

        style.configure(
            "Treeview",
            background=self.COLOR_CARD,
            foreground=self.COLOR_TEXT,
            fieldbackground=self.COLOR_CARD,
            borderwidth=0,
            font=("Segoe UI", 9),
            rowheight=26
        )
        style.configure(
            "Treeview.Heading",
            background=self.COLOR_INPUT,
            foreground=self.COLOR_TEXT_BRIGHT,
            relief="flat",
            font=("Segoe UI", 9, "bold")
        )
        style.map(
            "Treeview",
            background=[("selected", "#1f6feb")],
            foreground=[("selected", "#ffffff")]
        )
        style.map(
            "Treeview.Heading",
            background=[("active", "#30363d")]
        )

        style.configure(
            "TCombobox",
            background=self.COLOR_INPUT,
            fieldbackground=self.COLOR_INPUT,
            foreground=self.COLOR_TEXT_BRIGHT,
            darkcolor=self.COLOR_BORDER,
            lightcolor=self.COLOR_BORDER,
            arrowcolor=self.COLOR_CYAN
        )

        style.configure(
            "Vertical.TScrollbar",
            background=self.COLOR_INPUT,
            troughcolor=self.COLOR_BG,
            borderwidth=0,
            arrowsize=11
        )

    def _build_ui(self):
        # 1. Top Header & Title Bar
        header_frame = tk.Frame(self.root, bg=self.COLOR_CARD, height=60, bd=1, relief="solid")
        header_frame.pack(fill="x", padx=14, pady=(12, 6))

        title_box = tk.Frame(header_frame, bg=self.COLOR_CARD)
        title_box.pack(side="left", padx=16, pady=10)
        lbl_title = tk.Label(
            title_box,
            text="🌌 INFINITE DISCOVERER",
            font=("Segoe UI", 14, "bold"),
            fg=self.COLOR_CYAN,
            bg=self.COLOR_CARD
        )
        lbl_title.pack(side="left")
        lbl_sub = tk.Label(
            title_box,
            text=" │  Autonomous Discovery Cluster  │  11 Proxy Sessions  │  C DLL Engine",
            font=("Segoe UI", 9),
            fg=self.COLOR_TEXT_DIM,
            bg=self.COLOR_CARD
        )
        lbl_sub.pack(side="left", padx=6)

        # Status Pill Badge
        self.lbl_status_pill = tk.Label(
            header_frame,
            text="● CLUSTER STOPPED",
            font=("Segoe UI", 9, "bold"),
            fg=self.COLOR_TEXT_DIM,
            bg=self.COLOR_INPUT,
            padx=12,
            pady=4,
            relief="flat"
        )
        self.lbl_status_pill.pack(side="right", padx=16, pady=12)

        # 2. Main Control & Configuration Strip
        ctrl_frame = tk.Frame(self.root, bg=self.COLOR_CARD, bd=1, relief="solid")
        ctrl_frame.pack(fill="x", padx=14, pady=6)

        # Buttons (Left)
        btn_box = tk.Frame(ctrl_frame, bg=self.COLOR_CARD)
        btn_box.pack(side="left", padx=12, pady=10)

        self.btn_toggle = tk.Button(
            btn_box,
            text="▶ Start Cluster",
            font=("Segoe UI", 10, "bold"),
            bg=self.COLOR_GREEN,
            fg="#ffffff",
            activebackground="#2ea043",
            activeforeground="#ffffff",
            bd=0,
            padx=16,
            pady=6,
            cursor="hand2",
            command=self._toggle_cluster
        )
        self.btn_toggle.pack(side="left", padx=(0, 6))

        self.btn_trim_ram = tk.Button(
            btn_box,
            text="🧹 Trim RAM Now",
            font=("Segoe UI", 9, "bold"),
            bg="#1f6feb",
            fg="#ffffff",
            activebackground="#388bfd",
            activeforeground="#ffffff",
            bd=0,
            padx=12,
            pady=6,
            cursor="hand2",
            command=self._on_trim_ram
        )
        self.btn_trim_ram.pack(side="left", padx=4)

        self.btn_save_cache = tk.Button(
            btn_box,
            text="💾 Save Cache",
            font=("Segoe UI", 9),
            bg=self.COLOR_INPUT,
            fg=self.COLOR_TEXT,
            activebackground=self.COLOR_BORDER,
            activeforeground="#ffffff",
            bd=0,
            padx=12,
            pady=6,
            cursor="hand2",
            command=self._on_save_cache
        )
        self.btn_save_cache.pack(side="left", padx=4)

        self.btn_settings = tk.Button(
            btn_box,
            text="⚙ Settings",
            font=("Segoe UI", 9),
            bg=self.COLOR_INPUT,
            fg=self.COLOR_TEXT,
            activebackground=self.COLOR_BORDER,
            activeforeground="#ffffff",
            bd=0,
            padx=10,
            pady=6,
            cursor="hand2",
            command=self._open_settings
        )
        self.btn_settings.pack(side="left", padx=4)

        # Options Strip (Right)
        opt_box = tk.Frame(ctrl_frame, bg=self.COLOR_CARD)
        opt_box.pack(side="right", padx=12, pady=10)

        # Instance Presets Combobox
        lbl_inst = tk.Label(opt_box, text="Instances:", font=("Segoe UI", 9), fg=self.COLOR_TEXT_DIM, bg=self.COLOR_CARD)
        lbl_inst.pack(side="left", padx=(6, 4))
        self.var_inst_preset = tk.StringVar(value="All (11)")
        self.cbo_inst = ttk.Combobox(
            opt_box,
            textvariable=self.var_inst_preset,
            values=["All (11)", "First 3", "First 5", "First 8", "First 10", "Custom Selection"],
            state="readonly",
            width=13
        )
        self.cbo_inst.pack(side="left", padx=(0, 10))
        self.cbo_inst.bind("<<ComboboxSelected>>", self._on_instance_preset_selected)

        # Headless Toggle
        self.var_headless = tk.BooleanVar(value=True)
        chk_headless = tk.Checkbutton(
            opt_box,
            text="Headless",
            variable=self.var_headless,
            font=("Segoe UI", 9),
            fg=self.COLOR_TEXT_BRIGHT,
            bg=self.COLOR_CARD,
            selectcolor=self.COLOR_INPUT,
            activebackground=self.COLOR_CARD,
            activeforeground=self.COLOR_TEXT_BRIGHT
        )
        chk_headless.pack(side="left", padx=6)

        # Low-RAM Toggle
        self.var_opt_mem = tk.BooleanVar(value=True)
        chk_opt = tk.Checkbutton(
            opt_box,
            text="Low-RAM",
            variable=self.var_opt_mem,
            font=("Segoe UI", 9),
            fg=self.COLOR_TEXT_BRIGHT,
            bg=self.COLOR_CARD,
            selectcolor=self.COLOR_INPUT,
            activebackground=self.COLOR_CARD,
            activeforeground=self.COLOR_TEXT_BRIGHT
        )
        chk_opt.pack(side="left", padx=6)

        # Auto-Trim RAM Toggle
        self.var_auto_trim = tk.BooleanVar(value=True)
        chk_trim = tk.Checkbutton(
            opt_box,
            text="Auto-Trim",
            variable=self.var_auto_trim,
            font=("Segoe UI", 9),
            fg=self.COLOR_TEXT_BRIGHT,
            bg=self.COLOR_CARD,
            selectcolor=self.COLOR_INPUT,
            activebackground=self.COLOR_CARD,
            activeforeground=self.COLOR_TEXT_BRIGHT
        )
        chk_trim.pack(side="left", padx=6)

        # Strategy Combobox
        lbl_strat = tk.Label(opt_box, text="Strategy:", font=("Segoe UI", 9), fg=self.COLOR_TEXT_DIM, bg=self.COLOR_CARD)
        lbl_strat.pack(side="left", padx=(8, 4))
        self.var_strategy = tk.StringVar(value="smart")
        cbo_strat = ttk.Combobox(
            opt_box,
            textvariable=self.var_strategy,
            values=["smart", "exhaustive"],
            state="readonly",
            width=11
        )
        cbo_strat.pack(side="left", padx=(0, 4))

        # 3. Global Metric Cards Grid
        metrics_container = tk.Frame(self.root, bg=self.COLOR_BG)
        metrics_container.pack(fill="x", padx=14, pady=6)
        metrics_container.columnconfigure((0, 1, 2, 3, 4, 5), weight=1)

        self.card_tested = self._create_metric_card(metrics_container, 0, "🧪 RECIPES TESTED", "0", "+0 session", self.COLOR_CYAN)
        self.card_elements = self._create_metric_card(metrics_container, 1, "🌟 ELEMENTS UNLOCKED", "0", "+0 session", self.COLOR_GREEN)
        self.card_speed = self._create_metric_card(metrics_container, 2, "🚀 COMBINED SPEED", "0.0 req/s", "Avg: 0.0 req/s", self.COLOR_PURPLE)
        self.card_browsers = self._create_metric_card(metrics_container, 3, "💻 BROWSERS ACTIVE", "0/0", "0 connected", self.COLOR_YELLOW)
        self.card_ram = self._create_metric_card(metrics_container, 4, "🧠 PHYSICAL RAM", "0.0 GB Free", "Load: 0%", "#58a6ff")
        self.card_cluster_ram = self._create_metric_card(metrics_container, 5, "🌐 CLUSTER RAM", "0 MB", "0 MB/instance", "#3fb950")

        # 4. Lower Split Panes (Instances Treeview + Live Discoveries Feed)
        paned = tk.PanedWindow(self.root, orient="horizontal", bg=self.COLOR_BG, bd=0, sashwidth=6)
        paned.pack(fill="both", expand=True, padx=14, pady=(6, 10))

        # Left: Instances Treeview Frame
        left_frame = tk.Frame(paned, bg=self.COLOR_CARD, bd=1, relief="solid")
        paned.add(left_frame, minsize=560, stretch="always")

        inst_top_bar = tk.Frame(left_frame, bg=self.COLOR_CARD)
        inst_top_bar.pack(fill="x", padx=10, pady=(8, 4))

        lbl_inst_header = tk.Label(
            inst_top_bar,
            text="💻 CLUSTER INSTANCES MONITOR",
            font=("Segoe UI", 10, "bold"),
            fg=self.COLOR_TEXT_BRIGHT,
            bg=self.COLOR_CARD
        )
        lbl_inst_header.pack(side="left")

        lbl_inst_hint = tk.Label(
            inst_top_bar,
            text="(Double-click row to Toggle ON/OFF)",
            font=("Segoe UI", 8),
            fg=self.COLOR_TEXT_DIM,
            bg=self.COLOR_CARD
        )
        lbl_inst_hint.pack(side="left", padx=8)

        self.lbl_inst_active_count = tk.Label(
            inst_top_bar,
            text="11/11 Enabled",
            font=("Segoe UI", 9, "bold"),
            fg=self.COLOR_GREEN,
            bg=self.COLOR_INPUT,
            padx=8,
            pady=2
        )
        self.lbl_inst_active_count.pack(side="right")

        tree_scroll = ttk.Scrollbar(left_frame, orient="vertical")
        self.tree = ttk.Treeview(
            left_frame,
            columns=("enabled", "name", "port", "ip", "status", "detail", "tested", "new"),
            show="headings",
            yscrollcommand=tree_scroll.set
        )
        tree_scroll.config(command=self.tree.yview)
        tree_scroll.pack(side="right", fill="y", padx=(0, 6), pady=(0, 8))
        self.tree.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=(0, 8))

        self.tree.heading("enabled", text="Active")
        self.tree.heading("name", text="ID & Name")
        self.tree.heading("port", text="Port")
        self.tree.heading("ip", text="Public IP / Proxy")
        self.tree.heading("status", text="Status")
        self.tree.heading("detail", text="Detail")
        self.tree.heading("tested", text="Tested")
        self.tree.heading("new", text="New")

        self.tree.column("enabled", width=55, anchor="center")
        self.tree.column("name", width=140, anchor="w")
        self.tree.column("port", width=55, anchor="center")
        self.tree.column("ip", width=130, anchor="w")
        self.tree.column("status", width=95, anchor="center")
        self.tree.column("detail", width=130, anchor="w")
        self.tree.column("tested", width=90, anchor="e")
        self.tree.column("new", width=55, anchor="center")

        self.tree.bind("<Double-1>", self._on_tree_double_click)
        self.tree.bind("<space>", self._on_tree_double_click)

        # Right: Live Chronicle & Event Logs
        right_frame = tk.Frame(paned, bg=self.COLOR_CARD, bd=1, relief="solid")
        paned.add(right_frame, minsize=460, stretch="always")

        feed_top_bar = tk.Frame(right_frame, bg=self.COLOR_CARD)
        feed_top_bar.pack(fill="x", padx=10, pady=(8, 4))

        lbl_feed_header = tk.Label(
            feed_top_bar,
            text="📜 LIVE DISCOVERIES STREAM",
            font=("Segoe UI", 10, "bold"),
            fg=self.COLOR_YELLOW,
            bg=self.COLOR_CARD
        )
        lbl_feed_header.pack(side="left")

        btn_clear = tk.Button(
            feed_top_bar,
            text="Clear Feed",
            font=("Segoe UI", 8),
            bg=self.COLOR_INPUT,
            fg=self.COLOR_TEXT_DIM,
            activebackground=self.COLOR_BORDER,
            activeforeground="#ffffff",
            bd=0,
            padx=8,
            pady=2,
            cursor="hand2",
            command=self._clear_feed
        )
        btn_clear.pack(side="right")

        self.txt_feed = scrolledtext.ScrolledText(
            right_frame,
            bg="#0d1117",
            fg=self.COLOR_TEXT,
            font=("Consolas", 9),
            bd=0,
            padx=8,
            pady=8,
            wrap="word"
        )
        self.txt_feed.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        # Text styles for live feed
        self.txt_feed.tag_config("timestamp", foreground=self.COLOR_TEXT_DIM)
        self.txt_feed.tag_config("instance", foreground=self.COLOR_CYAN)
        self.txt_feed.tag_config("new_badge", foreground="#3fb950", font=("Consolas", 9, "bold"))
        self.txt_feed.tag_config("first_badge", foreground="#e3b341", font=("Consolas", 9, "bold"))
        self.txt_feed.tag_config("formula", foreground=self.COLOR_TEXT)
        self.txt_feed.tag_config("result", foreground="#ffffff", font=("Consolas", 9, "bold"))
        self.txt_feed.tag_config("banner", foreground=self.COLOR_CYAN, font=("Consolas", 9, "bold"))

        self.txt_feed.insert("end", "✨ Cluster Discovery Stream Ready. Click 'Start Cluster' to begin discovery.\n", "banner")

        # Initial instance list populate
        self._populate_instances_table()

    def _create_metric_card(self, parent, col, title, main_val, sub_val, accent_color):
        card = tk.Frame(parent, bg=self.COLOR_CARD, bd=1, relief="solid")
        card.grid(row=0, column=col, sticky="nsew", padx=4, pady=2)

        lbl_t = tk.Label(card, text=title, font=("Segoe UI", 8, "bold"), fg=self.COLOR_TEXT_DIM, bg=self.COLOR_CARD)
        lbl_t.pack(anchor="w", padx=10, pady=(6, 2))

        lbl_m = tk.Label(card, text=main_val, font=("Segoe UI", 13, "bold"), fg=accent_color, bg=self.COLOR_CARD)
        lbl_m.pack(anchor="w", padx=10, pady=(0, 2))

        lbl_s = tk.Label(card, text=sub_val, font=("Segoe UI", 8), fg=self.COLOR_TEXT_DIM, bg=self.COLOR_CARD)
        lbl_s.pack(anchor="w", padx=10, pady=(0, 6))

        return {"main": lbl_m, "sub": lbl_s}

    def _populate_instances_table(self):
        for item in self.tree.get_children():
            self.tree.delete(item)

        instances = self.controller.raw_config.get("instances", [])
        enabled_count = 0
        for inst in instances:
            iid = inst["id"]
            is_en = self.inst_state.get(iid, True)
            if is_en:
                enabled_count += 1
            act_symbol = "✔ ON" if is_en else "✖ OFF"
            name = inst.get("name", iid)
            port = str(inst.get("port", ""))
            proxy = inst.get("proxy") or "Direct IP"
            status_text = "READY" if is_en else "DISABLED"
            detail_text = "Waiting to start..." if is_en else "Excluded from run"
            self.tree.insert(
                "",
                "end",
                iid=iid,
                values=(act_symbol, name, port, proxy, status_text, detail_text, "0", "+0")
            )

        self.lbl_inst_active_count.config(text=f"{enabled_count}/{len(instances)} Enabled")

    def _on_instance_preset_selected(self, event=None):
        val = self.var_inst_preset.get()
        if val == "All (11)":
            self._apply_instance_count_preset(11)
        elif val == "First 3":
            self._apply_instance_count_preset(3)
        elif val == "First 5":
            self._apply_instance_count_preset(5)
        elif val == "First 8":
            self._apply_instance_count_preset(8)
        elif val == "First 10":
            self._apply_instance_count_preset(10)

    def _apply_instance_count_preset(self, count: int):
        instances = self.controller.raw_config.get("instances", [])
        for idx, inst in enumerate(instances):
            self.inst_state[inst["id"]] = (idx < count)
        self._populate_instances_table()

    def _on_tree_double_click(self, event=None):
        if self.controller.is_running:
            return  # Lock changes while active
        selected = self.tree.selection()
        if not selected:
            return
        iid = selected[0]
        cur = self.inst_state.get(iid, True)
        self.inst_state[iid] = not cur
        self.var_inst_preset.set("Custom Selection")
        self._populate_instances_table()
        # Restore selection
        if self.tree.exists(iid):
            self.tree.selection_set(iid)

    def _open_settings(self):
        SettingsModal(self.root, self.settings, self._on_settings_saved)

    def _on_settings_saved(self, new_settings: Dict[str, Any]):
        self.settings.update(new_settings)
        self._log_banner(
            f"⚙ Settings updated: Concurrency={self.settings['concurrency']}, Batch={self.settings['batch_size']}, "
            f"TrimInterval={self.settings['trim_interval']}s, MaxRecipes={self.settings['max_recipes'] or 'Unlimited'}"
        )

    def _clear_feed(self):
        self.txt_feed.delete("1.0", "end")

    def _toggle_cluster(self):
        if not self.controller.is_running:
            # Gather active instances
            active_ids = [iid for iid, enabled in self.inst_state.items() if enabled]
            if not active_ids:
                messagebox.showwarning("No Instances Enabled", "Please enable at least one instance to start the cluster.")
                return

            self.btn_toggle.config(text="⏹ Stop Cluster", bg=self.COLOR_RED, activebackground="#da3633")
            self.lbl_status_pill.config(text="● RUNNING", fg=self.COLOR_GREEN, bg="#1a3321")
            self.cbo_inst.config(state="disabled")

            max_r = self.settings.get("max_recipes", 0)
            self.controller.start_cluster(
                instance_ids=active_ids,
                is_headless=self.var_headless.get(),
                opt_memory=self.var_opt_mem.get(),
                auto_trim=self.var_auto_trim.get(),
                trim_interval=self.settings.get("trim_interval", 30.0),
                strategy_name=self.var_strategy.get(),
                concurrency_override=self.settings.get("concurrency"),
                batch_size_override=self.settings.get("batch_size"),
                max_recipes=(max_r if max_r > 0 else None)
            )
            self._log_banner(f"🚀 Cluster launched with {len(active_ids)} active instances (Headless={self.var_headless.get()})...")
        else:
            self.btn_toggle.config(text="▶ Start Cluster", bg=self.COLOR_GREEN, activebackground="#2ea043")
            self.lbl_status_pill.config(text="● STOPPING...", fg=self.COLOR_YELLOW, bg="#332a1a")
            self._log_banner("🛑 Stopping cluster and saving final cache to disk...")
            self.controller.stop_cluster()
            self.cbo_inst.config(state="readonly")
            self.root.after(2000, lambda: self.lbl_status_pill.config(text="● STOPPED", fg=self.COLOR_TEXT_DIM, bg=self.COLOR_INPUT))

    def _on_trim_ram(self):
        res = self.controller.trim_ram_now()
        saved = res.get("saved_mb", 0.0)
        before = res.get("before_mb", 0.0)
        after = res.get("after_mb", 0.0)
        self._log_banner(f"🧹 Working Set Trimmed: {before:.0f} MB -> {after:.0f} MB (Freed {saved:.0f} MB Physical RAM)")

    def _on_save_cache(self):
        ok = self.controller.save_cache_now()
        if ok:
            self._log_banner("💾 Recipe cache successfully written to disk.")
        else:
            self._log_banner("⚠️ Cache save not ready or already up to date.")

    def _log_banner(self, text: str):
        t_str = time.strftime("[%H:%M:%S] ")
        self.txt_feed.insert("end", t_str, "timestamp")
        self.txt_feed.insert("end", f"{text}\n", "banner")
        self.txt_feed.see("end")

    def _start_poll_timer(self):
        self._update_metrics()
        self.root.after(300, self._start_poll_timer)

    def _update_metrics(self):
        # 1. Update System RAM & Cluster RAM
        sys_mem = MemoryOptimizer.get_system_memory()
        self.card_ram["main"].config(text=f"{sys_mem['avail_gb']:.1f} GB Free")
        self.card_ram["sub"].config(text=f"Total: {sys_mem['total_gb']:.1f} GB ({sys_mem['load_percent']}% Load)")

        cluster_mb = self.controller.launcher.get_cluster_memory_mb() if (self.controller.launcher and self.controller.is_running) else 0.0
        active_w_count = sum(1 for w in self.controller.workers if w.running)
        self.card_cluster_ram["main"].config(text=f"{cluster_mb:.0f} MB")
        self.card_cluster_ram["sub"].config(text=f"Avg {cluster_mb/max(1, active_w_count):.0f} MB/inst" if active_w_count else "0 MB/inst")

        # 2. Update Engine Metrics
        stats = self.controller.get_stats()
        tested = stats.get("total_tested_pairs", 0)
        s_tested = stats.get("session_tested", 0)
        elements = stats.get("total_elements", 0)
        s_disc = stats.get("session_discoveries", 0)
        speed = sum(w.current_rate for w in self.controller.workers if w.running) if self.controller.is_running else 0.0
        avg_speed = stats.get("overall_rate", 0.0)

        self.card_tested["main"].config(text=f"{tested:,}")
        self.card_tested["sub"].config(text=f"+{s_tested:,} session")

        self.card_elements["main"].config(text=f"{elements:,}")
        self.card_elements["sub"].config(text=f"+{s_disc:,} session")

        self.card_speed["main"].config(text=f"{speed:.1f} req/s")
        self.card_speed["sub"].config(text=f"Avg: {avg_speed:.1f} req/s")

        total_workers = len(self.controller.workers)
        self.card_browsers["main"].config(text=f"{active_w_count}/{total_workers}")
        self.card_browsers["sub"].config(text=f"{active_w_count} active discovering")

        # 3. Stream new discoveries to feed
        if self.controller.shared_engine:
            recent = list(self.controller.shared_engine.recent_discoveries)
            for item in recent:
                key = (item.get("timestamp"), item.get("name"), item.get("recipe_str"))
                if key not in self.seen_discoveries:
                    self.seen_discoveries.add(key)
                    self._render_discovery_item(item)

        # 4. Update Instances Treeview
        if self.controller.workers and self.controller.is_running:
            for w in self.controller.workers:
                snap = w.get_snapshot()
                inst_id = snap["id"]
                if self.tree.exists(inst_id):
                    status_badge = "🟢 ACTIVE" if snap["status"] == "ACTIVE" else snap["status"]
                    tested_str = f"{snap['tested_count']:,} ({snap['current_rate']:.1f}/s)"
                    new_str = f"+{snap['discoveries_count']}"
                    ip_str = snap["public_ip"] or "Pending..."
                    self.tree.item(
                        inst_id,
                        values=(
                            "✔ ON",
                            snap["name"],
                            str(snap["port"]),
                            ip_str,
                            status_badge,
                            snap["status_detail"],
                            tested_str,
                            new_str
                        )
                    )

    def _render_discovery_item(self, item: Dict[str, Any]):
        t_str = f"[{item.get('timestamp', '')}] "
        inst_str = f"[{item.get('instance_id', 'multi')}] "
        badge_text = " ⭐ [FIRST DISCOVERY] " if item.get("discovered") else " ✨ [NEW] "
        badge_tag = "first_badge" if item.get("discovered") else "new_badge"
        formula_str = f"{item.get('recipe_str', '')} => "
        result_str = f"{item.get('emoji', '')} {item.get('name', '')}\n"

        self.txt_feed.insert("end", t_str, "timestamp")
        self.txt_feed.insert("end", inst_str, "instance")
        self.txt_feed.insert("end", badge_text, badge_tag)
        self.txt_feed.insert("end", formula_str, "formula")
        self.txt_feed.insert("end", result_str, "result")
        self.txt_feed.see("end")

    def _on_close(self):
        if self.controller.is_running:
            if messagebox.askyesno("Exit Confirmation", "A multi-instance discovery cluster is currently running.\n\nDo you want to safely stop all browsers and save the master recipe cache?"):
                self.controller.stop_cluster()
                self.root.destroy()
        else:
            self.root.destroy()


def run_gui(initial_args=None):
    root = tk.Tk()
    app = InfiniteDiscovererGUI(root, initial_args=initial_args)
    root.mainloop()


if __name__ == "__main__":
    run_gui()
