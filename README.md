# Infinite Discoverer v3

High-performance autonomous discovery agent for Infinite Craft. Powered by a C computation engine (v3), Chrome DevTools Protocol (CDP) browser automation, heuristic pair pruning, and multi-instance browser clustering.

---

## Features

- High-Yield Pairing: Prioritizes self-combinations, first discoveries, and high-fertility catalyst hubs to minimize wasted queries.
- Multi-Instance Clustering: Runs multiple isolated browser instances simultaneously, supporting independent proxies to avoid Cloudflare rate limits.
- Bi-Directional State Synchronization: Synchronizes newly discovered elements across all active browser windows in real time.
- Desktop GUI and CLI: Includes a dark-mode desktop interface as well as a terminal dashboard.
- Automatic Working-Set Memory Management: Periodically trims browser working-set memory to prevent system exhaustion during long runs.
- High-Speed Dataset Importer: Fast C++ dataset processor for seeding existing recipe databases from CSV or TSV dumps.

---

## Project Structure

```
infinitediscoverer/
├── bridge/
│   └── opera_cdp.py           # Chrome DevTools Protocol WebSocket client
├── c_engine/
│   ├── fast_importer.cpp      # Fast C++ dataset importer source
│   ├── fast_importer.exe      # Compiled dataset importer binary
│   ├── recipe_engine_v3.c     # C recipe engine source (v3)
│   ├── recipe_engine_v3.h     # C recipe engine header
│   └── recipe_engine_v3.dll   # Precompiled x64 Windows DLL
├── core/
│   ├── config_manager.py      # Runtime configuration loader
│   ├── discovery_runner.py    # Single-instance discovery orchestrator
│   └── engine_wrapper.py      # Python ctypes wrapper for C engine
├── discoveries/
│   └── logger.py              # Discovery chronicle markdown logger
├── multi/
│   ├── browser_client.py      # Multi-instance CDP browser client
│   ├── browser_launcher.py    # Browser process manager
│   ├── cli_dashboard.py       # Terminal status dashboard
│   ├── gui_app.py             # Desktop GUI interface
│   ├── instance_worker.py     # Worker thread for each browser instance
│   ├── memory_optimizer.py    # Windows memory trimming utility
│   ├── proxy_forwarder.py     # Proxy credential forwarder
│   ├── setup_profiles.py      # Browser profile generator
│   └── shared_engine.py       # Thread-safe multi-instance coordinator
├── gui_main.py                # Desktop GUI entrypoint
├── import_recipes.py          # Dataset import CLI script
├── instances_config.json      # Multi-instance configuration
├── Launch_GUI.bat             # Windows launcher script
├── main.py                    # Single-instance CLI entrypoint
├── multi_main.py              # Multi-instance CLI entrypoint
├── requirements.txt           # Python dependencies
├── runner_config.json         # Single-instance runner configuration
└── settings.json              # Persistent settings and run statistics
```

---

## Requirements

- Windows 10/11 (64-bit)
- Python 3.10+
- Microsoft Edge, Google Chrome, or Opera / Opera GX
- Optional: MinGW-w64 GCC (only if recompiling the C engine or importer from source)

---

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/bladeslashed/infinitediscoverer.git
   cd infinitediscoverer
   ```

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

The repository includes precompiled x64 binaries for Windows (`c_engine/recipe_engine_v3.dll` and `c_engine/fast_importer.exe`). No compilation is required to run.

---

## How to Run

### Option 1: Desktop GUI

Launch the desktop interface using either:
- Double-clicking `Launch_GUI.bat`
- Or running via Python:
  ```bash
  python gui_main.py
  ```

From the GUI, configure active instances, start or stop the discovery cluster, monitor live telemetry, and manually save cache or trim RAM.

### Option 2: Multi-Instance Cluster (CLI)

Run multiple headless browser sessions in parallel:
```bash
# Run configured instances headless:
python multi_main.py

# Run with visible browser windows:
python multi_main.py --headed

# Run a specific number of instances:
python multi_main.py --instances 3
```

Configure instances, browser executables, and optional proxies in `instances_config.json`. See `instances_config.example.json` for proxy configuration syntax.

### Option 3: Single-Instance Runner

Run against a manually opened browser instance with remote debugging enabled:

1. Launch your browser with remote debugging on port 9223:
   ```powershell
   # Example with Opera:
   opera.exe --remote-debugging-port=9223

   # Example with Edge:
   msedge.exe --remote-debugging-port=9223
   ```

2. Open https://neal.fun/infinite-craft/ in the browser window.

3. Start the discovery runner:
   ```bash
   python main.py
   ```

---

## Dataset Importing

Pre-populate known combinations into your local cache (`data/recipes_cache.bin`):

```bash
# Import a CSV or TSV file:
python import_recipes.py path/to/dataset.csv

# Directly via compiled C++ importer:
./c_engine/fast_importer.exe path/to/dataset.csv --cache data/recipes_cache.bin
```

Supported formats include `A=B=Result`, `A+B=Result`, `A+B=>Result`, and standard delimited columns (comma, tab, semicolon, pipe).

---

## Configuration

### `instances_config.json`
Controls multi-instance cluster behavior:
- `general`: Headless toggle, cache path, strategy, and memory optimization settings.
- `browser_paths`: Paths to browser executables on your system.
- `instances`: List of browser instances with port, user data directory, and optional proxy string (`http://user:pass@host:port` or `null` for direct connection).

### `runner_config.json`
Controls single-instance CLI parameters (`main.py`):
- `port`: Remote debugging port (default: 9223).
- `concurrency`: Number of concurrent workers.
- `batch_size`: Batch size per dispatch cycle.
- `strategy`: Pairing strategy (`smart` or `exhaustive`).
- `rate_limit_cooldown`: Cooldown duration on rate limits.

---

## Compiling from Source (Optional)

If modifying the C/C++ engine files, recompile using MinGW-w64:

```bash
# Recompile C recipe engine DLL:
gcc -O3 -shared -fPIC -o c_engine/recipe_engine_v3.dll c_engine/recipe_engine_v3.c

# Recompile C++ fast importer executable:
g++ -I. -O3 -std=c++17 -o c_engine/fast_importer.exe c_engine/fast_importer.cpp
```

---

## Building Standalone Executable (Optional)

To package the desktop GUI as a standalone Windows executable:
```bash
pip install pyinstaller
pyinstaller InfiniteDiscovererGUI.spec
```
The output will be placed in the `dist/` directory.

---

## License

MIT License. See LICENSE for details.
