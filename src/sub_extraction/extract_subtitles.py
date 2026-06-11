#!/usr/bin/env python3
"""
Extract subtitles for all videos catalogued in the Bodhicitta Multimedia Library
(https://bodhicitta.tsadra.org/index.php/Library/Multimedia).

Pipeline:
  Stage 1: Enumerate all media pages via the MediaWiki API (Category:Multimedia).
  Stage 2: Fetch each page's wikitext (batched) and extract YouTube/Vimeo URLs.
           Results saved to manifest.csv / manifest.json.
  Stage 3: Download subtitles with yt-dlp (manual subs in ALL languages +
           auto-generated captions), saved as .vtt files. (No ffmpeg
           required -- subtitles are kept in their original WebVTT format.)
  Stage 4: Convert every .srt/.vtt to a clean plain-text transcript (.txt),
           using srt_to_text.py.

The script is resumable: re-running it skips videos whose subtitles were
already fetched (tracked in done.log) and reuses the manifest if present.

Requirements:
  pip install requests yt-dlp

Usage:
  python3 extract_subtitles.py                 # full run
  python3 extract_subtitles.py --limit 10      # test on first 10 videos
  python3 extract_subtitles.py --stage manifest  # only build the manifest
  python3 extract_subtitles.py --langs "en.*"     # English subtitles only (default)
"""

import argparse
import concurrent.futures
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import unicodedata
from pathlib import Path

import requests

try:
    from sub_extraction.srt_to_text import collect_subtitle_files, convert_file
except ImportError:  # running as a standalone script next to srt_to_text.py
    from srt_to_text import collect_subtitle_files, convert_file

API = "https://bodhicitta.tsadra.org/api.php"
HEADERS = {"User-Agent": "subtitle-research-script/1.0 (personal research use)"}

# Output locations. Defaults below; main() re-points them via set_out_dir()
# according to the --out-dir CLI argument before any stage runs.
OUT_DIR = Path("bodhicitta_subtitles")
SUBS_DIR = OUT_DIR / "srt"
TXT_DIR = OUT_DIR / "txt"
MANIFEST_CSV = OUT_DIR / "manifest.csv"
MANIFEST_JSON = OUT_DIR / "manifest.json"
DONE_LOG = OUT_DIR / "done.log"
FAIL_LOG = OUT_DIR / "failures.log"


def _normalize(text: str) -> str:
    """Lowercase + strip diacritics for fuzzy matching.

    Converts e.g. "Bodhicaryāvatāra" → "bodhicaryavatara" so that
    accented and ASCII spellings both match.
    """
    return unicodedata.normalize("NFD", text.lower()).encode("ascii", "ignore").decode()


def filter_manifest(manifest: list[dict], filter_text: str) -> list[dict]:
    """Return only manifest rows whose page title matches *filter_text*.

    Matching is case-insensitive and diacritic-insensitive (so
    "Bodhicaryāvatāra" matches "Bodhicharyavatara", "bodhicaryavatara", etc.).
    Multiple keywords can be supplied separated by commas; a row is kept when
    ANY keyword matches (OR logic).
    """
    keywords = [_normalize(k.strip()) for k in filter_text.split(",") if k.strip()]
    if not keywords:
        return manifest
    kept = []
    for row in manifest:
        title_norm = _normalize(row.get("page", ""))
        if any(kw in title_norm for kw in keywords):
            kept.append(row)
    return kept


def set_out_dir(out_dir: str) -> None:
    """Re-point all output paths at the directory given by --out-dir."""
    global OUT_DIR, SUBS_DIR, TXT_DIR, MANIFEST_CSV, MANIFEST_JSON, DONE_LOG, FAIL_LOG
    OUT_DIR = Path(out_dir)
    SUBS_DIR = OUT_DIR / "srt"
    TXT_DIR = OUT_DIR / "txt"
    MANIFEST_CSV = OUT_DIR / "manifest.csv"
    MANIFEST_JSON = OUT_DIR / "manifest.json"
    DONE_LOG = OUT_DIR / "done.log"
    FAIL_LOG = OUT_DIR / "failures.log"


def get_with_retry(session: requests.Session, url: str, params: dict,
                   retries: int = 3, backoff: float = 2.0,
                   timeout: int = 60) -> requests.Response:
    """GET with retries and exponential backoff on network/HTTP errors."""
    for attempt in range(retries):
        try:
            r = session.get(url, params=params, timeout=timeout)
            r.raise_for_status()
            return r
        except requests.exceptions.RequestException:
            if attempt == retries - 1:
                raise
            time.sleep(backoff * (2 ** attempt))


def log_failure(key: str, message: str) -> None:
    """Append a failure entry, unless that key is already logged."""
    if FAIL_LOG.exists():
        existing = {line.split("\t", 1)[0]
                    for line in FAIL_LOG.read_text(encoding="utf-8").splitlines()
                    if line.strip()}
        if key in existing:
            return
    with open(FAIL_LOG, "a", encoding="utf-8") as f:
        f.write(f"{key}\t{message}\n")

YOUTUBE_RE = re.compile(
    r"(?:youtube\.com/(?:watch\?(?:[^\s\"'<>|]*&)?v=|embed/|shorts/|live/|vi/)"
    r"|youtu\.be/|ytimg\.com/vi/)"
    r"([A-Za-z0-9_-]{11})"
)
VIMEO_RE = re.compile(r"vimeo\.com/(?:video/)?(\d+)")


def find_ffmpeg() -> str | None:
    """Return the directory containing ffmpeg.exe/ffmpeg, or None if yt-dlp
    should already be able to find it on PATH.

    yt-dlp needs ffmpeg to convert downloaded subtitles to .srt. If ffmpeg
    is already on PATH, nothing extra is needed. Otherwise, on Windows,
    look in the WinGet Packages folder (winget installs ffmpeg there but
    doesn't always add it to PATH) and return its "bin" directory so it can
    be passed to yt-dlp via --ffmpeg-location.
    """
    if shutil.which("ffmpeg"):
        return None  # already on PATH

    if sys.platform == "win32":
        local_appdata = os.environ.get("LOCALAPPDATA")
        if local_appdata:
            winget_dir = Path(local_appdata) / "Microsoft" / "WinGet" / "Packages"
            if winget_dir.exists():
                for exe in winget_dir.rglob("ffmpeg.exe"):
                    return str(exe.parent)
    return None


# ----------------------------------------------------------------------
# Stage 1: enumerate media pages
# ----------------------------------------------------------------------
def list_media_pages(session: requests.Session) -> list[str]:
    """Return all page titles in Category:Multimedia."""
    titles = []
    params = {
        "action": "query",
        "list": "categorymembers",
        "cmtitle": "Category:Multimedia",
        "cmlimit": "500",
        "format": "json",
    }
    while True:
        r = get_with_retry(session, API, params)
        data = r.json()
        members = data.get("query", {}).get("categorymembers", [])
        titles.extend(m["title"] for m in members if m.get("ns", 0) == 0)
        cont = data.get("continue")
        if not cont:
            break
        params.update(cont)
        time.sleep(0.5)  # be polite

    # Fallback/supplement: also list pages with the "Media/" prefix in case
    # some entries are not categorized.
    params = {
        "action": "query",
        "list": "allpages",
        "apprefix": "Media/",
        "aplimit": "500",
        "format": "json",
    }
    seen = set(titles)
    while True:
        r = get_with_retry(session, API, params)
        data = r.json()
        for p in data.get("query", {}).get("allpages", []):
            if p["title"] not in seen:
                titles.append(p["title"])
                seen.add(p["title"])
        cont = data.get("continue")
        if not cont:
            break
        params.update(cont)
        time.sleep(0.5)

    return titles


# ----------------------------------------------------------------------
# Stage 2: fetch wikitext and extract video URLs
# ----------------------------------------------------------------------
def fetch_wikitext_batch(session: requests.Session, titles: list[str]) -> dict[str, str]:
    """Fetch raw wikitext for up to 50 titles in one API call."""
    params = {
        "action": "query",
        "prop": "revisions",
        "rvprop": "content",
        "rvslots": "main",
        "titles": "|".join(titles),
        "format": "json",
    }
    r = get_with_retry(session, API, params, timeout=120)
    pages = r.json().get("query", {}).get("pages", {})
    out = {}
    for page in pages.values():
        title = page.get("title", "")
        revs = page.get("revisions")
        if not revs:
            out[title] = ""
            continue
        slot = revs[0].get("slots", {}).get("main", {})
        out[title] = slot.get("*", "") or revs[0].get("*", "")
    return out


def fetch_parsed_html(session: requests.Session, title: str) -> str:
    """Fetch the rendered HTML of a single page (fallback when the raw
    wikitext doesn't contain the video link, e.g. when it is generated by
    a template or Semantic MediaWiki query)."""
    params = {
        "action": "parse",
        "page": title,
        "prop": "text",
        "format": "json",
    }
    try:
        r = get_with_retry(session, API, params)
        return r.json().get("parse", {}).get("text", {}).get("*", "")
    except Exception:
        return ""


def extract_videos(wikitext: str) -> tuple[list[dict], list[str]]:
    """Pull all YouTube / Vimeo references out of a page's wikitext.

    Returns (videos, other_urls) where other_urls are any remaining links
    found on the page — useful for diagnosing unrecognized formats.
    """
    videos = []
    seen = set()

    def add(platform: str, vid: str):
        key = f"{platform}:{vid}"
        if key in seen:
            return
        seen.add(key)
        url = (f"https://www.youtube.com/watch?v={vid}"
               if platform == "youtube" else f"https://vimeo.com/{vid}")
        videos.append({"platform": platform, "video_id": vid, "url": url})

    for vid in YOUTUBE_RE.findall(wikitext):
        add("youtube", vid)

    # {{#widget:YouTube|id=XXXX}} / {{#evu:...}} style embeds
    for m in re.finditer(r"(?i)youtube[^}|\n]*?\bid\s*=\s*([A-Za-z0-9_-]{11})", wikitext):
        add("youtube", m.group(1))

    # Bare video IDs in template parameters, e.g.:
    #   |VideoID=3zcywOs9op4   |YouTubeID=...   |MediaID=...
    for m in re.finditer(
        r"(?im)^\s*\|\s*[\w ]*(?:video|youtube|media)[\w ]*id[\w ]*\s*=\s*"
        r"([A-Za-z0-9_-]{11})\s*$",
        wikitext,
    ):
        add("youtube", m.group(1))

    for vid in VIMEO_RE.findall(wikitext):
        add("vimeo", vid)

    # Diagnostics: every other URL on the page that we did NOT recognize
    all_urls = re.findall(r"https?://[^\s|<>\"'}\]]+", wikitext)
    other_urls = [u for u in all_urls
                  if "youtube" not in u and "youtu.be" not in u
                  and "vimeo" not in u]
    return videos, other_urls


def build_manifest(limit: int | None = None) -> list[dict]:
    session = requests.Session()
    session.headers.update(HEADERS)

    print("Stage 1: listing media pages ...")
    titles = list_media_pages(session)
    print(f"  found {len(titles)} pages")
    if limit:
        titles = titles[:limit]

    print("Stage 2: extracting video URLs ...")
    debug_dir = OUT_DIR / "debug_wikitext"
    debug_dir.mkdir(parents=True, exist_ok=True)
    debug_dumped = 0
    manifest = []
    for i in range(0, len(titles), 50):
        batch = titles[i:i + 50]
        texts = fetch_wikitext_batch(session, batch)
        for title, text in texts.items():
            vids, other_urls = extract_videos(text)
            source = "wikitext"
            if not vids:
                # Fallback: the link may only exist in the rendered page
                html = fetch_parsed_html(session, title)
                if html:
                    vids, html_urls = extract_videos(html)
                    if vids:
                        source = "html"
                    elif not other_urls:
                        other_urls = html_urls
            if not vids:
                manifest.append({"page": title, "platform": "", "video_id": "",
                                 "url": "", "source": "",
                                 "other_urls": "; ".join(other_urls[:5])})
                # Dump the first few unmatched pages' raw wikitext for inspection
                if debug_dumped < 5 and text.strip():
                    safe = re.sub(r"[^\w.-]+", "_", title)[:80]
                    (debug_dir / f"{safe}.wiki.txt").write_text(text, encoding="utf-8")
                    debug_dumped += 1
            for v in vids:
                manifest.append({"page": title, **v, "source": source,
                                 "other_urls": ""})
        print(f"  processed {min(i + 50, len(titles))}/{len(titles)} pages", end="\r")
        time.sleep(0.5)
    print()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(MANIFEST_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["page", "platform", "video_id", "url",
                                          "source", "other_urls"])
        w.writeheader()
        w.writerows(manifest)
    MANIFEST_JSON.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    with_video = sum(1 for m in manifest if m["url"])
    without = sum(1 for m in manifest if not m["url"])
    print(f"  manifest saved: {with_video} video links, {without} pages with no video link")
    if with_video == 0 and manifest:
        print("\n  !! No video links recognized. Sample wikitext was saved to:")
        print(f"     {debug_dir}/")
        print("     Open those files (or share them) to see how videos are stored,")
        print("     and check the 'other_urls' column in manifest.csv.")
        empty_pages = sum(1 for m in manifest if not m["url"] and not m["other_urls"])
        print(f"     Pages with no URLs of any kind: {empty_pages}/{len(manifest)}")
    return manifest


# ----------------------------------------------------------------------
# Stage 3: download subtitles with yt-dlp
# ----------------------------------------------------------------------
def download_subtitles(manifest: list[dict], langs: str, sleep_secs: float,
                       workers: int = 4):
    SUBS_DIR.mkdir(parents=True, exist_ok=True)
    done = set()
    if DONE_LOG.exists():
        done = set(DONE_LOG.read_text(encoding="utf-8").splitlines())

    entries = [m for m in manifest if m["url"]]
    # Deduplicate by video id (same video can be cited on several pages)
    unique = {}
    for m in entries:
        unique.setdefault(f"{m['platform']}:{m['video_id']}", m)
    entries = list(unique.values())
    print(f"Stage 3: downloading subtitles for {len(entries)} unique videos "
          f"({len(done)} already done)")

    ffmpeg_dir = find_ffmpeg()
    if ffmpeg_dir:
        print(f"  ffmpeg not on PATH; using {ffmpeg_dir}")

    todo = [(n, m) for n, m in enumerate(entries, 1)
            if f"{m['platform']}:{m['video_id']}" not in done]
    log_lock = threading.Lock()

    def fetch_one(n: int, m: dict):
        key = f"{m['platform']}:{m['video_id']}"
        safe_id = m["video_id"]
        out_tpl = str(SUBS_DIR / safe_id / f"{safe_id}.%(ext)s")
        cmd = [
            "yt-dlp",
            "--skip-download",
            "--write-subs",            # manually uploaded subtitles
            "--write-auto-subs",       # auto-generated captions (fallback)
            "--sub-langs", langs,      # ONLY the requested language(s)
            "--convert-subs", "srt",   # requires ffmpeg; if ffmpeg is
                                        # missing, yt-dlp still saves the
                                        # raw .vtt and only the conversion
                                        # step fails (handled below).
            "--no-warnings",
            "--ignore-errors",
            "-o", out_tpl,
        ]
        if ffmpeg_dir:
            cmd += ["--ffmpeg-location", ffmpeg_dir]
        cmd.append(m["url"])
        print(f"[{n}/{len(entries)}] {m['page']}  ({m['url']})")
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
            video_dir = SUBS_DIR / safe_id
            got_subs = video_dir.exists() and (
                any(video_dir.glob("*.srt")) or any(video_dir.glob("*.vtt"))
            )
            if res.returncode == 0 or got_subs:
                with log_lock:
                    with open(DONE_LOG, "a", encoding="utf-8") as f:
                        f.write(key + "\n")
                    if res.returncode != 0:
                        # subs were downloaded but --convert-subs srt failed
                        # (almost always: ffmpeg not found) -- srt_to_text.py
                        # can still read the .vtt directly.
                        log_failure(key, f"{m['url']}\t"
                                    f"(subs saved as .vtt; srt conversion failed: "
                                    f"{res.stderr.strip()[:200]})")
            else:
                with log_lock:
                    log_failure(key, f"{m['url']}\t{res.stderr.strip()[:300]}")
        except subprocess.TimeoutExpired:
            with log_lock:
                log_failure(key, f"{m['url']}\tTIMEOUT")
        time.sleep(sleep_secs)  # avoid YouTube rate limiting

    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(fetch_one, n, m) for n, m in todo]
        for fut in concurrent.futures.as_completed(futures):
            fut.result()  # surface any unexpected worker exception


# ----------------------------------------------------------------------
# Stage 4: SRT/VTT -> plain text (via srt_to_text.py)
# ----------------------------------------------------------------------
def convert_all_srt():
    TXT_DIR.mkdir(parents=True, exist_ok=True)
    subs = collect_subtitle_files(SUBS_DIR)
    print(f"Stage 4: converting {len(subs)} subtitle files to plain text")
    for sub in subs:
        rel = sub.relative_to(SUBS_DIR)
        txt_path = (TXT_DIR / rel).with_suffix(".txt")
        convert_file(sub, txt_path, timestamps=False, paragraphs=False)
    print(f"  transcripts written to {TXT_DIR}/")


# ----------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stage", choices=["all", "manifest", "download", "convert"],
                    default="all")
    ap.add_argument("--limit", type=int, default=None,
                    help="process only the first N pages (for testing)")
    ap.add_argument("--langs", default="en.*",
                    help="subtitle language(s) to download, as yt-dlp patterns. "
                         "Default 'en.*' = English only (en, en-US, en-GB, and "
                         "auto-generated English). Examples: 'en' exact only, "
                         "'en.*,bo.*' English + Tibetan, 'all' everything.")
    ap.add_argument("--sleep", type=float, default=2.0,
                    help="seconds to wait between videos (default 2)")
    ap.add_argument("--out-dir", default="bodhicitta_subtitles",
                    help="output directory (default: bodhicitta_subtitles)")
    ap.add_argument("--workers", type=int, default=4,
                    help="parallel subtitle download workers (default 4, max 8)")
    ap.add_argument("--filter-text", default=None,
                    help="only download subtitles for pages whose title contains "
                         "this text (case- and diacritic-insensitive). Separate "
                         "multiple keywords with commas for OR matching. "
                         'Example: --filter-text "Bodhicaryavatara,Way of the Bodhisattva"')
    ap.add_argument("--probe", metavar="PAGE_TITLE",
                    help="diagnostic: fetch ONE page, print its wikitext and "
                         "what the extractor finds, then exit. Try: "
                         '--probe "Media/37 Things That Bodhisattvas Do - Song 1"')
    args = ap.parse_args()

    # Parse args before any directory constant is used: all output paths
    # derive from --out-dir.
    set_out_dir(args.out_dir)
    workers = max(1, min(args.workers, 8))

    if args.probe:
        session = requests.Session()
        session.headers.update(HEADERS)
        text = fetch_wikitext_batch(session, [args.probe]).get(args.probe, "")
        print(f"=== WIKITEXT of '{args.probe}' ({len(text)} chars) ===")
        print(text[:3000] or "(empty)")
        vids, others = extract_videos(text)
        print(f"\n=== extracted from wikitext: {vids}")
        print(f"=== other urls: {others[:10]}")
        if not vids:
            html = fetch_parsed_html(session, args.probe)
            vids, others = extract_videos(html)
            print(f"\n=== extracted from rendered HTML: {vids}")
            print(f"=== other urls in HTML: {others[:10]}")
        return

    if args.stage in ("all", "manifest") or not MANIFEST_JSON.exists():
        manifest = build_manifest(limit=args.limit)
    else:
        manifest = json.loads(MANIFEST_JSON.read_text(encoding="utf-8"))
        if args.limit:
            manifest = manifest[:args.limit]
        print(f"Loaded existing manifest with {len(manifest)} rows")

    if args.filter_text:
        before = len([m for m in manifest if m.get("url")])
        manifest = filter_manifest(manifest, args.filter_text)
        after = len([m for m in manifest if m.get("url")])
        print(f"Filter '{args.filter_text}': {after} matching video(s) "
              f"out of {before} total (kept {len(manifest)} manifest rows)")
        if not manifest:
            print("  No pages matched — check your keyword spelling.")
            return

    if args.stage in ("all", "download"):
        download_subtitles(manifest, args.langs, args.sleep, workers=workers)

    if args.stage in ("all", "convert"):
        convert_all_srt()

    print("Done.")


if __name__ == "__main__":
    main()
