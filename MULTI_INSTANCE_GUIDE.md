# 🌐 Infinite Discoverer Multi-Instance Architecture & Setup Guide

This guide explains how the **Multi-Instance Autonomous Discovery Coordinator** (`multi_main.py`) operates, how to configure multiple browser windows with distinct IP addresses to bypass Cloudflare rate limits, and how inventory synchronization works across sessions.

---

## 🏗️ Architecture Overview

```
                               ┌──────────────────────────────────────────────────────────┐
                               │                 SharedEngine (Python + C)                │
                               │  • Thread-Safe Mutex       • Master RecipeEngine (C DLL) │
                               │  • Global Discovery Log    • Cross-Browser Sync Queue    │
                               └─────────────▲──────────────────────────────▲─────────────┘
                                             │                              │
                        ┌────────────────────┴──────────┐        ┌──────────┴────────────────────┐
                        │                               │        │                               │
             ┌──────────▼──────────┐         ┌──────────▼──────────┐  ┌──────────▼──────────┐ ┌──────────▼──────────┐
             │   Worker Thread 1   │         │   Worker Thread 2   │  │   Worker Thread 3   │ │   Worker Thread 4/5 │
             │   Opera GX #1       │         │   Microsoft Edge #1 │  │   Microsoft Edge #2 │ │   Edge / Opera GX   │
             │   Port 9231         │         │   Port 9232         │  │   Port 9233         │ │   Port 9234 / 9235  │
             └──────────┬──────────┘         └──────────┬──────────┘  └──────────┬──────────┘ └──────────┬──────────┘
                        │ CDP                           │ CDP                    │ CDP                   │ CDP
             ┌──────────▼──────────┐         ┌──────────▼──────────┐  ┌──────────▼──────────┐ ┌──────────▼──────────┐
             │ Opera GX Window #1  │         │ Edge Window #1      │  │ Edge Window #2      │ │ Edge / Opera Windows│
             │ data/profiles/opera1│         │ data/profiles/edge1 │  │ data/profiles/edge2 │ │ data/profiles/...   │
             │ IP: 180.252.14.88   │         │ IP: 104.28.21.12    │  │ IP: 45.14.71.190    │ │ IPs: Independent   │
             └─────────────────────┘         └─────────────────────┘  └─────────────────────┘ └─────────────────────┘
```

---

## 🔍 In-Depth: Option 1 vs. Option 2 for IP Address Diversification

### Option 1: Explicit Proxy / VPN Endpoints (`instances_config.json`)
* **How it works**:
  Both Microsoft Edge and Opera GX are built on Chromium. When launched, our `BrowserLauncher` supplies the `--proxy-server="protocol://host:port"` command-line flag to each window.
  - Window 1 can run on direct home connection (`proxy: null`).
  - Window 2 can run through a SOCKS5 proxy from your VPN provider (`socks5://...`).
  - Window 3 can run through a different SOCKS5/HTTP proxy endpoint.
  - Window 4 can run through a local Tor SOCKS5 proxy (`socks5://127.0.0.1:9050`).
* **Advantages**:
  1. **100% Autonomous**: Zero manual clicking required. Every browser automatically starts with its designated IP.
  2. **Infinite Scalability**: Scale to 3, 5, 10, or 20 browsers seamlessly, each mapped to a distinct proxy port.
  3. **Identical Across Browsers**: Works equally on Microsoft Edge and Opera GX.
  4. **Included with Most VPNs**: Major VPNs (NordVPN, Surfshark, PIA, Windscribe, Mullvad) provide SOCKS5 proxy server addresses and credentials across 50+ countries at no additional cost.

---

### Option 2: Opera GX Built-In Free VPN
* **How it works**:
  Opera GX includes a free built-in VPN that routes traffic through Opera's internal proxy infrastructure (Americas, Europe, Asia).
* **Comparison & Limitations**:
  1. **Manual Setup per Profile**: Opera does not expose a standard command-line flag to activate its built-in VPN on a fresh profile. You must open the profile window, go to Settings, and toggle the VPN switch manually once (it persists in `data/profiles/opera_X` afterwards).
  2. **Only 3 Geographic Regions**: Opera's free VPN only offers 3 regions. If you open 5 Opera instances, multiple windows will share the same exit IP and collide on Cloudflare rate limits.
  3. **Heavy Cloudflare Captchas**: Because millions of free users use Opera's free VPN exit nodes, Cloudflare aggressively challenges these IPs with Turnstile and Error 1015 IP rate limits.
  4. **Opera-Only**: Does not work for Microsoft Edge.

---

### 💡 The Hybrid Approach (Supported Out of the Box):
You can mix and match:
- Instance 1 (Opera GX): Direct Home IP
- Instance 2 (Edge): VPN SOCKS5 Endpoint A (or Proxy A)
- Instance 3 (Edge): VPN SOCKS5 Endpoint B (or Proxy B)
- Instance 4 (Edge): Local Tor SOCKS5 or Proxy C
- Instance 5 (Opera GX): Opera GX Built-in VPN toggled on in its profile

The CLI Dashboard automatically detects and displays the **actual public IP** of every window with visual badges:
- `104.28.21.12 🛡️` (Unique IP - safe from shared rate limits)
- `180.252.14.88 ⚠️` (Shared IP - warn if multiple instances share an IP)

---

## 🖥️ Running the Graphical User Interface (Tkinter GUI)

You can run Infinite Discoverer using a modern dark-themed desktop application with full real-time telemetry, 6 live performance metric cards, interactive instance monitor, and discovery chronicle feed.

Whenever the GUI is used, the **CLI dashboard is automatically disabled**, preventing terminal clutter and ANSI redraw sequences.

### 1. Launch via Standalone Windows Executable (.exe)
```powershell
.\dist\InfiniteDiscovererGUI.exe
```
* **No Console Window**: Built with `--noconsole` for a seamless desktop experience.
* **Self-Contained**: Automatically bundles C recipe engine DLLs, Chromium CDP bindings, and configuration fallbacks.

### 2. Launch via Python Script
```powershell
python gui_main.py
```

### 3. Launch via Coordinator Flag (Disables CLI Dashboard)
```powershell
python multi_main.py --gui
```
You can also pass CLI arguments to pre-configure the GUI:
```powershell
# Launch GUI with 5 instances pre-selected in Headless mode:
python multi_main.py --gui -n 5 --headless

# Launch GUI in visible browser mode:
python multi_main.py --gui --headed
```

### 🎛️ GUI Features & Controls:
* **▶ Start / ⏹ Stop Cluster**: One-click cluster execution and graceful shutdown with auto-saving.
* **Instances Selector**: Quick preset dropdown (`All (11)`, `First 3`, `First 5`, `First 8`, `First 10`, `Custom Selection`).
* **Interactive Instance Table**: Double-click any instance row in the table to toggle it `✔ ON` or `✖ OFF`.
* **Headless & Low-RAM Toggles**: Switch between headless and headed mode, enable/disable GPU elimination and ad network blocking.
* **Auto-Trim RAM & Manual Trim**: Win32 working-set trimmer runs automatically every 30 seconds; or click `🧹 Trim RAM Now` to purge memory on demand.
* **💾 Save Cache**: Instantly flush all discoveries and tested pairs to `data/recipes_cache.bin`.
* **⚙ Advanced Settings**: Customize worker concurrency, batch size, trim intervals, auto-save timers, and recipe test limits.
* **📜 Live Discoveries Stream**: Color-coded discovery logs with ⭐ `[FIRST DISCOVERY]` badges, ✨ `[NEW]` badges, timestamps, recipe formulas, and emojis.

---

## 🚀 How to Run the Multi-Instance Coordinator (CLI Mode)

### 1. Launch All Configured Instances in Headless Mode (Recommended for 12+ Sessions)
```powershell
python multi_main.py
```
This runs all enabled instances in **Headless Mode** with full memory optimizations (GPU disabled, ad networks blocked, V8 heap capped, and automatic Windows Working Set trimming enabled).

### 2. Launch with Visible GUI Windows
```powershell
python multi_main.py --headed
```

### 3. Launch with a Custom Number of Instances
```powershell
# Run 3 instances:
python multi_main.py --instances 3

# Run 12 instances in headless mode:
python multi_main.py --instances 12 --headless

# Run specific instances by ID:
python multi_main.py --instances edge-warp,edge-uk,opera-home
```

### 4. Interactive Keyboard Controls
While the CLI dashboard is live:
* **`M`**: Instantly trims physical RAM working set across all browser instances (Wise Memory Optimizer equivalent).
* **`S`**: Forces an immediate manual save of the master recipe cache.
* **`R`**: Clears and redraws the terminal dashboard.
* **`Q`**: Performs a clean shutdown, gracefully terminating all browser processes and saving the cache.

---

## ⚡ Memory Optimization & Headless Mode Architecture

When running 12+ browser instances, standard Chromium instances would consume 5GB–8GB+ of RAM and exhaust system resources. Infinite Discoverer includes a multi-tiered memory optimization suite:

1. **Headless Operation (`--headless=new`)**:
   Zero desktop window rendering buffers and D3D compositing overhead. Masks `HeadlessChrome` in the User-Agent so Cloudflare treats instances as standard desktop browsers.
2. **GPU & Media Elimination**:
   `--disable-gpu`, `--disable-software-rasterizer`, `--mute-audio`, and `--disable-audio-output` eliminate separate Chromium GPU processes (saving ~150MB–250MB RAM per instance).
3. **Renderer & Feature Trimming**:
   `--renderer-process-limit=1` and `--disable-features=SpareRendererForSitePerProcess` stop Chromium from keeping warm spare renderers in RAM.
4. **Ad Network Blocking**:
   Neal.fun injects 30+ third-party ad network iframes (Intergient, PubMatic, Criteo, DoubleClick, Amazon, etc.) per tab. The launcher blocks these domains via `--host-rules`, stopping 360+ heavy ad iframes from loading across 12 instances.
5. **Built-In Working Set Trimmer (Wise Memory Optimizer equivalent)**:
   Via native Win32 API (`psapi.EmptyWorkingSet`), a background daemon automatically trims idle page tables from physical RAM every 30 seconds, bringing per-instance physical RAM footprint down to ~60MB–100MB.

---

## ⚙️ Configuration Reference (`instances_config.json`)

```json
{
  "general": {
    "headless": true,
    "master_cache_path": "data/recipes_cache.bin",
    "discoveries_dir": "discoveries",
    "strategy": "smart",
    "prune_threshold": 0.04,
    "max_depth_delta": 2,
    "catalyst_cap": 24,
    "auto_launch_browsers": true,
    "auto_close_browsers_on_exit": true,
    "auto_sync_interval_sec": 5.0,
    "cache_auto_save_interval_sec": 20.0,
    "dashboard_refresh_interval_sec": 0.4,
    "memory_optimization": {
      "enabled": true,
      "auto_trim_working_set": true,
      "trim_interval_sec": 30.0,
      "disable_gpu": true,
      "block_ad_networks": true,
      "max_v8_heap_mb": 128
    }
  },
  "browser_paths": {
    "edge": "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
    "opera_gx": "C:\\Users\\CHRISTOPHER\\AppData\\Local\\Programs\\Opera GX\\opera.exe"
  },
  "instances": [
    {
      "id": "webshare-uk",
      "name": "Webshare UK (London)",
      "browser": "edge",
      "port": 9231,
      "user_data_dir": "data/profiles/webshare_uk",
      "proxy": "http://zzpjxqgg:2x7vz0icjfh1@45.38.107.97:6014",
      "concurrency": 12,
      "batch_size": 12,
      "query_interval_ms": 300,
      "rate_limit_cooldown": 60.0,
      "enabled": true
    }
  ]
}
```

---

## 🔄 Cross-Browser Inventory Synchronization

1. **Initial Hydration**:
   When each browser connects, the coordinator queries its local Vue state (`window.__vue__.items`). All existing unlocked elements from all browsers are unioned into the master engine. Any items missing from any browser are immediately injected into its DOM in bulk.
2. **Real-Time Cross-Pollination**:
   When Browser A discovers a new element (e.g. `✨ Plasma`):
   - It is added to the master C engine.
   - It is appended to `discoveries/Discoveries.md`.
   - It is pushed to the global sync queue.
   - Within 4 seconds, Worker B, C, D, and E inject `✨ Plasma` directly into their live browser tabs.

---

## 📊 Live CLI Dashboard Controls

While `multi_main.py` is running:
- **`q`**: Gracefully stop all worker threads, save final recipe cache, and exit.
- **`s`**: Force an immediate cache save to disk.
- **`r`**: Force a full screen redraw.
- **`Ctrl+C`**: Standard interrupt trigger for graceful termination.

---

## 📁 Pre-Configured Profile Templates in `data/profiles/`

The system comes with 4 ready-to-run profile templates inside `data/profiles/`:

| Directory | Target Browser | Routing / Network Behavior |
|---|---|---|
| `data/profiles/opera_home` | Opera GX | **Direct Home Connection** (no VPN). |
| `data/profiles/opera_vpn` | Opera GX | **Pre-configured with Opera's built-in Free VPN** (Americas/Europe/Asia). |
| `data/profiles/edge_home` | Microsoft Edge | **Direct Home Connection** (no proxy). |
| `data/profiles/edge_proxy` | Microsoft Edge | **Configured for a local proxy / free VPN** (WARP, SOCKS5, Tor). |

You can regenerate or reset these templates at any time by running:
```powershell
python multi/setup_profiles.py
```

---

## 🛡️ Top Recommended Free VPNs & Proxies for Multi-Instance Scraping

### 1. Cloudflare WARP (1.1.1.1) in Local Proxy Mode *(Top Recommendation)*
* **Why it's the best**: It is operated by Cloudflare directly! Neal.fun uses Cloudflare, so Cloudflare WARP IPs have high trust scores and almost never trigger Captchas.
* **Cost**: 100% Free, Unlimited Bandwidth.
* **How to configure as a per-browser proxy**:
  1. Install [1.1.1.1 for Windows](https://one.one.one.one/).
  2. Open PowerShell and run:
     ```powershell
     warp-cli mode proxy
     warp-cli proxy port 40000
     warp-cli connect
     ```
  3. In `instances_config.json`, set:
     ```json
     "proxy": "socks5://127.0.0.1:40000"
     ```
  *Your whole PC stays on your normal home internet, and only this Edge instance routes through Cloudflare WARP!*

---

### 2. Opera GX Built-in Free VPN *(Instant, Zero Install)*
* **Cost**: 100% Free, Unlimited Bandwidth.
* **Location**: Profile `data/profiles/opera_vpn`.
* **How to adjust region**:
  1. Open Opera GX in this profile:
     ```powershell
     & "C:\Users\CHRISTOPHER\AppData\Local\Programs\Opera GX\opera.exe" --user-data-dir="data/profiles/opera_vpn"
     ```
  2. Click the **VPN badge** to the left of the address bar.
  3. Choose **Americas**, **Europe**, or **Asia**.
  4. The setting is saved permanently in `data/profiles/opera_vpn` for all future automated runs.

---

### 3. Proton VPN Free *(Split Tunneling)*
* **Cost**: 100% Free, Unlimited Bandwidth, Fast speeds.
* **How to isolate to one browser**:
  1. Install [Proton VPN Free](https://protonvpn.com/free-vpn).
  2. Go to **Settings > Advanced > Split Tunneling**.
  3. Turn on Split Tunneling and select **"Only include selected apps"**.
  4. Add `msedge.exe` (located at `C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe`).
  *Now, all Microsoft Edge windows use Proton VPN, while Opera GX uses your home IP!*

---

### 4. Windscribe VPN Free *(Local Proxy Gateway)*
* **Cost**: 10GB / month Free.
* **How to use as a local proxy**:
  1. Install Windscribe for Windows.
  2. Go to **Preferences > Connection > Proxy Gateway**.
  3. Turn on **Proxy Gateway**; it provides a local HTTP proxy address (e.g., `http://127.0.0.1:PORT`).
  4. Put that proxy URL in `instances_config.json`!

---

### 5. Webshare.io Free Permanent Proxies *(10 Free Proxies)*
* **Cost**: 10 permanent proxies free forever (1GB/mo, no credit card required).
* **How**: Sign up at [webshare.io](https://www.webshare.io/), copy your proxy list with credentials, and paste into `instances_config.json`:
  ```json
  "proxy": "http://username:password@proxy.example.com:8080"
  ```

