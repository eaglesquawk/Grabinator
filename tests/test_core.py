"""
Unit tests for the pure logic in grabinator.cli — no network access, no
ffmpeg, no yt-dlp calls. These run in milliseconds and are what CI executes
on every push/PR.
"""

import pytest

from grabinator.cli import (
    build_cookie_opts,
    check_internet,
    gather_video_paths,
    get_platform,
    get_playlist_index_offset,
    human_size,
    is_channel_url,
    is_playlist_url,
    normalize_channel_url,
    parse_range,
    resolve_playlist_bounds,
    resolve_safe_destination,
    sanitize_component,
    sanitize_title,
    setup_run_logging,
    unique_path,
    validate_source_url,
)


# --------------------------------------------------------------------------
# Filename sanitization
# --------------------------------------------------------------------------
def test_sanitize_component_strips_unsafe_characters():
    assert sanitize_component("weird/../name!!") == "weirdname"


def test_sanitize_component_empty_falls_back():
    assert sanitize_component("") == "unknown"
    assert sanitize_component("...", fallback="x") == "x"


def test_sanitize_title_keeps_spaces_and_punctuation():
    assert sanitize_title("My Cool Video (2026)!") == "My Cool Video (2026)!"


def test_sanitize_title_strips_path_separators_and_illegal_chars():
    result = sanitize_title('bad/name\\with:illegal*chars?"<>|')
    assert "/" not in result
    assert "\\" not in result
    assert ":" not in result
    assert "*" not in result


def test_sanitize_title_empty_falls_back():
    assert sanitize_title("") == "video"
    assert sanitize_title("   ") == "video"


# --------------------------------------------------------------------------
# Path traversal protection
# --------------------------------------------------------------------------
def test_resolve_safe_destination_allows_normal_filename(tmp_path):
    dest = resolve_safe_destination(tmp_path, "my video.mp4")
    assert dest.parent == tmp_path.resolve()


def test_resolve_safe_destination_blocks_traversal(tmp_path):
    with pytest.raises(ValueError):
        resolve_safe_destination(tmp_path, "../../etc/passwd")


def test_unique_path_avoids_clobbering(tmp_path):
    existing = tmp_path / "file.mp4"
    existing.write_text("x")
    result = unique_path(existing)
    assert result != existing
    assert result.name == "file-1.mp4"


def test_unique_path_returns_same_path_if_free(tmp_path):
    candidate = tmp_path / "free.mp4"
    assert unique_path(candidate) == candidate


# --------------------------------------------------------------------------
# URL validation / platform routing
# --------------------------------------------------------------------------
def test_validate_source_url_accepts_known_hosts():
    assert validate_source_url("https://www.tiktok.com/@user/video/123")
    assert validate_source_url("https://www.youtube.com/watch?v=abc")
    assert validate_source_url("https://soundcloud.com/artist/track")


def test_validate_source_url_rejects_unknown_host():
    with pytest.raises(ValueError):
        validate_source_url("https://evil.example.com/video/123")


def test_validate_source_url_rejects_bad_scheme():
    with pytest.raises(ValueError):
        validate_source_url("ftp://tiktok.com/@user/video/123")


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.tiktok.com/@user/video/123", "tiktok"),
        ("https://www.youtube.com/watch?v=abc", "youtube"),
        ("https://youtu.be/abc", "youtube"),
        ("https://www.dailymotion.com/video/xyz", "dailymotion"),
        ("https://soundcloud.com/artist/track", "soundcloud"),
        ("https://www.instagram.com/p/abc123/", "instagram"),
        ("https://www.instagram.com/reel/abc123/", "instagram"),
        ("https://x.com/user/status/123", "x"),
        ("https://twitter.com/user/status/123", "x"),
        ("https://www.twitter.com/user/status/123", "x"),
        ("https://www.threads.net/@user/post/123", "threads"),
        ("https://threads.com/@user/post/123", "threads"),
    ],
)
def test_get_platform(url, expected):
    assert get_platform(url) == expected


def test_get_platform_rejects_unrecognized_host():
    with pytest.raises(ValueError):
        get_platform("https://evil.example.com/video/123")


def test_validate_source_url_accepts_instagram():
    assert validate_source_url("https://www.instagram.com/p/abc123/")


# --------------------------------------------------------------------------
# File size formatting
# --------------------------------------------------------------------------
def test_human_size_bytes():
    assert human_size(500) == "500.0 B"


def test_human_size_kilobytes():
    assert human_size(1536) == "1.5 KB"


def test_human_size_megabytes():
    assert human_size(3 * 1024 * 1024) == "3.0 MB"


# --------------------------------------------------------------------------
# Playlist detection (platform-specific URL shapes)
# --------------------------------------------------------------------------
def test_youtube_playlist_detected_via_list_param():
    url = "https://www.youtube.com/playlist?list=PL12345"
    assert is_playlist_url(url, "youtube") is True


def test_youtube_single_video_not_a_playlist():
    url = "https://www.youtube.com/watch?v=abc123"
    assert is_playlist_url(url, "youtube") is False


def test_soundcloud_set_detected_via_path():
    url = "https://soundcloud.com/artist/sets/album-name"
    assert is_playlist_url(url, "soundcloud") is True


def test_soundcloud_single_track_not_a_playlist():
    url = "https://soundcloud.com/artist/track-name"
    assert is_playlist_url(url, "soundcloud") is False


# --------------------------------------------------------------------------
# --range parsing
# --------------------------------------------------------------------------
def test_parse_range_single_number_means_first_n():
    assert parse_range("10") == (1, 10)


def test_parse_range_hyphen_range():
    assert parse_range("3-7") == (3, 7)


def test_parse_range_comma_range():
    assert parse_range("3,7") == (3, 7)


def test_parse_range_strips_whitespace():
    assert parse_range(" 3 - 7 ") == (3, 7)


def test_parse_range_single_video():
    assert parse_range("1") == (1, 1)


@pytest.mark.parametrize(
    "bad_value",
    ["abc", "7-3", "0", "-5", "3,7,9", "", "3,", ",7", "3--7"],
)
def test_parse_range_rejects_invalid_input(bad_value):
    with pytest.raises(ValueError):
        parse_range(bad_value)


# --------------------------------------------------------------------------
# --convert path resolution (single file / folder / .txt manifest)
# --------------------------------------------------------------------------
def test_gather_video_paths_single_file(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fake video data")
    assert gather_video_paths(video) == [video]


def test_gather_video_paths_folder_finds_only_video_files(tmp_path):
    video1 = tmp_path / "a.mp4"
    video2 = tmp_path / "b.mov"
    not_a_video = tmp_path / "notes.txt"
    video1.write_bytes(b"x")
    video2.write_bytes(b"x")
    not_a_video.write_text("just some notes")

    result = gather_video_paths(tmp_path)
    assert result == [video1, video2]


def test_gather_video_paths_manifest_resolves_relative_paths(tmp_path):
    video = tmp_path / "clip.mp4"
    video.write_bytes(b"x")
    manifest = tmp_path / "list.txt"
    manifest.write_text("clip.mp4\n# a comment line\n\n")

    result = gather_video_paths(manifest)
    assert result == [video]


def test_gather_video_paths_rejects_unsupported_file(tmp_path):
    bogus = tmp_path / "notes.md"
    bogus.write_text("not a video")
    with pytest.raises(ValueError):
        gather_video_paths(bogus)


# --------------------------------------------------------------------------
# YouTube `index` param as a playlist starting point
# --------------------------------------------------------------------------
def test_get_playlist_index_offset_reads_valid_index():
    url = "https://www.youtube.com/watch?v=abc&list=PL123&index=5"
    assert get_playlist_index_offset(url) == 5


def test_get_playlist_index_offset_ignores_index_one():
    url = "https://www.youtube.com/watch?v=abc&list=PL123&index=1"
    assert get_playlist_index_offset(url) is None


def test_get_playlist_index_offset_none_when_absent():
    url = "https://www.youtube.com/playlist?list=PL123"
    assert get_playlist_index_offset(url) is None


def test_get_playlist_index_offset_none_when_malformed():
    url = "https://www.youtube.com/watch?v=abc&list=PL123&index=notanumber"
    assert get_playlist_index_offset(url) is None


def test_resolve_playlist_bounds_no_index_no_range_is_default_full_playlist():
    url = "https://www.youtube.com/playlist?list=PL123"
    start, end = resolve_playlist_bounds(url, None)
    assert start == 1


def test_resolve_playlist_bounds_no_index_with_range_unchanged():
    url = "https://www.youtube.com/playlist?list=PL123"
    assert resolve_playlist_bounds(url, (3, 7)) == (3, 7)


def test_resolve_playlist_bounds_index_becomes_start_with_no_range():
    url = "https://www.youtube.com/watch?v=abc&list=PL123&index=5"
    start, end = resolve_playlist_bounds(url, None)
    assert start == 5


def test_resolve_playlist_bounds_index_shifts_start_preserves_count():
    # --range 3-7 is a count of 5 videos; index=5 makes video 5 the first
    # one downloaded, so the same count of 5 becomes videos 5 through 9.
    url = "https://www.youtube.com/watch?v=abc&list=PL123&index=5"
    assert resolve_playlist_bounds(url, (3, 7)) == (5, 9)


def test_resolve_playlist_bounds_index_one_behaves_like_no_index():
    url = "https://www.youtube.com/watch?v=abc&list=PL123&index=1"
    assert resolve_playlist_bounds(url, (3, 7)) == (3, 7)


# --------------------------------------------------------------------------
# YouTube channel URL detection and normalization
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.youtube.com/@SomeChannel", True),
        ("https://www.youtube.com/channel/UCxxxxxxxxxxxxxxxxxxxxxx", True),
        ("https://www.youtube.com/c/SomeChannel", True),
        ("https://www.youtube.com/user/SomeUser", True),
        ("https://www.youtube.com/watch?v=abc123", False),
        ("https://www.youtube.com/shorts/abc123", False),
        ("https://youtu.be/abc123", False),
    ],
)
def test_is_channel_url(url, expected):
    assert is_channel_url(url) is expected


def test_normalize_channel_url_appends_videos_tab():
    url = "https://www.youtube.com/@SomeChannel"
    assert normalize_channel_url(url) == "https://www.youtube.com/@SomeChannel/videos"


def test_normalize_channel_url_leaves_existing_tab_alone():
    url = "https://www.youtube.com/@SomeChannel/shorts"
    assert normalize_channel_url(url) == url


def test_is_playlist_url_recognizes_channel_urls_for_youtube():
    assert is_playlist_url("https://www.youtube.com/@SomeChannel", "youtube") is True
    assert is_playlist_url("https://www.youtube.com/watch?v=abc", "youtube") is False


# --------------------------------------------------------------------------
# Cookie options
# --------------------------------------------------------------------------
def test_build_cookie_opts_from_browser():
    assert build_cookie_opts("chrome", None) == {"cookiesfrombrowser": ("chrome",)}


def test_build_cookie_opts_from_file(tmp_path):
    cookie_file = tmp_path / "cookies.txt"
    assert build_cookie_opts(None, cookie_file) == {"cookiefile": str(cookie_file)}


def test_build_cookie_opts_empty_when_neither_given():
    assert build_cookie_opts(None, None) == {}


def test_build_cookie_opts_never_reads_file_contents(tmp_path):
    # build_cookie_opts only ever passes yt-dlp the *path* to a cookies
    # file — it never opens or reads the file itself, so cookie values
    # never pass through Grabinator's own code (and therefore can't end up
    # in --log output or the dedupe index).
    cookie_file = tmp_path / "cookies.txt"
    cookie_file.write_text("super-secret-session-token-should-never-be-read")
    result = build_cookie_opts(None, cookie_file)
    assert result == {"cookiefile": str(cookie_file)}
    assert "super-secret-session-token-should-never-be-read" not in str(result)


# --------------------------------------------------------------------------
# check_internet: defense-in-depth host validation
# --------------------------------------------------------------------------
def test_check_internet_rejects_unrecognized_host():
    with pytest.raises(ValueError):
        check_internet("https://evil.example.com/")


# --------------------------------------------------------------------------
# --log: run logging
# --------------------------------------------------------------------------
def test_setup_run_logging_creates_timestamped_file(tmp_path, capsys):
    import sys

    orig_stdout, orig_stderr = sys.stdout, sys.stderr
    try:
        log_path = setup_run_logging(tmp_path)
        assert log_path.parent == tmp_path / "logs"
        assert log_path.suffix == ".txt"
        assert log_path.name.startswith("grabinator_")

        print("hello from the test")
    finally:
        sys.stdout, sys.stderr = orig_stdout, orig_stderr

    assert log_path.exists()
    content = log_path.read_text()
    assert "hello from the test" in content


def test_setup_run_logging_does_not_duplicate_console_output(tmp_path):
    import io
    import sys

    fake_stdout = io.StringIO()
    orig_stdout, orig_stderr = sys.stdout, sys.stderr
    sys.stdout = fake_stdout
    try:
        setup_run_logging(tmp_path)
        print("only once")
    finally:
        sys.stdout, sys.stderr = orig_stdout, orig_stderr

    # The tee should write to the real (fake, in this test) stream exactly
    # once — the console copy isn't duplicated by the logging side.
    assert fake_stdout.getvalue().count("only once") == 1

