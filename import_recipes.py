import os
import sys
import json
import csv
import io
import argparse
import itertools
from typing import List, Dict, Any, Optional, Tuple, Union

# Fix Windows console UTF-8 output
if sys.platform == "win32":
    try:
        if hasattr(sys.stdout, 'reconfigure'):
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        if hasattr(sys.stderr, 'reconfigure'):
            sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from core.engine_wrapper import RecipeEngine

# Header column alias sets for automatic schema detection
FIRST_ALIASES = {
    "first", "elem_a", "elema", "element1", "element_1", "elem1", "elem_1",
    "parent1", "parent_1", "parenta", "parent_a", "from1", "from_1", "from_a",
    "item1", "item_1", "ingredient1", "ingredient_1", "input1", "input_1",
    "recipe_a", "base1", "primary", "a"
}

SECOND_ALIASES = {
    "second", "elem_b", "elemb", "element2", "element_2", "elem2", "elem_2",
    "parent2", "parent_2", "parentb", "parent_b", "from2", "from_2", "from_b",
    "item2", "item_2", "ingredient2", "ingredient_2", "input2", "input_2",
    "recipe_b", "base2", "secondary", "b"
}

RESULT_ALIASES = {
    "result", "result_name", "resultname", "res", "elem_res", "element_result",
    "child", "to", "name", "output", "product", "crafted", "c", "discovered"
}

PAIR_ALIASES = {
    "pair", "recipe", "combo", "combination", "ingredients", "formula"
}

EMOJI_ALIASES = {
    "emoji", "icon", "result_emoji", "res_emoji", "symbol"
}

FIRST_DISC_ALIASES = {
    "is_first_discovery", "first_discovery", "firstdiscovery", "isnew", "is_new", "new"
}


def is_likely_emoji(s: str) -> bool:
    """Checks if a string is likely an emoji or icon symbol."""
    if not s:
        return False
    s = s.strip()
    if len(s) > 8:
        return False
    for ch in s:
        if ord(ch) >= 0x2000:
            return True
    return False


def record_recipe_to_engine(
    engine: RecipeEngine,
    first: str,
    second: str,
    result: str,
    emoji: str = "✨",
    is_first_discovery: bool = False
) -> bool:
    """Validates and registers a recipe combination and its result in the RecipeEngine."""
    if not first or not second or not result:
        return False

    first = first.strip()
    second = second.strip()
    result = result.strip()
    if not first or not second or not result or result.lower() == "nothing":
        return False

    emoji = emoji.strip() if emoji else "✨"
    if not emoji:
        emoji = "✨"

    id_a = engine.find_element(first)
    if id_a < 0:
        id_a = engine.add_element(first, "", False, 0)

    id_b = engine.find_element(second)
    if id_b < 0:
        id_b = engine.add_element(second, "", False, 0)

    id_res = engine.find_element(result)
    if id_res < 0:
        id_res = engine.add_element(result, emoji, is_first_discovery, 1)

    # Check if already tested with this same result to avoid duplicate counting
    if engine.is_tested(id_a, id_b) == RecipeEngine.PAIR_STATUS_TESTED:
        if engine.get_result(id_a, id_b) == id_res:
            return True

    engine.record_result(id_a, id_b, id_res, is_new_element=False)
    return True


def detect_csv_delimiter(sample: str) -> str:
    """Detects delimiter from a text sample with Sniffer and fallback heuristics."""
    try:
        sniffer = csv.Sniffer()
        dialect = sniffer.sniff(sample, delimiters=['=', ',', '\t', ';', '|'])
        return dialect.delimiter
    except Exception:
        counts = {d: sample.count(d) for d in ['=', ',', '\t', ';', '|']}
        best_delimiter = max(counts, key=counts.get) if any(counts.values()) else ','
        return best_delimiter


def identify_csv_headers(headers: List[str]) -> Optional[Dict[str, int]]:
    """
    Identifies column positions from header names.
    Returns a dict mapping role -> column index, or None if headers are not recognized.
    """
    cleaned = [h.strip().lower().replace(" ", "_").replace("-", "_") for h in headers]
    col_map: Dict[str, int] = {}

    for idx, col in enumerate(cleaned):
        if col in FIRST_ALIASES and "first" not in col_map:
            col_map["first"] = idx
        elif col in SECOND_ALIASES and "second" not in col_map:
            col_map["second"] = idx
        elif col in RESULT_ALIASES and "result" not in col_map:
            col_map["result"] = idx
        elif col in PAIR_ALIASES and "pair" not in col_map:
            col_map["pair"] = idx
        elif col in EMOJI_ALIASES and "emoji" not in col_map:
            col_map["emoji"] = idx
        elif col in FIRST_DISC_ALIASES and "first_discovery" not in col_map:
            col_map["first_discovery"] = idx

    # Valid if we have (first + second + result) OR (pair + result)
    if ("first" in col_map and "second" in col_map and "result" in col_map) or ("pair" in col_map and "result" in col_map):
        return col_map

    return None


def import_csv_file(csv_path: str, engine: RecipeEngine) -> int:
    """Imports recipes from a CSV, TSV, or delimiter-separated text file."""
    encoding = "utf-8-sig"
    try:
        with open(csv_path, "r", encoding=encoding) as f:
            sample = f.read(8192)
    except UnicodeDecodeError:
        encoding = "latin-1"
        with open(csv_path, "r", encoding=encoding) as f:
            sample = f.read(8192)

    if not sample.strip():
        print(f"⚠️ Empty CSV file: {csv_path}")
        return 0

    delimiter = detect_csv_delimiter(sample)
    imported_count = 0

    with open(csv_path, "r", encoding=encoding, newline="") as f:
        reader = csv.reader(f, delimiter=delimiter)
        try:
            first_row = next(reader)
        except StopIteration:
            return 0

        # Skip leading empty rows if any
        while first_row is not None and not any(c.strip() for c in first_row):
            try:
                first_row = next(reader)
            except StopIteration:
                return 0

        col_map = identify_csv_headers(first_row)

        if col_map is not None:
            # Header detected! Process remaining rows using col_map
            row_iter = reader
        else:
            # No recognized header: treat first_row as data
            row_iter = itertools.chain([first_row], reader)

        for row in row_iter:
            if not row or not any(c.strip() for c in row):
                continue

            # Skip comment lines
            if row[0].strip().startswith("#"):
                continue

            first, second, result, emoji = None, None, None, "✨"
            is_first_disc = False

            if col_map is not None:
                # Named columns
                if "pair" in col_map and col_map["pair"] < len(row):
                    pair_text = row[col_map["pair"]].strip()
                    parts = [p.strip() for p in pair_text.split("+")]
                    if len(parts) == 2:
                        first, second = parts[0], parts[1]
                else:
                    first = row[col_map["first"]].strip() if col_map.get("first", -1) < len(row) else None
                    second = row[col_map["second"]].strip() if col_map.get("second", -1) < len(row) else None

                result = row[col_map["result"]].strip() if col_map.get("result", -1) < len(row) else None

                if "emoji" in col_map and col_map["emoji"] < len(row):
                    emoji = row[col_map["emoji"]].strip() or "✨"

                if "first_discovery" in col_map and col_map["first_discovery"] < len(row):
                    val = row[col_map["first_discovery"]].strip().lower()
                    is_first_disc = val in ("true", "1", "yes", "y")
            else:
                # Positional columns without recognized header
                row_clean = [c.strip() for c in row]
                if len(row_clean) >= 4:
                    first = row_clean[0]
                    second = row_clean[1]
                    if is_likely_emoji(row_clean[2]) and not is_likely_emoji(row_clean[3]):
                        emoji = row_clean[2]
                        result = row_clean[3]
                    else:
                        result = row_clean[2]
                        emoji = row_clean[3] or "✨"
                elif len(row_clean) == 3:
                    first = row_clean[0]
                    second = row_clean[1]
                    result = row_clean[2]
                elif len(row_clean) == 2:
                    if "+" in row_clean[0]:
                        parts = [p.strip() for p in row_clean[0].split("+")]
                        if len(parts) == 2:
                            first, second = parts[0], parts[1]
                            result = row_clean[1]
                elif len(row_clean) == 1:
                    line = row_clean[0]
                    parts_eq = [p.strip() for p in line.split("=")]
                    if len(parts_eq) >= 3:
                        first = parts_eq[0]
                        second = parts_eq[1]
                        result = parts_eq[2]
                        if len(parts_eq) >= 4 and is_likely_emoji(parts_eq[3]):
                            emoji = parts_eq[3]
                    else:
                        for sep in ["=>", "->", "="]:
                            if sep in line:
                                left, right = line.split(sep, 1)
                                if "+" in left:
                                    parts = [p.strip() for p in left.split("+")]
                                    if len(parts) == 2:
                                        first, second = parts[0], parts[1]
                                        result = right.strip()
                                break

            if first and second and result:
                if record_recipe_to_engine(engine, first, second, result, emoji, is_first_disc):
                    imported_count += 1
                    if imported_count % 50000 == 0:
                        print(f"   ⏳ Processed {imported_count:,} recipes...")

    return imported_count


def import_json_file(json_path: str, engine: RecipeEngine) -> int:
    """Imports recipes from a JSON file (lists, dicts, key-value mappings)."""
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    imported_count = 0

    # 1. List of dicts or list of lists:
    if isinstance(data, list):
        for entry in data:
            if isinstance(entry, dict):
                first = entry.get("first") or entry.get("elem_a") or entry.get("from", [None, None])[0]
                second = entry.get("second") or entry.get("elem_b") or entry.get("from", [None, None])[1]
                result = entry.get("result") or entry.get("to") or entry.get("name")
                emoji = entry.get("emoji", "✨")
                is_first_disc = bool(entry.get("is_first_discovery") or entry.get("isNew") or False)

                if first and second and result:
                    if record_recipe_to_engine(engine, first, second, result, emoji, is_first_disc):
                        imported_count += 1
                        if imported_count % 50000 == 0:
                            print(f"   ⏳ Processed {imported_count:,} recipes...")

            elif isinstance(entry, (list, tuple)):
                if len(entry) >= 3:
                    first = str(entry[0])
                    second = str(entry[1])
                    result = str(entry[2])
                    emoji = str(entry[3]) if len(entry) >= 4 else "✨"
                    if record_recipe_to_engine(engine, first, second, result, emoji):
                        imported_count += 1
                        if imported_count % 50000 == 0:
                            print(f"   ⏳ Processed {imported_count:,} recipes...")

    # 2. Key-value dict: {"Water + Fire": "Steam", ...} or nested under "recipes"
    elif isinstance(data, dict):
        recipes_dict = data.get("recipes", data.get("data", data))
        if isinstance(recipes_dict, dict):
            for pair_key, res_val in recipes_dict.items():
                parts = [p.strip() for p in pair_key.split("+")]
                if len(parts) == 2:
                    first, second = parts[0], parts[1]
                    if isinstance(res_val, str):
                        result_name = res_val.strip()
                        emoji = "✨"
                        is_first_disc = False
                    elif isinstance(res_val, dict):
                        result_name = res_val.get("result", "").strip()
                        emoji = res_val.get("emoji", "✨")
                        is_first_disc = bool(res_val.get("is_first_discovery") or res_val.get("isNew") or False)
                    else:
                        continue

                    if result_name:
                        if record_recipe_to_engine(engine, first, second, result_name, emoji, is_first_disc):
                            imported_count += 1
                            if imported_count % 50000 == 0:
                                print(f"   ⏳ Processed {imported_count:,} recipes...")

    return imported_count


def is_json_file(file_path: str) -> bool:
    """Determines whether a file is JSON based on extension and initial bytes."""
    ext = os.path.splitext(file_path)[1].lower()
    if ext == ".json":
        return True
    if ext in (".csv", ".tsv"):
        return False

    # For .txt or unknown extensions, peek at first non-whitespace character
    try:
        with open(file_path, "r", encoding="utf-8-sig") as f:
            sample = f.read(1024).strip()
            if sample and sample[0] in ("{", "["):
                return True
    except Exception:
        pass
    return False


def ensure_fast_importer() -> Optional[str]:
    """Ensures c_engine/fast_importer.exe is built and available."""
    base_dir = os.path.dirname(os.path.abspath(__file__))
    importer_exe = os.path.join(base_dir, "c_engine", "fast_importer.exe")
    importer_cpp = os.path.join(base_dir, "c_engine", "fast_importer.cpp")

    if os.path.exists(importer_exe):
        return importer_exe

    if os.path.exists(importer_cpp):
        print("🔨 Compiling high-performance C++ dataset importer (fast_importer.exe)...")
        import subprocess
        try:
            res = subprocess.run(
                ["g++", "-O3", "-std=c++17", "-o", importer_exe, importer_cpp],
                capture_output=True,
                text=True
            )
            if res.returncode == 0 and os.path.exists(importer_exe):
                print("   ✅ C++ importer compiled successfully.")
                return importer_exe
            else:
                print(f"   ⚠️ Compilation failed: {res.stderr}")
        except Exception as e:
            print(f"   ⚠️ g++ compiler not accessible: {e}")

    return None


def import_recipes_to_cache(
    file_path: Optional[Union[str, List[str]]] = None,
    cache_path: str = "data/recipes_cache.bin",
    json_path: Optional[str] = None
) -> int:
    """
    Imports known recipes from JSON, CSV, or TSV datasets into the persistent binary cache.
    Accepts a single file path or a list of file paths.
    """
    target = file_path if file_path is not None else json_path
    if not target:
        print("❌ No input file specified.")
        return 0

    file_list = [target] if isinstance(target, str) else list(target)
    valid_files = [f for f in file_list if os.path.exists(f)]
    missing_files = [f for f in file_list if not os.path.exists(f)]

    for mf in missing_files:
        print(f"⚠️ File not found: {mf}")

    if not valid_files:
        print("❌ No valid recipe files to import.")
        return 0

    # Separate CSV/TSV/delimited files from JSON files
    delimited_files = [f for f in valid_files if not is_json_file(f)]
    json_files = [f for f in valid_files if is_json_file(f)]

    # 1. Use high-speed C++ importer for delimited files if available
    fast_exe = ensure_fast_importer()
    if fast_exe and delimited_files:
        import subprocess
        cmd = [fast_exe, "--cache", cache_path] + delimited_files
        print(f"⚡ Delegating {len(delimited_files)} file(s) to C++ fast_importer: {' '.join(delimited_files)}")
        ret = subprocess.run(cmd)
        if ret.returncode != 0:
            print("⚠️ C++ importer exited with non-zero status. Falling back to Python reader.")
        else:
            delimited_files = [] # Successfully handled!

    # 2. Handle remaining files (JSON or fallback) via Engine
    remaining_files = delimited_files + json_files
    if remaining_files:
        engine = RecipeEngine()
        if os.path.exists(cache_path):
            print(f"📦 Loading existing cache from: {cache_path}")
            engine.load_cache(cache_path)
        else:
            print("📦 Starting fresh cache.")

        total_imported = 0
        for fpath in remaining_files:
            is_json = is_json_file(fpath)
            ftype = "JSON" if is_json else "CSV/TSV"
            print(f"📖 Reading recipes from [{ftype}]: {fpath}...")
            try:
                if is_json:
                    count = import_json_file(fpath, engine)
                else:
                    count = import_csv_file(fpath, engine)
                print(f"   ✓ Imported {count:,} recipes from {os.path.basename(fpath)}")
                total_imported += count
            except Exception as e:
                print(f"❌ Error importing {fpath}: {e}")

        engine.save_cache(cache_path)
        stats = engine.get_stats()
        print(f"\n✅ Total successfully imported recipes: {total_imported:,}")
        print(f"   • Total Elements in Cache: {stats['total_elements']:,}")
        print(f"   • Total Tested Pairs: {stats['total_tested_pairs']:,}")
        print(f"💾 Saved to {cache_path}")
        engine.cleanup()
        return total_imported

    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Pre-seed Infinite Craft binary cache from JSON or CSV recipe datasets"
    )
    parser.add_argument(
        "files",
        nargs="+",
        help="Path to JSON or CSV/TSV recipe dump file(s)"
    )
    parser.add_argument(
        "--cache",
        default="data/recipes_cache.bin",
        help="Path to persistent binary recipe cache (default: data/recipes_cache.bin)"
    )
    args = parser.parse_args()

    import_recipes_to_cache(args.files, args.cache)

