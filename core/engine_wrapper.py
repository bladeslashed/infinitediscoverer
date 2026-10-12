import ctypes
import os
import sys
from typing import List, Tuple, Optional, Dict, Any

class CElement(ctypes.Structure):
    _fields_ = [
        ("id", ctypes.c_int),
        ("name", ctypes.c_char * 128),
        ("emoji", ctypes.c_char * 64),
        ("is_first_discovery", ctypes.c_bool),
        ("depth", ctypes.c_int),
        ("trials_count", ctypes.c_int),
        ("success_count", ctypes.c_int),
        ("fertility", ctypes.c_float),
        ("is_catalyst", ctypes.c_bool)
    ]

class CEngineStats(ctypes.Structure):
    _fields_ = [
        ("total_elements", ctypes.c_int),
        ("total_tested_pairs", ctypes.c_int),
        ("total_in_flight_pairs", ctypes.c_int),
        ("total_pruned_pairs", ctypes.c_int),
        ("total_first_discoveries", ctypes.c_int),
        ("total_possible_pairs", ctypes.c_uint64),
        ("frontier_size", ctypes.c_int),
        ("avg_fertility", ctypes.c_float)
    ]

class RecipeEngine:
    PAIR_STATUS_EMPTY = 0
    PAIR_STATUS_IN_FLIGHT = 1
    PAIR_STATUS_TESTED = 2
    PAIR_STATUS_SKIPPED = 3
    RESULT_NOTHING = -1

    STRATEGY_SMART_HEURISTIC = 0
    STRATEGY_EXHAUSTIVE = 1
    STRATEGY_FIRST_DISCOVERY_FOCUS = 2

    def __init__(self, dll_path: Optional[str] = None):
        if dll_path is None:
            # Check multiple potential base directories for PyInstaller & source runs
            search_dirs = []
            if hasattr(sys, "_MEIPASS"):
                search_dirs.append(sys._MEIPASS)
            if getattr(sys, "frozen", False):
                search_dirs.append(os.path.dirname(sys.executable))
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            search_dirs.append(base_dir)
            search_dirs.append(os.getcwd())

            for sdir in search_dirs:
                v3 = os.path.join(sdir, "c_engine", "recipe_engine_v3.dll")
                v3_flat = os.path.join(sdir, "recipe_engine_v3.dll")
                for candidate in [v3, v3_flat]:
                    if os.path.exists(candidate):
                        dll_path = candidate
                        break
                if dll_path:
                    break

        if not dll_path or not os.path.exists(dll_path):
            raise FileNotFoundError(f"Recipe engine DLL not found. Searched paths in: {search_dirs}")

        self._dll = ctypes.CDLL(dll_path)
        self.is_v3 = "v3" in os.path.basename(dll_path).lower()
        self.is_v2 = ("v2" in os.path.basename(dll_path).lower()) or self.is_v3
        self._setup_bindings()
        if not self._dll.engine_init():
            raise RuntimeError("Failed to initialize C recipe engine")

    def _setup_bindings(self):
        d = self._dll
        d.engine_init.restype = ctypes.c_bool
        d.engine_cleanup.restype = None
        d.engine_reset.restype = None

        if hasattr(d, "engine_set_strategy"):
            d.engine_set_strategy.argtypes = [ctypes.c_int]
            d.engine_set_strategy.restype = None

        if hasattr(d, "engine_set_prune_threshold"):
            d.engine_set_prune_threshold.argtypes = [ctypes.c_float]
            d.engine_set_prune_threshold.restype = None

        if hasattr(d, "engine_set_max_depth_delta"):
            d.engine_set_max_depth_delta.argtypes = [ctypes.c_int]
            d.engine_set_max_depth_delta.restype = None

        if hasattr(d, "engine_set_catalyst_cap"):
            d.engine_set_catalyst_cap.argtypes = [ctypes.c_int]
            d.engine_set_catalyst_cap.restype = None

        d.engine_add_element.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_bool, ctypes.c_int]
        d.engine_add_element.restype = ctypes.c_int

        d.engine_find_element.argtypes = [ctypes.c_char_p]
        d.engine_find_element.restype = ctypes.c_int

        d.engine_get_element.argtypes = [ctypes.c_int, ctypes.POINTER(CElement)]
        d.engine_get_element.restype = ctypes.c_bool

        d.engine_get_element_count.restype = ctypes.c_int

        d.engine_is_tested.argtypes = [ctypes.c_int, ctypes.c_int]
        d.engine_is_tested.restype = ctypes.c_int

        d.engine_get_result.argtypes = [ctypes.c_int, ctypes.c_int]
        d.engine_get_result.restype = ctypes.c_int

        if self.is_v2:
            d.engine_record_result.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_bool]
        else:
            d.engine_record_result.argtypes = [ctypes.c_int, ctypes.c_int, ctypes.c_int]
        d.engine_record_result.restype = ctypes.c_bool

        d.engine_revert_in_flight.argtypes = [ctypes.c_int, ctypes.c_int]
        d.engine_revert_in_flight.restype = None

        d.engine_get_untested_batch.argtypes = [
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_int)
        ]
        d.engine_get_untested_batch.restype = ctypes.c_int

        d.engine_save_cache.argtypes = [ctypes.c_char_p]
        d.engine_save_cache.restype = ctypes.c_bool

        d.engine_load_cache.argtypes = [ctypes.c_char_p]
        d.engine_load_cache.restype = ctypes.c_bool

        d.engine_get_stats.argtypes = [ctypes.POINTER(CEngineStats)]
        d.engine_get_stats.restype = None

    def set_strategy(self, strategy: int):
        if hasattr(self._dll, "engine_set_strategy"):
            self._dll.engine_set_strategy(strategy)

    def set_prune_threshold(self, min_fertility: float):
        if hasattr(self._dll, "engine_set_prune_threshold"):
            self._dll.engine_set_prune_threshold(ctypes.c_float(min_fertility))

    def set_max_depth_delta(self, max_delta: int):
        if hasattr(self._dll, "engine_set_max_depth_delta"):
            self._dll.engine_set_max_depth_delta(ctypes.c_int(max_delta))

    def set_catalyst_cap(self, k: int):
        if hasattr(self._dll, "engine_set_catalyst_cap"):
            self._dll.engine_set_catalyst_cap(ctypes.c_int(k))

    def add_element(self, name: str, emoji: str = "", is_first_discovery: bool = False, depth: int = 0) -> int:
        name_bytes = name.encode('utf-8', errors='replace')
        emoji_bytes = emoji.encode('utf-8', errors='replace')
        return self._dll.engine_add_element(name_bytes, emoji_bytes, is_first_discovery, depth)

    def find_element(self, name: str) -> int:
        name_bytes = name.encode('utf-8', errors='replace')
        return self._dll.engine_find_element(name_bytes)

    def get_element(self, elem_id: int) -> Optional[Dict[str, Any]]:
        c_el = CElement()
        if not self._dll.engine_get_element(elem_id, ctypes.byref(c_el)):
            return None
        return {
            "id": c_el.id,
            "name": c_el.name.decode('utf-8', errors='replace'),
            "emoji": c_el.emoji.decode('utf-8', errors='replace'),
            "is_first_discovery": c_el.is_first_discovery,
            "depth": c_el.depth,
            "trials_count": getattr(c_el, "trials_count", 0),
            "success_count": getattr(c_el, "success_count", 0),
            "fertility": getattr(c_el, "fertility", 0.0),
            "is_catalyst": getattr(c_el, "is_catalyst", False)
        }

    def get_element_count(self) -> int:
        return self._dll.engine_get_element_count()

    def is_tested(self, elem_a: int, elem_b: int) -> int:
        return self._dll.engine_is_tested(elem_a, elem_b)

    def get_result(self, elem_a: int, elem_b: int) -> int:
        return self._dll.engine_get_result(elem_a, elem_b)

    def record_result(self, elem_a: int, elem_b: int, result_id: int, is_new_element: bool = False) -> bool:
        if self.is_v2:
            return self._dll.engine_record_result(elem_a, elem_b, result_id, is_new_element)
        else:
            return self._dll.engine_record_result(elem_a, elem_b, result_id)

    def revert_in_flight(self, elem_a: int, elem_b: int) -> None:
        self._dll.engine_revert_in_flight(elem_a, elem_b)

    def get_untested_batch(self, max_count: int = 30) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
        out_a = (ctypes.c_int * max_count)()
        out_b = (ctypes.c_int * max_count)()
        out_count = ctypes.c_int(0)

        found = self._dll.engine_get_untested_batch(max_count, out_a, out_b, ctypes.byref(out_count))
        pairs = []
        for i in range(found):
            el_a = self.get_element(out_a[i])
            el_b = self.get_element(out_b[i])
            if el_a and el_b:
                pairs.append((el_a, el_b))
        return pairs

    def save_cache(self, filepath: str) -> bool:
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        return self._dll.engine_save_cache(filepath.encode('utf-8'))

    def load_cache(self, filepath: str) -> bool:
        if not os.path.exists(filepath):
            return False
        return self._dll.engine_load_cache(filepath.encode('utf-8'))

    def get_stats(self) -> Dict[str, Any]:
        stats = CEngineStats()
        self._dll.engine_get_stats(ctypes.byref(stats))
        return {
            "total_elements": stats.total_elements,
            "total_tested_pairs": stats.total_tested_pairs,
            "total_in_flight_pairs": stats.total_in_flight_pairs,
            "total_pruned_pairs": getattr(stats, "total_pruned_pairs", 0),
            "total_first_discoveries": stats.total_first_discoveries,
            "total_possible_pairs": stats.total_possible_pairs,
            "frontier_size": stats.frontier_size,
            "avg_fertility": getattr(stats, "avg_fertility", 0.0)
        }

    def cleanup(self):
        self._dll.engine_cleanup()
