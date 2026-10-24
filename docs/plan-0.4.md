# FileMorph 0.4 — OCR, SHRINK, Recipes & watch folders

Three features, built in this order (each one is useful on its own, and recipes get more
valuable once OCR and SHRINK exist).

---

## 1. Offline OCR

**Problem.** "PDF → editable Word / real Excel numbers" only works when the PDF has a text
layer. Scans, phone photos of documents and faxes are the most common real-world input, and
today they fail with *"No text found — this PDF looks like a scan."*

**Engine.** [RapidOCR](https://github.com/RapidAI/RapidOCR) (PP-OCRv6 small, ONNX). The wheel
ships its models (~31 MB: detection, recognition, orientation), runs fully offline, covers
English + ~50 Latin-script languages, and runs on onnxruntime, which PyMuPDF already depends on.
About 2 s per page on a laptop CPU. Windows' built-in OCR was rejected: its results depend on
which OS language packs are installed, which can't be tested in CI.

**Behaviour.**
| Input | What changes |
|---|---|
| Scanned / image-only PDF → DOCX, XLSX, TXT, HTML, CSV | Pages with no text layer are OCR'd automatically first. Digital pages are untouched. |
| PDF or image → **OCR** (new, "Searchable PDF") | Same pages, same look, with an invisible text layer: selectable, searchable, copyable. Output `Name - searchable.pdf`. |
| Image (photo of a page/receipt/table) → TXT, DOCX, XLSX | New targets, via image → PDF → OCR. |
| Scanned PDF dropped on the orb | OCR is promoted into the 5-format pill (detected in < 50 ms by checking the first pages for a text layer). |

**Design.**
- `core/converters/ocr.py`
  - `engine()` – cached RapidOCR instance, logging silenced, models from the package.
  - `read_image(PIL) -> [Line(text, box, score)]` – runs OCR, keeps lines with score ≥ 0.5.
  - `page_needs_ocr(page)` – < 12 chars of text and at least one image covering ≥ 30% of it.
  - `looks_scanned(path)` – quick check for the UI (first 3 pages).
  - `rebuild_text_pdf(src, ctx) -> Path` – a temp copy where each scanned page is replaced by a
    white page carrying the OCR'd text as real, visible text at its original position and size.
    Every existing PDF converter (pdf2docx, pdfplumber tables, text, HTML) then just works on it.
  - `make_searchable(src, dst, ctx)` – keeps the scan image and adds the text as invisible
    text (render mode 3), sized to each line's box, so selection lines up with the picture.
- `pdf.py`: `pdf_to_docx/xlsx/txt/html` call `ocr.prepare(src, ctx)` first (returns `src` when
  no page needs OCR, so digital PDFs keep the exact current behaviour and speed).
- Format `ocrpdf` (chip **OCR**, label "Searchable PDF", category *Tools*, output `.pdf`).
- Registry: images may now target `txt`, `docx`, `xlsx`, `ocrpdf`.
- Errors stay friendly: *"No text found, even after reading the scan."*

**Acceptance.**
- Generated scan (text rendered to an image, rotated 1°, blurred, saved as image-only PDF):
  - → TXT contains ≥ 90% of the source words.
  - → XLSX has the invoice amounts as numbers in cells.
  - → DOCX has the words as editable paragraphs.
  - → OCR PDF: `page.get_text()` finds the words; page still renders the original image.
- Digital PDFs: identical output to 0.3.4 (OCR never runs, checked by monkeypatch test).
- Cancel between pages works; frozen build self-test includes `scan-pdf->txt`.

---

## 2. SHRINK — make it smaller

**Problem.** The most common file task isn't changing format, it's "this is too big to email
or upload". Today that means guessing quality sliders under •••.

**Behaviour.** A new **SHRINK** chip (category *Tools*) for PDF, JPG, PNG, WebP, AVIF, TIFF,
DOCX, PPTX, XLSX, MP4, MOV, MKV, WebM, MP3, M4A, OGG, Opus. Output keeps the format and
extension: `Report - small.pdf`. One option, **Strength: Light · Balanced · Strong**.

| Family | Light | Balanced (default) | Strong |
|---|---|---|---|
| PDF (images re-encoded, streams compacted) | 200 dpi, JPEG q80 | 150 dpi, q70 | 96 dpi, q55 |
| Photos (JPG/WebP/AVIF/TIFF) | q85, full size | q75, ≤ 2560 px | q60, ≤ 1600 px |
| PNG | lossless optimise | 256-colour palette (only when it really saves), ≤ 2560 px | palette, ≤ 1600 px |
| DOCX/PPTX/XLSX (embedded pictures) | ≤ 2560 px, q85 | ≤ 1920 px, q75 | ≤ 1280 px, q60 |
| Video (H.264/VP9) | CRF 24 | CRF 28, ≤ 1080p | CRF 32, ≤ 720p |
| Audio | 160 kbps | 128 kbps | 80 kbps |

- Metadata that's only weight (EXIF thumbnails, PDF orphans) is dropped; photo orientation and
  colour profiles are kept.
- If the result isn't at least 3% smaller, nothing is written and the user sees
  *"Already as small as it gets — Report.pdf can't be shrunk further."*
- Done state shows the saving: **✓ Report - small.pdf · 12.4 MB → 1.8 MB** (batches show the total).
- Pill: SHRINK is in the suggested formats for PDF, photos, Office files and videos.

**Design.**
- `Fmt` gains `keep_ext=True`; the engine names the output with the source's own extension.
- `core/converters/shrink.py` registers direct `X → shrink` edges only (never chained), and
  `target_allowed` only offers *Tools* formats where a direct edge exists.
- Controller passes `shrink_strength` (remembered like other options) and builds the
  before/after caption from file sizes.

**Acceptance.** For every SHRINK source in the test matrix: output opens as the same format,
is smaller than the input (samples are generated deliberately "fat"), and keeps page/slide/
duration counts. Already-compact input gives the friendly error and leaves no file.

---

## 3. Recipes & watch folders

**Problem.** The same conversion is repeated constantly (iPhone photos → JPG, every scan →
searchable PDF, every recording → MP3). Today each one is drop → pick → options.

**Recipe** = name + target format + options + where to save (next to original / a folder) +
rename pattern (`{name}`, `{date}`, `{time}`, `{n}`) + optional watch folder.
Stored in `%LOCALAPPDATA%\FileMorph\recipes.json` (core module, no Qt, unit-tested).

**Where recipes show up.**
1. **The orb.** When dropped files can use a recipe, it's the first chip (`★JPG`, up to 2);
   hovering shows the recipe's name. One click runs it with its saved options, folder and name.
2. **Explorer.** Right-click → **FileMorph recipes ▸ Phone photos → JPG** (a per-user cascading
   menu, rewritten whenever recipes change; installed builds only). Multi-select becomes one batch.
3. **Watch folders.** A recipe can watch a folder: files that *arrive after watching starts*
   are converted silently in the background, with one tray notification per burst
   ("Converted 3 files with *Scans → searchable*"). Rules:
   - waits until a file stops growing and can be opened (downloads, phone imports, scanners);
   - ignores partial/temp files (`.crdownload`, `.part`, `.tmp`, `~$…`, hidden) and anything
     the recipe can't convert;
   - never re-converts its own outputs or a file it already did (ledger keyed by path + size +
     mtime), so writing into the watched folder can't loop;
   - catches up on files added while FileMorph was closed (anything newer than the
     watch's start time and not in the ledger);
   - *Pause watching* in the tray menu.

**UI.**
- Panel header gets a ★ button → **Recipes** page: list (name, "PDF → OCR · watching Scans"),
  each with a watch switch, edit and delete; **New recipe**.
- **Recipe editor** (scrolls inside the panel): name, convert-to (all formats, grouped), the
  same option rows the All formats page uses, save location, rename pattern with a live
  example, watch folder.
- **All formats** page gets *Save as recipe…*: the current format + options open in the editor.

**Design.**
- `core/recipes.py`: `Recipe` dataclass, load/save (atomic write, tolerant of damaged files),
  `render_name(pattern, src, n)`, `Ledger`.
- `engine.convert_file(..., out_stem=...)`: final file name from the rendered pattern
  (page suffixes etc. still appended).
- `instance.post(paths, recipe=id)` / `drain()` returns batches with an optional recipe;
  `FileMorph.exe --recipe <id> files…` runs it.
- `shell.install_recipes(recipes)` writes the cascading menu; `uninstall()` removes it.
- `ui/node/watch.py`: `WatchService` (QFileSystemWatcher + 4 s poll, stability check, queue,
  background worker thread, tray message).

**Acceptance.** Unit tests for name rendering, persistence round-trip, damaged-file recovery,
ledger, stability/ignore rules and loop prevention (output dropped into the watched folder).
A UI drive test: create recipe through the editor → drop a file → recipe chip runs it with the
right name/folder → enable watch → copy a file into the folder → converted output appears
exactly once.

---

## Verification (all features)

1. `python tests/make_samples.py tests/_samples` (adds a scanned PDF, a scanned PNG, and fat
   samples for SHRINK).
2. `python tests/run_matrix.py tests/_samples tests/_out --jobs 4`. Every sample → every
   offered format, including OCR and SHRINK, with new validators (OCR text present, SHRINK
   smaller and same type).
3. `python tests/test_features.py`: focused OCR quality, SHRINK, recipes and watch tests.
4. `python tests/node_screens.py tests/_samples _shots`: real UI end to end, plus new screens
   (scanned-PDF pill with OCR, SHRINK done caption, recipes page, editor, recipe chip, watch).
5. `python -m filemorph --selftest`: new `scan->txt`, `scan->ocrpdf`, `pdf->shrink` steps.
6. Frozen build (PyInstaller) self-test if PyInstaller is available locally; otherwise CI.

## Release

Version 0.4.0, a `CHANGELOG.md` section for users, README feature and FAQ updates. Not tagged or
released. That's the owner's call.
