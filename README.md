<h1 align="center">
  <br>
  <a href="https://openpecha.org"><img src="https://avatars.githubusercontent.com/u/82142807?s=400&u=19e108a15566f3a1449bafb03b8dd706a72aebcd&v=4" alt="OpenPecha" width="150"></a>
  <br>
</h1>

# Bodhicitta Multimedia Library — Subtitle Extractor

Extracts subtitles for all ~1,361 videos catalogued at
https://bodhicitta.tsadra.org/index.php/Library/Multimedia

The videos are hosted on YouTube (a few on Vimeo); the scripts find them via
the site's MediaWiki API and pull their captions with yt-dlp.

## Setup

```bash
pip install requests yt-dlp
```

ffmpeg is recommended (so yt-dlp can convert downloaded subtitles to
`.srt`), but not required: if ffmpeg is missing, subtitles are still saved
in their original WebVTT (`.vtt`) format and `srt_to_text.py` reads `.vtt`
directly.

On Windows, install it with `winget install ffmpeg`. The script
auto-detects ffmpeg even if it isn't on your PATH: it checks PATH first,
and if not found, searches `%LOCALAPPDATA%\Microsoft\WinGet\Packages` for
`ffmpeg.exe` (where winget installs it) and passes it to yt-dlp directly.
No manual PATH setup needed.
Install ffmpeg (recommended):
```
winget install ffmpeg
```

## Run

```bash
# Recommended: test on 10 pages first
python3 src/sub_extraction/extract_subtitles.py --limit 10

# Full run (resumable — re-running skips completed videos)
python3 src/sub_extraction/extract_subtitles.py
```

## Output (in ./bodhicitta_subtitles/)

- `manifest.csv` / `manifest.json` — every catalog page and its video URL
- `srt/<video_id>/` — subtitle files: `.srt` if ffmpeg was available,
  otherwise `.vtt`, one per language track
- `txt/<video_id>/` — clean plain-text transcripts converted from the
  subtitles (timestamps, tags, and rolling auto-caption duplicates removed)
- `done.log` — completed videos (used for resuming)
- `failures.log` — videos where subtitle download failed (private, deleted,
  region-locked, or no captions)

## Cleaning subtitles to text (srt_to_text.py)

`extract_subtitles.py` runs this automatically as Stage 4, but it can also be
run on its own — e.g. to (re)convert subtitles, including .srt files from
other sources:

```bash
# whole folder (.srt and .vtt; "-orig" duplicates are skipped automatically)
python3 src/sub_extraction/srt_to_text.py bodhicitta_subtitles/srt -o bodhicitta_subtitles/txt

# single file
python3 src/sub_extraction/srt_to_text.py video.vtt

# merge lines into readable paragraphs, or keep [hh:mm:ss] timestamps
python3 src/sub_extraction/srt_to_text.py video.vtt --paragraphs
python3 src/sub_extraction/srt_to_text.py video.vtt --timestamps

example: 
python src/sub_extraction/extract_subtitles.py --filter-text "Bodhicaryāvatāra,A Guide to the Bodhisattva's Way of Life,Shantideva's Guide to the Bodhisattva's Way of Life,Shantideva's Engaging in the Bodhisattva's Deeds,Shantideva - Way of the Bodhisattva,Bodhicharyavatara" --limit 30
```

## Options

- `--stage manifest|download|convert|all` — run a single stage
- `--langs "en.*"` — which subtitle language(s) to download (default:
  English only, covering en, en-US, en-GB and auto-generated English).
  Applies to both manual and auto-generated tracks. Examples:
  `--langs "en.*,bo.*"` for English + Tibetan, `--langs all` for everything.
- `--sleep 2` — delay between videos; raise it if YouTube starts throttling

## Notes

- The script downloads English subtitles only by default: manually-uploaded
  English tracks when available, otherwise YouTube's auto-generated English
  captions. Tibetan-language videos usually have neither, so they end up in
  failures.log or with empty folders — those would need speech-to-text
  (e.g. Whisper) as a separate step.
- A full run of 1,361 videos at a 2 s delay takes roughly 1.5–3 hours.

## Other scripts

- `src/sub_extraction/dedupe_srt.py` — removes duplicate rolling auto-caption
  lines from `.srt` files.

## Skills

- `dharma-transcript-correction/` — skill + glossary for correcting
  Dharma-related transcription errors.
- `subtitle-cleaning-eval/` — skill for evaluating subtitle-to-text cleaning
  quality (raw `.srt`/`.vtt` vs. cleaned `.txt`).

## Contributing guidelines

If you'd like to help out, check out our [contributing guidelines](/CONTRIBUTING.md).

## Terms of use

This project is licensed under the [MIT License](/LICENSE).
