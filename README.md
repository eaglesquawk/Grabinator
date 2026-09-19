# Grabinator

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue)
![Platforms](https://img.shields.io/badge/platform-Linux%20%7C%20Windows%20%7C%20macOS-lightgrey)

A command-line downloader for **TikTok, YouTube, Dailymotion, SoundCloud, Instagram,
X, and Threads** — security-hardened, with automatic quality-aware deduplication and
playback fixes for native macOS players. Also converts local video files to MP3 with
`--convert`, no network access required.

## Table of contents

- [Features](#features)
- [Supported platforms (OS)](#supported-platforms-os)
- [Installation](#installation)
- [Usage](#usage)
- [Authentication (cookies)](#authentication-cookies)
- [Configuration](#configuration)
- [Security measures](#security-measures)
- [Testing status](#testing-status)
- [Legal](#legal)
- [Development](#development)
- [Author](#author)
- [License](#license)

## Features

| | |
|---|---|
| **Sources** | TikTok, YouTube, Dailymotion, SoundCloud, Instagram, X, Threads |
| **Naming** | TikTok/Instagram/X/Threads → `@username_id.mp4` · YouTube/Dailymotion → `title.mp4` |
| **Organization** | Each platform gets its own subfolder (`TikTok/`, `YouTube/`, etc.) |
| **Audio** | `--mp3` extracts clean, padding-free audio on any platform |
| **Local conversion** | `--convert PATH` turns existing video files into MP3s — no downloading |
| **Captions** | `--captions` downloads subtitles only (converted to `.srt`), for a video or a whole playlist |
| **Channels** | Point a YouTube channel/handle URL at Grabinator and it downloads every upload, same as a playlist |
| **Playlists** | Full YouTube/SoundCloud playlist support, with `--range` to grab a specific span |
| **Quality selection** | Capped one tier above 1080p by default, or pick interactively with `-q` |
| **Dedupe** | Re-downloading never creates duplicates — a lower/equal-quality repeat is skipped, a genuinely better one replaces the old file |
| **macOS fix** | Auto re-encodes tracks that play in VLC but are silent/blank in QuickTime, Preview, or Photos |
| **Proxy** | `--proxy` routes every request (including the connectivity check) through a SOCKS5/HTTP(S) proxy |
| **Cookies** | `--cookies-from-browser` or `--cookies` unlock private/login-required content |
| **Size check** | `-c` shows the estimated download size — one total for a whole playlist — before anything downloads |

## Supported platforms (OS)

Pure Python, using only `pathlib`/`subprocess` for filesystem and process work — it
runs the same way on:

- **Linux** — any distro with Python 3.10+ and `ffmpeg` available.
- **macOS** — including the playback-compatibility fixes this tool specifically adds.
- **Windows** — the script forces UTF-8 console output and enables ANSI color
  processing on startup, so the colored status output and emoji indicators render
  correctly instead of crashing or printing garbled escape codes on a legacy `cmd.exe`
  codepage. Works from PowerShell, Windows Terminal, or plain `cmd.exe`.

The one external dependency that varies by OS is `ffmpeg` itself — see
[Installation](#installation) for the install command on each.

## Installation

```bash
git clone https://github.com/eaglesquawk/grabinator.git
cd grabinator
pip install -e .
```

This also installs `yt-dlp`, `tqdm`, and `certifi`. Separately, install `ffmpeg`
(which includes `ffprobe`) via your OS package manager:

```bash
brew install ffmpeg          # macOS
sudo apt install ffmpeg      # Debian/Ubuntu
winget install ffmpeg        # Windows
```

## Usage

### Single items

```bash
grabinator "https://www.tiktok.com/@user/video/123"
grabinator "https://www.youtube.com/watch?v=XXXXXXXXXXX"
grabinator "https://www.dailymotion.com/video/XXXXXXX"
grabinator "https://soundcloud.com/artist/track-name"
grabinator "https://www.instagram.com/p/XXXXXXXXXXX/"
grabinator "https://x.com/user/status/XXXXXXXXXXX"
grabinator "https://www.threads.net/@user/post/XXXXXXXXXXX"
```

### Playlists and channels

```bash
grabinator "https://www.youtube.com/playlist?list=XXXXXXXXXXX"
grabinator "https://soundcloud.com/artist/sets/album-name"

# A YouTube channel or handle downloads every upload, the same as a playlist —
# no special flag needed, Grabinator recognizes the URL shape automatically
grabinator "https://www.youtube.com/@SomeChannel"
grabinator "https://www.youtube.com/channel/UCxxxxxxxxxxxxxxxxxxxxxx"

# Only videos 3 through 7 of a playlist or channel
grabinator "PLAYLIST_OR_CHANNEL_URL" --range 3-7

# Just the first 10
grabinator "PLAYLIST_OR_CHANNEL_URL" --range 10
```

### Multiple URLs at once

```bash
grabinator "URL1,URL2,URL3"
```

### Audio

```bash
# Audio only, on any platform — clean MP3, no leading silence
grabinator "URL" --mp3
```

The leading-silence "padding" that naive MP3 extraction leaves in place comes from
source timestamps that don't start at zero — this isn't a TikTok-specific quirk, it
affects YouTube (and Dailymotion, SoundCloud, the rest) just as much. `--mp3` runs
the exact same ffmpeg fix — zeroing negative timestamps and regenerating clean
presentation timestamps before encoding — on every platform uniformly, YouTube
included, so the output is padding-free no matter where it came from.

```bash
# Convert local video files to MP3 instead — no network access at all,
# originals are never touched. PATH can be a file, a folder, or a .txt
# manifest listing one path per line.
grabinator --convert /path/to/videos
grabinator --convert /path/to/video.mp4
grabinator --convert /path/to/list.txt
```

### Captions

```bash
# Download only the subtitles for a video, saved as .srt
grabinator "URL" --captions

# Works on a whole playlist or channel too — one .srt per video
grabinator "PLAYLIST_OR_CHANNEL_URL" --captions

# A specific language (default: en)
grabinator "URL" --captions --caption-lang es
```

Whatever subtitle format the source actually provides gets converted to `.srt`, so
the output is consistent regardless of platform. If a video simply has no captions
available, Grabinator says so and moves on rather than failing the whole run.

### Quality selection

```bash
# Interactively pick a resolution from a numbered menu
grabinator "URL" -q

# See the estimated file size and confirm before downloading
# (one total for an entire playlist, not one prompt per video)
grabinator "URL" -c
```

### Proxy

```bash
grabinator "URL" --proxy socks5://127.0.0.1:9050
grabinator "URL" --proxy http://user:pass@host:port
```

### Other flags

```bash
grabinator "URL" --silent                  # suppress progress bars and status output
grabinator "URL" --output-dir /some/path   # override the default download folder
grabinator "URL" --log                     # also write this run's output to a timestamped .txt file
grabinator --version                       # print the installed version
```

`--log` writes a full copy of everything printed during that run to
`<output-dir>/logs/grabinator_<timestamp>.txt`, one file per run, alongside — not
instead of — the normal console output. Live-updating progress-bar frames aren't
logged individually (that would just be noise); each bar's final result still is.

Run without installing, straight from the source file:

```bash
python src/grabinator/cli.py "URL"
```

## Authentication (cookies)

Some content requires being logged in to view at all — a private Instagram account,
an age-restricted YouTube video, some Threads posts. Grabinator doesn't handle logins
itself; instead it borrows a session you already have, the same way `yt-dlp` does
under the hood.

```bash
# Reuse cookies from a browser you're already logged into
grabinator "PRIVATE_URL" --cookies-from-browser chrome
grabinator "PRIVATE_URL" --cookies-from-browser firefox

# Or use an exported cookies.txt file instead, without touching a live browser profile
grabinator "PRIVATE_URL" --cookies /path/to/cookies.txt
```

The two are mutually exclusive — pick one. `--cookies-from-browser` reads directly
from that browser's cookie storage each run; `--cookies` points at a Netscape-format
file you've exported once (browser extensions like "Get cookies.txt" can produce
this). Neither option is stored, logged, or written anywhere by Grabinator itself —
they're passed straight through to `yt-dlp` for that run only.

## Configuration

The default download folder is set at the top of `src/grabinator/cli.py`:

```python
OUTPUT_DIR = Path.home() / "Downloads" / "media by Grabinator"
```

Edit that constant, or pass `--output-dir` on the command line to override it per run.
Whatever you choose, each platform still gets its own subfolder underneath it.

## Security measures

- URLs are checked against an explicit host allowlist (TikTok/YouTube/Dailymotion/
  SoundCloud/Instagram/X/Threads domains only) before any network request is made.
- All subprocess calls (`ffmpeg`, `ffprobe`) use argument lists, never `shell=True`.
- Filenames derived from remote titles/usernames are sanitized, and every final
  destination path is resolved and verified to stay inside the configured output
  directory before anything is written — blocking path traversal from a malicious or
  unexpected title.
- Per-run URL and playlist-size caps guard against accidental bulk-scraping.
- The connectivity check only probes the exact host a given URL points to — never a
  fixed external address unrelated to what you asked to download.
- `--convert` never opens the network at all, and never modifies or deletes the
  original video files it reads.
- Cookies passed via `--cookies-from-browser` or `--cookies` are used only for that
  run's requests — Grabinator never writes them to disk, logs them, or includes them
  in the dedupe index.

## Testing status

The pure logic (URL/platform detection, path safety, filename sanitization, range
parsing, cookie-options handling, etc.) is covered by an automated test suite and
verified on every push. A few things are logic-verified but **not yet confirmed
against real, live usage**:

- **Windows.** The UTF-8/ANSI console hardening is implemented and tested for
  correctness, but hasn't been run on an actual Windows machine.
- **Cookies** (`--cookies-from-browser`, `--cookies`). The options are built and
  passed to `yt-dlp` correctly, but haven't been exercised against a real
  login-gated download.
- **Channel downloads.** URL detection and normalization to a channel's "Videos"
  tab are tested, but a real channel hasn't been downloaded end-to-end yet.
- **Captions.** The download and `.srt` conversion path hasn't been run against a
  real video with real subtitles.

If you hit something that doesn't work as documented in one of these areas, that's
useful to know about.

## Legal

Built on [yt-dlp](https://github.com/yt-dlp/yt-dlp) and `ffmpeg`. Use it for content
you have the right to download — your own uploads, permissively licensed content, or
personal archival use consistent with each platform's Terms of Service and applicable
copyright law. You're responsible for how you use it.

## Development

```bash
pip install -e ".[dev]"
pre-commit install
pytest
```

Linting/formatting runs automatically on commit via `pre-commit` + `ruff`. See
[CONTRIBUTING.md](CONTRIBUTING.md) for how to add a new platform, what's expected
of a pull request, and the release process. See [CHANGELOG.md](CHANGELOG.md) for the
project's history.

## Author

EagleSquwak — September 2026

## License

[MIT](LICENSE)
