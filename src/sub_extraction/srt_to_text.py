#!/usr/bin/env python3
"""
Convert .srt or .vtt subtitle files into clean plain-text transcripts (.txt).

An SRT file is made of blocks like:

    12
    00:01:05,400 --> 00:01:08,200
    May all beings be free from suffering

A WebVTT (.vtt) file is similar but starts with a "WEBVTT" header, may have
"Kind:"/"Language:" metadata lines, cue-settings after the timestamp
(e.g. "align:start position:0%"), and auto-generated captions sprinkle in
inline word-by-word timing tags like "these<00:00:02.15><c> are</c>".

This script removes block numbers, VTT headers/metadata, timestamps and cue
settings, HTML/timing tags (<i>, <b>, <font>, <c>, <00:01:05.400>), position
codes ({\an8}), and the rolling duplicate lines that YouTube auto-generated
captions produce, leaving only the clean spoken text.

Usage:
  python3 srt_to_text.py video.vtt                 # -> video.txt next to it
  python3 srt_to_text.py video.srt                 # .srt also supported
  python3 srt_to_text.py bodhicitta_subtitles/srt  # convert a whole folder
                                                    # (.srt and .vtt files;
                                                    # when both an "*.en.*"
                                                    # and "*.en-orig.*" file
                                                    # exist for the same
                                                    # video, only one is used)
  python3 srt_to_text.py srt_folder -o transcripts # choose output folder
  python3 srt_to_text.py video.srt --timestamps    # keep [hh:mm:ss] prefixes
  python3 srt_to_text.py video.srt --paragraphs    # merge lines into paragraphs

No external libraries needed.
"""

import argparse
import re
import sys
from pathlib import Path

# matches timestamp lines:  00:01:05,400 --> 00:01:08,200
# (also matches VTT timestamps "00:01:05.400 --> 00:01:08.400 align:start ..."
# since we only check the start of the line)
TS_LINE = re.compile(
    r"^(\d{2}:\d{2}:\d{2})[,.]\d{3}\s+-->\s+\d{2}:\d{2}:\d{2}[,.]\d{3}"
)
TAGS = re.compile(r"<[^>]+>")          # <i>, <b>, <font ...>, <c>, <00:01:05.400>
POS = re.compile(r"\{\\an\d\}")        # position codes like {\an8}
# VTT preamble/metadata lines that should be skipped wherever they appear
VTT_META = re.compile(r"^(WEBVTT|Kind:|Language:|STYLE|NOTE|Region:)", re.IGNORECASE)


def parse_srt(path: Path) -> list[tuple[str, str]]:
    """Return a list of (start_time, text) pairs, one per subtitle block.

    Handles both .srt and WebVTT (.vtt) input.
    """
    blocks = []
    cur_time, cur_lines = None, []
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    for raw in text.splitlines() + [""]:          # sentinel blank line at end
        line = raw.strip()
        m = TS_LINE.match(line)
        if m:
            cur_time = m.group(1)
            cur_lines = []
        elif line == "":
            if cur_time is not None and cur_lines:
                blocks.append((cur_time, "\n".join(cur_lines)))
            cur_time, cur_lines = None, []
        elif line.isdigit() and cur_time is None:
            continue                              # block counter
        elif cur_time is None and VTT_META.match(line):
            continue                              # WEBVTT/Kind/Language/etc.
        elif cur_time is not None:
            clean = POS.sub("", TAGS.sub("", line)).strip()
            if clean:
                cur_lines.append(clean)
    return blocks


def dedupe(blocks: list[tuple[str, str]]) -> list[tuple[str, str]]:
    """Remove the rolling duplicates that YouTube auto-captions create.

    Auto-captions repeat each line in two consecutive blocks, and blocks
    often contain 'previous line + new line'. We keep a small window of
    recently seen lines and drop any line we've just seen.
    """
    out, recent = [], []
    for time, text in blocks:
        kept_parts = []
        for part in text.split("\n"):
            part = part.strip()
            if part and part not in recent:
                kept_parts.append(part)
                recent.append(part)
                recent = recent[-4:]              # sliding window
        # also handle blocks given as a single merged string
        if not kept_parts and text.strip() and text.strip() not in recent:
            kept_parts = [text.strip()]
            recent.append(text.strip())
            recent = recent[-4:]
        if kept_parts:
            out.append((time, " ".join(kept_parts)))
    # second pass: drop consecutive identical lines
    final, prev = [], None
    for time, text in out:
        if text != prev:
            final.append((time, text))
            prev = text
    return final


def to_text(blocks: list[tuple[str, str]], timestamps: bool, paragraphs: bool) -> str:
    if timestamps:
        return "\n".join(f"[{t}] {x}" for t, x in blocks)
    lines = [x for _, x in blocks]
    if not paragraphs:
        return "\n".join(lines)
    # merge into paragraphs, starting a new one roughly every ~80 words
    paras, cur, count = [], [], 0
    for line in lines:
        cur.append(line)
        count += len(line.split())
        if count >= 80 and line.rstrip().endswith((".", "!", "?", "।", "॥")):
            paras.append(" ".join(cur))
            cur, count = [], 0
    if cur:
        paras.append(" ".join(cur))
    return "\n\n".join(paras)


def convert_file(src: Path, dst: Path, timestamps: bool, paragraphs: bool):
    blocks = dedupe(parse_srt(src))
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(to_text(blocks, timestamps, paragraphs), encoding="utf-8")
    print(f"  {src} -> {dst}  ({len(blocks)} lines)")


def collect_subtitle_files(root: Path) -> list[Path]:
    """Find .srt/.vtt files under root, picking one file per video.

    yt-dlp typically writes both a "<id>.en.vtt" (or .srt) and an
    "<id>.en-orig.vtt" file with identical content when no manual subtitles
    exist. To avoid producing duplicate transcripts, group files by
    (folder, video id) -- the part of the filename before the first "." --
    and keep only one per group, preferring a non "-orig" file and .srt over
    .vtt.
    """
    files = list(root.rglob("*.srt")) + list(root.rglob("*.vtt"))
    groups: dict[tuple[Path, str], list[Path]] = {}
    for f in files:
        video_id = f.name.split(".")[0]
        groups.setdefault((f.parent, video_id), []).append(f)

    def rank(p: Path) -> tuple[int, int]:
        return ("-orig" in p.stem, p.suffix.lower() != ".srt")

    chosen = [sorted(group, key=rank)[0] for group in groups.values()]
    return sorted(chosen)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", help=".srt/.vtt file or a folder containing such files")
    ap.add_argument("-o", "--output", default=None,
                    help="output .txt file or folder (default: next to input)")
    ap.add_argument("--timestamps", action="store_true",
                    help="keep [hh:mm:ss] at the start of each line")
    ap.add_argument("--paragraphs", action="store_true",
                    help="merge lines into readable paragraphs")
    args = ap.parse_args()

    src = Path(args.input)
    if not src.exists():
        sys.exit(f"error: {src} does not exist")

    if src.is_file():
        dst = Path(args.output) if args.output else src.with_suffix(".txt")
        convert_file(src, dst, args.timestamps, args.paragraphs)
    else:
        out_root = Path(args.output) if args.output else src.parent / "txt"
        srts = collect_subtitle_files(src)
        if not srts:
            sys.exit(f"error: no .srt or .vtt files found under {src}")
        print(f"Converting {len(srts)} files ...")
        for f in srts:
            rel = f.relative_to(src)
            convert_file(f, (out_root / rel).with_suffix(".txt"),
                         args.timestamps, args.paragraphs)
        print(f"Done. Transcripts in {out_root}/")


if __name__ == "__main__":
    main()
