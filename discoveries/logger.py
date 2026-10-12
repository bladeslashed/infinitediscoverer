import os
import re
from datetime import datetime
from typing import Set, Dict, Any, Optional

class DiscoveriesLogger:
    def __init__(self, discoveries_dir: Optional[str] = None):
        if discoveries_dir is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            discoveries_dir = os.path.join(base_dir, "discoveries")
        
        self.discoveries_dir = discoveries_dir
        self.filepath = os.path.join(self.discoveries_dir, "Discoveries.md")
        os.makedirs(self.discoveries_dir, exist_ok=True)
        
        self._logged_names: Set[str] = set()
        self._total_discoveries = 0
        self._first_discoveries = 0
        self._recipes_tested = 0
        
        self._init_file()

    def _init_file(self):
        if not os.path.exists(self.filepath):
            self._write_fresh_file()
        else:
            self._parse_existing_file()

    def _write_fresh_file(self):
        content = (
            "# 🌌 Infinite Craft - Discoveries Archive\n\n"
            "> Automated Autonomous Discovery Agent powered by C Computation Engine & Opera CDP.\n\n"
            "| Statistic | Value |\n"
            "|:---|:---|\n"
            "| **Total Unlocked Elements** | 0 |\n"
            "| **⭐ First Discoveries (Global)** | 0 |\n"
            "| **🧪 Total Recipes Tested** | 0 |\n"
            f"| **🕒 Last Updated** | {datetime.now().strftime('%Y-%m-%d %H:%M:%S')} |\n\n"
            "---\n\n"
            "## 📜 Discovery Chronicle\n\n"
            "| # | Result | Recipe | Discovery Type | Timestamp |\n"
            "|:---:|:---|:---|:---:|:---:|\n"
        )
        with open(self.filepath, "w", encoding="utf-8") as f:
            f.write(content)

    def _parse_existing_file(self):
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                content = f.read()

            # Find all logged rows
            # Pattern matches: | index | emoji name | recipe | type | date |
            rows = re.findall(r"^\|\s*(\d+)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|", content, re.MULTILINE)
            for r in rows:
                idx, res_cell, recipe, dtype, tstamp = r
                # Extract clean name without emoji
                clean_name = res_cell.strip()
                self._logged_names.add(clean_name.lower())
                self._total_discoveries += 1
                if "First Discovery" in dtype:
                    self._first_discoveries += 1
        except Exception:
            pass

    def is_already_logged(self, element_name: str) -> bool:
        return element_name.lower() in self._logged_names

    def log_discovery(
        self,
        result_name: str,
        result_emoji: str,
        elem_a: str,
        elem_a_emoji: str,
        elem_b: str,
        elem_b_emoji: str,
        is_first_discovery: bool = False,
        total_recipes_tested: int = 0
    ) -> bool:
        key = result_name.lower()
        if key in self._logged_names:
            return False

        self._logged_names.add(key)
        self._total_discoveries += 1
        if is_first_discovery:
            self._first_discoveries += 1
        if total_recipes_tested > self._recipes_tested:
            self._recipes_tested = total_recipes_tested

        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        dtype = "⭐ **First Discovery!**" if is_first_discovery else "✨ Discovered"
        
        result_str = f"{result_emoji} **{result_name}**" if result_emoji else f"**{result_name}**"
        recipe_str = f"`{elem_a_emoji} {elem_a}` + `{elem_b_emoji} {elem_b}`"

        row = f"| {self._total_discoveries} | {result_str} | {recipe_str} | {dtype} | {timestamp} |\n"

        # Update stats header and append row
        self._update_file(row)
        return True

    def _update_file(self, new_row: str):
        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        with open(self.filepath, "r", encoding="utf-8") as f:
            content = f.read()

        # Update statistics in header
        content = re.sub(
            r"\|\s*\*\*Total Unlocked Elements\*\*\s*\|\s*(\d+)\s*\|",
            f"| **Total Unlocked Elements** | {self._total_discoveries} |",
            content
        )
        content = re.sub(
            r"\|\s*\*\*⭐ First Discoveries \(Global\)\*\*\s*\|\s*(\d+)\s*\|",
            f"| **⭐ First Discoveries (Global)** | {self._first_discoveries} |",
            content
        )
        content = re.sub(
            r"\|\s*\*\*🧪 Total Recipes Tested\*\*\s*\|\s*(\d+)\s*\|",
            f"| **🧪 Total Recipes Tested** | {self._recipes_tested} |",
            content
        )
        content = re.sub(
            r"\|\s*\*\*🕒 Last Updated\*\*\s*\|\s*.*?\s*\|",
            f"| **🕒 Last Updated** | {now_str} |",
            content
        )

        content += new_row

        with open(self.filepath, "w", encoding="utf-8") as f:
            f.write(content)

    def get_stats(self) -> Dict[str, Any]:
        return {
            "total_discoveries": self._total_discoveries,
            "first_discoveries": self._first_discoveries,
            "recipes_tested": self._recipes_tested
        }
