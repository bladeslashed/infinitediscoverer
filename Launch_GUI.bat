@echo off
echo Starting Infinite Discoverer GUI...
if exist "%~dp0InfiniteDiscovererGUI.exe" (
    start "" "%~dp0InfiniteDiscovererGUI.exe"
) else if exist "%~dp0dist\InfiniteDiscovererGUI.exe" (
    start "" "%~dp0dist\InfiniteDiscovererGUI.exe"
) else (
    start "" python "%~dp0gui_main.py"
)
exit
