---
name: dharma-transcript-correction
description: Corrects speech-recognition (ASR) errors in auto-generated YouTube subtitle transcripts of Buddhist/Dharma teachings, while preserving the exact line/structure so the text can be mapped back to SRT timestamps. Works on both plain-text transcripts (.txt) and subtitle files (.srt), preserving timestamps and indices in the latter. Use this skill whenever the user wants to clean, fix, correct, or improve an extracted subtitle transcript or .srt file, mentions garbled Buddhist terms (e.g. "bodhisattva" misheard as "Buddhist thought was"), auto-generated captions, YouTube transcripts, or ASR errors — even if they just say "fix this transcript" or "fix this srt" or "make a corrected version like my manual edit".
---

# Dharma Transcript Correction

## Purpose

YouTube's auto-captioning mishears Sanskrit/Tibetan Buddhist terminology and
accented English. Teachers are often Tibetan speakers, so terms like
*bodhicitta*, *bodhisattva*, *paramita* get mapped to similar-sounding English
("booty toois", "Buddha softball", "parameter"). This skill restores the
intended words while leaving everything else exactly as spoken.

## Critical constraint: preserve line/structure

The transcript lines correspond 1:1 to subtitle timing blocks in the source
.srt file. If lines are merged, split, added, or removed, the text can no
longer be re-aligned to timestamps. Therefore:

- Output exactly the same number of lines as the input.
- Never move words across line boundaries, even when a sentence would read
  better — a correction may change a line's length, but each line's content
  must correspond to the same spoken segment.
- Keep non-speech markers like `[Music]` or `[Applause]` unchanged.

### Additional rules when correcting a .srt file directly

A .srt file is made of blocks separated by blank lines, each block being:

```
<index number>
<start> --> <end>
<one or more lines of subtitle text>
```

When correcting a .srt:

- Only edit the subtitle **text** lines. Never change index numbers,
  timestamp lines (`00:00:01,234 --> 00:00:04,000`), or the blank lines
  separating blocks.
- Preserve the exact number of text lines within each block — if a block has
  two text lines, the corrected block must also have two text lines, with the
  same word-to-line split as before (apply the same "don't move words across
  line boundaries" rule, but per-block instead of per-file).
- Do not renumber blocks, merge blocks, or split blocks, even if a sentence
  spans multiple blocks awkwardly.
- Leave the file's line-ending/encoding conventions as-is where possible.

## What to correct (and what not to)

Fix only what the speech recognizer got wrong. The goal is a faithful record
of what the teacher actually said — not polished prose. Do not fix the
speaker's grammar, do not add punctuation, do not rephrase.

Error categories to fix, in rough order of frequency:

1. **Garbled dharma terms** — the most damaging errors. ASR maps unknown
   Sanskrit/Tibetan words to English sound-alikes, sometimes absurdly
   ("non ass of buddha softball" = "known as bodhisattva"). Read the line
   aloud mentally and match against the glossary in
   `references/glossary.md` (read it before correcting).
2. **Homophones and near-homophones** — "profession" for *perfection*,
   "parameter" for *paramita*, "more discipline" for *moral discipline*,
   "part" for *path*, "ensured" for *in short*.
3. **Misheard ordinals and numbers** — "fought one" = *fourth one*,
   "feat one" = *fifth one*. Use list context: if the teacher is enumerating
   six perfections, the ordinals must run first through sixth.
4. **Accent artifacts** — Tibetan-accented English often drops or shifts
   consonants; e.g. "literate/little meaning" for *literal meaning*.

When unsure whether a strange phrase is an ASR error or the speaker's actual
wording, prefer leaving it unchanged — a missed correction is recoverable, a
wrong "correction" silently corrupts the teaching.

## Workflow

1. Read `references/glossary.md` for the term list and known mishearing
   patterns.
2. Read the input file (.txt or .srt).
3. Go through it line by line (for .srt, only the subtitle text lines — see
   above). For each suspicious phrase, ask: "what would a Tibetan teacher
   giving a Dharma talk plausibly have said that sounds like this?" Use
   surrounding context (the topic being explained) to resolve ambiguity.
4. Write the corrected output to a sibling file with `.corrected` inserted
   before the extension, preserving the original extension:
   - `abc.en.txt` → `abc.en.corrected.txt`
   - `abc.en.srt` → `abc.en.corrected.srt`
   unless the user names a different output.
5. Verify:
   - For .txt: count lines in input and output — they must match exactly.
   - For .srt: the number of blocks, every index number, every timestamp
     line, and the number of text lines per block must match the input
     exactly. Only the text content may differ.
   If anything doesn't match, fix before finishing.
6. Report to the user: number of lines/blocks changed, and a short list of the
   corrections made (original → corrected) so they can spot-check.

## Example

Input lines:

```
booty toois is non ass of buddha
softball but then there are many
different levels of thought well like
```

Corrected (same 3 lines, same boundaries):

```
bodhicitta is known as bodhisattva
but then there are many
different levels of bodhisattva like
```

Note "softball" disappeared from line 2 because it was the tail of
"bodhisattva" bleeding over the line break — removing it is correct, but the
line itself remains and still begins the next phrase.
