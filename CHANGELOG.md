# Changelog

Each `## <version>` section becomes the "What's new" text users see in
FileMorph → ⋯ → Check for updates. Write it for users, in Markdown.

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
