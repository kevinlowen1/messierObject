#!/usr/bin/env python3
"""Replace a single Messier PDF with a specified URL and normalize it for printing.

Default behavior:
- Downloads the PDF at --url
- Normalizes rotation (transfers /Rotate into content)
- Auto-rotates landscape pages to portrait
- Places content on a target page size (default: A4) and centers it

Example:
  python replace_messier_pdf.py --m 106 \
    --url https://freestarcharts.com/images/Articles/Messier/Single/M106_Finder_Chart.pdf

Then rebuild the combined PDF:
  python combine_messier_findercharts.py
"""

from __future__ import annotations

import argparse
import io
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from pypdf import PdfReader, PdfWriter, Transformation


A4_POINTS = (595.2756, 841.8898)  # 210mm x 297mm at 72 dpi
LETTER_POINTS = (612.0, 792.0)  # 8.5in x 11in


@dataclass(frozen=True)
class PageSize:
    width: float
    height: float


def _download_pdf_bytes(url: str, timeout_s: float = 60.0) -> bytes:
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "messierObjects-replacer/1.0"},
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        return resp.read()


def _normalize_page_rotation(page) -> None:
    # pypdf supports this helper on PageObject; it sets /Rotate to 0
    # and bakes rotation into the content stream.
    transfer = getattr(page, "transfer_rotation_to_content", None)
    if callable(transfer):
        transfer()


def _page_size_points(page) -> tuple[float, float]:
    box = page.mediabox
    return (float(box.width), float(box.height))


def _make_target_page_size(target: str) -> PageSize:
    t = target.lower()
    if t == "a4":
        w, h = A4_POINTS
        return PageSize(w, h)
    if t in {"letter", "us-letter", "us_letter"}:
        w, h = LETTER_POINTS
        return PageSize(w, h)
    raise SystemExit("--target must be one of: a4, letter")


def replace_messier_pdf(
    *,
    messier_number: int,
    url: str,
    dest_dir: Path,
    target: str,
    margin_in: float,
    timeout_s: float,
) -> Path:
    if not (1 <= messier_number <= 110):
        raise SystemExit("--m must be between 1 and 110")

    dest_dir = dest_dir.expanduser().resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)

    out_path = dest_dir / f"M{messier_number:03d}.pdf"
    tmp_path = out_path.with_suffix(out_path.suffix + ".part")

    data = _download_pdf_bytes(url, timeout_s=timeout_s)
    reader = PdfReader(io.BytesIO(data))
    if not reader.pages:
        raise SystemExit("Downloaded PDF has no pages")

    target_size = _make_target_page_size(target)
    margin = max(0.0, margin_in) * 72.0
    available_w = max(1.0, target_size.width - 2 * margin)
    available_h = max(1.0, target_size.height - 2 * margin)

    writer = PdfWriter()

    for src_page in reader.pages:
        _normalize_page_rotation(src_page)

        w, h = _page_size_points(src_page)
        if w > h:
            src_page.rotate(90)
            _normalize_page_rotation(src_page)
            w, h = _page_size_points(src_page)

        scale = min(available_w / w, available_h / h)
        new_w = w * scale
        new_h = h * scale

        tx = (target_size.width - new_w) / 2.0
        ty = (target_size.height - new_h) / 2.0

        dst_page = writer.add_blank_page(width=target_size.width, height=target_size.height)
        transform = Transformation().scale(scale, scale).translate(tx, ty)
        dst_page.merge_transformed_page(src_page, transform)

    with open(tmp_path, "wb") as f:
        writer.write(f)

    tmp_path.replace(out_path)
    return out_path


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--m", type=int, required=True, help="Messier number to replace (1-110)")
    ap.add_argument("--url", required=True, help="Replacement PDF URL")
    ap.add_argument("--dest", default="messier-finder-charts-pdfs", help="Destination folder")
    ap.add_argument("--target", default="a4", help="Target page size: a4 or letter")
    ap.add_argument("--margin", type=float, default=0.25, help="Margin in inches")
    ap.add_argument("--timeout", type=float, default=60.0, help="Download timeout seconds")
    args = ap.parse_args(argv)

    out = replace_messier_pdf(
        messier_number=args.m,
        url=args.url,
        dest_dir=Path(args.dest),
        target=args.target,
        margin_in=args.margin,
        timeout_s=args.timeout,
    )
    print(f"Wrote: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
