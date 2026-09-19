#!/usr/bin/env python3
"""
grabinator.py — TikTok, YouTube, Dailymotion, SoundCloud, Instagram, X, and
Threads downloader, plus local video->MP3 conversion via --convert, caption
downloading via --captions, and full YouTube channel downloads.

By EagleSquwak, September 2026.

Requires: yt-dlp, tqdm, certifi (pip install yt-dlp tqdm certifi) and
ffmpeg/ffprobe on PATH. See README.md for full usage, flags, and security
notes.
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import ssl
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

try:
    import certifi
    _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CONTEXT = ssl.create_default_context()

try:
    from tqdm import tqdm
except ImportError:
    tqdm = None

try:
    import yt_dlp
except ImportError:
    yt_dlp = None

# --------------------------------------------------------------------------
# Hardcoded configuration — edit this path to wherever you want files saved.
# --------------------------------------------------------------------------
OUTPUT_DIR = Path.home() / "Downloads" / "media by Grabinator"

TIKTOK_HOSTS = {
    "tiktok.com", "www.tiktok.com", "m.tiktok.com",
    "vm.tiktok.com", "vt.tiktok.com",
}
YOUTUBE_HOSTS = {
    "youtube.com", "www.youtube.com", "m.youtube.com",
    "music.youtube.com", "youtu.be",
}
DAILYMOTION_HOSTS = {
    "dailymotion.com", "www.dailymotion.com", "dai.ly",
}
SOUNDCLOUD_HOSTS = {
    "soundcloud.com", "www.soundcloud.com", "m.soundcloud.com", "snd.sc",
}
INSTAGRAM_HOSTS = {
    "instagram.com", "www.instagram.com", "m.instagram.com",
}
X_HOSTS = {
    "x.com", "www.x.com", "twitter.com", "www.twitter.com",
    "mobile.twitter.com", "m.twitter.com",
}
THREADS_HOSTS = {
    "threads.net", "www.threads.net", "threads.com", "www.threads.com",
}
ALLOWED_HOSTS = TIKTOK_HOSTS | YOUTUBE_HOSTS | DAILYMOTION_HOSTS | SOUNDCLOUD_HOSTS | INSTAGRAM_HOSTS | X_HOSTS | THREADS_HOSTS

# Each platform's downloads are filed into their own subfolder under OUTPUT_DIR.
PLATFORM_FOLDER_NAMES = {
    "tiktok": "TikTok",
    "youtube": "YouTube",
    "dailymotion": "Dailymotion",
    "soundcloud": "SoundCloud",
    "instagram": "Instagram",
    "x": "X",
    "threads": "Threads",
}

MAX_URLS_PER_RUN = 25
MAX_VIDEO_HEIGHT = 1440  # cap quality one tier above 1080p (i.e. 1440p/2K) by default
MAX_PLAYLIST_ITEMS = 200
INDEX_FILENAME = ".grabinator_index.json"
NETWORK_TIMEOUT = 4  # seconds
VIDEO_EXTENSIONS = {
    ".mp4", ".mov", ".mkv", ".avi", ".webm", ".flv", ".wmv", ".m4v", ".3gp",
    ".ts", ".mpg", ".mpeg",
}
__version__ = "0.5.0"


# --------------------------------------------------------------------------
# Setup / environment checks
# --------------------------------------------------------------------------
# On legacy Windows consoles (plain cmd.exe, non-UTF-8 codepage), this
# script's emoji output can throw UnicodeEncodeError and crash outright, and
# raw ANSI color codes render as garbage instead of color. Both are fixed by
# opting into UTF-8 output and enabling virtual terminal processing; this is
# a no-op (and safe) on Linux/macOS.
def _harden_console_for_windows() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    if sys.platform == "win32":
        try:
            import ctypes
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
            mode = ctypes.c_uint32()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(handle, mode.value | 0x0004)  # ENABLE_VIRTUAL_TERMINAL_PROCESSING
        except Exception:
            pass  # best-effort — if this fails, colors just won't render


def check_dependencies(need_ytdlp: bool = True) -> None:
    missing = []
    if need_ytdlp and yt_dlp is None:
        missing.append("yt-dlp  (pip install yt-dlp)")
    if shutil.which("ffmpeg") is None:
        missing.append("ffmpeg  (install via your OS package manager)")
    if shutil.which("ffprobe") is None:
        missing.append("ffprobe (ships with ffmpeg)")
    if missing:
        print("Missing dependencies:")
        for m in missing:
            print(f"  - {m}")
        sys.exit(1)


# Mirrors everything written to a real stream (stdout/stderr) into the
# logging module as well, line by line, so every print() call in this file
# gets captured to --log's timestamped file without needing to be rewritten
# as a logger call individually. Lines are only forwarded on a real
# newline, so tqdm's \r-based live progress-bar updates don't flood the log
# file with hundreds of intermediate frames — only each bar's final state
# (written with a trailing newline on close) actually reaches the log.
class StreamToLogger:
    def __init__(self, logger: logging.Logger, level: int, real_stream):
        self.logger = logger
        self.level = level
        self.real_stream = real_stream
        self._buffer = ""

    def write(self, message: str) -> None:
        self.real_stream.write(message)
        self._buffer += message
        while "\n" in self._buffer:
            line, self._buffer = self._buffer.split("\n", 1)
            if line.strip():
                self.logger.log(self.level, line)

    def flush(self) -> None:
        self.real_stream.flush()

    def isatty(self) -> bool:
        return self.real_stream.isatty()


# Set up a timestamped .txt log file for this run under out_dir/logs/, and
# tee stdout/stderr into it via StreamToLogger — console output is
# unchanged, the log file just gets a second copy of everything. Returns
# the log file path so it can be reported to the user.
#
# Note: this reassigns sys.stdout/sys.stderr for the whole process, which
# is fine for a single-shot CLI script like this one, but is NOT something
# to reuse as-is if this module is ever imported as a library rather than
# run as __main__ — a library has no business silently hijacking its
# caller's stdout/stderr.
def setup_run_logging(out_dir: Path) -> Path:
    log_dir = out_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / f"grabinator_{timestamp}.txt"

    logger = logging.getLogger("grabinator")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    handler = logging.FileHandler(log_path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s  %(message)s", datefmt="%Y-%m-%d %H:%M:%S"))
    logger.addHandler(handler)

    sys.stdout = StreamToLogger(logger, logging.INFO, sys.stdout)
    sys.stderr = StreamToLogger(logger, logging.ERROR, sys.stderr)
    return log_path


# Probe connectivity against the exact host being downloaded from (not a
# fixed third-party address), via HTTPS rather than a raw TCP ping — some
# networks block bare TCP probes while normal HTTPS still works.
def check_internet(url: str, silent: bool = False, proxy: str | None = None) -> bool:
    host = urllib.parse.urlparse(url).netloc.lower().split(":")[0]
    if host not in ALLOWED_HOSTS:
        # Defense in depth: callers are expected to run validate_source_url()
        # first, but this function never opens a connection to a host it
        # hasn't independently confirmed is on the allowlist itself.
        raise ValueError(f"rejected (host not allowed): {host!r}")
    probe_url = f"https://{host}/"
    ok = False
    try:
        req = urllib.request.Request(probe_url, method="HEAD", headers={"User-Agent": "Mozilla/5.0"})
        if proxy:
            opener = urllib.request.build_opener(
                urllib.request.ProxyHandler({"http": proxy, "https": proxy}),
                urllib.request.HTTPSHandler(context=_SSL_CONTEXT),
            )
            with opener.open(req, timeout=NETWORK_TIMEOUT):
                ok = True
        else:
            with urllib.request.urlopen(req, timeout=NETWORK_TIMEOUT, context=_SSL_CONTEXT):
                ok = True
    except Exception:
        ok = False

    if not silent:
        if ok:
            print(f"\033[92m✅ Internet: connected ({host})\033[0m")
        else:
            print(f"\033[97m⚪ Internet: unavailable ({host})\033[0m")
    return ok


# --------------------------------------------------------------------------
# Security helpers
# --------------------------------------------------------------------------
def validate_source_url(raw_url: str) -> str:
    url = raw_url.strip()
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise ValueError(f"rejected (bad scheme): {raw_url}")
    host = parsed.netloc.lower().split(":")[0]
    if host not in ALLOWED_HOSTS:
        raise ValueError(f"rejected (host not allowed): {raw_url}")
    return url


def get_platform(url: str) -> str:
    host = urllib.parse.urlparse(url).netloc.lower().split(":")[0]
    if host in YOUTUBE_HOSTS:
        return "youtube"
    if host in DAILYMOTION_HOSTS:
        return "dailymotion"
    if host in SOUNDCLOUD_HOSTS:
        return "soundcloud"
    if host in INSTAGRAM_HOSTS:
        return "instagram"
    if host in X_HOSTS:
        return "x"
    if host in THREADS_HOSTS:
        return "threads"
    if host in TIKTOK_HOSTS:
        return "tiktok"
    raise ValueError(f"unrecognized host, not in any known platform's allowlist: {host!r}")


def is_playlist_url(url: str, platform: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    if platform == "soundcloud":
        # SoundCloud playlists ("sets") are a path segment, not a query
        # param: soundcloud.com/<artist>/sets/<name>
        return "/sets/" in parsed.path
    if platform == "youtube" and is_channel_url(url):
        return True
    return "list=" in parsed.query


# A YouTube URL that points at a channel/handle rather than a single video
# or an existing playlist — these need to be treated like a (very long)
# playlist so the whole channel's uploads get pulled in.
def is_channel_url(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc.lower().split(":")[0]
    if host == "youtu.be":
        return False
    path = parsed.path
    if "/watch" in path or "/shorts/" in path:
        return False
    return any(seg in path for seg in ("/channel/", "/c/", "/@", "/user/"))


# yt-dlp defaults to a channel's "Home" tab, which isn't a clean video
# listing. Point it at the "Videos" tab explicitly unless a specific tab
# (videos/shorts/streams/playlists/etc.) is already present in the URL.
def normalize_channel_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    path = parsed.path.rstrip("/")
    known_tabs = ("/videos", "/shorts", "/streams", "/playlists", "/community", "/about")
    if any(path.endswith(tab) for tab in known_tabs):
        return url
    return urllib.parse.urlunparse(parsed._replace(path=path + "/videos"))


# Build the yt-dlp options fragment for cookie-based auth, from whichever
# of --cookies-from-browser / --cookies was given (mutually exclusive,
# enforced in main()).
def build_cookie_opts(cookies_from_browser: str | None, cookies_file: Path | None) -> dict:
    if cookies_from_browser:
        return {"cookiesfrombrowser": (cookies_from_browser,)}
    if cookies_file:
        return {"cookiefile": str(cookies_file)}
    return {}


# Inspect a URL (without downloading) and return every distinct video
# resolution available, highest first. For a playlist, the first entry is
# used as a representative sample.
def list_video_qualities(
    url: str, proxy: str | None = None,
    cookies_from_browser: str | None = None, cookies_file: Path | None = None,
) -> list[dict]:
    opts = {"quiet": True, "no_warnings": True, "noplaylist": True}
    if proxy:
        opts["proxy"] = proxy
    opts.update(build_cookie_opts(cookies_from_browser, cookies_file))
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)

    if info.get("_type") == "playlist":
        entries = [e for e in (info.get("entries") or []) if e]
        if not entries:
            raise RuntimeError("could not read any entries from this playlist")
        info = entries[0]

    by_height: dict[int, dict] = {}
    for f in info.get("formats") or []:
        height = f.get("height")
        if not height or f.get("vcodec") in (None, "none"):
            continue
        tbr = f.get("tbr") or 0
        if height not in by_height or tbr > by_height[height].get("tbr", 0):
            by_height[height] = {"height": height, "ext": f.get("ext"), "fps": f.get("fps"), "tbr": tbr}

    qualities = sorted(by_height.values(), key=lambda x: x["height"], reverse=True)
    if not qualities:
        raise RuntimeError("no selectable video qualities were found for this URL")
    return qualities


# Print a numbered menu of available qualities and return the chosen height.
def prompt_quality_choice(url: str, qualities: list[dict]) -> int:
    print(f"\nAvailable qualities for: {url}")
    for i, q in enumerate(qualities, start=1):
        fps_part = f" {q['fps']:.0f}fps" if q.get("fps") else ""
        print(f"  {i}) {q['height']}p{fps_part} (.{q['ext']})")

    while True:
        choice = input(f"Choose a quality [1-{len(qualities)}]: ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(qualities):
            return qualities[int(choice) - 1]["height"]
        print("Invalid choice, try again.")


# Pull the @handle straight out of a TikTok URL — more reliable than
# metadata TikTok sometimes withholds when serving a JS-challenge response.
def extract_username_from_url(url: str) -> str | None:
    match = re.search(r"@([\w.\-]+)", urllib.parse.urlparse(url).path)
    return match.group(1) if match else None


# Strict whitelist sanitizer for usernames: filename-safe, no path
# separators, no dots-only.
def sanitize_component(name: str, fallback: str = "unknown") -> str:
    name = name or fallback
    name = re.sub(r"[^A-Za-z0-9_\-]", "", name)
    name = name.strip("._-")
    return name[:64] or fallback


# Blacklist sanitizer for video titles/playlist names: keeps spaces and
# readable punctuation, strips only characters illegal on common
# filesystems or that could enable path tricks.
def sanitize_title(name: str, fallback: str = "video") -> str:
    name = name or fallback
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", name)
    name = re.sub(r"\s+", " ", name).strip(" .")
    return name[:150] or fallback


# Join filename to base_dir and guarantee the result stays inside base_dir
# (blocks path traversal).
def resolve_safe_destination(base_dir: Path, filename: str) -> Path:
    dest = (base_dir / filename).resolve()
    base_resolved = base_dir.resolve()
    if base_resolved not in dest.parents and dest != base_resolved:
        raise ValueError("blocked path traversal attempt")
    return dest


# Avoid clobbering existing files by appending -1, -2, ... if needed.
def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    i = 1
    while True:
        candidate = path.with_name(f"{stem}-{i}{suffix}")
        if not candidate.exists():
            return candidate
        i += 1


# --------------------------------------------------------------------------
# Dedupe / quality-comparison index
#
# Keeps a small JSON file inside each download directory mapping each piece
# of content (platform + source id + video-or-mp3) to the file it was last
# saved as and the quality that file was measured at. This is what lets a
# second, lower-quality download of the same post get skipped instead of
# overwriting or duplicating a better copy already on disk.
# --------------------------------------------------------------------------
def load_index(out_dir: Path) -> dict:
    path = out_dir / INDEX_FILENAME
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}  # corrupt/unreadable index — start fresh rather than crash


def save_index(out_dir: Path, index: dict) -> None:
    path = out_dir / INDEX_FILENAME
    tmp = path.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(index, indent=2), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass  # dedupe bookkeeping is best-effort; never fail the download over it


def content_key(platform: str, content_id: str, mp3_only: bool) -> str:
    return f"{platform}:{content_id}:{'mp3' if mp3_only else 'video'}"


def get_video_height(path: Path) -> int:
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=height",
        "-of", "csv=p=0",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    try:
        return int(result.stdout.strip())
    except ValueError:
        return 0


# Actual (file size / duration) bitrate — more reliable than reported
# stream metadata for VBR-encoded audio.
def get_effective_bitrate_kbps(path: Path) -> int:
    try:
        size_bits = path.stat().st_size * 8
    except OSError:
        return 0
    duration = get_media_duration(path)
    return round(size_bits / duration / 1000) if duration else 0


def measure_quality(path: Path, mp3_only: bool) -> int:
    return get_effective_bitrate_kbps(path) if mp3_only else get_video_height(path)


def find_owner_key(index: dict, filename: str) -> str | None:
    for key, record in index.items():
        if record.get("path") == filename:
            return key
    return None


# Decide whether to save, skip, or replace an existing file for this same
# piece of content: no existing file -> save; existing file is equal/higher
# quality -> skip, nothing changes; existing file is lower quality -> it's
# replaced. A different piece of content that happens to want the same
# filename is never quality-compared — it gets a -1/-2 suffix instead.
# Returns the path saved to, or None if skipped.
def finalize_output(
    media_file: Path, out_dir: Path, desired_filename: str,
    platform: str, content_id: str, mp3_only: bool, silent: bool,
) -> Path | None:
    index = load_index(out_dir)
    key = content_key(platform, content_id, mp3_only)
    new_quality = measure_quality(media_file, mp3_only)

    target_path = resolve_safe_destination(out_dir, desired_filename)
    owner_key = find_owner_key(index, target_path.name)

    if owner_key and owner_key != key:
        # Different content entirely just happens to want the same filename.
        target_path = unique_path(target_path)
    elif target_path.exists():
        existing_quality = index.get(key, {}).get("quality")
        if existing_quality is None:
            existing_quality = measure_quality(target_path, mp3_only)
        if new_quality <= existing_quality:
            if not silent:
                print(f"⏭️  Skipped (existing file is equal/higher quality): {target_path.name}")
            return None
        target_path.unlink()

    shutil.move(str(media_file), str(target_path))
    index[key] = {"path": target_path.name, "quality": new_quality}
    save_index(out_dir, index)
    if not silent:
        size = human_size(target_path.stat().st_size)
        print(f"✅ Saved: {target_path} ({size})")
    return target_path


# --------------------------------------------------------------------------
# Local video -> MP3 conversion (no downloading — reformats files already
# on disk). Reuses the same padding-free MP3 extraction and quality-aware
# dedupe logic that downloads already use, so re-running this against the
# same folder never duplicates or downgrades an existing conversion.
# --------------------------------------------------------------------------
# Resolve --convert's argument into a concrete list of video files: a
# folder (non-recursive), a .txt manifest (one path per line, relative
# paths resolved against the manifest's own location, '#' comments and
# blank lines ignored), or a single video file.
def gather_video_paths(input_path: Path) -> list[Path]:
    if input_path.is_dir():
        return sorted(
            p for p in input_path.iterdir()
            if p.is_file() and p.suffix.lower() in VIDEO_EXTENSIONS
        )

    if input_path.suffix.lower() == ".txt":
        paths = []
        for line in input_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            p = Path(line).expanduser()
            if not p.is_absolute():
                p = (input_path.parent / p).resolve()
            paths.append(p)
        return paths

    if input_path.is_file() and input_path.suffix.lower() in VIDEO_EXTENSIONS:
        return [input_path]

    raise ValueError(
        f"{input_path} is not a video file, a folder of videos, "
        f"or a .txt manifest listing video paths"
    )


# Convert every video found via gather_video_paths() to a clean,
# padding-free MP3, without touching or deleting the originals. Output goes
# into an "MP3s" folder alongside the source.
def convert_local_videos_to_mp3(input_path: Path, silent: bool) -> None:
    input_path = input_path.expanduser().resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"path does not exist: {input_path}")

    videos = gather_video_paths(input_path)
    if not videos:
        print(f"No video files found at: {input_path}")
        return

    base_dir = input_path if input_path.is_dir() else input_path.parent
    mp3_dir = base_dir / "MP3s"
    mp3_dir.mkdir(parents=True, exist_ok=True)

    if not silent:
        print(f"Converting {len(videos)} video(s) to MP3 -> {mp3_dir}")

    converted, skipped, failed = 0, 0, 0
    for video in videos:
        if not video.exists():
            failed += 1
            print(f"❌ Not found: {video}")
            continue
        if video.suffix.lower() not in VIDEO_EXTENSIONS:
            failed += 1
            print(f"❌ Not a recognized video file: {video}")
            continue

        title = sanitize_title(video.stem)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                tmp_mp3 = Path(tmp) / (title + ".mp3")
                extract_clean_mp3(video, tmp_mp3, silent)
                # "local" is a pseudo-platform here purely so this shares
                # the exact same dedupe index/quality logic downloads use;
                # the original video's absolute path is the content id,
                # since two different source files could share a title.
                result = finalize_output(
                    tmp_mp3, mp3_dir, title + ".mp3",
                    "local", str(video), mp3_only=True, silent=silent,
                )
            if result is None:
                skipped += 1
            else:
                converted += 1
        except Exception as e:  # noqa: BLE001 — keep converting the rest
            failed += 1
            print(f"❌ Failed [{video.name}]: {e}")

    if not silent:
        print(f"Conversion done: {converted} converted, {skipped} skipped, {failed} failed.")
    if converted == 0 and skipped == 0:
        raise RuntimeError("all conversions in this run failed")


# --------------------------------------------------------------------------
# Progress bar hook for yt-dlp
# --------------------------------------------------------------------------
class ProgressHook:
    def __init__(self, silent: bool = False):
        self.bar = None
        self.silent = silent

    def __call__(self, d: dict) -> None:
        if self.silent or tqdm is None:
            return
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            downloaded = d.get("downloaded_bytes", 0)
            if self.bar is None:
                self.bar = tqdm(
                    total=total, unit="B", unit_scale=True, desc="Downloading", leave=False,
                    ascii="─━", colour="red",
                )
            self.bar.total = total or self.bar.total
            self.bar.n = downloaded
            self.bar.refresh()
        elif d.get("status") == "finished" and self.bar is not None:
            self.bar.n = self.bar.total or self.bar.n
            self.bar.refresh()
            self.bar.close()
            self.bar = None


# --------------------------------------------------------------------------
# ffmpeg helpers
# --------------------------------------------------------------------------
def get_media_duration(path: Path) -> float:
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    try:
        return max(float(result.stdout.strip()), 1.0)
    except ValueError:
        return 3.0


# Run an ffmpeg command with a real progress bar, driven by ffmpeg's own
# machine-readable `-progress` output (actual encoded timestamp vs. total
# duration), not a spinner or time estimate. `cmd` must start with
# ["ffmpeg", "-y", ...]. Falls back to a plain blocking call when silent or
# tqdm isn't installed.
def run_ffmpeg_with_progress(cmd: list[str], total_duration: float, desc: str, silent: bool) -> None:
    if silent or tqdm is None:
        kwargs = {}
        if silent:
            kwargs["stdout"] = subprocess.DEVNULL
            kwargs["stderr"] = subprocess.DEVNULL
        subprocess.run(cmd, check=True, **kwargs)
        return

    progress_cmd = cmd[:2] + ["-progress", "pipe:1", "-nostats"] + cmd[2:]
    proc = subprocess.Popen(
        progress_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, bufsize=1,
    )

    bar = tqdm(
        total=round(total_duration, 1), unit="s", desc=desc, leave=False,
        ascii="─━", colour="red",
    )
    last = 0.0
    try:
        for line in proc.stdout:
            line = line.strip()
            if line.startswith("out_time="):
                parts = line.split("=", 1)[1].split(":")
                try:
                    if len(parts) == 3:
                        h, m, s = parts
                        seconds = int(h) * 3600 + int(m) * 60 + float(s)
                    else:
                        seconds = last
                except ValueError:
                    seconds = last
                seconds = min(seconds, total_duration)
                if seconds > last:
                    bar.update(seconds - last)
                    last = seconds
            elif line == "progress=end":
                break
    finally:
        proc.wait()
        bar.n = bar.total
        bar.refresh()
        bar.close()

    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, progress_cmd)


# Stitch still images + one audio track into an mp4 using ffmpeg.
def render_slideshow(image_paths: list[Path], audio_path: Path, out_path: Path, silent: bool) -> None:
    if not image_paths:
        raise RuntimeError("no images provided for slideshow render")

    duration = get_media_duration(audio_path)
    per_image_duration = duration / len(image_paths)

    with tempfile.TemporaryDirectory() as tmp:
        concat_list = Path(tmp) / "concat.txt"
        with open(concat_list, "w", encoding="utf-8") as f:
            for img in image_paths:
                f.write(f"file '{img.as_posix()}'\n")
                f.write(f"duration {per_image_duration:.3f}\n")
            f.write(f"file '{image_paths[-1].as_posix()}'\n")

        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", str(concat_list),
            "-i", str(audio_path),
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-shortest",
            str(out_path),
        ]
        run_ffmpeg_with_progress(cmd, duration, "Rendering slideshow", silent)


def has_video_stream(path: Path) -> bool:
    cmd = [
        "ffprobe", "-v", "error",
        "-select_streams", "v:0",
        "-show_entries", "stream=codec_type",
        "-of", "csv=p=0",
        str(path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    return "video" in result.stdout


# Re-encode video and/or audio only if needed for native macOS playback
# (QuickTime/Preview/Photos), which reliably supports only H.264/HEVC video
# and AAC audio. TikTok often serves MP3, YouTube/Dailymotion often serve
# Opus/VP9/AV1 — all play fine in VLC but fail silently on Apple's stack.
# Whichever track is already compatible is stream-copied untouched; only a
# genuinely incompatible track gets transcoded, in one ffmpeg pass.
def ensure_mac_compatible(path: Path, silent: bool) -> Path:
    def probe(stream: str) -> str:
        cmd = [
            "ffprobe", "-v", "error",
            "-select_streams", stream,
            "-show_entries", "stream=codec_name",
            "-of", "csv=p=0",
            str(path),
        ]
        return subprocess.run(cmd, capture_output=True, text=True).stdout.strip().lower()

    video_codec = probe("v:0")
    audio_codec = probe("a:0")

    video_ok = video_codec in ("h264", "hevc", "")
    audio_ok = audio_codec in ("aac", "")

    if video_ok and audio_ok:
        return path  # already fully compatible, nothing to do

    video_args = ["-c:v", "copy"] if video_ok else ["-c:v", "libx264", "-crf", "18", "-preset", "medium"]
    audio_args = ["-c:a", "copy"] if audio_ok else ["-c:a", "aac", "-b:a", "192k"]

    fixed_path = path.with_name(path.stem + ".fixed" + path.suffix)
    cmd = [
        "ffmpeg", "-y", "-i", str(path),
        *video_args, *audio_args,
        "-movflags", "+faststart",
        str(fixed_path),
    ]
    desc = "Fixing compatibility" if not video_ok else "Fixing audio"
    run_ffmpeg_with_progress(cmd, get_media_duration(path), desc, silent)

    path.unlink()
    fixed_path.rename(path)
    return path


# Transcode audio/video to MP3 with no leading silence/padding. The
# "padding" artifact comes from source timestamps that don't start at zero
# — this affects YouTube just as much as TikTok, SoundCloud, and the rest;
# it's not a TikTok-specific quirk. Zeroing negative timestamps and
# regenerating clean presentation timestamps before encoding removes the
# gap without trimming any real audio. This same function handles every
# platform's --mp3 output, so the fix applies uniformly everywhere,
# YouTube included.
def extract_clean_mp3(input_path: Path, out_path: Path, silent: bool) -> None:
    cmd = [
        "ffmpeg", "-y",
        "-fflags", "+genpts",
        "-i", str(input_path),
        "-vn",
        "-avoid_negative_ts", "make_zero",
        "-c:a", "libmp3lame", "-q:a", "0", "-ar", "44100",
        str(out_path),
    ]
    run_ffmpeg_with_progress(cmd, get_media_duration(input_path), "Extracting MP3", silent)


# --------------------------------------------------------------------------
# TikTok + Instagram download logic — both are short-form, username-driven
# platforms with the same @handle_id naming convention and the same
# possibility of a photo/slideshow post with no native video track.
# --------------------------------------------------------------------------
def download_tiktok(
    url: str, out_dir: Path, silent: bool, mp3_only: bool, platform: str = "tiktok",
    proxy: str | None = None, cookies_from_browser: str | None = None, cookies_file: Path | None = None,
) -> None:
    hook = ProgressHook(silent=silent)

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        ydl_opts = {
            "outtmpl": str(tmp_path / "%(id)s.%(ext)s"),
            "format": "bestaudio/best" if mp3_only else "best/bestvideo+bestaudio",
            "merge_output_format": None if mp3_only else "mp4",
            "quiet": silent,
            "no_warnings": silent,
            "noprogress": silent or tqdm is None,
            "progress_hooks": [] if silent else [hook],
            "restrictfilenames": True,
            "retries": 3,
            "socket_timeout": 15,
            "noplaylist": True,
        }
        if proxy:
            ydl_opts["proxy"] = proxy
        ydl_opts.update(build_cookie_opts(cookies_from_browser, cookies_file))

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        post_id = sanitize_component(str(info.get("id", "post")))
        username_from_url = extract_username_from_url(url)
        username = sanitize_component(
            username_from_url or info.get("uploader") or info.get("uploader_id") or info.get("creator") or "unknown"
        )

        downloaded_files = list(tmp_path.glob(f"{info.get('id')}.*"))
        if not downloaded_files:
            raise RuntimeError("yt-dlp reported success but no output file was found")
        media_file = downloaded_files[0]

        base_name = f"@{username}_{post_id}"

        if mp3_only:
            extract_clean_mp3(media_file, media_file.with_suffix(".mp3"), silent)
            finalize_output(
                media_file.with_suffix(".mp3"), out_dir, base_name + ".mp3",
                platform, post_id, mp3_only=True, silent=silent,
            )
            return

        # If yt-dlp gave us something with no video track, it's likely a
        # photo/slideshow post — try to reconstruct it from its images+audio.
        if not has_video_stream(media_file):
            images = sorted(tmp_path.glob(f"{info.get('id')}_image*"))
            audio_candidates = [f for f in tmp_path.glob(f"{info.get('id')}*") if f.suffix in (".mp3", ".m4a", ".aac", ".wav")]
            if images and audio_candidates:
                rendered = tmp_path / f"{info.get('id')}_slideshow.mp4"
                render_slideshow(images, audio_candidates[0], rendered, silent)
                finalize_output(
                    rendered, out_dir, base_name + ".mp4",
                    platform, post_id, mp3_only=False, silent=silent,
                )
                return
            else:
                raise RuntimeError(
                    "post has no video track and no separable image/audio assets were found; "
                    "your yt-dlp version may need updating for this post type"
                )

        media_file = ensure_mac_compatible(media_file, silent)
        finalize_output(
            media_file, out_dir, base_name + ".mp4",
            platform, post_id, mp3_only=False, silent=silent,
        )


# --------------------------------------------------------------------------
# Generic yt-dlp download logic — used for YouTube, Dailymotion, and
# SoundCloud. Nothing here is YouTube-specific: playlist auto-detection is
# platform-aware (see is_playlist_url), so a plain single-item URL on any of
# these three simply never matches it and is treated as one item.
# --------------------------------------------------------------------------
# Parse a --range value into a 1-indexed, inclusive (start, end) tuple,
# matching yt-dlp's own playliststart/playlistend numbering. Accepts a
# single number ("10" -> videos 1-10) or a range ("3,7"/"3-7" -> videos 3-7).
def parse_range(range_str: str) -> tuple[int, int]:
    s = range_str.strip()
    if "," in s:
        parts = s.split(",", 1)
    elif "-" in s:
        parts = s.split("-", 1)
    else:
        parts = [s]
    parts = [p.strip() for p in parts]

    if any(p == "" for p in parts):
        raise ValueError(f"{range_str!r} — expected a number like 10, or a range like 3-7 or 3,7")
    parts = [p.strip() for p in parts if p.strip() != ""]

    try:
        nums = [int(p) for p in parts]
    except ValueError:
        raise ValueError(f"{range_str!r} — expected a number like 10, or a range like 3-7 or 3,7")

    if len(nums) == 1:
        n = nums[0]
        if n < 1:
            raise ValueError(f"{range_str!r} — must be at least 1")
        return 1, n
    if len(nums) == 2:
        start, end = nums
        if start < 1 or end < 1:
            raise ValueError(f"{range_str!r} — both numbers must be at least 1")
        if start > end:
            raise ValueError(f"{range_str!r} — start ({start}) can't be greater than end ({end})")
        return start, end
    raise ValueError(f"{range_str!r} — expected a number like 10, or a range like 3-7 or 3,7")


# If a YouTube URL carries its own `index` query param (the position it was
# at within a playlist when the link was copied) of 2 or higher, return it;
# otherwise None. index=1 is treated the same as "not present" since that's
# already the normal starting point.
def get_playlist_index_offset(url: str) -> int | None:
    query = urllib.parse.urlparse(url).query
    values = urllib.parse.parse_qs(query).get("index")
    if not values:
        return None
    try:
        idx = int(values[0])
    except (TypeError, ValueError):
        return None
    return idx if idx >= 2 else None


# Compute the actual 1-indexed playlist start/end to fetch. If the URL has
# its own index>=2, that position becomes the first video downloaded, and
# whatever count --range asked for (or the full-playlist default when
# --range wasn't given) is preserved from there — e.g. index=5 with
# --range 3-7 (a count of 5) downloads videos 5-9, not 3-7. With no index
# in the URL, this is unchanged: counts normally from video 1. Either way,
# the number of videos fetched in one run is capped at MAX_PLAYLIST_ITEMS.
def resolve_playlist_bounds(url: str, playlist_range: tuple[int, int] | None) -> tuple[int, int]:
    if playlist_range:
        start, end = playlist_range
        count = end - start + 1
    else:
        start, end = 1, MAX_PLAYLIST_ITEMS
        count = MAX_PLAYLIST_ITEMS

    index = get_playlist_index_offset(url)
    if index is not None:
        start = index
        end = index + count - 1

    if end - start + 1 > MAX_PLAYLIST_ITEMS:
        end = start + MAX_PLAYLIST_ITEMS - 1

    return start, end


def download_generic(
    url: str, out_dir: Path, silent: bool, mp3_only: bool,
    platform: str, target_height: int | None = None, proxy: str | None = None,
    playlist_range: tuple[int, int] | None = None,
    cookies_from_browser: str | None = None, cookies_file: Path | None = None,
) -> None:
    playlist = is_playlist_url(url, platform)
    hook = ProgressHook(silent=silent)

    if platform == "youtube" and is_channel_url(url):
        url = normalize_channel_url(url)

    if playlist:
        start, end = resolve_playlist_bounds(url, playlist_range)
        if not silent:
            print(f"Downloading playlist videos {start}-{end}...")

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        ydl_opts = {
            # Always key temp filenames off the source id — titles can
            # contain characters that are awkward on some filesystems; we
            # rename to the sanitized title ourselves once the file is
            # safely on disk.
            "outtmpl": str(tmp_path / "%(id)s.%(ext)s"),
            "format": "bestaudio/best" if mp3_only else f"bestvideo[height<={target_height or MAX_VIDEO_HEIGHT}]+bestaudio/best[height<={target_height or MAX_VIDEO_HEIGHT}]",
            "merge_output_format": None if mp3_only else "mp4",
            "quiet": silent,
            "no_warnings": silent,
            "noprogress": silent or tqdm is None,
            "progress_hooks": [] if silent else [hook],
            "restrictfilenames": True,
            "retries": 3,
            "socket_timeout": 15,
            "noplaylist": not playlist,
            "ignoreerrors": playlist,
        }
        if playlist:
            ydl_opts["playliststart"] = start
            ydl_opts["playlistend"] = end
        if proxy:
            ydl_opts["proxy"] = proxy
        ydl_opts.update(build_cookie_opts(cookies_from_browser, cookies_file))

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=True)

        entries = info.get("entries") if playlist else [info]
        entries = [e for e in (entries or []) if e]
        if not entries:
            raise RuntimeError("no videos were successfully downloaded")

        dest_root = out_dir
        if playlist:
            playlist_name = sanitize_title(info.get("title") or "playlist")
            dest_root = out_dir / playlist_name
            dest_root.mkdir(parents=True, exist_ok=True)

        saved, skipped, failed = 0, 0, 0
        for entry in entries:
            vid_id = entry.get("id")
            if not vid_id:
                failed += 1
                continue
            matches = list(tmp_path.glob(f"{vid_id}.*"))
            if not matches:
                failed += 1
                if not silent:
                    print(f"❌ Skipped (no file produced): {entry.get('title', vid_id)}")
                continue
            media_file = matches[0]
            title = sanitize_title(entry.get("title") or vid_id)
            desired_name = title

            try:
                if mp3_only:
                    mp3_tmp = media_file.with_suffix(".mp3")
                    extract_clean_mp3(media_file, mp3_tmp, silent)
                    result = finalize_output(
                        mp3_tmp, dest_root, desired_name + ".mp3",
                        platform, vid_id, mp3_only=True, silent=silent,
                    )
                else:
                    if not has_video_stream(media_file):
                        failed += 1
                        if not silent:
                            print(f"❌ Skipped (no video track): {title}")
                        continue
                    media_file = ensure_mac_compatible(media_file, silent)
                    result = finalize_output(
                        media_file, dest_root, desired_name + ".mp4",
                        platform, vid_id, mp3_only=False, silent=silent,
                    )
                if result is None:
                    skipped += 1
                else:
                    saved += 1
            except Exception as e:  # noqa: BLE001 — keep processing the rest of the playlist
                failed += 1
                if not silent:
                    print(f"❌ Failed [{title}]: {e}")

        if playlist and not silent:
            print(f"Playlist done: {saved} saved, {skipped} skipped, {failed} failed.")
        if saved == 0 and skipped == 0:
            raise RuntimeError("all downloads in this run failed")


# Download only captions/subtitles for a video or a playlist of videos, on
# any platform — no video/audio is downloaded at all. Whatever native
# subtitle format the source provides (vtt, ttml, etc.) is converted to a
# consistent .srt. Works the same for a single URL or a playlist URL
# (respecting --range), mirroring download_generic's playlist handling.
def download_captions(
    url: str, out_dir: Path, silent: bool, platform: str,
    proxy: str | None = None, cookies_from_browser: str | None = None, cookies_file: Path | None = None,
    lang: str = "en", playlist_range: tuple[int, int] | None = None,
) -> None:
    is_pl = platform in ("youtube", "dailymotion", "soundcloud") and is_playlist_url(url, platform)

    working_url = url
    if platform == "youtube" and is_channel_url(url):
        working_url = normalize_channel_url(url)

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        ydl_opts = {
            "outtmpl": str(tmp_path / "%(id)s.%(ext)s"),
            "skip_download": True,
            "writesubtitles": True,
            "writeautomaticsub": True,
            "subtitleslangs": [lang],
            "subtitlesformat": "vtt/srt/best",
            "postprocessors": [{"key": "FFmpegSubtitlesConvertor", "format": "srt"}],
            "quiet": silent,
            "no_warnings": silent,
            "noprogress": True,
            "restrictfilenames": True,
            "retries": 3,
            "socket_timeout": 15,
            "noplaylist": not is_pl,
            "ignoreerrors": is_pl,
        }
        if is_pl:
            start, end = resolve_playlist_bounds(working_url, playlist_range)
            ydl_opts["playliststart"] = start
            ydl_opts["playlistend"] = end
            if not silent:
                print(f"Fetching captions for playlist videos {start}-{end}...")
        if proxy:
            ydl_opts["proxy"] = proxy
        ydl_opts.update(build_cookie_opts(cookies_from_browser, cookies_file))

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(working_url, download=True)

        entries = info.get("entries") if is_pl else [info]
        entries = [e for e in (entries or []) if e]
        if not entries:
            raise RuntimeError("no videos were found to fetch captions for")

        platform_dir = out_dir / PLATFORM_FOLDER_NAMES.get(platform, platform.capitalize())
        dest_root = platform_dir
        if is_pl:
            playlist_name = sanitize_title(info.get("title") or "playlist")
            dest_root = platform_dir / playlist_name
        dest_root.mkdir(parents=True, exist_ok=True)

        saved, skipped, failed = 0, 0, 0
        for entry in entries:
            vid_id = entry.get("id")
            if not vid_id:
                failed += 1
                continue
            subtitle_files = sorted(tmp_path.glob(f"{vid_id}.*.srt"))
            if not subtitle_files:
                skipped += 1
                if not silent:
                    label = entry.get("title") or vid_id
                    print(f"⏭️  No captions available: {label}")
                continue

            if platform in ("tiktok", "instagram", "x", "threads"):
                username_from_url = extract_username_from_url(url)
                username = sanitize_component(
                    username_from_url or entry.get("uploader") or entry.get("uploader_id") or entry.get("creator") or "unknown"
                )
                base_name = f"@{username}_{sanitize_component(str(vid_id))}"
            else:
                base_name = sanitize_title(entry.get("title") or vid_id)

            for sub_path in subtitle_files:
                # yt-dlp names these "<id>.<lang>.srt" — pull the lang code
                # back out so multiple languages never collide on disk.
                sub_lang = sub_path.stem.split(".")[-1] if "." in sub_path.stem else lang
                filename = f"{base_name}.{sub_lang}.srt" if len(subtitle_files) > 1 else f"{base_name}.srt"
                out_path = unique_path(resolve_safe_destination(dest_root, filename))
                shutil.move(str(sub_path), str(out_path))
                saved += 1
                if not silent:
                    size = human_size(out_path.stat().st_size)
                    print(f"✅ Saved captions: {out_path} ({size})")

        if is_pl and not silent:
            print(f"Captions done: {saved} saved, {skipped} had none, {failed} failed.")
        if saved == 0:
            raise RuntimeError("no captions were found for this URL (this video/platform may not have any)")


def human_size(num_bytes: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if num_bytes < 1024:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024
    return f"{num_bytes:.1f} PB"


# Ask yt-dlp for the size of the exact format(s) that would be downloaded,
# without downloading anything.
def estimate_download_size(
    url: str, format_str: str, proxy: str | None = None,
    cookies_from_browser: str | None = None, cookies_file: Path | None = None,
) -> int | None:
    opts = {
        "quiet": True, "no_warnings": True, "noplaylist": True,
        "format": format_str, "simulate": True,
    }
    if proxy:
        opts["proxy"] = proxy
    opts.update(build_cookie_opts(cookies_from_browser, cookies_file))
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception:
        return None

    candidates = info.get("requested_formats") or [info]
    total = 0
    found = False
    for f in candidates:
        size = f.get("filesize") or f.get("filesize_approx")
        if size:
            total += size
            found = True
    return total if found else None


# Show the estimated download size (without downloading) and ask the user
# whether to proceed. Returns True to continue, False to skip.
def prompt_size_and_confirm(
    url: str, format_str: str, proxy: str | None = None,
    cookies_from_browser: str | None = None, cookies_file: Path | None = None,
) -> bool:
    size = estimate_download_size(url, format_str, proxy, cookies_from_browser, cookies_file)
    if size is None:
        print(f"Could not determine file size for: {url}")
    else:
        print(f"Estimated size: {human_size(size)}  ({url})")
    while True:
        choice = input("Download this file? [y/N]: ").strip().lower()
        if choice in ("y", "yes"):
            return True
        if choice in ("", "n", "no"):
            return False
        print("Please answer y or n.")


# Ask yt-dlp for the size of every entry in a playlist (respecting --range
# if given, otherwise up to MAX_PLAYLIST_ITEMS — the same bounds the real
# download uses), without downloading anything. Returns (total_bytes,
# entries_with_known_size, total_entries), or None if the playlist couldn't
# be read at all.
def estimate_playlist_size(
    url: str, format_str: str, proxy: str | None = None,
    playlist_range: tuple[int, int] | None = None,
    cookies_from_browser: str | None = None, cookies_file: Path | None = None,
) -> tuple[int, int, int] | None:
    start, end = resolve_playlist_bounds(url, playlist_range)
    opts = {
        "quiet": True, "no_warnings": True, "noplaylist": False,
        "format": format_str, "simulate": True,
        "ignoreerrors": True,
        "playliststart": start,
        "playlistend": end,
    }
    if proxy:
        opts["proxy"] = proxy
    opts.update(build_cookie_opts(cookies_from_browser, cookies_file))
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception:
        return None

    entries = [e for e in (info.get("entries") or []) if e]
    if not entries:
        return None

    total = 0
    counted = 0
    for entry in entries:
        candidates = entry.get("requested_formats") or [entry]
        entry_size = 0
        entry_found = False
        for f in candidates:
            size = f.get("filesize") or f.get("filesize_approx")
            if size:
                entry_size += size
                entry_found = True
        if entry_found:
            total += entry_size
            counted += 1

    return total, counted, len(entries)


# Show one aggregate size estimate for an entire playlist (without
# downloading anything) and ask once whether to proceed with all of it,
# rather than prompting separately for every video inside it.
def prompt_playlist_size_and_confirm(
    url: str, format_str: str, proxy: str | None = None,
    playlist_range: tuple[int, int] | None = None,
    cookies_from_browser: str | None = None, cookies_file: Path | None = None,
) -> bool:
    result = estimate_playlist_size(url, format_str, proxy, playlist_range, cookies_from_browser, cookies_file)
    if result is None:
        print(f"Could not read playlist metadata for: {url}")
    else:
        total, counted, entry_count = result
        if counted == 0:
            print(f"{entry_count} videos found, but size could not be determined for any of them. ({url})")
        elif counted < entry_count:
            unknown = entry_count - counted
            print(f"{entry_count} videos, ~{human_size(total)} total (size unknown for {unknown} of them). ({url})")
        else:
            print(f"{entry_count} videos, ~{human_size(total)} total. ({url})")
    while True:
        choice = input("Download this entire playlist? [y/N]: ").strip().lower()
        if choice in ("y", "yes"):
            return True
        if choice in ("", "n", "no"):
            return False
        print("Please answer y or n.")


def download_one(
    url: str, out_dir: Path, silent: bool, mp3_only: bool,
    choose_quality: bool = False, check_size: bool = False, proxy: str | None = None,
    playlist_range: tuple[int, int] | None = None,
    cookies_from_browser: str | None = None, cookies_file: Path | None = None,
    captions_only: bool = False, caption_lang: str = "en",
) -> None:
    url = validate_source_url(url)
    platform = get_platform(url)

    if platform == "soundcloud":
        # SoundCloud tracks have no video stream at all — always save as
        # audio, regardless of whether --mp3 was passed.
        mp3_only = True

    is_pl = platform in ("youtube", "dailymotion", "soundcloud") and is_playlist_url(url, platform)

    if playlist_range and not is_pl and not silent:
        print(f"Note: --range only applies to playlist URLs — downloading this one normally. ({url})")

    if captions_only:
        download_captions(url, out_dir, silent, platform, proxy, cookies_from_browser, cookies_file, caption_lang, playlist_range)
        return

    target_height = None
    if choose_quality and not mp3_only and platform != "soundcloud":
        qualities = list_video_qualities(url, proxy, cookies_from_browser, cookies_file)
        target_height = prompt_quality_choice(url, qualities)

    if check_size:
        if mp3_only:
            probe_format = "bestaudio/best"
        elif platform in ("tiktok", "instagram", "x", "threads"):
            probe_format = "best/bestvideo+bestaudio"
        else:
            h = target_height or MAX_VIDEO_HEIGHT
            probe_format = f"bestvideo[height<={h}]+bestaudio/best[height<={h}]"

        if is_pl:
            if not prompt_playlist_size_and_confirm(url, probe_format, proxy, playlist_range, cookies_from_browser, cookies_file):
                print(f"Skipped by user: {url}")
                return
        else:
            if not prompt_size_and_confirm(url, probe_format, proxy, cookies_from_browser, cookies_file):
                print(f"Skipped by user: {url}")
                return

    # File every platform's downloads into their own subfolder.
    platform_dir = out_dir / PLATFORM_FOLDER_NAMES.get(platform, platform.capitalize())
    platform_dir.mkdir(parents=True, exist_ok=True)

    if platform in ("youtube", "dailymotion", "soundcloud"):
        download_generic(url, platform_dir, silent, mp3_only, platform, target_height, proxy, playlist_range, cookies_from_browser, cookies_file)
    else:
        download_tiktok(url, platform_dir, silent, mp3_only, platform, proxy, cookies_from_browser, cookies_file)


def main() -> None:
    _harden_console_for_windows()
    parser = argparse.ArgumentParser(
        description="Download TikTok, YouTube, Dailymotion, SoundCloud, Instagram, X, and Threads videos/tracks/playlists.",
    )
    parser.add_argument("urls", nargs="?", default=None, help="One URL, or several separated by commas")
    parser.add_argument("-s", "--silent", action="store_true", help="Suppress progress bar and status output")
    parser.add_argument("--mp3", action="store_true", help="Download audio only, as a clean MP3 with no padding")
    parser.add_argument(
        "-q", "--choose-quality", action="store_true",
        help="List every available resolution for each URL and choose one by number before downloading",
    )
    parser.add_argument(
        "-c", "--check-size", action="store_true",
        help="Show the estimated file size and ask for confirmation before downloading each URL, instead of downloading immediately",
    )
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR, help="Override the destination folder")
    parser.add_argument(
        "--proxy", type=str, default=None,
        help="Route all traffic through this proxy, e.g. socks5://127.0.0.1:9050 or http://user:pass@host:port",
    )
    parser.add_argument(
        "--range", type=str, default=None, metavar="N or N-M",
        help="Limit a playlist to specific videos: a single number (e.g. 10) downloads the first 10; "
             "a range (e.g. 3-7 or 3,7) downloads videos 3 through 7 inclusive. 1-indexed. "
             "Ignored for a single video/track URL.",
    )
    parser.add_argument(
        "--convert", type=Path, default=None, metavar="PATH",
        help="Convert local video file(s) to MP3 instead of downloading anything — no network access, "
             "originals are never modified or deleted. PATH may be a single video file, a folder of "
             "videos (not recursive), or a .txt file listing one video path per line. Output goes into "
             "an 'MP3s' folder alongside the source.",
    )
    cookie_group = parser.add_mutually_exclusive_group()
    cookie_group.add_argument(
        "--cookies-from-browser", type=str, default=None, metavar="BROWSER",
        help="Reuse cookies from a browser you're logged into (e.g. chrome, firefox, edge, safari, brave) "
             "to access private/age-restricted/login-required content. Mutually exclusive with --cookies.",
    )
    cookie_group.add_argument(
        "--cookies", type=Path, default=None, metavar="FILE",
        help="Use a Netscape-format cookies.txt file for the same purpose as --cookies-from-browser, "
             "without touching your live browser profile. Mutually exclusive with --cookies-from-browser.",
    )
    parser.add_argument(
        "--captions", action="store_true",
        help="Download only captions/subtitles (converted to .srt) instead of the video/audio itself. "
             "Works for a single video or a playlist (respects --range).",
    )
    parser.add_argument(
        "--caption-lang", type=str, default="en", metavar="LANG",
        help="Language code to request with --captions (default: en).",
    )
    parser.add_argument(
        "--log", action="store_true",
        help="Also write this run's full output to a timestamped .txt file under <output-dir>/logs/, "
             "in addition to the normal console output.",
    )
    parser.add_argument("-V", "--version", action="version", version=f"grabinator {__version__}")
    args = parser.parse_args()

    if args.convert:
        check_dependencies(need_ytdlp=False)
        try:
            convert_local_videos_to_mp3(args.convert, args.silent)
        except Exception as e:
            print(f"❌ Conversion failed: {e}")
            sys.exit(1)
        return

    if not args.urls:
        parser.error("the following arguments are required: urls (unless --convert is used)")

    if args.silent and (args.choose_quality or args.check_size):
        print("--choose-quality and --check-size require an interactive prompt and can't be combined with --silent.")
        sys.exit(1)

    if args.captions and (args.mp3 or args.choose_quality or args.check_size):
        print("--captions can't be combined with --mp3, --choose-quality, or --check-size — captions have no video/audio quality or size to select.")
        sys.exit(1)

    playlist_range = None
    if args.range:
        try:
            playlist_range = parse_range(args.range)
        except ValueError as e:
            print(f"Invalid --range value: {e}")
            sys.exit(1)

    check_dependencies()

    out_dir = args.output_dir.expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.log:
        log_path = setup_run_logging(out_dir)
        if not args.silent:
            print(f"Logging this run to: {log_path}")

    raw_urls = [u for u in (part.strip() for part in args.urls.split(",")) if u]
    if not raw_urls:
        print("No URLs provided.")
        sys.exit(1)
    if len(raw_urls) > MAX_URLS_PER_RUN:
        print(f"Too many URLs in one run (max {MAX_URLS_PER_RUN}).")
        sys.exit(1)

    failures = 0
    for url in raw_urls:
        try:
            validated_url = validate_source_url(url)
            check_internet(validated_url, silent=args.silent, proxy=args.proxy)
            download_one(
                validated_url, out_dir, args.silent, args.mp3,
                args.choose_quality, args.check_size, args.proxy, playlist_range,
                args.cookies_from_browser, args.cookies,
                args.captions, args.caption_lang,
            )
        except Exception as e:  # noqa: BLE001 — surface every failure, keep going
            failures += 1
            print(f"❌ Failed [{url}]: {e}")

    if failures:
        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped (Ctrl+C).")
        sys.exit(130)
