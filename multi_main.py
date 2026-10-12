import os
import sys
import time
import json
import io
import signal
import argparse
from typing import Dict, Any, List, Optional

# Fix Windows console UTF-8 output
if sys.platform == "win32":
    if hasattr(sys.stdout, 'buffer'):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
    if hasattr(sys.stderr, 'buffer'):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)

# Ensure current directory is on python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.engine_wrapper import RecipeEngine
from multi.shared_engine import SharedEngine
from multi.browser_launcher import BrowserLauncher
from multi.instance_worker import InstanceWorker
from multi.cli_dashboard import CLIDashboard
from multi.memory_optimizer import MemoryOptimizer, MemoryOptimizerDaemon

def parse_args():
    parser = argparse.ArgumentParser(
        description="Infinite Craft Multi-Instance Autonomous Discovery Coordinator (Edge + Opera GX)"
    )
    parser.add_argument(
        "--config",
        type=str,
        default="instances_config.json",
        help="Path to multi-instance configuration JSON (default: instances_config.json)"
    )
    parser.add_argument(
        "--instances", "-n",
        type=str,
        default=None,
        help="Active instances: specify a count (e.g. 3, 5, 12) or comma-separated IDs (e.g. 'opera-1,edge-1')"
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        default=None,
        help="Run browser instances in headless mode (zero desktop window overhead)"
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        default=False,
        help="Force browser instances to open visible desktop GUI windows"
    )
    parser.add_argument(
        "--no-launch",
        action="store_true",
        help="Do not spawn browser windows; attach directly to already running browsers on configured ports"
    )
    parser.add_argument(
        "--no-opt-memory",
        action="store_true",
        help="Disable aggressive Chromium per-instance memory optimization flags"
    )
    parser.add_argument(
        "--no-trim",
        action="store_true",
        help="Disable automatic Windows Working Set memory trimmer"
    )
    parser.add_argument(
        "--trim-interval",
        type=float,
        default=None,
        help="Periodic memory trim interval in seconds (default: 30.0s)"
    )
    parser.add_argument(
        "--concurrency", "-c",
        type=int,
        default=None,
        help="Override worker concurrency per browser instance"
    )
    parser.add_argument(
        "--batch-size", "-b",
        type=int,
        default=None,
        help="Override batch size per browser instance"
    )
    parser.add_argument(
        "--strategy", "-s",
        type=str,
        choices=["smart", "exhaustive"],
        default=None,
        help="Pairing strategy: 'smart' (heuristic) or 'exhaustive'"
    )
    parser.add_argument(
        "--max-recipes", "-m",
        type=int,
        default=None,
        help="Maximum recipes to test across all instances before auto-stopping"
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        default=False,
        help="Launch the modern graphical user interface (Tkinter GUI) and disable CLI dashboard"
    )
    return parser.parse_args()

def load_config(config_path: str) -> Dict[str, Any]:
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"Configuration file not found at: {config_path}")
    with open(config_path, "r", encoding="utf-8") as f:
        return json.load(f)

def select_active_instances(all_instances: List[Dict[str, Any]], filter_arg: Optional[str]) -> List[Dict[str, Any]]:
    """Filters which instances to run based on CLI argument or enabled flags."""
    if not filter_arg:
        # Default: all instances marked enabled: true
        active = [inst for inst in all_instances if inst.get("enabled", True)]
        return active if active else all_instances[:3]

    # If argument is an integer count (e.g. "3" or "5")
    if filter_arg.isdigit():
        count = int(filter_arg)
        return all_instances[:count]

    # Comma-separated IDs (e.g. "opera-1,edge-1,edge-2")
    target_ids = {x.strip().lower() for x in filter_arg.split(",")}
    selected = [inst for inst in all_instances if inst["id"].lower() in target_ids]
    if not selected:
        print(f"⚠️ Warning: No instances matched filter '{filter_arg}'. Using first 3 instances.")
        return all_instances[:3]
    return selected

def main():
    args = parse_args()
    if args.gui:
        # Disable CLI dashboard and launch Tkinter GUI
        from multi.gui_app import run_gui
        run_gui(initial_args=args)
        return

    raw_cfg = load_config(args.config)

    general_cfg = raw_cfg.get("general", {})
    all_instances = raw_cfg.get("instances", [])
    browser_paths = raw_cfg.get("browser_paths", {})
    mem_cfg = general_cfg.get("memory_optimization", {})

    active_instances = select_active_instances(all_instances, args.instances)
    if not active_instances:
        print("❌ Error: No instances configured to run. Check instances_config.json.")
        sys.exit(1)

    # Determine headless mode preference
    if args.headed:
        is_headless = False
    elif args.headless:
        is_headless = True
    else:
        is_headless = general_cfg.get("headless", True)

    # Memory optimization configuration
    opt_memory = not args.no_opt_memory and mem_cfg.get("enabled", True)
    block_ads = mem_cfg.get("block_ad_networks", True)
    auto_trim = not args.no_trim and mem_cfg.get("auto_trim_working_set", True)
    trim_interval = args.trim_interval or mem_cfg.get("trim_interval_sec", 30.0)

    # Apply overrides
    for inst in active_instances:
        if args.concurrency is not None:
            inst["concurrency"] = args.concurrency
        if args.batch_size is not None:
            inst["batch_size"] = args.batch_size

    strat_name = args.strategy or general_cfg.get("strategy", "smart")
    strat_code = (
        RecipeEngine.STRATEGY_SMART_HEURISTIC
        if strat_name == "smart"
        else RecipeEngine.STRATEGY_EXHAUSTIVE
    )

    sys_ram = MemoryOptimizer.get_system_memory()
    mode_str = "HEADLESS (Ultra-Low RAM)" if is_headless else "GUI WINDOWS"

    print("==================================================")
    print("🚀 INFINITE CRAFT MULTI-INSTANCE COORDINATOR")
    print(f"   • Active Instances: {len(active_instances)}")
    print(f"   • Browser Mode: {mode_str}")
    print(f"   • Memory Optimizations: {'ENABLED (GPU disabled, adblock, V8 capped)' if opt_memory else 'DISABLED'}")
    print(f"   • Auto Working-Set Trimmer: {'ENABLED (' + str(trim_interval) + 's interval)' if auto_trim else 'DISABLED'}")
    print(f"   • Available System RAM: {sys_ram['avail_gb']:.1f} GB / {sys_ram['total_gb']:.1f} GB ({sys_ram['load_percent']}% Load)")
    for inst in active_instances:
        proxy_info = inst.get('proxy') or 'Direct IP'
        print(f"     - [{inst['id']}] {inst.get('name', '')} ({inst.get('browser')}) on Port {inst['port']} | Proxy: {proxy_info}")
    print(f"   • Strategy: {strat_name.upper()} | Cache: {general_cfg.get('master_cache_path')}")
    print("==================================================\n")

    # 1. Initialize Thread-Safe Shared Engine
    shared_engine = SharedEngine(
        cache_path=general_cfg.get("master_cache_path", "data/recipes_cache.bin"),
        discoveries_dir=general_cfg.get("discoveries_dir", "discoveries"),
        strategy=strat_code,
        max_depth_delta=general_cfg.get("max_depth_delta", 2),
        catalyst_cap=general_cfg.get("catalyst_cap", 24),
        prune_threshold=general_cfg.get("prune_threshold", 0.04)
    )

    launcher = BrowserLauncher(
        config_browser_paths=browser_paths,
        default_headless=is_headless,
        optimize_memory=opt_memory,
        block_ads=block_ads
    )
    workers: List[InstanceWorker] = []
    mem_daemon: Optional[MemoryOptimizerDaemon] = None
    running = True

    # Signal handlers for clean termination
    def handle_signal(sig, frame):
        nonlocal running
        running = False

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    try:
        # 2. Launch Browser Windows (if auto_launch is enabled)
        should_launch = general_cfg.get("auto_launch_browsers", True) and not args.no_launch
        if should_launch:
            print("🌐 Spawning isolated browser profiles...")
            for inst in active_instances:
                port = inst["port"]
                b_name = inst.get("browser", "edge")
                print(f"   Launching {inst.get('name')} ({b_name}) on port {port}...")
                ok = launcher.launch_instance(inst, wait_ready=True)
                if ok:
                    print(f"   ✅ {inst['id']} ready on port {port}.")
                else:
                    print(f"   ⚠️ {inst['id']} browser did not respond in time on port {port}. Will attempt attachment.")

        # 3. Start Background Memory Optimizer Daemon
        if auto_trim:
            mem_daemon = MemoryOptimizerDaemon(
                get_parent_pids_func=launcher.get_spawned_pids,
                interval_sec=trim_interval
            )
            mem_daemon.start()

        # 4. Spawn Worker Threads
        print("\n🧵 Starting worker threads...")
        for inst in active_instances:
            w = InstanceWorker(instance_cfg=inst, shared_engine=shared_engine)
            workers.append(w)
            w.start()

        time.sleep(1.0)

        # 5. Initialize and Run Live CLI Dashboard
        dashboard = CLIDashboard(
            shared_engine=shared_engine,
            workers=workers,
            launcher=launcher,
            headless=is_headless
        )
        refresh_sec = general_cfg.get("dashboard_refresh_interval_sec", 0.4)
        save_interval = general_cfg.get("cache_auto_save_interval_sec", 20.0)

        has_msvcrt = (sys.platform == "win32")
        if has_msvcrt:
            import msvcrt

        while running:
            dashboard.render()

            # Interactive keyboard commands
            if has_msvcrt and msvcrt.kbhit():
                try:
                    ch = msvcrt.getch().decode('utf-8', errors='ignore').lower()
                    if ch == 'q':
                        running = False
                        break
                    elif ch == 's':
                        shared_engine.save_cache()
                        dashboard.set_flash_message("Cache manually saved to disk!")
                    elif ch == 'm':
                        res = launcher.trim_all_memory()
                        dashboard.set_flash_message(
                            f"RAM Trimmed: {res['before_mb']:.0f} MB -> {res['after_mb']:.0f} MB (Freed {res['saved_mb']:.0f} MB physical RAM)"
                        )
                    elif ch == 'r':
                        os.system('cls' if os.name == 'nt' else 'clear')
                except Exception:
                    pass

            # Check max recipes limit
            if args.max_recipes and shared_engine.session_tested >= args.max_recipes:
                break

            # Auto-save cache
            shared_engine.save_cache_if_due(interval_sec=save_interval)

            time.sleep(refresh_sec)

    except KeyboardInterrupt:
        pass
    finally:
        print("\n\n🛑 Shutting down multi-instance discovery cluster...")
        # Stop background memory daemon
        if mem_daemon:
            mem_daemon.stop()

        # Stop all workers
        for w in workers:
            w.stop()
        for w in workers:
            w.join(timeout=2.0)

        # Terminate spawned browser windows and all child process trees
        if general_cfg.get("auto_close_browsers_on_exit", True):
            launcher.terminate_all()

        # Save cache
        print("💾 Saving final cache...")
        shared_engine.cleanup()

        stats = shared_engine.get_stats()
        print("\n==================================================")
        print("🏁 MULTI-INSTANCE SESSION COMPLETED")
        print(f"   • Total Tested: {stats['total_tested_pairs']} (+{stats['session_tested']} session)")
        print(f"   • Unlocked Elements: {stats['total_elements']} (+{stats['session_discoveries']} session)")
        print(f"   • Session Discoveries: +{stats['session_discoveries']}")
        print(f"   • Global First Discoveries: {stats['total_first_discoveries']}")
        print(f"   • Average Throughput: {stats['overall_rate']:.1f} req/s")
        print("==================================================\n")

if __name__ == "__main__":
    main()
