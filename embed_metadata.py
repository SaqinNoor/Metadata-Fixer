"""
Google Takeout Metadata Embedder
=================================
Embeds photoTakenTime from Google's JSON sidecar files into image/video EXIF data.

Handles all naming patterns found in this collection:
  - photo.jpg.supplemental-metadata.json          (standard)
  - photo.jpg.supplemental-metadata(1).json       (duplicate photo, version 2)
  - photo.jpg.supplemental-metadata(2).json       (duplicate photo, version 3)
  - photo.jpg.supplemental-met.json               (truncated, various lengths)
  - photo.jpg.su.json / photo.jpg.s.json          (heavily truncated)
  - photo.jpg..json                               (extreme truncation)
  - .trashed-TIMESTAMP-photo.jpg.su.json          (trashed files)
  - photo.jpg.jpg.supplemental-metadata.json      (double-extension edge case)
  - metadata.json                                 (album-level, skipped)

Usage:
  1. Set TAKEOUT_FOLDER below to your Takeout path
  2. Run:  python embed_metadata.py
  3. Check the summary and the log files created alongside the script

Requirements:
  - Python 3.7+
  - ExifTool installed and on PATH (https://exiftool.org)
"""

import os
import json
import re
import subprocess
import sys
import datetime
from pathlib import Path

# ═══════════════════════════════════════════════════════════════
#  CONFIGURATION  — edit this path
# ═══════════════════════════════════════════════════════════════

TAKEOUT_FOLDER = r"D:\Takeout\Takeout"

# Set to True to do a dry run (no files are changed, just logging)
DRY_RUN = False

# Set to True to also process .trashed-* files (deleted from Google Photos)
PROCESS_TRASHED = False

# ═══════════════════════════════════════════════════════════════
#  CONSTANTS
# ═══════════════════════════════════════════════════════════════

IMAGE_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp',
                    '.tif', '.tiff', '.heic', '.bmp'}
VIDEO_EXTENSIONS = {'.mp4', '.mov', '.3gp', '.mpg', '.mpeg', '.m4v'}
ALL_EXTENSIONS   = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS

# All known truncations of ".supplemental-metadata" that Google produces.
# Sorted longest-first so we always try the most specific match first.
SUPPLEMENTAL_SUFFIXES = [
    ".supplemental-metadata",
    ".supplemental-metadat",
    ".supplemental-metada",
    ".supplemental-metad",
    ".supplemental-meta",
    ".supplemental-met",
    ".supplemental-me",
    ".supplemental-m",
    ".supplemental-",
    ".supplemental",
    ".supplemen",
    ".supple",
    ".suppl",
    ".supplement",
    ".su",
    ".s",
    ".",    # extreme truncation: photo.jpg..json
]

# ═══════════════════════════════════════════════════════════════
#  JSON FINDER
# ═══════════════════════════════════════════════════════════════

def glob_escape(s):
    """Escape glob special characters so we can use them in Path.glob()."""
    return re.sub(r'([\[\]*?])', r'[\1]', s)


def find_json(photo: Path):
    """
    Try every known Google Takeout JSON naming variant for a given photo.
    Returns the Path of the first match, or None.
    """
    folder = photo.parent
    name   = photo.name      # e.g. "IMG_1234.jpg"
    ext    = photo.suffix    # e.g. ".jpg"

    candidates = []

    for suffix in SUPPLEMENTAL_SUFFIXES:
        # Standard:   photo.jpg.supplemental-metadata.json
        candidates.append(folder / f"{name}{suffix}.json")
        # Duplicates: photo.jpg.supplemental-metadata(1).json
        candidates.append(folder / f"{name}{suffix}(1).json")
        candidates.append(folder / f"{name}{suffix}(2).json")
        # Double-extension edge case: photo.jpg.jpg.supplemental-metadata.json
        candidates.append(folder / f"{name}{ext}{suffix}.json")

    # Fuzzy glob fallback — catches any truncation length not listed above
    try:
        safe = glob_escape(name)
        for f in folder.glob(f"{safe}*.json"):
            candidates.append(f)
        # Also try with first 40 chars for very long filenames
        if len(name) > 40:
            safe40 = glob_escape(name[:40])
            for f in folder.glob(f"{safe40}*.json"):
                candidates.append(f)
    except Exception:
        pass  # unusual filenames can cause glob to fail; listed candidates still tried

    # Return first existing match (deduplicated, preserving order)
    seen = set()
    for c in candidates:
        if c in seen:
            continue
        seen.add(c)
        if c.exists():
            return c

    return None


# ═══════════════════════════════════════════════════════════════
#  TIMESTAMP EXTRACTION
# ═══════════════════════════════════════════════════════════════

def get_timestamp(meta: dict):
    """
    Return the best Unix timestamp string from Google's JSON metadata.
    Prefers photoTakenTime over creationTime.
    Returns None if no valid timestamp is found.
    """
    for key in ("photoTakenTime", "creationTime"):
        entry = meta.get(key, {})
        ts = entry.get("timestamp")
        if ts and str(ts) not in ("0", "", "null"):
            try:
                int(ts)   # validate it's a real integer
                return str(ts)
            except (ValueError, TypeError):
                continue
    return None


# ═══════════════════════════════════════════════════════════════
#  EXIFTOOL COMMAND BUILDER
# ═══════════════════════════════════════════════════════════════

def build_cmd(photo: Path, timestamp: str, dry_run: bool):
    """Build the exiftool command list to embed a Unix timestamp into a file."""
    is_video = photo.suffix.lower() in VIDEO_EXTENSIONS

    if is_video:
        tags = [
            f"-CreateDate@={timestamp}",
            f"-ModifyDate@={timestamp}",
            f"-TrackCreateDate@={timestamp}",
            f"-TrackModifyDate@={timestamp}",
            f"-MediaCreateDate@={timestamp}",
            f"-MediaModifyDate@={timestamp}",
        ]
    else:
        tags = [
            f"-DateTimeOriginal@={timestamp}",
            f"-CreateDate@={timestamp}",
            f"-ModifyDate@={timestamp}",
        ]

    cmd = ["exiftool"]
    if not dry_run:
        cmd.append("-overwrite_original")
    cmd += tags
    cmd.append(str(photo))
    return cmd


# ═══════════════════════════════════════════════════════════════
#  MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    folder = Path(TAKEOUT_FOLDER)

    # ── Preflight checks ──────────────────────────────────────
    if not folder.exists():
        print(f"ERROR: Folder not found:\n  {folder}")
        sys.exit(1)

    try:
        ver = subprocess.run(["exiftool", "-ver"],
                             capture_output=True, text=True, check=True)
        print(f"ExifTool version: {ver.stdout.strip()}")
    except FileNotFoundError:
        print("ERROR: exiftool not found on PATH.")
        print("Download from https://exiftool.org, rename executable to exiftool.exe,")
        print("and place it in C:\\Windows or another folder on your PATH.")
        sys.exit(1)

    if DRY_RUN:
        print("\n*** DRY RUN MODE — no files will be modified ***\n")

    # ── Collect all media files ───────────────────────────────
    all_media = []
    for p in folder.rglob("*"):
        if not p.is_file():
            continue
        if p.suffix.lower() not in ALL_EXTENSIONS:
            continue
        if not PROCESS_TRASHED and p.name.startswith(".trashed"):
            continue
        all_media.append(p)

    total = len(all_media)
    print(f"Found {total} media files under:\n  {folder}\n")
    if total == 0:
        print("Nothing to process. Check your TAKEOUT_FOLDER path.")
        sys.exit(0)

    # ── Process each file ─────────────────────────────────────
    updated = []
    no_json = []
    no_ts   = []
    failed  = []

    for i, photo in enumerate(sorted(all_media), 1):
        prefix = f"[{i:>5}/{total}]"

        # Find matching JSON sidecar
        json_path = find_json(photo)
        if not json_path:
            no_json.append(photo)
            print(f"{prefix} ✗ NO JSON   {photo.name}")
            continue

        # Parse JSON
        try:
            with open(json_path, encoding="utf-8") as f:
                meta = json.load(f)
        except Exception as e:
            failed.append((photo, f"JSON parse error: {e}"))
            print(f"{prefix} ✗ BAD JSON  {photo.name} — {e}")
            continue

        # Extract timestamp
        timestamp = get_timestamp(meta)
        if not timestamp:
            no_ts.append(photo)
            print(f"{prefix} ✗ NO DATE   {photo.name}")
            continue

        # Format date for display
        try:
            dt = datetime.datetime.utcfromtimestamp(int(timestamp))
            dt_str = dt.strftime("%Y-%m-%d %H:%M UTC")
        except Exception:
            dt_str = f"ts={timestamp}"

        # Dry run — don't actually call ExifTool
        if DRY_RUN:
            updated.append(photo)
            print(f"{prefix} ~ DRY RUN   {photo.name}  →  {dt_str}")
            continue

        # Run ExifTool
        cmd = build_cmd(photo, timestamp, dry_run=False)
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except subprocess.TimeoutExpired:
            failed.append((photo, "ExifTool timed out"))
            print(f"{prefix} ✗ TIMEOUT   {photo.name}")
            continue

        if result.returncode == 0:
            updated.append(photo)
            print(f"{prefix} ✓ OK        {photo.name}  →  {dt_str}")
        else:
            err = (result.stderr or result.stdout).strip()
            failed.append((photo, err))
            print(f"{prefix} ✗ FAILED    {photo.name} — {err}")

    # ── Summary ───────────────────────────────────────────────
    print("\n" + "═" * 70)
    print("  SUMMARY")
    print("═" * 70)
    print(f"  ✓ Updated successfully : {len(updated)}")
    print(f"  ✗ No JSON sidecar      : {len(no_json)}")
    print(f"  ✗ No valid timestamp   : {len(no_ts)}")
    print(f"  ✗ Failed (ExifTool)    : {len(failed)}")
    if not PROCESS_TRASHED:
        trashed_count = sum(
            1 for p in folder.rglob("*")
            if p.is_file()
            and p.name.startswith(".trashed")
            and p.suffix.lower() in ALL_EXTENSIONS
        )
        if trashed_count:
            print(f"  ○ Trashed files skipped: {trashed_count}"
                  f"  (set PROCESS_TRASHED=True to include them)")
    print("═" * 70)

    # ── Write log files next to the script ───────────────────
    log_dir = Path(__file__).parent

    if no_json:
        p = log_dir / "log_no_json.txt"
        with open(p, "w", encoding="utf-8") as f:
            f.write("Files with no matching JSON sidecar\n")
            f.write("These may need manual attention.\n\n")
            for item in no_json:
                f.write(f"{item}\n")
        print(f"\n  Missing JSON logged → {p}")

    if failed:
        p = log_dir / "log_failed.txt"
        with open(p, "w", encoding="utf-8") as f:
            f.write("Files that failed during ExifTool processing\n\n")
            for item, err in failed:
                f.write(f"{item}\n    Error: {err}\n\n")
        print(f"  Failed files logged  → {p}")

    if no_ts:
        p = log_dir / "log_no_timestamp.txt"
        with open(p, "w", encoding="utf-8") as f:
            f.write("Files whose JSON sidecar contained no usable timestamp\n\n")
            for item in no_ts:
                f.write(f"{item}\n")
        print(f"  No-timestamp logged  → {p}")

    print()
    if len(updated) == total:
        print("  All files processed successfully! Ready to upload.")
    else:
        remaining = total - len(updated)
        print(f"  {remaining} file(s) could not be updated — check the log files above.")


if __name__ == "__main__":
    main()
