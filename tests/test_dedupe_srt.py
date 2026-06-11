from sub_extraction.dedupe_srt import dedupe, fmt, parse, to_ms, write


ROLLING_SRT = """1
00:00:01,000 --> 00:00:01,010
May all

2
00:00:01,500 --> 00:00:03,500
May all beings

3
00:00:03,500 --> 00:00:03,510
May all beings be

4
00:00:04,000 --> 00:00:06,000
May all beings be free
"""


def test_to_ms():
    assert to_ms("00", "01", "02", "500") == ((1 * 60) + 2) * 1000 + 500


def test_fmt_round_trips_to_ms():
    assert fmt(to_ms("01", "02", "03", "004")) == "01:02:03,004"


def test_parse_reads_cues(tmp_path):
    path = tmp_path / "sample.en.srt"
    path.write_text(ROLLING_SRT, encoding="utf-8")
    cues = parse(path)
    assert len(cues) == 4
    assert cues[0][2] == ["May all"]


def test_dedupe_drops_filler_cues_and_keeps_new_text(tmp_path):
    path = tmp_path / "sample.en.srt"
    path.write_text(ROLLING_SRT, encoding="utf-8")
    cues = dedupe(parse(path))
    # the ~10ms filler cues (1 and 3) are dropped
    texts = [c[2] for c in cues]
    assert texts == ["May all beings", "May all beings be free"]


def test_write_roundtrip(tmp_path):
    cues = [[1000, 3000, "hello"], [3000, 5000, "world"]]
    out = tmp_path / "out.srt"
    write(cues, out)
    content = out.read_text(encoding="utf-8")
    assert "00:00:01,000 --> 00:00:03,000" in content
    assert "hello" in content
    assert "world" in content
