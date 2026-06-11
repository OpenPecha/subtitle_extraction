"""Deduplicate YouTube rolling auto-captions in SRT files.

YouTube auto-captions use a rolling 2-line window: each cue repeats the
previous line and adds a new one, with tiny ~10ms filler cues in between.
This script keeps only the new text per cue and rebuilds clean timings.
The deduplication itself is the shared sliding-window implementation in
srt_to_text.py; this script adds filler-cue removal and timing rebuild,
and writes .srt output (not plain text).

Usage:
    python dedupe_srt.py <input.srt> [output.srt]
    python dedupe_srt.py --all <root_dir>   # processes every .srt/.vtt under
                                            # root_dir -> *.clean.<ext>
"""
import re
import sys
from pathlib import Path

try:
    from sub_extraction.srt_to_text import dedupe as dedupe_blocks
except ImportError:  # running as a standalone script next to srt_to_text.py
    from srt_to_text import dedupe as dedupe_blocks

TS = re.compile(r"(\d{2}):(\d{2}):(\d{2})[,.](\d{3}) --> (\d{2}):(\d{2}):(\d{2})[,.](\d{3})")


def to_ms(h, m, s, ms):
    return ((int(h) * 60 + int(m)) * 60 + int(s)) * 1000 + int(ms)


def fmt(ms):
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def parse(path):
    cues = []
    block = []
    for line in Path(path).read_text(encoding="utf-8", errors="replace").splitlines() + [""]:
        if line.strip() == "":
            if block:
                m, i = None, None
                for idx, l in enumerate(block):
                    m = TS.match(l)
                    if m:
                        i = idx
                        break
                if m:
                    text = [l for l in block[i + 1:]]
                    cues.append((to_ms(*m.groups()[:4]), to_ms(*m.groups()[4:]), text))
                block = []
        else:
            block.append(line)
    return cues


def dedupe(cues, min_dur_ms=100):
    """Drop filler cues, then dedupe rolling text via the shared
    sliding-window implementation in srt_to_text.dedupe()."""
    # Keep real cues only (filler cues last ~10ms).
    real = [(start, end, lines) for start, end, lines in cues
            if end - start >= min_dur_ms]
    # Run the shared dedup; use the cue index as the pass-through "time" key
    # so we can map deduped blocks back to their original timings.
    blocks = [(idx, "\n".join(lines)) for idx, (_, _, lines) in enumerate(real)]
    kept = []
    for idx, text in dedupe_blocks(blocks):
        start, end, _ = real[idx]
        kept.append([start, end, text])
    # Extend each cue to the next cue's start for smoother display.
    for i in range(len(kept) - 1):
        kept[i][1] = max(kept[i][1], min(kept[i + 1][0], kept[i][0] + 7000))
    return kept


def write(cues, path):
    out = []
    for n, (start, end, text) in enumerate(cues, 1):
        out.append(f"{n}\n{fmt(start)} --> {fmt(end)}\n{text}\n")
    Path(path).write_text("\n".join(out), encoding="utf-8")


def main():
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        sys.exit(1)
    if args[0] == "--all":
        root = Path(args[1])
        subs = sorted(set(root.rglob("*.srt")) | set(root.rglob("*.vtt")))
        for sub in subs:
            if sub.stem.endswith(".clean"):
                continue  # skip output files from a previous run
            outp = sub.with_name(sub.stem + ".clean" + sub.suffix)
            cues = dedupe(parse(sub))
            write(cues, outp)
            print(f"{sub.parent.name}: {len(cues)} cues -> {outp.name}")
    else:
        inp = Path(args[0])
        outp = Path(args[1]) if len(args) > 1 else inp.with_name(inp.stem + ".clean.srt")
        cues = dedupe(parse(inp))
        write(cues, outp)
        print(f"{len(cues)} cues -> {outp}")


if __name__ == "__main__":
    main()
