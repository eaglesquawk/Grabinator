# Contributing to Grabinator

Thanks for considering a contribution — here's how to get set up and where to look first.

## Setup

```bash
git clone https://github.com/eaglesquawk/grabinator.git
cd grabinator
pip install -e ".[dev]"
pre-commit install
```

`pre-commit install` registers a git hook that runs `ruff` automatically before
every commit — it catches lint errors (unused imports, undefined names,
redefined functions) and auto-formats the code, so problems get caught locally
before they ever reach a pull request. You only need to run this once per clone.

`ffmpeg` (which includes `ffprobe`) must also be installed and on `PATH`:

```bash
brew install ffmpeg          # macOS
sudo apt install ffmpeg      # Debian/Ubuntu
winget install ffmpeg        # Windows
```

## Running tests

```bash
pytest
```

To run the same lint check pre-commit runs, without committing anything:

```bash
ruff check .
```

Tests are network-free by design — they exercise the pure logic (`sanitize_title`,
`resolve_safe_destination`, `parse_range`, platform/playlist detection, `human_size`,
etc.), so they run in milliseconds and never depend on a platform being reachable or
unchanged. CI (`.github/workflows/test.yml`) runs the same suite on every push/PR
across Python 3.10–3.12.

## Adding a new platform

Platform support follows one consistent pattern — look at how Instagram or SoundCloud
was added for a concrete example:

1. Add the platform's hostnames to a `<PLATFORM>_HOSTS` set and fold it into
   `ALLOWED_HOSTS`.
2. Add an entry to `PLATFORM_FOLDER_NAMES` so its downloads get their own subfolder.
3. Teach `get_platform()` to recognize the new hosts.
4. Decide which existing download path it's closer to:
   - Short-form, username-driven, no reliable "title" (the TikTok/Instagram/X
     pattern) → route through `download_tiktok()`.
   - Long-form, title-driven, potentially has playlists (the
     YouTube/Dailymotion/SoundCloud pattern) → route through `download_generic()`.
5. If it has its own playlist URL shape (SoundCloud's `/sets/` vs. YouTube's
   `?list=`), teach `is_playlist_url()` about it.
6. Add test cases to `tests/test_core.py` for `get_platform()` and, if relevant,
   `is_playlist_url()`.

## Security expectations

Any new code that touches URLs, filesystem paths, or subprocess calls should keep the
same guarantees the rest of the codebase has:

- Validate the host against an explicit allowlist before any network call.
- Never use `shell=True`; always pass argument lists to `subprocess`.
- Sanitize any remote-supplied string (title, username) before it touches a file
  path, and resolve the final path to confirm it stays inside the intended output
  directory.

## Pull requests

- Keep changes focused — one feature or fix per PR is easier to review than several
  bundled together.
- Add or update tests for anything in the "pure logic" category above.
  Network-dependent behavior (an actual download) is intentionally left untested in
  CI, so a clear description of how you manually verified it helps a lot.
- Update `CHANGELOG.md` under an `[Unreleased]` heading for anything user-facing.

## Releasing (PyPI)

1. Bump the version in **both** places — they must match:
   - `__version__` in `src/grabinator/cli.py`
   - `version` in `pyproject.toml`
2. Move the `CHANGELOG.md` entry from `[Unreleased]` to the new version number.
3. Commit, then tag and push:
   ```bash
   git tag v0.5.0
   git push --tags
   ```
4. Build and publish:
   ```bash
   pip install build twine
   python -m build
   twine upload dist/*
   ```
   `twine upload` will prompt for PyPI credentials (an API token is recommended
   over a password — generate one at pypi.org under Account Settings).
5. Turn the git tag into a GitHub Release and paste in that version's changelog
   entry as the release notes.
