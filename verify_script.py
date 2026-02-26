"""
Fast simulation verifier for embed_metadata.py (updated logic)
"""

import re
import sys
from pathlib import Path
from collections import defaultdict

STRUCTURE_FILE = r"D:\Metadata Fixer\structure.txt"
TAKEOUT_ROOT   = r"D:\Takeout"

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp',
                    '.tif', '.tiff', '.heic', '.bmp'}
VIDEO_EXTENSIONS = {'.mp4', '.mov', '.3gp', '.mpg', '.mpeg', '.m4v'}
ALL_EXTENSIONS   = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS

SUPPLEMENTAL_SUFFIXES = [
    ".supplemental-metadata", ".supplemental-metadat", ".supplemental-metada",
    ".supplemental-metad",    ".supplemental-meta",    ".supplemental-met",
    ".supplemental-me",       ".supplemental-m",       ".supplemental-",
    ".supplemental",          ".supplemen",            ".supple",
    ".suppl",                 ".supplement",           ".su",
    ".s",                     ".",
]


def parse_structure(path, root):
    text = open(path, "r", encoding="utf-16le", errors="replace").read()
    lines = text.splitlines()
    # folder_json_names: folder_str -> set of lowercase json filenames
    folder_json   = defaultdict(set)
    media_files   = []
    dir_stack     = [Path(root)]

    for line in lines:
        clean = line.replace('\u2502','|').replace('\u251c','+') \
                    .replace('\u2514','\\').replace('\u2500','-')
        dir_m = re.match(r'^([| ]*)[+\\]---(.+)$', clean)
        if dir_m:
            depth   = len(dir_m.group(1)) // 4 + 1
            dirname = dir_m.group(2).strip()
            while len(dir_stack) > depth:
                dir_stack.pop()
            dir_stack.append(dir_stack[-1] / dirname)
            continue
        file_m = re.match(r'^[| ]+(.+\.\S+)\s*$', clean)
        if not file_m:
            continue
        fname = file_m.group(1).strip()
        if fname.startswith(('+---', '\\---')):
            continue
        fpath = dir_stack[-1] / fname
        ext   = Path(fname).suffix.lower()
        folder_str = str(dir_stack[-1])
        if ext == '.json':
            folder_json[folder_str].add(fname.lower())
        elif ext in ALL_EXTENSIONS:
            media_files.append(fpath)

    return folder_json, media_files


def find_json_sim(photo: Path, folder_json: dict):
    """Mirrors updated embed_metadata.py find_json() logic."""
    folder_str  = str(photo.parent)
    known_jsons = folder_json.get(folder_str, set())
    name = photo.name
    ext  = photo.suffix
    stem = photo.stem

    def found(candidate: str) -> bool:
        return candidate.lower() in known_jsons

    def first_glob(prefix: str):
        """Return first json name in folder that starts with prefix (case-insensitive)."""
        pl = prefix.lower()
        for j in known_jsons:
            if j.startswith(pl):
                return j
        return None

    # 1. Standard supplemental-metadata variants
    for suffix in SUPPLEMENTAL_SUFFIXES:
        if found(f"{name}{suffix}.json"):     return f"{name}{suffix}.json"
        if found(f"{name}{suffix}(1).json"):  return f"{name}{suffix}(1).json"
        if found(f"{name}{suffix}(2).json"):  return f"{name}{suffix}(2).json"
        if found(f"{name}{ext}{suffix}.json"):return f"{name}{ext}{suffix}.json"

    # 2. Bare .json sidecar
    if found(f"{stem}.json"):
        return f"{stem}.json"

    # 3. Fuzzy glob (JSON name starts with full media filename)
    hit = first_glob(name)
    if hit:
        return hit
    if len(name) > 40:
        hit = first_glob(name[:40])
        if hit:
            return hit

    # 4. Reverse-truncation: JSON name shorter than media name
    if len(name) > 20:
        for trim in range(1, 9):
            short_stem = stem[:-trim]
            if not short_stem:
                break
            if found(f"{short_stem}.json"):
                return f"{short_stem}.json"
            hit = first_glob(short_stem)
            if hit:
                return hit

    # 5. Strip -edited / (N) suffix
    base_stem = re.sub(r'(?:-edited|[\s_-]?\(\d+\))$', '', stem, flags=re.IGNORECASE).strip()
    if base_stem and base_stem != stem:
        base_name = base_stem + ext
        for suffix in SUPPLEMENTAL_SUFFIXES:
            if found(f"{base_name}{suffix}.json"):    return f"{base_name}{suffix}.json"
            if found(f"{base_name}{suffix}(1).json"): return f"{base_name}{suffix}(1).json"
        if found(f"{base_stem}.json"):
            return f"{base_stem}.json"

    return None


def main():
    print("Parsing structure.txt …")
    folder_json, media_files = parse_structure(STRUCTURE_FILE, TAKEOUT_ROOT)
    total_json = sum(len(v) for v in folder_json.values())
    print(f"  Media files : {len(media_files)}")
    print(f"  JSON files  : {total_json}\n")

    matched   = []
    unmatched = []
    for photo in sorted(media_files):
        if find_json_sim(photo, folder_json):
            matched.append(photo)
        else:
            unmatched.append(photo)

    pct = 100 * len(matched) / len(media_files) if media_files else 0
    print(f"✓ Matched   : {len(matched)}  ({pct:.1f}%)")
    print(f"✗ Unmatched : {len(unmatched)}  ({100-pct:.1f}%)")

    if unmatched:
        print(f"\n── Unmatched files ──")
        for p in unmatched[:50]:
            print(f"  {p.name}")
        out = Path(STRUCTURE_FILE).parent / "sim_unmatched.txt"
        with open(out, "w", encoding="utf-8") as f:
            f.write(f"Unmatched: {len(unmatched)} of {len(media_files)}\n\n")
            for p in unmatched:
                f.write(str(p.name) + "\n")
        print(f"\nSaved → {out}")
    else:
        print("\n✓ PERFECT: every media file matched a JSON sidecar.")


if __name__ == "__main__":
    main()
