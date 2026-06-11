from sub_extraction.srt_to_text import dedupe, parse_srt, to_text


SRT_SAMPLE = """1
00:00:01,000 --> 00:00:03,000
May all beings

2
00:00:03,000 --> 00:00:05,000
May all beings
be free from suffering
"""

VTT_SAMPLE = """WEBVTT
Kind: captions
Language: en

00:00:01.000 --> 00:00:03.000 align:start position:0%
May<00:00:01.500><c> all</c><00:00:01.800><c> beings</c>

00:00:03.000 --> 00:00:05.000 align:start position:0%
May all beings
be free from suffering
"""


def write(tmp_path, name, content):
    p = tmp_path / name
    p.write_text(content, encoding="utf-8")
    return p


def test_parse_srt_strips_block_numbers_and_timestamps(tmp_path):
    path = write(tmp_path, "sample.srt", SRT_SAMPLE)
    blocks = parse_srt(path)
    assert blocks == [
        ("00:00:01", "May all beings"),
        ("00:00:03", "May all beings\nbe free from suffering"),
    ]


def test_parse_srt_handles_vtt_headers_and_tags(tmp_path):
    path = write(tmp_path, "sample.vtt", VTT_SAMPLE)
    blocks = parse_srt(path)
    assert blocks[0] == ("00:00:01", "May all beings")
    assert blocks[1] == ("00:00:03", "May all beings\nbe free from suffering")


def test_dedupe_removes_rolling_auto_caption_duplicates():
    blocks = [
        ("00:00:01", "May all beings"),
        ("00:00:03", "May all beings\nbe free from suffering"),
    ]
    result = dedupe(blocks)
    assert result == [
        ("00:00:01", "May all beings"),
        ("00:00:03", "be free from suffering"),
    ]


def test_dedupe_drops_consecutive_identical_lines():
    blocks = [
        ("00:00:01", "hello"),
        ("00:00:02", "hello"),
        ("00:00:03", "world"),
    ]
    result = dedupe(blocks)
    assert result == [
        ("00:00:01", "hello"),
        ("00:00:03", "world"),
    ]


def test_to_text_plain():
    blocks = [("00:00:01", "hello"), ("00:00:03", "world")]
    assert to_text(blocks, timestamps=False, paragraphs=False) == "hello\nworld"


def test_to_text_with_timestamps():
    blocks = [("00:00:01", "hello"), ("00:00:03", "world")]
    assert to_text(blocks, timestamps=True, paragraphs=False) == (
        "[00:00:01] hello\n[00:00:03] world"
    )


def test_to_text_paragraphs_merges_short_lines():
    blocks = [("00:00:01", "hello"), ("00:00:02", "world.")]
    assert to_text(blocks, timestamps=False, paragraphs=True) == "hello world."
