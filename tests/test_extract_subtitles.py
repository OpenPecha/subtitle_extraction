from sub_extraction.extract_subtitles import extract_videos, find_ffmpeg


def video_ids(videos):
    return [(v["platform"], v["video_id"]) for v in videos]


def test_extract_videos_youtube_watch_url():
    videos, _ = extract_videos(
        "See https://www.youtube.com/watch?v=dQw4w9WgXcQ for the teaching."
    )
    assert video_ids(videos) == [("youtube", "dQw4w9WgXcQ")]
    assert videos[0]["url"] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"


def test_extract_videos_youtube_short_and_embed_urls():
    wikitext = (
        "https://youtu.be/abcdefghijk and "
        "https://www.youtube.com/embed/ABCDEFGHIJ0"
    )
    videos, _ = extract_videos(wikitext)
    assert video_ids(videos) == [
        ("youtube", "abcdefghijk"),
        ("youtube", "ABCDEFGHIJ0"),
    ]


def test_extract_videos_vimeo_urls():
    videos, _ = extract_videos(
        "https://vimeo.com/12345678 and https://vimeo.com/video/87654321"
    )
    assert video_ids(videos) == [
        ("vimeo", "12345678"),
        ("vimeo", "87654321"),
    ]
    assert videos[0]["url"] == "https://vimeo.com/12345678"


def test_extract_videos_template_videoid_param():
    wikitext = "|Title=Some Teaching\n|VideoID=3zcywOs9op4\n|Year=2020\n"
    videos, _ = extract_videos(wikitext)
    assert video_ids(videos) == [("youtube", "3zcywOs9op4")]


def test_extract_videos_widget_id_param():
    videos, _ = extract_videos("{{#evu:youtube id=dQw4w9WgXcQ}}")
    assert video_ids(videos) == [("youtube", "dQw4w9WgXcQ")]


def test_extract_videos_dedupes_repeated_ids():
    wikitext = (
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ\n"
        "https://youtu.be/dQw4w9WgXcQ\n"
        "|VideoID=dQw4w9WgXcQ\n"
    )
    videos, _ = extract_videos(wikitext)
    assert video_ids(videos) == [("youtube", "dQw4w9WgXcQ")]


def test_extract_videos_reports_other_urls():
    videos, other = extract_videos("https://example.com/page no videos here")
    assert videos == []
    assert other == ["https://example.com/page"]


def test_find_ffmpeg_returns_none_when_not_found(monkeypatch):
    monkeypatch.setattr("sub_extraction.extract_subtitles.shutil.which",
                        lambda name: None)
    # Force the non-Windows branch so the WinGet lookup is skipped.
    monkeypatch.setattr("sub_extraction.extract_subtitles.sys.platform",
                        "linux")
    assert find_ffmpeg() is None


def test_find_ffmpeg_returns_none_when_on_path(monkeypatch):
    monkeypatch.setattr("sub_extraction.extract_subtitles.shutil.which",
                        lambda name: "/usr/bin/ffmpeg")
    assert find_ffmpeg() is None
