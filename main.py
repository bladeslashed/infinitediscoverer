import argparse
import sys
import os
import io

# Fix Windows console UTF-8 output
if sys.platform == "win32":
    if hasattr(sys.stdout, 'buffer'):
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', line_buffering=True)
    if hasattr(sys.stderr, 'buffer'):
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace', line_buffering=True)

# Ensure current directory is on python path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.engine_wrapper import RecipeEngine
from core.discovery_runner import DiscoveryRunner
from core.config_manager import ConfigManager

def main():
    parser = argparse.ArgumentParser(
        description="Infinite Craft Hyper-Performance Autonomous Discovery Agent v2 (C Backend + Opera CDP)"
    )
    parser.add_argument(
        "--config",
        type=str,
        default="runner_config.json",
        help="Path to pre-run parameter config file (default: runner_config.json)"
    )
    parser.add_argument(
        "--settings",
        type=str,
        default="settings.json",
        help="Path to persistent remembered settings file (default: settings.json)"
    )
    parser.add_argument(
        "--port", "-p",
        type=int,
        default=None,
        help="Remote debugging port for Opera (default: from runner_config.json or 9223)"
    )
    parser.add_argument(
        "--batch-size", "-b",
        type=int,
        default=None,
        help="Number of recipes to feed per sliding window cycle (default: from runner_config.json)"
    )
    parser.add_argument(
        "--concurrency", "-c",
        type=int,
        default=None,
        help="Continuous concurrent in-flight iframe workers (default: from runner_config.json)"
    )
    parser.add_argument(
        "--delay", "-d",
        type=float,
        default=None,
        help="Delay in seconds between batch cycles (default: from runner_config.json)"
    )
    parser.add_argument(
        "--strategy", "-s",
        type=str,
        default=None,
        choices=["smart", "exhaustive"],
        help="Pairing strategy: 'smart' (heuristic & fertility pruning) or 'exhaustive'"
    )
    parser.add_argument(
        "--prune-threshold",
        type=float,
        default=None,
        help="Fertility threshold under which dual-exhausted pairs are skipped (default: from runner_config.json)"
    )
    parser.add_argument(
        "--max-depth-delta",
        type=int,
        default=None,
        help="Maximum generation depth gap allowed between non-catalyst pairs (default: 2)"
    )
    parser.add_argument(
        "--catalyst-cap",
        type=int,
        default=None,
        help="Number of top catalyst elements prioritized as hubs (default: 24)"
    )
    parser.add_argument(
        "--max-recipes", "-m",
        type=int,
        default=None,
        help="Maximum recipes to test in this session (default: from runner_config.json or unlimited)"
    )
    parser.add_argument(
        "--cache",
        type=str,
        default=None,
        help="Path to persistent binary recipe cache (default: from runner_config.json)"
    )
    parser.add_argument(
        "--discoveries",
        type=str,
        default=None,
        help="Path to directory containing Discoveries.md (default: from runner_config.json)"
    )
    parser.add_argument(
        "--rate-limit-cooldown",
        type=float,
        default=None,
        help="Base cooldown in seconds on Cloudflare Error 1015 (default: 60.0)"
    )
    parser.add_argument(
        "--query-interval-ms",
        type=int,
        default=None,
        help="Minimum inter-query spacing in ms across all workers (default: 300)"
    )

    args = parser.parse_args()

    # Load and merge configuration: defaults -> settings.json -> runner_config.json -> CLI flags
    cfg_mgr = ConfigManager(runner_config_path=args.config, settings_path=args.settings)
    cli_overrides = {
        "port": args.port,
        "batch_size": args.batch_size,
        "concurrency": args.concurrency,
        "delay": args.delay,
        "strategy": args.strategy,
        "prune_threshold": args.prune_threshold,
        "max_depth_delta": args.max_depth_delta,
        "catalyst_cap": args.catalyst_cap,
        "max_recipes": args.max_recipes,
        "cache_path": args.cache,
        "discoveries_dir": args.discoveries,
        "rate_limit_cooldown": args.rate_limit_cooldown,
        "query_interval_ms": args.query_interval_ms
    }
    cfg = cfg_mgr.load_active_config(cli_overrides)

    print("📄 Configuration active:")
    print(f"   • Pre-run parameters loaded from: {args.config}")
    print(f"   • Remembered settings synced to: {args.settings}")
    print(f"   • Workers: {cfg.get('concurrency')} | Batch: {cfg.get('batch_size')} | Delay: {cfg.get('delay')}s | Strategy: {cfg.get('strategy')}")
    print(f"   • Max Depth Delta: {cfg.get('max_depth_delta', 2)} | Catalyst Cap: {cfg.get('catalyst_cap', 24)}")
    print(f"   • Pacing Interval: {cfg.get('query_interval_ms', 300)}ms | Rate Limit Cooldown: {cfg.get('rate_limit_cooldown', 60.0)}s\n")

    strat_code = (
        RecipeEngine.STRATEGY_SMART_HEURISTIC
        if cfg.get("strategy") == "smart"
        else RecipeEngine.STRATEGY_EXHAUSTIVE
    )

    runner = DiscoveryRunner(
        port=cfg.get("port", 9223),
        batch_size=cfg.get("batch_size", 35),
        concurrency=cfg.get("concurrency", 25),
        delay_between_batches=cfg.get("delay", 0.05),
        strategy=strat_code,
        max_depth_delta=cfg.get("max_depth_delta", 2),
        catalyst_cap=cfg.get("catalyst_cap", 24),
        cache_path=cfg.get("cache_path", "data/recipes_cache.bin"),
        discoveries_dir=cfg.get("discoveries_dir", "discoveries"),
        rate_limit_cooldown=cfg.get("rate_limit_cooldown", 60.0),
        query_interval_ms=cfg.get("query_interval_ms", 300)
    )
    runner.engine.set_prune_threshold(cfg.get("prune_threshold", 0.04))

    try:
        runner.setup()
        runner.run(max_recipes=cfg.get("max_recipes"))
    except KeyboardInterrupt:
        print("\nShutdown requested by user.")
    except Exception as e:
        print(f"\n[ERROR] Error during execution: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
