"""
Migration script: Upgrade hsdata_searchable.json schema.

Adds 3 new fields to every record:
- chapter_id (str): 2-digit chapter code derived from hs_code
- is_leaf (bool): True if hs_code is a complete 8-digit code
- aliases (list[str]): empty by default, to be enriched later

Run: python3 tools/migrate_searchable_db.py
"""

import json
import os
import shutil
import tempfile

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INPUT_FILE = os.path.join(BASE_DIR, "database", "hsdata_searchable.json")
OUTPUT_FILE = INPUT_FILE  # In-place upgrade (atomic write)


def _extract_chapter_id(hs_code: str) -> str:
    """
    Extract 2-digit chapter ID from an hs_code string.
    Examples:
      "01012100" -> "01"
      "0101"     -> "01"
      "010130"   -> "01"
    """
    # Strip non-digit characters just in case
    digits = "".join(c for c in str(hs_code) if c.isdigit())
    if len(digits) >= 2:
        return digits[:2].zfill(2)
    return "00"


def _is_leaf(hs_code: str) -> bool:
    """
    A record is a leaf node (submittable HS code) when its purely-digit
    portion is exactly 8 characters long.  Headings (4 digits) and
    subheadings (6 digits) are not leaves.
    """
    digits = "".join(c for c in str(hs_code) if c.isdigit())
    return len(digits) == 8


def migrate(input_path: str, output_path: str) -> None:
    print(f"[migrate] Loading {input_path} ...")
    with open(input_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    total = len(data)
    leaf_count = 0
    upgraded = 0

    print(f"[migrate] Processing {total:,} records ...")
    for record in data:
        hs_code = record.get("hs_code", "")

        chapter_id = _extract_chapter_id(hs_code)
        leaf = _is_leaf(hs_code)

        # Only add fields that are missing (idempotent migration)
        changed = False
        if "chapter_id" not in record:
            record["chapter_id"] = chapter_id
            changed = True
        if "is_leaf" not in record:
            record["is_leaf"] = leaf
            changed = True
        if "aliases" not in record:
            record["aliases"] = []
            changed = True

        if leaf:
            leaf_count += 1
        if changed:
            upgraded += 1

    print(f"[migrate] Total records : {total:,}")
    print(f"[migrate] Leaf nodes    : {leaf_count:,} ({leaf_count/total*100:.1f}%)")
    print(f"[migrate] Intermediate  : {total - leaf_count:,}")
    print(f"[migrate] Records updated: {upgraded:,}")

    # Atomic write — write to temp then rename
    dir_path = os.path.dirname(output_path)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8",
        dir=dir_path, delete=False, suffix=".tmp"
    ) as tmp_f:
        json.dump(data, tmp_f, ensure_ascii=False, indent=2)
        tmp_path = tmp_f.name

    shutil.move(tmp_path, output_path)
    print(f"[migrate] ✅ Written to {output_path}")
    print("[migrate] Migration complete!")


if __name__ == "__main__":
    migrate(INPUT_FILE, OUTPUT_FILE)
