# FileMorph

Drag a file in, pick a format, done. A Windows desktop converter for documents, PDFs,
spreadsheets, presentations, images (incl. SVG & HEIC), audio and video — **fully offline**,
nothing is uploaded.

## What it converts

| Family | Formats | Highlights |
|---|---|---|
| **PDF** | → DOCX, XLSX, CSV, PPTX, TXT, HTML, PNG, JPG, WebP, TIFF, SVG (+ ODT/RTF/EPUB/MD via Word) | Real table extraction to Excel (numbers & currency kept as numbers); layout-preserving Word; one image per page; multi-page TIFF |
| **Documents** | DOCX, DOC*, ODT, RTF, TXT, MD, HTML, EPUB ↔ each other, → PDF, → images | Built-in PDF renderer works **without Office**; uses Word/LibreOffice when present for exact fidelity |
| **Spreadsheets** | XLSX, XLS, ODS, CSV, TSV, JSON ↔, → PDF/HTML | Every sheet preserved (one CSV per sheet), headers styled, wide tables go landscape in PDF |
| **Presentations** | PPTX, PPT*, ODP* ↔, → PDF*, → PNG/JPG per slide*, → TXT | |
| **Images** | PNG, JPG, WebP, AVIF, GIF, TIFF, BMP, ICO, HEIC (in), SVG | Raster → **true vector SVG** (traced, 3 detail levels); SVG → anything; animated GIF/WebP kept; multi-size ICO |
| **Audio** | MP3, WAV, M4A/AAC, FLAC, OGG, Opus; WMA/AIFF in | |
| **Video** | MP4, MOV, MKV, WebM, AVI; WMV in | → GIF (palette-optimised), → audio track |

\* needs Microsoft Office **or** the free LibreOffice installed (detected automatically; the app tells the user when it would help).

**Multi-step routing:** every converter is an edge in a graph, and the app finds the cheapest
path for any pair (e.g. `.doc → PDF → JPG`, `HEIC → SVG`), so adding one converter unlocks every
format reachable through it. Nonsense routes (PNG → XLSX, slide *text* → "PDF of slides") are blocked.

**Batches:** drop many files (or a folder). Only formats all files share are offered; files already in
the target format are kept. **Combine into one PDF** merges any mix (PDF + Word + Excel + images…).

## The Morph UI (v0.2)
FileMorph lives on your desktop as a small floating orb (design option **B · Shape-shift**):

| State | What you see |
|---|---|
| Idle | 96 px glass orb with a slowly spinning colour rim; hover it for "Drop a file · click to open" |
| Drag a file over it | grows into a wobbling rounded square, glow floods out — "Release to convert" |
| Drop | stretches into a pill of the 5 best formats (+ ••• for all of them); a white indicator springs to the chip under your mouse |
| Convert | springs back into an orb that fills with liquid, with a live percentage |
| Done | check-mark draws itself, shockwave ring, squash-and-stretch — "report.docx saved". Click the orb to open the file |
| Error | shakes, "Couldn't convert · click for details" |

Click the orb for the **glass panel**: drop zone, Recent conversions (click to show in folder; failures show why),
"Save next to original" switch, pin (keep on top) and collapse. **•••** opens *All formats* with every target plus
options (quality, combine into one PDF, resolution, SVG detail, page size, GIF width).
Drag the orb anywhere; right-click it (or the tray icon) for colorways (Prism, Citrus, Frost), keep-on-top, hide, quit.
Keyboard: in the pill use ←/→ and Enter, Esc to cancel. `FileMorph.exe --classic` opens the original window UI.

## Using it
- Drop files on the orb (or click it, then browse). Pick a format from the pill — that's it.
- Right-click any file in Explorer → **Convert with FileMorph** (Windows 11: *Show more options*), or *Send to → FileMorph*. Selecting several files opens them together in one window.
- Output goes next to the original by default (never overwrites — `name (1).ext`); switch to Downloads or any folder from **Save to**.
- Contextual options appear only when relevant: quality (JPG/WebP/AVIF/video), resolution (document → image), SVG detail, page size, GIF width.

## Project layout
```
filemorph/
  app.py                 entry point, single-instance handoff, --selftest
  core/                  formats, conversion graph, engine, updater.py (Velopack), shell.py (Explorer integration)
    formats.py           every format, extension detection + magic-byte sniffing
    registry.py          conversion graph, path planning, which targets make sense
    engine.py            runs a plan in a temp dir, publishes results safely, merge-to-PDF
    proc.py              runs bundled tools (no console windows, cancellable)
    converters/          images · pdf · documents (pandoc + HTML→PDF) · sheets · media (ffmpeg) · office (COM/LibreOffice)
  ui/node/               the Morph UI: node.py (floating orb), panel.py (glass panel), controller.py, motion.py (springs)
  ui/                    worker thread, classic window (--classic)
packaging/               PyInstaller spec, build.ps1 (Velopack release), release-notes + icon generators
tests/                   sample generator, full conversion matrix, node_screens.py (drives the real UI end-to-end)
assets/fonts/            Geist + Geist Mono (SIL Open Font License)
```

## Develop
```bash
pip install -r requirements.txt
python -m filemorph                     # run the app
python tests/make_samples.py tests/_samples
python tests/run_matrix.py tests/_samples tests/_out   # converts every sample to every offered format and validates output
```

## Releasing & updates
FileMorph is installed and updated with [Velopack](https://docs.velopack.io). Updates are **user-initiated only**:
nothing checks in the background. Users click **⋯ → Check for updates** (or right-click the orb) and see
"Version X is available" with your release notes; FileMorph downloads and installs it only after they click
**Update & restart**, then relaunches and shows "Updated to X" on the orb. Downloads are small delta packages
when possible. Updating is blocked while a conversion is running.

**To ship a new version**
1. Bump `__version__` in `filemorph/__init__.py` (and `packaging/version_info.txt`).
2. Add a `## <version>` section to `CHANGELOG.md` — this is the "What's new" users see. CI refuses to release without it.
3. Commit, then tag and push: `git tag v0.4.0 && git push --tags`.
4. GitHub Actions tests everything, builds, self-tests the .exe, packages with `vpk` and publishes a GitHub Release
   with `FileMorph-win-Setup.exe` (for new users) plus the update packages installed copies download.

**Requirements**
- `UPDATE_URL` in `filemorph/__init__.py` must be a **public** GitHub repo (installed copies read its Releases with no
  token). If the code repo is private, use a separate public releases repo — see the comments in the workflow. CI checks
  that `UPDATE_URL` matches where it publishes.
- To build locally instead of CI: install Python 3.11+ and the .NET 8 SDK, then
  `powershell -ExecutionPolicy Bypass -File packaging\build.ps1` (add `-Publish` to upload).
- Installs go to `%LocalAppData%\FileMorph` (per-user, no admin). The installer's hooks add/remove the right-click
  "Convert with FileMorph" entry, "Send to" and "Open with" (`filemorph/core/shell.py`).
- `tests/update_flow.py` exercises every update screen against a simulated release feed.

## Before shipping publicly
- **Code signing:** unsigned installers *and updates* trigger SmartScreen ("Windows protected your PC"). Sign the exe and installer (e.g. Azure Trusted Signing) to remove it.
- **Licensing:** PyMuPDF (used for PDF rendering and by pdf2docx) is **AGPL** — distributing a closed-source/commercial build needs an Artifex commercial license, or the source must be published under AGPL. Pandoc and the bundled FFmpeg build are GPL (shipped as separate executables; include their licenses and a source offer). PySide6 is LGPL.
