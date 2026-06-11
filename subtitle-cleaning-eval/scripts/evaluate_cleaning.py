#!/usr/bin/env python3
"""
evaluate_cleaning.py - Compare raw .srt/.vtt subtitle files against the
cleaned .txt transcripts a subtitle-cleaning script (e.g. srt_to_text.py)
produced from them, and report cleaning-quality stats.

For every video this reports:
  - raw_lines / raw_words   - counts from the raw subtitle, AFTER stripping
                               timestamps/headers/tags but BEFORE any dedup
                               (so rolling auto-caption duplicates are still
                               present)
  - clean_lines / clean_words - counts from the cleaned .txt
  - pct_lines_removed / pct_words_removed - how much shrinkage cleaning did
  - content_retention        - % of the word BIGRAMS (consecutive word
                                pairs) seen in the raw subtitle that still
                                appear somewhere in the cleaned transcript.
                                This is the key quality signal: dedup of
                                repeated auto-caption lines should drop
                                pct_words_removed a lot while keeping
                                content_retention high. If content_retention
                                is low, cleaning likely dropped real spoken
                                content, not just duplicates.
  - flag                     - OK / LOW_REDUCTION / CONTENT_LOSS /
                                EMPTY_OUTPUT / MISSING_TXT

This script is self-contained (it does not import srt_to_text.py) so it can
be run against any srt/ + txt/ folder pair produced by a similar pipeline.

Usage:
  python3 evaluate_cleaning.py srt_folder txt_folder
  python3 evaluate_cleaning.py srt_folder txt_folder -o report.csv
  python3 evaluate_cleaning.py video.en.srt video.en.txt   # single pair
"""

import argparse
import csv
import re
import sys
from pathlib import Path

# Same patterns srt_to_text.py uses to strip structure from .srt/.vtt files.
TS_LINE = re.compile(
    r"^(\d{2}:\d{2}:\d{2})[,.]\d{3}\s+-->\s+\d{2}:\d{2}:\d{2}[,.]\d{3}"
)
TAGS = re.compile(r"<[^>]+>")
POS = re.compile(r"\{\\an\d\}")
VTT_META = re.compile(r"^(WEBVTT|Kind:|Language:|STYLE|NOTE|Region:)", re.IGNORECASE)
WORD_RE = re.compile(r"[\w'-]+", re.UNICODE)

# Thresholds used to set the `flag` field. Tweak these if a particular
# pipeline's "normal" numbers differ a lot from these defaults.
CONTENT_LOSS_THRESHOLD = 85.0   # below this content_retention% -> CONTENT_LOSS
LOW_REDUCTION_THRESHOLD = 5.0   # below this pct_lines_removed -> LOW_REDUCTION
LOW_REDUCTION_MIN_LINES = 20    # ...but only flag if the raw file is non-trivial


def parse_raw(path: Path) -> list[str]:
    """Return raw content lines from a .srt/.vtt file, BEFORE dedup --
    block numbers, VTT headers, timestamps, tags and position codes are
    stripped, but rolling auto-caption duplicates are left intact."""
    lines = []
    cur_time = None
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    for raw in text.splitlines():
        line = raw.strip()
        m = TS_LINE.match(line)
        if m:
            cur_time = m.group(1)
            continue
        if line == "":
            cur_time = None
            continue
        if line.isdigit() and cur_time is None:
            continue
        if cur_time is None and VTT_META.match(line):
            continue
        if cur_time is not None:
            clean = POS.sub("", TAGS.sub("", line)).strip()
            if clean:
                lines.append(clean)
    return lines


def words(text: str) -> list[str]:
    return [w.lower() for w in WORD_RE.findall(text)]


def bigrams(tokens: list[str]) -> set[tuple[str, str]]:
    """Return the set of consecutive word pairs in a token list."""
    return set(zip(tokens, tokens[1:]))


def find_pairs(srt_dir: Path, txt_dir: Path) -> list[tuple[Path, Path | None, str]]:
    """Find (raw_file, txt_file_or_None, video_id) for every video under
    srt_dir, picking one raw file per video.

    Preference order (lowest rank wins): a "canonical" `<video_id>.<lang>`
    file (exactly one extra dot-separated segment, e.g. "<id>.en.srt")
    beats any extra-suffixed variant (e.g. "<id>.en.clean.srt",
    "<id>.en-orig.vtt"); among canonical files, .srt beats .vtt.

    The matching .txt is looked up the same way: first the exact
    `<raw_stem>.txt`, then the canonical `<video_id>.<lang>.txt` in the
    corresponding folder, ignoring any extra-suffixed .txt variants
    (e.g. "*.corrected.txt", "*.manual.txt") that some workflows add
    alongside the pipeline's own output.
    """
    files = list(srt_dir.rglob("*.srt")) + list(srt_dir.rglob("*.vtt"))
    groups: dict[tuple[Path, str], list[Path]] = {}
    for f in files:
        video_id = f.name.split(".")[0]
        groups.setdefault((f.parent, video_id), []).append(f)

    def is_extra_variant(p: Path, video_id: str) -> bool:
        # "<id>.en.srt" -> rest = "en" (canonical); "<id>.en.clean.srt" or
        # "<id>.en-orig.vtt" -> rest contains "." or "-orig" -> extra variant
        rest = p.stem[len(video_id):].lstrip(".")
        return "." in rest or "-orig" in rest

    def rank(p: Path, video_id: str) -> tuple[bool, bool]:
        return (is_extra_variant(p, video_id), p.suffix.lower() != ".srt")

    pairs = []
    for (folder, video_id), group in groups.items():
        chosen = sorted(group, key=lambda p: rank(p, video_id))[0]
        rel = chosen.relative_to(srt_dir)
        txt_path = (txt_dir / rel).with_suffix(".txt")
        if not txt_path.exists():
            txt_dir_for_video = txt_dir / rel.parent
            if txt_dir_for_video.exists():
                candidates = sorted(
                    txt_dir_for_video.glob(f"{video_id}*.txt"),
                    key=lambda p: is_extra_variant(p, video_id),
                )
                txt_path = candidates[0] if candidates else None
        pairs.append((chosen, txt_path if txt_path and txt_path.exists() else None, video_id))
    return sorted(pairs, key=lambda p: p[2])


def evaluate_pair(raw_path: Path, txt_path: Path | None) -> dict:
    raw_lines = parse_raw(raw_path)
    raw_words = words("\n".join(raw_lines))
    raw_bigrams = bigrams(raw_words)

    if txt_path is None or not txt_path.exists():
        return {
            "raw_lines": len(raw_lines),
            "raw_words": len(raw_words),
            "clean_lines": 0,
            "clean_words": 0,
            "pct_lines_removed": "",
            "pct_words_removed": "",
            "content_retention": "",
            "flag": "MISSING_TXT",
        }

    clean_text = txt_path.read_text(encoding="utf-8", errors="replace")
    clean_lines = [l for l in clean_text.splitlines() if l.strip()]
    clean_words = words(clean_text)
    clean_bigrams = bigrams(clean_words)

    pct_lines_removed = (
        (len(raw_lines) - len(clean_lines)) / len(raw_lines) * 100
        if raw_lines else 0.0
    )
    pct_words_removed = (
        (len(raw_words) - len(clean_words)) / len(raw_words) * 100
        if raw_words else 0.0
    )
    content_retention = (
        len(raw_bigrams & clean_bigrams) / len(raw_bigrams) * 100
        if raw_bigrams else 100.0
    )

    flag = "OK"
    if not clean_lines and raw_lines:
        flag = "EMPTY_OUTPUT"
    elif content_retention < CONTENT_LOSS_THRESHOLD:
        flag = "CONTENT_LOSS"
    elif (pct_lines_removed < LOW_REDUCTION_THRESHOLD
          and len(raw_lines) > LOW_REDUCTION_MIN_LINES):
        flag = "LOW_REDUCTION"

    return {
        "raw_lines": len(raw_lines),
        "raw_words": len(raw_words),
        "clean_lines": len(clean_lines),
        "clean_words": len(clean_words),
        "pct_lines_removed": round(pct_lines_removed, 1),
        "pct_words_removed": round(pct_words_removed, 1),
        "content_retention": round(content_retention, 1),
        "flag": flag,
    }


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("srt", help="raw .srt/.vtt file, or a folder of them")
    ap.add_argument("txt", help="cleaned .txt file, or the matching folder")
    ap.add_argument("-o", "--output", help="write a CSV report to this path")
    args = ap.parse_args()

    srt_path, txt_path = Path(args.srt), Path(args.txt)
    if not srt_path.exists():
        sys.exit(f"error: {srt_path} does not exist")

    if srt_path.is_file():
        vid = srt_path.name.split(".")[0]
        rows = [(vid, evaluate_pair(srt_path, txt_path if txt_path.exists() else None))]
    else:
        pairs = find_pairs(srt_path, txt_path)
        if not pairs:
            sys.exit(f"error: no .srt/.vtt files found under {srt_path}")
        rows = [(vid, evaluate_pair(raw, txt)) for raw, txt, vid in pairs]

    header = ["video_id", "raw_lines", "raw_words", "clean_lines", "clean_words",
              "pct_lines_removed", "pct_words_removed", "content_retention", "flag"]

    print(f"{'video_id':<16} {'raw_ln':>7} {'clean_ln':>9} {'%lines-':>8} "
          f"{'%words-':>8} {'content%':>9}  flag")
    for vid, r in rows:
        print(f"{vid:<16} {r['raw_lines']:>7} {r['clean_lines']:>9} "
              f"{str(r['pct_lines_removed']):>8} {str(r['pct_words_removed']):>8} "
              f"{str(r['content_retention']):>9}  {r['flag']}")

    n_ok = sum(1 for _, r in rows if r["flag"] == "OK")
    print(f"\n{n_ok}/{len(rows)} videos OK")
    flagged = [(vid, r["flag"]) for vid, r in rows if r["flag"] != "OK"]
    if flagged:
        print("Flagged:")
        for vid, flag in flagged:
            print(f"  {vid}: {flag}")

    if args.output:
        with open(args.output, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=header)
            w.writeheader()
            for vid, r in rows:
                w.writerow({"video_id": vid, **r})
        print(f"\nCSV report written to {args.output}")


if __name__ == "__main__":
    main()
