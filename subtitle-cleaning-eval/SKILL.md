---
name: subtitle-cleaning-eval
description: >
  Evaluate how well a subtitle-to-text cleaning script (e.g. srt_to_text.py
  or any pipeline that converts .srt/.vtt subtitles into plain-text
  transcripts) actually cleaned its output. Compares each raw .srt/.vtt
  file against its cleaned .txt transcript and reports line/word reduction
  percentages plus a "content retention" score that flags transcripts where
  cleaning may have dropped real spoken content (CONTENT_LOSS), produced an
  empty file (EMPTY_OUTPUT), or barely changed anything (LOW_REDUCTION,
  often meaning duplicate rolling auto-captions weren't removed). Use this
  whenever the user wants to QA, audit, sanity-check, spot-check, or "track
  the difference" / "check the cleaning quality" between raw subtitles and
  their cleaned transcripts -- for a single video or an entire srt/ + txt/
  folder tree.
---

# Subtitle Cleaning Evaluation

This skill audits the *output* of a subtitle-cleaning step (raw `.srt`/`.vtt`
-> cleaned `.txt`). It does not do the cleaning itself -- it tells you
whether the cleaning did a good job.

## Why this matters

A subtitle cleaner typically does two things:
1. Strips structure: block numbers, timestamps, VTT headers, `<c>`/`<i>`
   tags, position codes.
2. Dedupes: YouTube auto-captions repeat each line across consecutive
   blocks ("rolling captions"), so a good cleaner removes those repeats.

Both of these legitimately shrink the output a lot. The risk is a cleaner
that's *too* aggressive and throws away real spoken words along with the
duplicates -- and that's easy to miss by skimming a few transcripts.

## How to run it

```bash
python3 scripts/evaluate_cleaning.py <srt_dir> <txt_dir>
```

- `<srt_dir>` and `<txt_dir>` should mirror each other, e.g.
  `bodhicitta_subtitles/srt` and `bodhicitta_subtitles/txt`. The script
  matches files the same way `srt_to_text.py` does: one raw file per video
  ID, preferring `.srt` over `.vtt` and skipping `-orig` duplicates.
- For a single video, pass the two files directly:
  ```bash
  python3 scripts/evaluate_cleaning.py video.en.srt video.en.txt
  ```
- Add `-o report.csv` to also save a CSV with one row per video.

The script is self-contained -- it doesn't import the project's cleaning
script, so it works on any srt/+txt folder pair with the same naming
convention.

## Reading the output

For each video the script prints:

| column | meaning |
|---|---|
| `raw_lines` / `raw_words` | counts from the raw subtitle, structure stripped, but **before dedup** (rolling duplicates still counted) |
| `clean_lines` / `clean_words` | counts from the `.txt` |
| `pct_lines_removed` / `pct_words_removed` | how much cleaning shrank the file |
| `content_retention` | % of the word *bigrams* (consecutive word pairs) in the raw subtitle that still appear somewhere in the cleaned transcript |
| `flag` | `OK`, `LOW_REDUCTION`, `CONTENT_LOSS`, `EMPTY_OUTPUT`, or `MISSING_TXT` |

`content_retention` is the key signal. It is a bigram-overlap score: all
consecutive word pairs are extracted from both the raw and cleaned text,
and the score is the percentage of raw bigrams still present in the cleaned
transcript. Dedup of auto-captions should make `pct_words_removed` large
(often 50%+) while `content_retention` stays high -- the word *sequences*
should survive even though raw word counts (which double/triple-count
repeated words) drop a lot. Bigram overlap is stricter than a plain
unique-word check: it also catches cleaners that keep the vocabulary but
scramble or drop parts of sentences.

## Acting on flags

- **OK** -- nothing to do.
- **CONTENT_LOSS** (`content_retention` < 85%) -- the cleaner likely dropped
  real words, not just duplicates. Open the raw and cleaned files for that
  video side by side and look for whole sentences or sections present in
  the raw subtitle but missing from the `.txt`.
- **LOW_REDUCTION** (`pct_lines_removed` < 5% on a file with > 20 raw
  lines) -- cleaning barely changed the file. If the raw subtitle was
  manually-written (not auto-generated), this can be normal -- manual subs
  rarely have rolling duplicates. If the raw subtitle *is* auto-generated
  (look for `<c>` tags or repeated lines in the raw file), this suggests
  the dedup step isn't triggering and should be investigated.
- **EMPTY_OUTPUT** -- the cleaner produced nothing from a non-empty raw
  file; something is broken for that video.
- **MISSING_TXT** -- a raw subtitle has no corresponding `.txt` yet (the
  conversion step hasn't run for that video).

## Tuning thresholds

The thresholds (`CONTENT_LOSS_THRESHOLD`, `LOW_REDUCTION_THRESHOLD`,
`LOW_REDUCTION_MIN_LINES`) are constants near the top of
`scripts/evaluate_cleaning.py`. If a particular pipeline's normal numbers
differ a lot from the defaults (85%, 5%, 20 lines), adjust them there
rather than re-deriving thresholds by hand each time.
