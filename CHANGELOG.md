# Changelog

Each `## <version>` section becomes the "What's new" text users see in
FileMorph → ⋯ → Check for updates. Write it for users, in Markdown.

## 0.4.0
**New: reads scans.** Scanned PDFs and photos of documents now turn into real, editable text,
right on your PC. A scanned invoice becomes a Word document with proper tables, or an Excel
sheet with the amounts as numbers. Pick **OCR** to keep the scan exactly as it looks, but make
its text searchable and copyable. When you drop a scan, OCR is offered first.

**New: SHRINK.** Too big to email? Pick **SHRINK** to get the same file, smaller: PDFs,
photos, Word, PowerPoint and Excel files with big pictures, videos and audio. Choose *Light*,
*Balanced* or *Strong* under •••. The orb shows what you saved (*6.2 MB → 1.4 MB*), and if a
file can't get any smaller it says so instead of making a copy.

**New: recipes.** Save a conversion you do often (format, options, where it goes and how files
are named) and run it with one click:
- it's the first chip on the orb (★) when you drop files it works on
- right-click files in Explorer → **FileMorph recipes**
- or let a recipe **watch a folder**: new files that land there are converted on their own,
  with one notification per batch. *Pause watching folders* is in the tray menu.

Make one from **All formats → Save as recipe…**, or with the new ★ button in the panel.

## 0.3.4
**A quieter orb.** The glow is gone: the orb now sits on your desktop as a clean, low-profile
button with just a soft shadow. All the motion is still there, from the morph into formats to
the liquid fill and the check-mark.

- Slightly refined app icon

## 0.3.3
**New: TRACE.** Drop a logo, sketch, signature, scan, photo or PDF on the orb and pick
**TRACE** to get a clean black & white vector SVG with the white removed. It's ready for vinyl
cutters, laser engraving, stencils and print. Under ••• you can choose *Detail* (Bold, Balanced
or Fine) and *Darkness* (Lighter, Auto or Darker).

Also in this update:
- New app icon: the FileMorph orb
- Double-clicking a format no longer cancels the conversion it just started
- Selecting lots of files in Explorer always opens them as one batch
- Clicks on the glow around the orb go through to whatever is underneath
- Long videos are no longer stopped after 30 minutes, and cancelling PDF → Word stops right away
- PDF tables keep ZIP codes, IDs and decimals exactly as written when exported to Excel
- An update never interrupts a conversion that's running

## 0.3.2
A new look and a big reliability pass.

- **New app icon:** the FileMorph orb, on the installer, Start menu and taskbar
- The progress orb keeps its color ring while filling, and the percentage is easier to read
- Selecting lots of files in Explorer now always opens them as one batch
- Double-clicking a format no longer cancels the conversion it just started
- Clicks on the glow around the orb now go through to whatever is underneath
- Long videos are no longer stopped after 30 minutes
- Cancelling PDF → Word now stops right away
- PDF tables keep ZIP codes, IDs and decimals exactly as written when exported to Excel
- CSV files with missing or extra fields convert without losing data
- Big multi-page PDFs convert to TIFF without running out of memory
- Documents can't pull in web images or other files from your PC, even with LibreOffice
- An update never interrupts a conversion that's running
- More helpful update messages, and errors are now logged for troubleshooting

## 0.3.1
Reliability and safety update.

- **Cancel anytime:** click the orb (or press Esc) while it's converting
- Selecting several files in Explorer and choosing *Convert with FileMorph* now opens them as one batch
- Spreadsheets keep ZIP codes, IDs and leading zeros intact; European `1,5`-style numbers are read correctly
- Text that looks like a formula stays text when converting tables to Excel
- 16-bit, CMYK and other unusual images convert with correct colors
- Password-protected Office files fail cleanly instead of hanging
- If a folder can't be written to, results are saved to *Downloads\FileMorph* instead of being lost
- Documents can no longer pull in web images or files from elsewhere on your PC
- Quitting stops any conversion tools still running in the background
- Lower CPU use while FileMorph sits idle

## 0.3.0
**Check for updates** from the ⋯ menu (or right-click the orb). When a new version is
available you'll see what's new, and FileMorph installs it and restarts — only when you click *Update*.

- Right-click "Convert with FileMorph" and "Send to" are now set up by the installer automatically
- Installs per-user in seconds, no admin rights needed

## 0.2.0
- New floating orb interface: drop a file on it, pick a format, done
- Glass panel with recent conversions and an All formats page
- Prism, Citrus and Frost colorways

## 0.1.0
- First release: 40+ formats across documents, PDF, spreadsheets, slides, images, audio and video
