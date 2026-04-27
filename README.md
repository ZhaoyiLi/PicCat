# Bunny Sort

Bunny Sort is a local desktop media sorting app for quickly reviewing large folders of photos and videos.

Core flow:

1. Open a source folder.
2. Preview the current image or video.
3. Press a configured shortcut to copy, move, or skip.
4. The app advances to the next item automatically.

## Features in this MVP

- Python + PySide6 desktop UI.
- Recursive scan for common image and video formats.
- Large image preview with background thumbnail generation.
- Video playback using `PySide6.QtMultimedia`.
- Editable classification rules with shortcut, label, target folder, action, and count.
- Immediate mode for live copy/move/skip.
- Batch mode with pending action list and commit.
- `Ctrl+Z` undo for copy, move, skip, and pending batch actions.
- `Right` / `Left` navigation.
- JSON session saved as `.media_sorter_session.json` inside the source folder.
- Conflict handling defaults to `rename_new_file`.
- Copy uses `shutil.copy2()` to preserve file metadata where possible.

## Install

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Optional but recommended for video metadata:

```powershell
winget install Gyan.FFmpeg
```

The app still plays videos without `ffprobe`, but duration/resolution metadata may be unavailable until Qt loads the media.

## Run

```powershell
python main.py
```

## Notes

- Session files are stored in the chosen source folder, so reopening the same folder restores progress, rules, undo history, and batch pending actions.
- Images are loaded as scaled previews in a background thread. The app keeps a bounded cache rather than holding original full-size images in memory.
- Videos are streamed from disk by Qt. The app does not preload full video files.

