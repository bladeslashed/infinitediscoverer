import os
import time
import threading
from collections import deque
from typing import Dict, Any, List, Tuple, Optional, Set

from core.engine_wrapper import RecipeEngine
from discoveries.logger import DiscoveriesLogger

class SharedEngine:
    """
    Thread-safe orchestrator wrapping the C computation engine,
    managing non-overlapping pair dispatching, real-time cross-browser inventory syncing,
    and discovery logging.
    """

    def __init__(
        self,
        cache_path: str = "data/recipes_cache.bin",
        discoveries_dir: str = "discoveries",
        strategy: int = RecipeEngine.STRATEGY_SMART_HEURISTIC,
        max_depth_delta: int = 2,
        catalyst_cap: int = 24,
        prune_threshold: float = 0.04
    ):
        self.lock = threading.RLock()
        self.cache_path = os.path.abspath(cache_path)
        self.discoveries_dir = os.path.abspath(discoveries_dir)

        # Initialize C backend
        self.engine = RecipeEngine()
        self.engine.set_strategy(strategy)
        self.engine.set_max_depth_delta(max_depth_delta)
        self.engine.set_catalyst_cap(catalyst_cap)
        self.engine.set_prune_threshold(prune_threshold)

        # Initialize markdown logger
        self.logger = DiscoveriesLogger(discoveries_dir=self.discoveries_dir)

        # In-flight tracking: maps instance_id -> list of (el_a, el_b)
        self._in_flight_map: Dict[str, List[Tuple[Dict[str, Any], Dict[str, Any]]]] = {}

        # Cross-browser synchronization tracking:
        # Maps instance_id -> Set of element names already synced into that browser's DOM/Vue
        self._synced_elements: Dict[str, Set[str]] = {}

        # Master list of all known elements: list of dicts {name, emoji, discovered}
        self._known_elements_list: List[Dict[str, Any]] = []
        self._known_elements_set: Set[str] = set()

        # Shared discovery feed for live CLI dashboard (most recent 25 discoveries)
        self.recent_discoveries: deque = deque(maxlen=25)

        # Total session stats
        self.session_discoveries = 0
        self.session_tested = 0
        self.start_time = time.time()
        self.last_cache_save = time.time()

        # Load cache if available
        self._init_cache()

    def _init_cache(self):
        with self.lock:
            if os.path.exists(self.cache_path):
                self.engine.load_cache(self.cache_path)

    def register_instance(self, instance_id: str, browser_inventory: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Registers a new browser instance. Merges any elements already in the browser into the master engine,
        and returns any missing elements that need to be injected into this browser.
        """
        with self.lock:
            if instance_id not in self._synced_elements:
                self._synced_elements[instance_id] = set()

            # Merge items from this browser's existing inventory
            for item in browser_inventory:
                name = item.get("text") or item.get("name", "")
                if not name:
                    continue
                name_clean = name.strip()
                emoji = item.get("emoji", "")
                is_first = bool(item.get("discovered", False))
                lower = name_clean.lower()

                self._synced_elements[instance_id].add(lower)

                if lower not in self._known_elements_set:
                    self._known_elements_set.add(lower)
                    self._known_elements_list.append({
                        "name": name_clean,
                        "text": name_clean,
                        "emoji": emoji,
                        "discovered": is_first
                    })
                    self.engine.add_element(name_clean, emoji, is_first, 0)

            # Ensure basic 4 elements exist if empty
            if self.engine.get_element_count() == 0:
                initial = [("Water", "💧"), ("Fire", "🔥"), ("Wind", "🌬️"), ("Earth", "🌍")]
                for n, em in initial:
                    self.engine.add_element(n, em, False, 0)
                    lower = n.lower()
                    if lower not in self._known_elements_set:
                        self._known_elements_set.add(lower)
                        self._known_elements_list.append({"name": n, "text": n, "emoji": em, "discovered": False})

            # Calculate elements this instance is missing
            missing = []
            for item in self._known_elements_list:
                if item["name"].lower() not in self._synced_elements[instance_id]:
                    missing.append(item)

            return missing

    def mark_elements_synced(self, instance_id: str, element_names: List[str]):
        """Marks elements as successfully synced into the instance's browser."""
        with self.lock:
            if instance_id not in self._synced_elements:
                self._synced_elements[instance_id] = set()
            for name in element_names:
                self._synced_elements[instance_id].add(name.lower())

    def get_pending_sync_for_instance(self, instance_id: str) -> List[Dict[str, Any]]:
        """Returns any new elements that have not yet been synced into this instance's browser."""
        with self.lock:
            if instance_id not in self._synced_elements:
                return list(self._known_elements_list)

            synced_set = self._synced_elements[instance_id]
            pending = []
            for item in self._known_elements_list:
                if item["name"].lower() not in synced_set:
                    pending.append(item)
            return pending

    def get_untested_batch(self, instance_id: str, batch_size: int) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
        """
        Atomically fetches the next batch of untested pairs for the requesting instance.
        Because pairs are marked IN_FLIGHT in the C engine, no other instance will get them.
        """
        with self.lock:
            batch = self.engine.get_untested_batch(batch_size)
            if batch:
                self._in_flight_map[instance_id] = batch
            else:
                self._in_flight_map[instance_id] = []
            return batch

    def revert_in_flight(self, instance_id: str, pairs: Optional[List[Tuple[Dict[str, Any], Dict[str, Any]]]] = None):
        """Reverts in-flight pairs for an instance (e.g. after a rate limit or network error)."""
        with self.lock:
            pairs_to_revert = pairs if pairs is not None else self._in_flight_map.get(instance_id, [])
            for el_a, el_b in pairs_to_revert:
                self.engine.revert_in_flight(el_a["id"], el_b["id"])
            if instance_id in self._in_flight_map:
                self._in_flight_map[instance_id] = []

    def process_results(
        self,
        instance_id: str,
        pairs_batch: List[Tuple[Dict[str, Any], Dict[str, Any]]],
        results: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Processes batch query results from an instance:
        records recipes into C engine, identifies new discoveries, updates logs,
        and broadcasts new items for other browsers to sync.
        """
        new_discoveries_in_batch = []
        with self.lock:
            for idx, res in enumerate(results):
                if idx >= len(pairs_batch):
                    break
                el_a, el_b = pairs_batch[idx]

                if not res or "error" in res:
                    self.engine.revert_in_flight(el_a["id"], el_b["id"])
                    continue

                self.session_tested += 1
                result_name = res.get("result", "").strip()
                result_emoji = res.get("emoji", "")
                is_first = bool(res.get("isNew", False))

                if not result_name or result_name.lower() == "nothing":
                    self.engine.record_result(el_a["id"], el_b["id"], RecipeEngine.RESULT_NOTHING, False)
                else:
                    existing_id = self.engine.find_element(result_name)
                    if existing_id >= 0:
                        self.engine.record_result(el_a["id"], el_b["id"], existing_id, False)
                    else:
                        # NEW DISCOVERY!
                        new_depth = max(el_a["depth"], el_b["depth"]) + 1
                        new_id = self.engine.add_element(result_name, result_emoji, is_first, new_depth)
                        self.engine.record_result(el_a["id"], el_b["id"], new_id, True)

                        self.session_discoveries += 1
                        stats = self.engine.get_stats()

                        # Markdown Chronicle Logging
                        self.logger.log_discovery(
                            result_name=result_name,
                            result_emoji=result_emoji,
                            elem_a=el_a["name"],
                            elem_a_emoji=el_a["emoji"],
                            elem_b=el_b["name"],
                            elem_b_emoji=el_b["emoji"],
                            is_first_discovery=is_first,
                            total_recipes_tested=stats["total_tested_pairs"]
                        )

                        item_dict = {
                            "name": result_name,
                            "text": result_name,
                            "emoji": result_emoji,
                            "discovered": is_first,
                            "recipe": [el_a["id"], el_b["id"]],
                            "instance_id": instance_id,
                            "recipe_str": f"{el_a['emoji']} {el_a['name']} + {el_b['emoji']} {el_b['name']}",
                            "timestamp": time.strftime("%H:%M:%S")
                        }

                        lower = result_name.lower()
                        self._known_elements_set.add(lower)
                        self._known_elements_list.append(item_dict)
                        new_discoveries_in_batch.append(item_dict)
                        self.recent_discoveries.appendleft(item_dict)

            # Clear in-flight record for this instance
            self._in_flight_map[instance_id] = []

        return new_discoveries_in_batch

    def save_cache_if_due(self, interval_sec: float = 20.0) -> bool:
        """Saves binary recipe cache if enough time has passed."""
        now = time.time()
        if now - self.last_cache_save >= interval_sec:
            return self.save_cache()
        return False

    def save_cache(self) -> bool:
        """Saves binary recipe cache to disk."""
        with self.lock:
            self.last_cache_save = time.time()
            return self.engine.save_cache(self.cache_path)

    def get_stats(self) -> Dict[str, Any]:
        """Returns thread-safe snapshot of global engine statistics."""
        with self.lock:
            c_stats = self.engine.get_stats()
            elapsed = time.time() - self.start_time
            rate = (self.session_tested / elapsed) if elapsed > 0 else 0.0
            return {
                **c_stats,
                "session_discoveries": self.session_discoveries,
                "session_tested": self.session_tested,
                "elapsed_sec": elapsed,
                "overall_rate": rate,
                "known_elements_count": len(self._known_elements_list)
            }

    def cleanup(self):
        """Saves cache and frees engine resources."""
        with self.lock:
            self.save_cache()
            self.engine.cleanup()
