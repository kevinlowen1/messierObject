#!/usr/bin/env python3
"""Invert (dark->light) a PDF and extract selected pages.

This is intended for the included visual guide PDF:
  Visual_Guide_to_Messier-objects_HT-Vgy_2023_ENG.pdf

What it does:
- Renders each page to an image, inverts colors, and rebuilds a new PDF
  with the same page size.
- Extracts two specific pages (defaults to 12 and 13) into a folder, named:
    M1_photograph.pdf
    M1_eyepiece.pdf

Notes:
- This method is reliable for printing but will rasterize pages (text won’t be selectable).

Usage:
  python process_visual_guide.py
  python process_visual_guide.py --dpi 200
  python process_visual_guide.py --extract-dir ./visual-guide-pictures
"""

from __future__ import annotations

import argparse
import io
import re
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image, ImageOps
from pypdf import PdfReader, PdfWriter


DEFAULT_IN = "Visual_Guide_to_Messier-objects_HT-Vgy_2023_ENG.pdf"
DEFAULT_EXTRACT_PAGES = (12, 13)  # 1-based pages for M1 (fallback)


_M_HEADER_RE = re.compile(r"^M\s*(\d{1,3})\b")
_M_ANY_RE = re.compile(r"\bM\s*(\d{1,3})\b")
_M_DESCRIPTION_LINE_RE = re.compile(r"^M\s*\d{1,3}\s*:")


def invert_pdf(
    in_path: Path,
    out_path: Path,
    *,
    dpi: int,
    overwrite: bool,
) -> None:
    if out_path.exists() and not overwrite:
        raise SystemExit(f"Refusing to overwrite existing: {out_path} (use --overwrite)")

    src = fitz.open(str(in_path))
    dst = fitz.open()

    try:
        for i in range(src.page_count):
            page = src.load_page(i)
            rect = page.rect

            pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csRGB)
            img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
            inv = ImageOps.invert(img)

            buf = io.BytesIO()
            inv.save(buf, format="PNG", optimize=True)

            out_page = dst.new_page(width=rect.width, height=rect.height)
            out_page.insert_image(rect, stream=buf.getvalue())

        out_path.parent.mkdir(parents=True, exist_ok=True)
        dst.save(str(out_path))
    finally:
        dst.close()
        src.close()


def extract_pages(
    pdf_path: Path,
    out_dir: Path,
    *,
    page_numbers_1based: tuple[int, int],
    overwrite: bool,
) -> tuple[Path, Path]:
    p_photo, p_eye = page_numbers_1based
    if p_photo < 1 or p_eye < 1:
        raise SystemExit("Page numbers must be >= 1")

    out_dir.mkdir(parents=True, exist_ok=True)

    out_photo = out_dir / "M1_photograph.pdf"
    out_eye = out_dir / "M1_eyepiece.pdf"

    for out_path in (out_photo, out_eye):
        if out_path.exists() and not overwrite:
            raise SystemExit(f"Refusing to overwrite existing: {out_path} (use --overwrite)")

    reader = PdfReader(str(pdf_path))
    if max(p_photo, p_eye) > len(reader.pages):
        raise SystemExit(f"PDF only has {len(reader.pages)} pages; cannot extract {p_photo}, {p_eye}")

    w1 = PdfWriter()
    w1.add_page(reader.pages[p_photo - 1])
    with open(out_photo, "wb") as f:
        w1.write(f)

    w2 = PdfWriter()
    w2.add_page(reader.pages[p_eye - 1])
    with open(out_eye, "wb") as f:
        w2.write(f)

    return out_photo, out_eye


def _find_messier_photo_pages(original_pdf_path: Path) -> dict[int, int]:
    """Return mapping M-number -> 1-based page index for the object's first page.

    Heuristic: the first page for an object starts with "M<nr> ...".
    This avoids index/list pages that contain many Mxx entries.
    """

    reader = PdfReader(str(original_pdf_path))
    found: dict[int, int] = {}

    for page_num, page in enumerate(reader.pages, start=1):
        text = (page.extract_text() or "").lstrip()
        if not text:
            continue

        # Only consider pages that begin with an M-header.
        if not text.startswith("M"):
            continue

        first_line = text.splitlines()[0].strip()

        # Skip description pages like: "M 59: An elongated elliptical galaxy ..."
        if _M_DESCRIPTION_LINE_RE.match(first_line):
            continue

        # Support grouped pages like: "M32, M31, M110 Galaxies in Andromeda"
        for num_s in _M_ANY_RE.findall(first_line):
            n = int(num_s)
            if not (1 <= n <= 110):
                continue
            found.setdefault(n, page_num)

    return found


def extract_all_messier_pages(
    *,
    inverted_pdf_path: Path,
    out_dir: Path,
    original_pdf_path: Path,
    overwrite: bool,
) -> None:
    photo_pages = _find_messier_photo_pages(original_pdf_path)
    missing = [n for n in range(1, 111) if n not in photo_pages]
    if missing:
        raise SystemExit(
            "Could not locate start page for some Messier objects: "
            + ", ".join(str(n) for n in missing[:20])
            + ("..." if len(missing) > 20 else "")
        )

    reader = PdfReader(str(inverted_pdf_path))
    total_pages = len(reader.pages)
    out_dir.mkdir(parents=True, exist_ok=True)

    for n in range(1, 111):
        photo_page = photo_pages[n]
        eye_page = photo_page + 1
        if eye_page > total_pages:
            raise SystemExit(f"M{n} eyepiece page would be out of range: {eye_page} > {total_pages}")

        out_photo = out_dir / f"M{n}_photograph.pdf"
        out_eye = out_dir / f"M{n}_eyepiece.pdf"

        for out_path in (out_photo, out_eye):
            if out_path.exists() and not overwrite:
                raise SystemExit(f"Refusing to overwrite existing: {out_path} (use --overwrite)")

        w1 = PdfWriter()
        w1.add_page(reader.pages[photo_page - 1])
        with open(out_photo, "wb") as f:
            w1.write(f)

        w2 = PdfWriter()
        w2.add_page(reader.pages[eye_page - 1])
        with open(out_eye, "wb") as f:
            w2.write(f)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="in_path", default=DEFAULT_IN, help="Input PDF path")
    ap.add_argument(
        "--out",
        dest="out_path",
        default=None,
        help="Output inverted PDF path (default: <input>-inverted.pdf)",
    )
    ap.add_argument(
        "--invert",
        action=getattr(argparse, "BooleanOptionalAction"),
        default=True,
        help="Generate the inverted PDF (default: true)",
    )
    ap.add_argument("--dpi", type=int, default=150, help="Render DPI for inversion")
    ap.add_argument("--overwrite", action="store_true", help="Overwrite outputs if they exist")
    ap.add_argument("--extract-dir", default="visual-guide-picture-pages", help="Folder for extracted PDFs")
    ap.add_argument(
        "--extract-all",
        action=getattr(argparse, "BooleanOptionalAction"),
        default=True,
        help="Extract M1..M110 photograph+eyepiece pages (default: true)",
    )
    ap.add_argument(
        "--photo-page",
        type=int,
        default=DEFAULT_EXTRACT_PAGES[0],
        help="(Fallback) 1-based page for photograph when not using --extract-all",
    )
    ap.add_argument(
        "--eyepiece-page",
        type=int,
        default=DEFAULT_EXTRACT_PAGES[1],
        help="(Fallback) 1-based page for eyepiece when not using --extract-all",
    )

    args = ap.parse_args(argv)

    in_path = Path(args.in_path).expanduser().resolve()
    if not in_path.exists():
        raise SystemExit(f"Input PDF not found: {in_path}")

    out_path = (
        Path(args.out_path).expanduser().resolve()
        if args.out_path
        else in_path.with_name(in_path.stem + "-inverted.pdf")
    )

    # Invert if requested.
    if args.invert:
        if out_path.exists() and not args.overwrite:
            print(f"Using existing inverted PDF: {out_path}")
        else:
            invert_pdf(in_path, out_path, dpi=args.dpi, overwrite=True)
            print(f"Wrote inverted: {out_path}")
    else:
        if not out_path.exists():
            raise SystemExit(f"Inverted PDF not found (run without --no-invert): {out_path}")
        print(f"Using existing inverted PDF: {out_path}")

    extract_dir = Path(args.extract_dir).expanduser().resolve()
    if args.extract_all:
        extract_all_messier_pages(
            inverted_pdf_path=out_path,
            out_dir=extract_dir,
            original_pdf_path=in_path,
            overwrite=args.overwrite,
        )
        print(f"Extracted all Messier pages to: {extract_dir}")
    else:
        out_photo, out_eye = extract_pages(
            out_path,
            extract_dir,
            page_numbers_1based=(args.photo_page, args.eyepiece_page),
            overwrite=args.overwrite,
        )
        print(f"Extracted: {out_photo}")
        print(f"Extracted: {out_eye}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
