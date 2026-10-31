"""The letter as a printable sheet for the head of department to read, sign and seal: the college's name, a blank
line for the authority and the date, the letter exactly as plan.json holds it, a signature and seal block and the
enclosures, plus the letter's sha256 so the signed paper can be matched to the page. Writes
OUT_DIR/letter-for-signing.html and, with headless Chrome, OUT_DIR/letter-for-signing.pdf (A4).
Run: python3 letter_pdf.py OUT_DIR SITE.json [--college "NAME"] [--signer "ROLE"]
"""
import argparse
import html
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pack
from video.split import CHROME_TIMEOUT_S, CHROMES

COLLEGE = "Lakshmi Narain College of Technology Excellence, Bhopal"
SIGNER = "Head of Department, Computer Science and Engineering (Data Science)"
STYLE = """@page { size: A4; margin: 18mm 20mm; }
body { font-family: "Times New Roman", Georgia, serif; font-size: 11.5pt; line-height: 1.45; color: #000;
       background: #fff; max-width: 170mm; margin: 0 auto; }
.head { text-align: center; border-bottom: 1px solid #000; padding-bottom: 6px; margin-bottom: 14px; }
.head b { font-size: 14pt; }
.meta p { margin: 2px 0; }
.letter { white-space: pre-wrap; margin: 14px 0; }
.sign { margin-top: 26px; display: grid; grid-template-columns: 1fr 1fr; gap: 24px; }
.sign div { border-top: 1px solid #000; padding-top: 4px; }
.small { font-size: 9pt; color: #333; margin-top: 18px; }"""


def sheet(plan, site, college=COLLEGE, signer=SIGNER):
    """The printable letter page as HTML. Nothing is added to the letter's own text."""
    filed = site.get("submitted") or {}
    to = html.escape(filed.get("to") or "The road authority: ______________________________________")
    opening = [line.strip().lower() for line in plan["letter"].strip().splitlines()[:6]]
    to_block = "" if any(line.startswith("to") for line in opening) else f"<p>To,</p><p>{to}</p>"
    subject = ("" if "subject" in plan["letter"][:500].lower() else
               f'<p><b>Subject:</b> Request for safety measures at the road crossing outside our main gate: '
               f'{html.escape(plan["fix"])}</p>')
    enclosures = ("Evidence page: measurements, blurred clips and method (printed copy)",
                  "Statement of support signed by teachers of the college (annexure)")
    return f"""<!doctype html><meta charset="utf-8"><title>Letter for signing</title><style>{STYLE}</style>
<div class="head"><b>{html.escape(college)}</b></div>
<div class="meta">{to_block}<p>Date: ____________________</p>{subject}</div>
<div class="letter">{html.escape(plan["letter"].strip())}</div>
<div class="sign"><div>Signature and seal<br>{html.escape(signer)}<br>for {html.escape(college)}</div>
<div>Name: ____________________<br>Date: ____________________</div></div>
<p><b>Enclosures:</b></p><ol>{"".join(f"<li>{html.escape(e)}</li>" for e in enclosures)}</ol>
<p class="small">Letter sha256 {pack.signed_sha(plan)}: the evidence page shows the same value for this exact text.</p>"""


def to_pdf(page, pdf):
    """Print `page` to `pdf` with headless Chrome in a throwaway profile."""
    chrome = os.environ.get("CHROME") or next((c for c in map(shutil.which, CHROMES) if c), None)
    if not chrome:
        raise SystemExit("no Chrome or Chromium found: set CHROME=/path/to/chrome, or print the .html from a browser")
    with tempfile.TemporaryDirectory() as profile:
        subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-first-run", "--no-pdf-header-footer",
                        f"--user-data-dir={profile}", f"--print-to-pdf={pdf.resolve()}", page.resolve().as_uri()],
                       check=True, capture_output=True, timeout=CHROME_TIMEOUT_S)
    if not pdf.exists():
        raise SystemExit(f"Chrome wrote no {pdf}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("out_dir", type=Path)
    parser.add_argument("site", type=Path)
    parser.add_argument("--college", default=COLLEGE)
    parser.add_argument("--signer", default=SIGNER)
    args = parser.parse_args()
    plan = pack.read_json(args.out_dir / "plan.json")
    if not plan or not (plan.get("letter") or "").strip():
        sys.exit(f"letter_pdf.py: no letter in {args.out_dir / 'plan.json'}; run pack.py first")
    page = args.out_dir / "letter-for-signing.html"
    page.write_text(sheet(plan, json.loads(args.site.read_text()), args.college, args.signer))
    pdf = page.with_suffix(".pdf")
    to_pdf(page, pdf)
    print(f"wrote {pdf}: print it, the HOD reads, signs and seals it")


if __name__ == "__main__":
    main()
