import importlib.util
from pathlib import Path

_SCRIPT = (Path(__file__).resolve().parents[1]
           / "subtitle-cleaning-eval" / "scripts" / "evaluate_cleaning.py")
_spec = importlib.util.spec_from_file_location("evaluate_cleaning", _SCRIPT)
ec = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ec)


SRT_SAMPLE = """1
00:00:01,000 --> 00:00:03,000
<i>May all beings</i>

2
00:00:03,000 --> 00:00:05,000
{\\an8}be free from suffering
"""

VTT_SAMPLE = """WEBVTT
Kind: captions
Language: en

00:00:01.000 --> 00:00:03.000 align:start position:0%
May<00:00:01.500><c> all</c><00:00:01.800><c> beings</c>
"""


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------- parse_raw
def test_parse_raw_strips_timestamps_numbers_and_tags(tmp_path):
    p = write(tmp_path / "a.srt", SRT_SAMPLE)
    assert ec.parse_raw(p) == ["May all beings", "be free from suffering"]


def test_parse_raw_strips_vtt_headers_and_timing_tags(tmp_path):
    p = write(tmp_path / "a.vtt", VTT_SAMPLE)
    assert ec.parse_raw(p) == ["May all beings"]


# ------------------------------------------------------------ evaluate_pair
def make_srt(lines):
    blocks = []
    for n, line in enumerate(lines, 1):
        blocks.append(f"{n}\n00:00:{n:02d},000 --> 00:00:{n:02d},500\n{line}\n")
    return "\n".join(blocks)


def test_evaluate_pair_ok(tmp_path):
    # 10 identical rolling-duplicate lines, deduped down to 2 in the .txt:
    # big reduction, full bigram retention.
    raw = write(tmp_path / "v.en.srt", make_srt(["om mani padme hum"] * 10))
    txt = write(tmp_path / "v.en.txt", "om mani padme hum\nom mani padme hum\n")
    r = ec.evaluate_pair(raw, txt)
    assert r["flag"] == "OK"
    assert r["content_retention"] == 100.0
    assert r["pct_lines_removed"] == 80.0


def test_evaluate_pair_content_loss(tmp_path):
    raw = write(tmp_path / "v.en.srt", make_srt(
        ["the bodhisattva path is profound",
         "compassion arises for all beings"]))
    txt = write(tmp_path / "v.en.txt", "the bodhisattva path is profound\n")
    r = ec.evaluate_pair(raw, txt)
    assert r["flag"] == "CONTENT_LOSS"
    assert r["content_retention"] < ec.CONTENT_LOSS_THRESHOLD


def test_evaluate_pair_empty_output(tmp_path):
    raw = write(tmp_path / "v.en.srt", make_srt(["some real content here"]))
    txt = write(tmp_path / "v.en.txt", "   \n")
    r = ec.evaluate_pair(raw, txt)
    assert r["flag"] == "EMPTY_OUTPUT"


def test_evaluate_pair_low_reduction(tmp_path):
    # >20 distinct raw lines and an identical .txt: nothing was removed.
    lines = [f"unique line number {i} spoken here" for i in range(25)]
    raw = write(tmp_path / "v.en.srt", make_srt(lines))
    txt = write(tmp_path / "v.en.txt", "\n".join(lines) + "\n")
    r = ec.evaluate_pair(raw, txt)
    assert r["flag"] == "LOW_REDUCTION"
    assert r["content_retention"] == 100.0


def test_evaluate_pair_missing_txt(tmp_path):
    raw = write(tmp_path / "v.en.srt", make_srt(["hello world"]))
    r = ec.evaluate_pair(raw, None)
    assert r["flag"] == "MISSING_TXT"


# --------------------------------------------------------------- find_pairs
def test_find_pairs_prefers_srt_over_vtt(tmp_path):
    srt_dir, txt_dir = tmp_path / "srt", tmp_path / "txt"
    write(srt_dir / "vid1" / "vid1.en.srt", make_srt(["a b"]))
    write(srt_dir / "vid1" / "vid1.en.vtt", "WEBVTT\n")
    write(txt_dir / "vid1" / "vid1.en.txt", "a b\n")
    pairs = ec.find_pairs(srt_dir, txt_dir)
    assert len(pairs) == 1
    raw, txt, vid = pairs[0]
    assert raw.name == "vid1.en.srt"
    assert txt.name == "vid1.en.txt"
    assert vid == "vid1"


def test_find_pairs_skips_orig_variants(tmp_path):
    srt_dir, txt_dir = tmp_path / "srt", tmp_path / "txt"
    write(srt_dir / "vid2" / "vid2.en.vtt", "WEBVTT\n")
    write(srt_dir / "vid2" / "vid2.en-orig.srt", make_srt(["a b"]))
    txt_dir.mkdir()
    pairs = ec.find_pairs(srt_dir, txt_dir)
    assert len(pairs) == 1
    raw, txt, vid = pairs[0]
    # the canonical .vtt beats the "-orig" .srt variant
    assert raw.name == "vid2.en.vtt"
    assert txt is None
