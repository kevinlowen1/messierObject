#!/usr/bin/env python3
"""Combine Messier finder-chart PDFs into a single print-friendly PDF.

Assumes the individual files are named M001.pdf .. M110.pdf.

Usage:
  python combine_messier_findercharts.py
  python combine_messier_findercharts.py --src ./messier-finder-charts-pdfs --out ./messier-finder-charts.pdf
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
from pathlib import Path

from pypdf import PdfReader, PdfWriter


SOURCE_DEFAULT_URL = "https://sherwood-observatory.org.uk/astronomy/finder-charts/messier-finder-charts/"


_MESSIER_RE = re.compile(r"^M(\d{3})\.pdf$", re.IGNORECASE)


def _sorted_messier_pdfs(src_dir: Path) -> list[Path]:
    pdfs: list[tuple[int, Path]] = []
    for p in src_dir.iterdir():
        if not p.is_file():
            continue
        m = _MESSIER_RE.match(p.name)
        if not m:
            continue
        pdfs.append((int(m.group(1)), p))

    pdfs.sort(key=lambda t: t[0])
    return [p for _, p in pdfs]


def _append_pdf(writer: PdfWriter, pdf_path: Path) -> None:
    reader = PdfReader(str(pdf_path))
    for page in reader.pages:
        writer.add_page(page)


def _first_page_size_points(pdf_path: Path) -> tuple[float, float]:
    reader = PdfReader(str(pdf_path))
    if not reader.pages:
        raise SystemExit(f"PDF has no pages: {pdf_path}")
    box = reader.pages[0].mediabox
    return (float(box.width), float(box.height))


def _create_cover_pdf(
    cover_path: Path,
    *,
    page_size_points: tuple[float, float],
    title: str,
    subtitle: str,
    note: str,
    source_url: str,
    binding_margin_in: float,
) -> None:
    try:
        from reportlab.lib.units import inch
        from reportlab.pdfgen import canvas
    except Exception as e:  # noqa: BLE001
        raise SystemExit(
            "Missing dependency 'reportlab'. Install with: pip install reportlab"
        ) from e

    page_w, page_h = page_size_points

    base_margin = 0.75 * inch
    left_margin = base_margin + max(0.0, binding_margin_in) * inch
    right_margin = base_margin
    top_margin = base_margin
    bottom_margin = base_margin

    safe_left = left_margin
    safe_right = page_w - right_margin
    safe_width = max(0.0, safe_right - safe_left)
    center_x = safe_left + safe_width / 2.0

    cover_path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(cover_path), pagesize=(page_w, page_h))

    y = page_h - top_margin - (1.25 * inch)
    c.setFont("Helvetica-Bold", 34)
    c.drawCentredString(center_x, y, title)

    y -= 0.6 * inch
    c.setFont("Helvetica", 18)
    c.drawCentredString(center_x, y, subtitle)

    y -= 0.4 * inch
    c.setFont("Helvetica", 12)
    today = dt.date.today().isoformat()
    c.drawCentredString(center_x, y, f"Generated {today}")

    # Source (small, on the front cover as requested).
    if source_url:
        y -= 0.5 * inch
        c.setFont("Helvetica", 10)
        c.drawCentredString(center_x, y, f"Source: {source_url}")

    if note:
        c.setFont("Helvetica", 10)
        c.drawString(safe_left, bottom_margin, note)

    c.showPage()
    c.save()


def combine_with_cover(
    src_dir: Path,
    out_path: Path,
    *,
    include_cover: bool,
    cover_path: Path,
    cover_title: str,
    cover_subtitle: str,
    cover_note: str,
    cover_source_url: str,
    binding_margin_in: float,
    pad_to_even_pages: bool,
) -> None:
    pdf_paths = _sorted_messier_pdfs(src_dir)
    if not pdf_paths:
        raise SystemExit(f"No Messier PDFs found in: {src_dir}")

    expected = {f"M{n:03d}.pdf" for n in range(1, 111)}
    found = {p.name for p in pdf_paths}
    missing = sorted(expected - found)
    if missing:
        raise SystemExit(
            "Missing expected PDFs (won't create incomplete combined PDF): "
            + ", ".join(missing[:15])
            + ("..." if len(missing) > 15 else "")
        )

    writer = PdfWriter()

    if include_cover:
        page_size = _first_page_size_points(pdf_paths[0])
        _create_cover_pdf(
            cover_path,
            page_size_points=page_size,
            title=cover_title,
            subtitle=cover_subtitle,
            note=cover_note,
            source_url=cover_source_url,
            binding_margin_in=binding_margin_in,
        )
        _append_pdf(writer, cover_path)

    for p in pdf_paths:
        _append_pdf(writer, p)

    if pad_to_even_pages and (len(writer.pages) % 2 == 1):
        w, h = _first_page_size_points(pdf_paths[0])
        writer.add_blank_page(width=w, height=h)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "wb") as f:
        writer.write(f)


def combine(src_dir: Path, out_path: Path) -> None:
    # Backwards-compatible entry point (no cover).
    combine_with_cover(
        src_dir,
        out_path,
        include_cover=False,
        cover_path=out_path.with_name(out_path.stem + "-cover.pdf"),
        cover_title="Messier Objects Finder Charts",
        cover_subtitle="M001–M110",
        cover_note="",
        cover_source_url="",
        binding_margin_in=0.0,
        pad_to_even_pages=False,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="messier-finder-charts-pdfs", help="Folder containing M001..M110 PDFs")
    ap.add_argument("--out", default="messier-finder-charts.pdf", help="Output combined PDF path")
    ap.add_argument("--no-cover", action="store_true", help="Do not generate/prepend a cover page")
    ap.add_argument(
        "--cover-pdf",
        default=None,
        help="Path to write the generated cover PDF (default: alongside --out)",
    )
    ap.add_argument("--cover-title", default="Messier Objects Finder Charts", help="Cover page title")
    ap.add_argument("--cover-subtitle", default="M001–M110", help="Cover page subtitle")
    ap.add_argument(
        "--cover-note",
        default="",
        help="Small note printed at the bottom-left of the cover",
    )
    ap.add_argument(
        "--cover-source-url",
        default=SOURCE_DEFAULT_URL,
        help="Website URL printed on the cover as the source",
    )
    ap.add_argument(
        "--binding-margin",
        type=float,
        default=0.75,
        help="Extra left margin (inches) reserved for spiral binding holes",
    )
    ap.add_argument(
        "--no-pad-even",
        action="store_true",
        help="Do not add a final blank page if total page count is odd",
    )
    args = ap.parse_args(argv)

    src_dir = Path(args.src).expanduser().resolve()
    out_path = Path(args.out).expanduser().resolve()

    cover_path = (
        Path(args.cover_pdf).expanduser().resolve()
        if args.cover_pdf
        else out_path.with_name(out_path.stem + "-cover.pdf")
    )

    combine_with_cover(
        src_dir,
        out_path,
        include_cover=not args.no_cover,
        cover_path=cover_path,
        cover_title=args.cover_title,
        cover_subtitle=args.cover_subtitle,
        cover_note=args.cover_note,
        cover_source_url=args.cover_source_url,
        binding_margin_in=args.binding_margin,
        pad_to_even_pages=not args.no_pad_even,
    )

    if not args.no_cover:
        print(f"Wrote cover: {cover_path}")
    print(f"Wrote combined: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
