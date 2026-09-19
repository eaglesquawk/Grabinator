# Changelog

Every notable change to Grabinator lives here, newest first. The format loosely
follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/), though the writing
leans toward plain explanation over strict categorization when that reads better.

## [Unreleased]

Cookies, captions, and full channel downloads — three additions that came out of the
same idea: some content just isn't reachable with a plain, logged-out request.

- **Cookie-based authentication.** Private accounts, age-restricted videos, and other
  login-gated content can now be reached by reusing a session you already have.
  `--cookies-from-browser chrome` (or firefox, edge, safari, brave) pulls cookies
  straight from a browser you're logged into; `--cookies FILE` does the same from an
  exported cookies.txt if you'd rather not have Grabinator touch a live browser
  profile. The two are mutually exclusive, and neither is ever written to disk,
  logged, or stored anywhere by Grabinator itself.
- **Caption/subtitle downloads.** `--captions` grabs just the subtitles for a video
  — or every video in a playlist or channel — and converts whatever format the
  platform actually provides into a consistent `.srt`. A video with no captions
  available is reported and skipped rather than failing the whole run.
- **Full YouTube channel downloads.** Point Grabinator at a channel or `@handle` URL
  and it downloads every upload, the same way it already handled playlists — no new
  flag needed, it just recognizes the URL shape. `--range` works here too, so
  grabbing "the first 20 uploads" or "videos 50 through 75" is one flag away.
- **`--log`.** Writes a full copy of a run's output to a timestamped `.txt` file
  under `<output-dir>/logs/`, in addition to — not instead of — the normal console
  output. Live progress-bar frames aren't logged individually, only each bar's final
  result, so the file stays readable rather than turning into a firehose.
- **Linting via pre-commit + ruff.** `pre-commit install` now sets up a git hook
  that runs `ruff` on every commit, catching things like unused imports and
  redefined functions before they're ever committed — the same check also runs in
  CI on every push and pull request.
- **Clarified:** the MP3 padding fix (`--mp3`, `--convert`) was never
  TikTok-specific — it's the same ffmpeg fix applied uniformly to every platform,
  YouTube included. This was already true in the code; the docs and comments just
  didn't say so clearly before.

## [0.5.0]

- Added Threads (`threads.net`/`threads.com`) support, routed the same way as
  TikTok, Instagram, and X, since it's the same kind of short-form,
  username-driven content.
- The startup banner got a small redesign: khaki instead of green, "By
  EagleSquwak" instead of "Made by EagleSquwak," and — worth calling out
  since it was a real bug — the box is now computed to a consistent width
  instead of hand-spaced, so it's actually centered.
- Removed the "This been scripted by..." line that used to print under `-h`.

## [0.4.0]

- Added `--convert PATH` for converting local video files to clean,
  padding-free MP3s without touching the network. `PATH` can be a single
  file, a folder, or a `.txt` manifest of paths, and the originals are
  never modified or deleted — output goes into a new `MP3s/` folder
  alongside whatever you pointed it at.
- Added `--version`/`-V`, and a short banner now shows on every non-silent
  run.
- Added `CONTRIBUTING.md` and this changelog.

## [0.3.0]

- Added `--range`, so a playlist download can be limited to a specific
  span of videos — a plain number like `10` for "the first 10," or
  `3-7`/`3,7` for a specific stretch.
- `-c`/`--check-size` now handles playlists properly instead of skipping
  them: one aggregate size estimate and one confirmation prompt for the
  whole thing, rather than nothing at all.
- Added `--proxy`, routing every request — downloads, the connectivity
  check, quality and size lookups, all of it — through a SOCKS5 or
  HTTP(S) proxy.
- Added X (`twitter.com`/`x.com`) support.
- Downloads are now filed into per-platform subfolders (`TikTok/`,
  `YouTube/`, `Dailymotion/`, `SoundCloud/`, `Instagram/`, `X/`) instead
  of dumping everything into one folder.
- The connectivity check now only pings the specific host being
  downloaded from, rather than a fixed third-party address.

## [0.2.0]

- Added Instagram, SoundCloud (tracks and "sets"), and Dailymotion
  support. SoundCloud tracks are always saved as MP3, since there's no
  video to speak of.
- Added `-q`/`--choose-quality` for picking a resolution interactively,
  and `-c`/`--check-size` for previewing a single file's size before
  committing to the download.
- Re-downloading the same content is no longer wasteful: a lower- or
  equal-quality repeat gets skipped automatically, and only a genuinely
  higher-quality re-download replaces the file already on disk.
- Fixed a real playback problem: tracks that played fine in VLC but were
  silent or blank in QuickTime/Preview/Photos (MP3-in-MP4, Opus, VP9,
  AV1) now get automatically re-encoded to something Apple's stack
  actually supports — only the track that needs it, nothing else.
- Progress bars for both downloading and encoding are now real, driven by
  actual byte counts and ffmpeg's own progress output rather than a
  spinner or a guess.

## [0.1.0]

The first working version: a TikTok downloader, secure by default from
day one (host allowlist, no `shell=True` anywhere, sanitized filenames,
path-traversal checks) — handling both regular video posts and
photo/slideshow posts. YouTube support followed quickly after, covering
single videos and full playlists with a sensible quality cap out of the
box, plus `--mp3` for clean, padding-free audio extraction on either
platform.
