import os
import sys
import time
import threading
import ctypes
from ctypes import wintypes
from typing import List, Dict, Any, Tuple, Optional

# Win32 API Definitions for Windows
if sys.platform == "win32":
    kernel32 = ctypes.windll.kernel32
    psapi = ctypes.windll.psapi

    TH32CS_SNAPPROCESS = 0x00000002
    PROCESS_QUERY_INFORMATION = 0x0400
    PROCESS_SET_QUOTA = 0x0100
    PROCESS_VM_READ = 0x0010
    PROCESS_TERMINATE = 0x0001

    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [
            ('dwSize', wintypes.DWORD),
            ('cntUsage', wintypes.DWORD),
            ('th32ProcessID', wintypes.DWORD),
            ('th32DefaultHeapID', ctypes.c_size_t),
            ('th32ModuleID', wintypes.DWORD),
            ('cntThreads', wintypes.DWORD),
            ('th32ParentProcessID', wintypes.DWORD),
            ('pcPriClassBase', wintypes.LONG),
            ('dwFlags', wintypes.DWORD),
            ('szExeFile', ctypes.c_char * 260)
        ]

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ('dwLength', wintypes.DWORD),
            ('dwMemoryLoad', wintypes.DWORD),
            ('ullTotalPhys', ctypes.c_ulonglong),
            ('ullAvailPhys', ctypes.c_ulonglong),
            ('ullTotalPageFile', ctypes.c_ulonglong),
            ('ullAvailPageFile', ctypes.c_ulonglong),
            ('ullTotalVirtual', ctypes.c_ulonglong),
            ('ullAvailVirtual', ctypes.c_ulonglong),
            ('sullAvailExtendedVirtual', ctypes.c_ulonglong),
        ]

    class PROCESS_MEMORY_COUNTERS(ctypes.Structure):
        _fields_ = [
            ('cb', wintypes.DWORD),
            ('PageFaultCount', wintypes.DWORD),
            ('PeakWorkingSetSize', ctypes.c_size_t),
            ('WorkingSetSize', ctypes.c_size_t),
            ('QuotaPeakPagedPoolUsage', ctypes.c_size_t),
            ('QuotaPagedPoolUsage', ctypes.c_size_t),
            ('QuotaPeakNonPagedPoolUsage', ctypes.c_size_t),
            ('QuotaNonPagedPoolUsage', ctypes.c_size_t),
            ('PagefileUsage', ctypes.c_size_t),
            ('PeakPagefileUsage', ctypes.c_size_t),
        ]


class MemoryOptimizer:
    """
    High-efficiency memory manager and Windows Working Set trimmer for
    multi-instance browser clusters. Performs the exact memory reduction
    technique used by tools like Wise Memory Optimizer via pure Win32 API.
    """

    @staticmethod
    def get_system_memory() -> Dict[str, float]:
        """Returns total physical RAM, free physical RAM in GB, and memory load percentage."""
        if sys.platform != "win32":
            return {"total_gb": 16.0, "avail_gb": 8.0, "load_percent": 50.0}

        stat = MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        if kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            total_gb = stat.ullTotalPhys / (1024 ** 3)
            avail_gb = stat.ullAvailPhys / (1024 ** 3)
            return {
                "total_gb": round(total_gb, 2),
                "avail_gb": round(avail_gb, 2),
                "load_percent": stat.dwMemoryLoad
            }
        return {"total_gb": 0.0, "avail_gb": 0.0, "load_percent": 0.0}

    @staticmethod
    def get_process_tree(parent_pid: int) -> List[int]:
        """Discovers all descendant PIDs of a given parent process via Toolhelp32."""
        if sys.platform != "win32":
            return [parent_pid]

        h_snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if h_snap == -1:
            return [parent_pid]

        entry = PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32)

        parent_map: Dict[int, List[int]] = {}
        if kernel32.Process32First(h_snap, ctypes.byref(entry)):
            while True:
                pid = entry.th32ProcessID
                ppid = entry.th32ParentProcessID
                if ppid not in parent_map:
                    parent_map[ppid] = []
                parent_map[ppid].append(pid)
                if not kernel32.Process32Next(h_snap, ctypes.byref(entry)):
                    break
        kernel32.CloseHandle(h_snap)

        result: List[int] = []
        queue = [parent_pid]
        while queue:
            curr = queue.pop(0)
            result.append(curr)
            if curr in parent_map:
                queue.extend(parent_map[curr])
        return result

    @staticmethod
    def get_process_memory_mb(pid: int) -> float:
        """Returns physical working set memory of a single process in MB."""
        if sys.platform != "win32":
            return 0.0

        h = kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, pid)
        if not h:
            return 0.0
        try:
            counters = PROCESS_MEMORY_COUNTERS()
            counters.cb = ctypes.sizeof(PROCESS_MEMORY_COUNTERS)
            if psapi.GetProcessMemoryInfo(h, ctypes.byref(counters), counters.cb):
                return counters.WorkingSetSize / (1024 * 1024)
        finally:
            kernel32.CloseHandle(h)
        return 0.0

    @classmethod
    def get_tree_memory_mb(cls, parent_pid: int) -> float:
        """Calculates total working set memory across a process and all its children."""
        pids = cls.get_process_tree(parent_pid)
        return sum(cls.get_process_memory_mb(p) for p in pids)

    @classmethod
    def get_cluster_memory_mb(cls, parent_pids: List[int]) -> float:
        """Calculates total working set memory across all tracked instances."""
        all_pids: List[int] = []
        for p in parent_pids:
            all_pids.extend(cls.get_process_tree(p))
        unique_pids = list(set(all_pids))
        return sum(cls.get_process_memory_mb(p) for p in unique_pids)

    @staticmethod
    def trim_working_set(pid: int) -> bool:
        """
        Empties the working set of a target process, flushing idle and unreferenced pages
        back to disk/standby memory. Equivalent to Wise Memory Optimizer.
        """
        if sys.platform != "win32":
            return False

        h = kernel32.OpenProcess(PROCESS_SET_QUOTA | PROCESS_QUERY_INFORMATION, False, pid)
        if not h:
            return False
        try:
            res = psapi.EmptyWorkingSet(h)
            return bool(res)
        finally:
            kernel32.CloseHandle(h)

    @classmethod
    def trim_process_tree(cls, parent_pid: int) -> int:
        """Trims working sets for parent process and all its descendant subprocesses."""
        pids = cls.get_process_tree(parent_pid)
        success_count = 0
        for p in pids:
            if cls.trim_working_set(p):
                success_count += 1
        return success_count

    @classmethod
    def trim_all(cls, parent_pids: List[int]) -> Dict[str, Any]:
        """
        Trims working sets across all browser instances in the cluster.
        Returns statistics about memory freed.
        """
        before_mb = cls.get_cluster_memory_mb(parent_pids)
        all_pids: List[int] = []
        for p in parent_pids:
            all_pids.extend(cls.get_process_tree(p))
        unique_pids = list(set(all_pids))

        trimmed_count = 0
        for pid in unique_pids:
            if cls.trim_working_set(pid):
                trimmed_count += 1

        after_mb = cls.get_cluster_memory_mb(parent_pids)
        saved_mb = max(0.0, before_mb - after_mb)

        return {
            "trimmed_processes": trimmed_count,
            "before_mb": round(before_mb, 1),
            "after_mb": round(after_mb, 1),
            "saved_mb": round(saved_mb, 1)
        }


class MemoryOptimizerDaemon(threading.Thread):
    """
    Background daemon thread that periodically runs working set optimization
    to keep browser cluster memory tightly constrained.
    """

    def __init__(self, get_parent_pids_func, interval_sec: float = 30.0):
        super().__init__(daemon=True, name="MemoryOptimizerDaemon")
        self.get_parent_pids = get_parent_pids_func
        self.interval_sec = max(5.0, interval_sec)
        self.running = False
        self.last_trim_stats: Optional[Dict[str, Any]] = None
        self._stop_event = threading.Event()

    def run(self):
        self.running = True
        # Allow browsers to finish initial loading before first trim
        time.sleep(10.0)

        while not self._stop_event.is_set():
            try:
                pids = self.get_parent_pids()
                if pids:
                    self.last_trim_stats = MemoryOptimizer.trim_all(pids)
            except Exception:
                pass
            self._stop_event.wait(self.interval_sec)

    def trigger_now(self) -> Optional[Dict[str, Any]]:
        """Performs immediate on-demand memory trim."""
        try:
            pids = self.get_parent_pids()
            if pids:
                self.last_trim_stats = MemoryOptimizer.trim_all(pids)
                return self.last_trim_stats
        except Exception:
            pass
        return None

    def stop(self):
        self.running = False
        self._stop_event.set()
