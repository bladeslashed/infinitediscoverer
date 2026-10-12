"""
Infinite Discoverer — Standalone GUI Main Entry Point
Supports running directly via `python gui_main.py` or compiled into a standalone `.exe`.
"""

import os
import sys
import io

# Ensure stdout and stderr do not raise AttributeError in PyInstaller --noconsole mode
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

# Add repository root to Python path
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# When launched as a frozen PyInstaller executable, ensure working directory matches
if getattr(sys, "frozen", False):
    exe_dir = os.path.dirname(sys.executable)
    if os.path.exists(os.path.join(exe_dir, "instances_config.json")):
        os.chdir(exe_dir)
    elif hasattr(sys, "_MEIPASS") and os.path.exists(os.path.join(sys._MEIPASS, "instances_config.json")):
        # Running from temp unpack folder or standalone folder
        pass

from multi.gui_app import run_gui

def main():
    run_gui()

if __name__ == "__main__":
    main()
