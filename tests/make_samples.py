"""Generate one realistic sample file for every input format FileMorph supports."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


SCAN_LINES = [("INVOICE 10442",), ("Billed to: Northwind Traders",), ("Item", "Qty", "Price"),
              ("Widget", "2", "14.50"), ("Gadget", "10", "120.00"), ("Total", "", "149.00"),
              ("Thank you for your business.",)]


def make_scan():
    """A letter-size page of text at 200 dpi, as a scanner would produce it."""
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    im = Image.new("RGB", (1700, 2200), "white")
    d = ImageDraw.Draw(im)
    try:
        f = ImageFont.truetype("times.ttf", 40)
    except OSError:
        f = ImageFont.load_default(40)
    for i, parts in enumerate(SCAN_LINES):
        for x, text in zip((150, 600, 850), parts):
            d.text((x, 200 + i * 80), text, fill="black", font=f)
    return im.rotate(0.8, fillcolor="white").filter(ImageFilter.GaussianBlur(0.7))


def make(out: Path) -> None:
    from PIL import Image, ImageDraw
    import pillow_heif
    from filemorph.core.converters.media import ffmpeg_exe
    from filemorph.core.converters.documents import pandoc_exe
    from filemorph.core.converters.office import soffice_exe

    out.mkdir(parents=True, exist_ok=True)

    # ---------- images
    im = Image.new("RGBA", (640, 420), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((20, 20, 620, 400), 40, fill=(52, 120, 246, 255))
    d.ellipse((220, 110, 420, 310), fill=(255, 255, 255, 230))
    d.polygon([(320, 140), (380, 280), (260, 280)], fill=(255, 170, 0, 255))
    im.save(out / "sample.png")
    photo = Image.radial_gradient("L").resize((800, 600)).convert("RGB")
    photo = Image.merge("RGB", (photo.getchannel(0), photo.rotate(90).getchannel(0),
                                Image.linear_gradient("L").resize((800, 600))))
    photo.save(out / "sample.jpg", quality=92)
    photo.save(out / "sample.webp", quality=85)
    photo.save(out / "sample.tiff")
    photo.save(out / "sample.bmp")
    photo.save(out / "sample.avif", quality=70)
    im.resize((256, 256)).save(out / "sample.ico")
    pillow_heif.from_pillow(photo).save(out / "sample.heic", quality=80)
    frames = []
    for i in range(6):
        f = Image.new("RGB", (240, 160), (30, 30, 40))
        ImageDraw.Draw(f).ellipse((20 + i * 30, 50, 80 + i * 30, 110), fill=(255, 90, 90))
        frames.append(f)
    frames[0].save(out / "sample.gif", save_all=True, append_images=frames[1:], duration=120, loop=0)
    (out / "sample.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="200" viewBox="0 0 300 200">'
        '<rect width="300" height="200" rx="24" fill="#0f766e"/><circle cx="150" cy="100" r="60" fill="#fde68a"/>'
        '<path d="M60 170 L240 170" stroke="#fff" stroke-width="8" stroke-linecap="round"/>'
        '<text x="150" y="110" font-family="Arial" font-size="28" text-anchor="middle" fill="#134e4a">SVG</text></svg>',
        encoding="utf-8")

    # ---------- documents
    import docx
    from docx.shared import Inches
    doc = docx.Document()
    doc.add_heading("Quarterly Report", 0)
    p = doc.add_paragraph("This sample document has ")
    p.add_run("bold").bold = True
    p.add_run(", ")
    p.add_run("italic").italic = True
    p.add_run(" text, accents like café and naïve, a table and an image.")
    doc.add_heading("Figures", level=1)
    t = doc.add_table(rows=4, cols=3)
    t.style = "Table Grid"
    for r, row in enumerate([["Region", "Units", "Revenue"], ["West", "120", "$4,800"],
                             ["East", "95", "$3,900"], ["South", "143", "$5,720"]]):
        for c, v in enumerate(row):
            t.cell(r, c).text = v
    doc.add_paragraph("Bullet one", style="List Bullet")
    doc.add_paragraph("Bullet two", style="List Bullet")
    doc.add_picture(str(out / "sample.png"), width=Inches(2.5))
    doc.save(out / "sample.docx")

    pandoc = pandoc_exe()
    for fmt, ext in [("odt", "odt"), ("rtf", "rtf"), ("gfm", "md"), ("html5", "html"), ("epub3", "epub")]:
        subprocess.run([pandoc, str(out / "sample.docx"), "-s", "-M", "title=Sample", "-t", fmt,
                        "-o", str(out / f"sample.{ext}")], check=True)
    (out / "sample.txt").write_text("Meeting notes\n\nAttendees: Ana, Bo, Chen.\nDecisions were made.\n\n"
                                    "Next steps: ship the MVP — café ☕.\n", encoding="utf-8")

    # PDF with real text + bordered table
    import pymupdf
    html = ("<h1>Invoice #1042</h1><p>Thank you for your business. Payment due in 30 days.</p>"
            "<table border='1'><tr><th>Item</th><th>Qty</th><th>Price</th></tr>"
            "<tr><td>Putter head</td><td>2</td><td>$350.00</td></tr>"
            "<tr><td>Grip</td><td>4</td><td>$22.50</td></tr>"
            "<tr><td>Headcover</td><td>1</td><td>$45.00</td></tr></table>"
            "<p>Second paragraph with more words so layout analysis has something to chew on.</p>")
    story = pymupdf.Story(html, user_css="table{border-collapse:collapse}td,th{border:1px solid #000;padding:4px}")
    w = pymupdf.DocumentWriter(str(out / "sample.pdf"))
    rect = pymupdf.paper_rect("letter")
    for _ in range(2):  # two pages
        dev = w.begin_page(rect)
        story.place(rect + (72, 72, -72, -72))
        story.draw(dev)
        w.end_page()
        story = pymupdf.Story(html)
    w.close()

    # Scanned invoice (no text layer: a picture of a page, a little crooked and soft) -> OCR
    scan = make_scan()
    scan.save(out / "scan.png")
    buf = __import__("io").BytesIO()
    scan.convert("L").save(buf, "JPEG", quality=80)
    sdoc = pymupdf.open()
    sdoc.new_page(width=612, height=792).insert_image(pymupdf.Rect(0, 0, 612, 792), stream=buf.getvalue())
    sdoc.save(out / "scan.pdf")

    # ---------- spreadsheets
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Sales"
    ws.append(["Region", "Units", "Revenue", "Rep"])
    for row in [["West", 120, 4800.5, "José"], ["East", 95, 3900, "Ann"], ["South", 143, 5720.25, "Lee"]]:
        ws.append(row)
    ws2 = wb.create_sheet("Inventory")
    ws2.append(["SKU", "On hand"])
    ws2.append(["PX-1", 40])
    ws2.append(["PX-2", 12])
    wb.save(out / "sample.xlsx")
    (out / "sample.csv").write_text("name,age,city\nAna,34,Orange\nBo,28,Irvine\nChén,41,Tustin\n", encoding="utf-8")
    (out / "sample.tsv").write_text("name\tage\nAna\t34\nBo\t28\n", encoding="utf-8")
    (out / "sample.json").write_text(json.dumps([{"id": 1, "name": "Ana", "tags": {"vip": True}},
                                                 {"id": 2, "name": "Bo", "tags": {"vip": False}}]), encoding="utf-8")

    # ---------- presentations
    from pptx import Presentation
    prs = Presentation()
    s = prs.slides.add_slide(prs.slide_layouts[0])
    s.shapes.title.text = "FileMorph"
    s.placeholders[1].text = "Drop a file, pick a format."
    s = prs.slides.add_slide(prs.slide_layouts[1])
    s.shapes.title.text = "Agenda"
    s.placeholders[1].text = "Intro\nDemo\nQ&A"
    prs.save(out / "sample.pptx")

    lo = soffice_exe()
    if lo:
        for src, fmt in [("sample.docx", "doc"), ("sample.xlsx", "xls"), ("sample.xlsx", "ods"),
                         ("sample.pptx", "ppt"), ("sample.pptx", "odp")]:
            subprocess.run([lo, "--headless", "--convert-to", fmt, "--outdir", str(out), str(out / src)],
                           check=True, capture_output=True)

    # ---------- audio & video
    ff = ffmpeg_exe()
    tone = ["-f", "lavfi", "-i", "sine=frequency=440:duration=3"]
    for ext, codec in [("mp3", ["-c:a", "libmp3lame"]), ("wav", []), ("flac", []), ("ogg", ["-c:a", "libvorbis"]),
                       ("m4a", ["-c:a", "aac"]), ("opus", ["-c:a", "libopus"]), ("wma", ["-c:a", "wmav2"]),
                       ("aiff", [])]:
        subprocess.run([ff, "-y", "-loglevel", "error", *tone, *codec, str(out / f"sample.{ext}")], check=True)
    vid = ["-f", "lavfi", "-i", "testsrc=duration=3:size=320x240:rate=24", "-f", "lavfi", "-i",
           "sine=frequency=330:duration=3", "-shortest"]
    for ext, codec in [("mp4", ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac"]),
                       ("mov", ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac"]),
                       ("mkv", ["-c:v", "libx264", "-c:a", "aac"]),
                       ("webm", ["-c:v", "libvpx-vp9", "-deadline", "realtime", "-c:a", "libopus"]),
                       ("avi", ["-c:v", "mpeg4", "-c:a", "libmp3lame"]),
                       ("wmv", ["-c:v", "wmv2", "-c:a", "wmav2"])]:
        subprocess.run([ff, "-y", "-loglevel", "error", *vid, *codec, str(out / f"sample.{ext}")], check=True)


if __name__ == "__main__":
    make(Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "tests" / "samples"))
    print("ok")
