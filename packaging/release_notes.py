"""Write the CHANGELOG.md section for a version (used as the in-app "What's new").

usage: python packaging/release_notes.py 0.3.0 -o notes.md
Writes UTF-8 directly to the file (never through the console, whose Windows code page
can't encode characters like "⋯" or "→"). Exits non-zero if the version has no section.
"""
import re
import sys
from pathlib import Path

args = sys.argv[1:]
out = None
if "-o" in args:
    i = args.index("-o")
    out = args[i + 1]
    del args[i:i + 2]
version = args[0].lstrip("v")

text = Path(__file__).resolve().parents[1].joinpath("CHANGELOG.md").read_text(encoding="utf-8")
m = re.search(rf"^## {re.escape(version)}\s*$(.*?)(?=^## |\Z)", text, re.M | re.S)
if not m or not m.group(1).strip():
    sys.exit(f"CHANGELOG.md has no '## {version}' section - add release notes before building.")
notes = m.group(1).strip() + "\n"
if out:
    Path(out).write_text(notes, encoding="utf-8")
else:
    sys.stdout.buffer.write(notes.encode("utf-8"))
