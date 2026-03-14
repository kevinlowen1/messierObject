#!/usr/bin/env python3
"""Build a duplex-friendly Messier observing book PDF.

Creates a single PDF with:
- 1 cover page
- 12 monthly constellation sky charts
- Messier objects laid out two-per-page (keeps total pages <= 120)

Per Messier object layout (one object = one row):
- Left column: Photograph (top) + Eyepiece sketch (bottom)
- Right column: Finder chart

This script expects these inputs to already exist:
- Monthly sky charts: sky-charts-pdfs/<year>/sky-chart-YYYY-MM.pdf
- Finder charts: messier-finder-charts-pdfs/M001.pdf .. M110.pdf
- Visual guide extracted pages:
    visual-guide-picture-pages/M1_photograph.pdf .. M110_photograph.pdf
    visual-guide-picture-pages/M1_eyepiece.pdf .. M110_eyepiece.pdf

Output defaults to: messier-observing-book.pdf

Notes:
- Uses PyMuPDF (fitz) to place PDF pages as vector content (no rasterization).
- Ensures final page count is even (adds a blank page if needed) for duplex.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.request import urlopen

import fitz  # PyMuPDF
from pypdf import PdfReader

import re


LETTER = (612.0, 792.0)  # 8.5 x 11 in @ 72 dpi
A4 = (595.2756, 841.8898)


@dataclass(frozen=True)
class Paper:
    width: float
    height: float


@dataclass(frozen=True)
class MessierMeta:
    number: int
    name: str
    constellation: str
    ra_hours: Optional[float]


_TITLE_RE = re.compile(r"^Messier\s+(\d{1,3})(?:\s*[-]\s*(.+?))?\s*$", re.IGNORECASE)
_CONST_RE = re.compile(r"^Constellation:\s*(.+?)\s*$", re.IGNORECASE)
_TYPE_RE = re.compile(r"^Type\s+of\s+object:\s*(.+?)\s*$", re.IGNORECASE)
_RA_RE = re.compile(r"^Right\s+ascension:\s*(\d{1,2})h\s*(\d{1,2})m", re.IGNORECASE)
_RA_ALT_RE = re.compile(r"\bRA:\s*(\d{1,2})h\s*(\d{1,2})m", re.IGNORECASE)


_SEDS_MONTH_URLS: dict[int, str] = {
    1: "http://www.messier.seds.org/xtra/12months/m-jan.txt",
    2: "http://www.messier.seds.org/xtra/12months/m-feb.txt",
    3: "http://www.messier.seds.org/xtra/12months/m-mar.txt",
    4: "http://www.messier.seds.org/xtra/12months/m-apr.txt",
    5: "http://www.messier.seds.org/xtra/12months/m-may.txt",
    6: "http://www.messier.seds.org/xtra/12months/m-jun.txt",
    7: "http://www.messier.seds.org/xtra/12months/m-jul.txt",
    8: "http://www.messier.seds.org/xtra/12months/m-aug.txt",
    9: "http://www.messier.seds.org/xtra/12months/m-sep.txt",
    10: "http://www.messier.seds.org/xtra/12months/m-oct.txt",
    11: "http://www.messier.seds.org/xtra/12months/m-nov.txt",
    12: "http://www.messier.seds.org/xtra/12months/m-dec.txt",
}

_SEDS_OBJ_LINE_RE = re.compile(r"^\s*(M\s*\d{1,3}(?:\s*,\s*M\s*\d{1,3})*)\b", re.IGNORECASE)
_SEDS_STOP_RE = re.compile(r"^\s*(Last\s+Month|Next\s+Month)\b", re.IGNORECASE)
_SEDS_CONST_RE_1 = re.compile(
    r"\bin\s+the\s+constellation\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*)\b"
)
_SEDS_CONST_RE_2 = re.compile(r"\bin\s+([A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*)\b")


_MONTH_TARGET_RA_22H = {
    1: 7.0,
    2: 9.0,
    3: 11.0,
    4: 13.0,
    5: 15.0,
    6: 17.0,
    7: 19.0,
    8: 21.0,
    9: 23.0,
    10: 1.0,
    11: 3.0,
    12: 5.0,
}

_MONTH_ABBR = {
    1: "Jan",
    2: "Feb",
    3: "Mar",
    4: "Apr",
    5: "May",
    6: "Jun",
    7: "Jul",
    8: "Aug",
    9: "Sep",
    10: "Oct",
    11: "Nov",
    12: "Dec",
}


def _circular_hour_distance(a: float, b: float) -> float:
    d = (a - b) % 24.0
    if d > 12.0:
        d = 24.0 - d
    return abs(d)


def _best_month_from_ra(ra_hours: float) -> int:
    best_m = 1
    best_d = 1e9
    for m, target in _MONTH_TARGET_RA_22H.items():
        d = _circular_hour_distance(ra_hours, target)
        if d < best_d:
            best_d = d
            best_m = m
    return best_m


def _season_from_month(m: int) -> str:
    if m in (12, 1, 2):
        return "Winter"
    if m in (3, 4, 5):
        return "Spring"
    if m in (6, 7, 8):
        return "Summer"
    return "Fall"


def _abbr_constellation(name: str) -> str:
    parts = [p for p in re.split(r"\s+", name.strip()) if p]
    if not parts:
        return ""
    if len(parts) == 1:
        s = parts[0]
        return (s[:3].title() if len(s) >= 3 else s.title())
    # Multi-word: take initials (e.g. Ursa Major -> UMa)
    return "".join(p[0].upper() for p in parts)


def _parse_finder_metadata(pdf_path: Path) -> MessierMeta:
    reader = PdfReader(str(pdf_path))
    if not reader.pages:
        raise SystemExit(f"Finder chart PDF has no pages: {pdf_path}")
    text = reader.pages[0].extract_text() or ""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    number: Optional[int] = None
    name: Optional[str] = None
    constellation: Optional[str] = None
    obj_type: Optional[str] = None
    ra_h: Optional[int] = None
    ra_m: Optional[int] = None

    for ln in lines[:200]:
        if number is None:
            m = _TITLE_RE.match(ln)
            if m:
                number = int(m.group(1))
                if m.group(2):
                    name = m.group(2).strip()
                continue

        if constellation is None:
            m = _CONST_RE.match(ln)
            if m:
                constellation = m.group(1).strip()
                continue

        if obj_type is None:
            m = _TYPE_RE.match(ln)
            if m:
                obj_type = m.group(1).strip()
                continue

        if ra_h is None:
            m = _RA_RE.match(ln)
            if not m:
                m = _RA_ALT_RE.search(ln)
            if m:
                ra_h = int(m.group(1))
                ra_m = int(m.group(2))
                continue

    if number is None:
        raise SystemExit(f"Could not parse Messier number from: {pdf_path}")
    if constellation is None:
        constellation = ""

    if not name:
        # Some charts omit a common name in the title (e.g. Messier 40).
        name = obj_type or "(no common name)"

    ra_hours: Optional[float]
    if ra_h is None or ra_m is None:
        ra_hours = None
    else:
        ra_hours = float(ra_h) + (float(ra_m) / 60.0)
    return MessierMeta(number=number, name=name, constellation=constellation, ra_hours=ra_hours)


def _fetch_text(url: str, *, timeout_s: float = 20.0) -> str:
    with urlopen(url, timeout=timeout_s) as resp:
        data = resp.read()
    return data.decode("utf-8", errors="replace")


def _parse_seds_month_text(text: str) -> tuple[set[int], dict[int, str]]:
    """Parse a SEDS monthly tour text.

    Returns:
      - set of Messier numbers featured in that month (main body only)
      - best-effort constellation mapping for single-object entries
    """

    lines = [ln.rstrip("\n") for ln in text.splitlines()]
    month_objects: set[int] = set()
    constellations: dict[int, str] = {}

    i = 0
    while i < len(lines):
        ln = lines[i]
        if _SEDS_STOP_RE.match(ln):
            break

        m = _SEDS_OBJ_LINE_RE.match(ln)
        if not m:
            i += 1
            continue

        nums = [int(x) for x in re.findall(r"\d{1,3}", m.group(1))]
        for n in nums:
            if 1 <= n <= 110:
                month_objects.add(n)

        # Best-effort constellation extraction for single-object entries.
        if len(nums) == 1:
            block_lines = [ln]
            # Capture a couple following lines (handles cases like 'M103' then '- This is...').
            j = i + 1
            while j < len(lines) and len(block_lines) < 4:
                ln2 = lines[j]
                if _SEDS_STOP_RE.match(ln2) or _SEDS_OBJ_LINE_RE.match(ln2):
                    break
                if ln2.strip():
                    block_lines.append(ln2)
                j += 1

            block = " ".join(s.strip() for s in block_lines if s.strip())
            m1 = _SEDS_CONST_RE_1.search(block)
            if m1:
                constellations[nums[0]] = m1.group(1).strip()
            else:
                m2 = _SEDS_CONST_RE_2.search(block)
                if m2:
                    constellations[nums[0]] = m2.group(1).strip()

        i += 1

    return month_objects, constellations


def _load_seds_best_month_map(*, cache_path: Path, refresh: bool) -> tuple[dict[int, int], dict[int, str]]:
    """Load (and optionally refresh) best-month mapping from SEDS 12-month tour."""

    if cache_path.exists() and not refresh:
        try:
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            best_month_raw = data.get("best_month", {})
            const_raw = data.get("constellation", {})
            best_month = {int(k): int(v) for k, v in best_month_raw.items()}
            constellations = {int(k): str(v) for k, v in const_raw.items()}
            return best_month, constellations
        except Exception:
            # Fall through to refresh.
            pass

    best_month: dict[int, int] = {}
    constellations: dict[int, str] = {}

    for month, url in _SEDS_MONTH_URLS.items():
        text = _fetch_text(url)
        objs, consts = _parse_seds_month_text(text)

        for n in objs:
            best_month.setdefault(n, month)
        for n, c in consts.items():
            if c and n not in constellations:
                constellations[n] = c

    cache_path.write_text(
        json.dumps(
            {
                "source": "http://www.messier.seds.org/xtra/12months/12months.html",
                "best_month": {str(k): v for k, v in sorted(best_month.items())},
                "constellation": {str(k): v for k, v in sorted(constellations.items())},
                "generated": dt.datetime.now(dt.timezone.utc).isoformat(),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    return best_month, constellations


def _load_all_messier_meta(finder_dir: Path) -> list[MessierMeta]:
    metas: list[MessierMeta] = []
    for n in range(1, 111):
        p = finder_dir / f"M{n:03d}.pdf"
        if not p.exists():
            raise SystemExit(f"Missing finder chart: {p}")
        metas.append(_parse_finder_metadata(p))
    # Ensure stable order by number.
    metas.sort(key=lambda m: m.number)
    return metas


def _paper(name: str) -> Paper:
    n = name.strip().lower()
    if n in {"letter", "us-letter", "us_letter"}:
        return Paper(*LETTER)
    if n == "a4":
        return Paper(*A4)
    raise SystemExit("--paper must be one of: letter, a4")


def _fit_rect(src_rect: fitz.Rect, dst_rect: fitz.Rect) -> fitz.Rect:
    """Return a rectangle inside dst_rect preserving src aspect ratio."""
    sw = max(1e-6, float(src_rect.width))
    sh = max(1e-6, float(src_rect.height))
    dw = max(1e-6, float(dst_rect.width))
    dh = max(1e-6, float(dst_rect.height))

    s_aspect = sw / sh
    d_aspect = dw / dh

    if s_aspect >= d_aspect:
        # Fit to width
        w = dw
        h = dw / s_aspect
    else:
        # Fit to height
        h = dh
        w = dh * s_aspect

    x0 = float(dst_rect.x0) + (dw - w) / 2.0
    y0 = float(dst_rect.y0) + (dh - h) / 2.0
    return fitz.Rect(x0, y0, x0 + w, y0 + h)


def _fit_rect_rotated(src_rect: fitz.Rect, dst_rect: fitz.Rect, *, rotate: int) -> fitz.Rect:
    r = rotate % 360
    if r in (90, 270):
        # Swap width/height for aspect purposes.
        sw = float(src_rect.height)
        sh = float(src_rect.width)
        return _fit_rect(fitz.Rect(0, 0, sw, sh), dst_rect)
    return _fit_rect(src_rect, dst_rect)


def _content_clip_rect(src_page: fitz.Page, *, padding: float = 6.0) -> fitz.Rect:
    """Best-effort content bounding box to reduce whitespace.

    Unions text/image block rectangles from get_text("dict"). If detection fails,
    returns full page rect.
    """

    page_rect = src_page.rect
    try:
        d = src_page.get_text("dict")
        blocks = d.get("blocks", []) if isinstance(d, dict) else []
        rect: Optional[fitz.Rect] = None
        for b in blocks:
            bbox = b.get("bbox") if isinstance(b, dict) else None
            if not bbox or len(bbox) != 4:
                continue
            r = fitz.Rect(bbox)
            if r.is_empty or r.width < 2 or r.height < 2:
                continue
            rect = r if rect is None else rect | r

        if rect is None:
            return page_rect

        # Expand slightly, then clamp to page.
        rect = fitz.Rect(
            rect.x0 - padding,
            rect.y0 - padding,
            rect.x1 + padding,
            rect.y1 + padding,
        )
        rect = rect & page_rect
        if rect.is_empty or rect.width < 10 or rect.height < 10:
            return page_rect
        return rect
    except Exception:
        return page_rect


def _show_pdf_page(
    dst_page: fitz.Page,
    dst_rect: fitz.Rect,
    src_doc: fitz.Document,
    *,
    clip: Optional[fitz.Rect] = None,
    rotate: int = 0,
) -> None:
    src_page = src_doc.load_page(0)
    src_rect = clip if clip is not None else src_page.rect
    placed = _fit_rect_rotated(src_rect, dst_rect, rotate=rotate)
    dst_page.show_pdf_page(placed, src_doc, 0, clip=clip, rotate=rotate)


def _cover_page(
    doc: fitz.Document,
    paper: Paper,
    *,
    title: str,
    subtitle: str,
    finder_dir: Path,
    binding_margin_in: float,
    seds_cache_path: Path,
    refresh_seds: bool,
) -> None:
    page = doc.new_page(width=paper.width, height=paper.height)

    binding = max(0.0, binding_margin_in) * 72.0
    margin = 18
    left = margin + binding
    rect = fitz.Rect(left, margin, paper.width - margin, paper.height - margin)

    # Title area
    title_h = 110
    title_rect = fitz.Rect(rect.x0, rect.y0, rect.x1, rect.y0 + title_h)
    today = dt.date.today().isoformat()

    cover_title = "Messier Observing Book"

    def centered_x(text: str, *, fontsize: float) -> float:
        w = fitz.get_text_length(text, fontname="helv", fontsize=fontsize)
        return rect.x0 + max(0.0, (rect.width - w) / 2.0)

    y = title_rect.y0 + 30
    fs_title = 24
    fs_sub = 10
    fs_date = 9

    page.insert_text(fitz.Point(centered_x(cover_title, fontsize=fs_title), y), cover_title, fontsize=fs_title, fontname="helv")
    y += 28

    sub = subtitle.strip()
    if sub:
        page.insert_text(fitz.Point(centered_x(sub, fontsize=fs_sub), y), sub, fontsize=fs_sub, fontname="helv")
        y += 16

    date_line = f"Generated {today}"
    page.insert_text(fitz.Point(centered_x(date_line, fontsize=fs_date), y), date_line, fontsize=fs_date, fontname="helv")

    # Table area
    table_rect = fitz.Rect(rect.x0, title_rect.y1 + 8, rect.x1, rect.y1 - 10)

    metas = _load_all_messier_meta(finder_dir)
    seds_best_month, seds_constellations = _load_seds_best_month_map(cache_path=seds_cache_path, refresh=refresh_seds)
    by_season: dict[str, list[tuple[int, MessierMeta]]] = {"Winter": [], "Spring": [], "Summer": [], "Fall": []}
    for meta in metas:
        best_m = seds_best_month.get(meta.number)
        if best_m is None:
            if meta.ra_hours is not None:
                best_m = _best_month_from_ra(meta.ra_hours)
            else:
                best_m = 1
        season = _season_from_month(best_m)
        by_season[season].append((best_m, meta))

    for season in by_season:
        by_season[season].sort(key=lambda t: (t[0], t[1].number))

    seasons = ["Winter", "Spring", "Summer", "Fall"]

    # Layout: 2 rows x 2 columns (Winter/Spring on top; Summer/Fall on bottom)
    col_gutter = 14
    row_gutter = 16
    col_w = (table_rect.width - col_gutter) / 2.0
    row_h = (table_rect.height - row_gutter) / 2.0

    grid: dict[str, fitz.Rect] = {}
    grid["Winter"] = fitz.Rect(table_rect.x0, table_rect.y0, table_rect.x0 + col_w, table_rect.y0 + row_h)
    grid["Spring"] = fitz.Rect(table_rect.x0 + col_w + col_gutter, table_rect.y0, table_rect.x1, table_rect.y0 + row_h)
    grid["Summer"] = fitz.Rect(table_rect.x0, table_rect.y0 + row_h + row_gutter, table_rect.x0 + col_w, table_rect.y1)
    grid["Fall"] = fitz.Rect(table_rect.x0 + col_w + col_gutter, table_rect.y0 + row_h + row_gutter, table_rect.x1, table_rect.y1)

    font = "helv"
    font_b = "helv"
    fs_header = 9
    fs = 6.4
    leading = 7.2

    def trunc_to_width(s: str, *, max_w: float, fontname: str, fontsize: float) -> str:
        s = " ".join(s.split())
        if not s:
            return s
        if fitz.get_text_length(s, fontname=fontname, fontsize=fontsize) <= max_w:
            return s
        ell = "…"
        max_w2 = max(0.0, max_w - fitz.get_text_length(ell, fontname=fontname, fontsize=fontsize))
        # Binary search over character count.
        lo, hi = 0, len(s)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if fitz.get_text_length(s[:mid], fontname=fontname, fontsize=fontsize) <= max_w2:
                lo = mid
            else:
                hi = mid - 1
        return s[:lo] + ell

    # Draw in season pairs, aligned row-by-row across the row.
    def draw_row(left_season: str, right_season: str) -> None:
        left_box = grid[left_season]
        right_box = grid[right_season]

        # Headers and column headers (same y baselines)
        def header_y(box: fitz.Rect) -> float:
            return box.y0

        # Draw headers
        page.insert_text(fitz.Point(left_box.x0 + 2, header_y(left_box) + fs_header), left_season, fontsize=fs_header, fontname=font_b)
        page.insert_text(fitz.Point(right_box.x0 + 2, header_y(right_box) + fs_header), right_season, fontsize=fs_header, fontname=font_b)

        y = left_box.y0 + fs_header + 4

        def col_xs(box: fitz.Rect) -> tuple[float, float, float, float, float]:
            pad = 2
            x_m = box.x0 + pad
            # Column order: M# | Con | Mo | Name
            x_con = x_m + 28
            x_mo = x_con + 26
            x_name = x_mo + 22
            max_name_w = max(10.0, box.x1 - 2 - x_name)
            return x_m, x_con, x_mo, x_name, max_name_w

        lx_m, lx_con, lx_mo, lx_name, l_name_w = col_xs(left_box)
        rx_m, rx_con, rx_mo, rx_name, r_name_w = col_xs(right_box)

        for x_m, x_con, x_mo, x_name in ((lx_m, lx_con, lx_mo, lx_name), (rx_m, rx_con, rx_mo, rx_name)):
            page.insert_text(fitz.Point(x_m, y + fs), "M#", fontsize=fs, fontname=font_b)
            page.insert_text(fitz.Point(x_con, y + fs), "Con", fontsize=fs, fontname=font_b)
            page.insert_text(fitz.Point(x_mo, y + fs), "Mo", fontsize=fs, fontname=font_b)
            page.insert_text(fitz.Point(x_name, y + fs), "Name", fontsize=fs, fontname=font_b)

        y += leading

        left_items = by_season[left_season]
        right_items = by_season[right_season]
        n_rows = max(len(left_items), len(right_items))

        for i in range(n_rows):
            if y + leading > left_box.y1 or y + leading > right_box.y1:
                break

            if i < len(left_items):
                best_m, meta = left_items[i]
                constellation = meta.constellation or seds_constellations.get(meta.number, "")
                con = _abbr_constellation(constellation) if constellation else ""
                mo = _MONTH_ABBR[best_m]
                name = trunc_to_width(meta.name, max_w=l_name_w, fontname=font, fontsize=fs)
                page.insert_text(fitz.Point(lx_m, y + fs), f"M{meta.number}", fontsize=fs, fontname=font)
                page.insert_text(fitz.Point(lx_con, y + fs), con, fontsize=fs, fontname=font)
                page.insert_text(fitz.Point(lx_mo, y + fs), mo, fontsize=fs, fontname=font)
                page.insert_text(fitz.Point(lx_name, y + fs), name, fontsize=fs, fontname=font)

            if i < len(right_items):
                best_m, meta = right_items[i]
                constellation = meta.constellation or seds_constellations.get(meta.number, "")
                con = _abbr_constellation(constellation) if constellation else ""
                mo = _MONTH_ABBR[best_m]
                name = trunc_to_width(meta.name, max_w=r_name_w, fontname=font, fontsize=fs)
                page.insert_text(fitz.Point(rx_m, y + fs), f"M{meta.number}", fontsize=fs, fontname=font)
                page.insert_text(fitz.Point(rx_con, y + fs), con, fontsize=fs, fontname=font)
                page.insert_text(fitz.Point(rx_mo, y + fs), mo, fontsize=fs, fontname=font)
                page.insert_text(fitz.Point(rx_name, y + fs), name, fontsize=fs, fontname=font)

            y += leading

    draw_row("Winter", "Spring")
    draw_row("Summer", "Fall")

    # Small note.
    note = "Best month/season from SEDS 12-month tour (fallback: RA). Names abbreviated to fit."
    page.insert_text(fitz.Point(rect.x0, rect.y1 - 2), note, fontsize=6, fontname=font)


def _add_monthly_charts(
    doc: fitz.Document,
    paper: Paper,
    *,
    charts_dir: Path,
    year: int,
    margin: float,
) -> None:
    for month in range(1, 13):
        in_path = charts_dir / str(year) / f"sky-chart-{year:04d}-{month:02d}.pdf"
        if not in_path.exists():
            raise SystemExit(f"Missing monthly chart: {in_path}")

        src = fitz.open(str(in_path))
        try:
            page = doc.new_page(width=paper.width, height=paper.height)
            dst_rect = fitz.Rect(margin, margin, paper.width - margin, paper.height - margin)
            _show_pdf_page(page, dst_rect, src)
        finally:
            src.close()


def _ensure_next_page_is_even(doc: fitz.Document, paper: Paper) -> None:
    """Ensure the next page number is even (left-hand page in a spread)."""

    # If we currently have an even number of pages, the next page would be odd.
    # Add a blank page to make the next page even.
    if doc.page_count % 2 == 0:
        doc.new_page(width=paper.width, height=paper.height)


def _add_messier_two_page_spreads(
    doc: fitz.Document,
    paper: Paper,
    *,
    finder_dir: Path,
    pictures_dir: Path,
    binding_margin_in: float,
    outer_margin_in: float,
    gutter_in: float,
    label_fontsize: float,
    crop_picture_pages: bool,
) -> None:
    binding = max(0.0, binding_margin_in) * 72.0
    outer_margin = max(0.0, outer_margin_in) * 72.0
    gutter = max(0.0, gutter_in) * 72.0

    left_margin = outer_margin + binding
    right_margin = outer_margin
    top_margin = outer_margin
    bottom_margin = outer_margin

    content = fitz.Rect(left_margin, top_margin, paper.width - right_margin, paper.height - bottom_margin)

    # Photo page layout: full-width top/bottom panels.
    sub_g = gutter
    sub_h = (content.height - sub_g) / 2.0
    photo_rect = fitz.Rect(content.x0, content.y0, content.x1, content.y0 + sub_h)
    eye_rect = fitz.Rect(content.x0, photo_rect.y1 + sub_g, content.x1, content.y1)

    # Finder page layout: place on the full page to match the original finder PDFs.
    finder_rect = fitz.Rect(0, 0, paper.width, paper.height)

    for n in range(1, 111):
        photo_pdf = pictures_dir / f"M{n}_photograph.pdf"
        eye_pdf = pictures_dir / f"M{n}_eyepiece.pdf"
        finder_pdf = finder_dir / f"M{n:03d}.pdf"

        missing: list[Path] = [p for p in (photo_pdf, eye_pdf, finder_pdf) if not p.exists()]
        if missing:
            raise SystemExit("Missing required input PDFs:\n" + "\n".join(str(p) for p in missing))

        # Even page (left): pictures.
        pics_page = doc.new_page(width=paper.width, height=paper.height)
        pics_page.insert_text(
            fitz.Point(content.x0, content.y0 + label_fontsize),
            f"M{n}",
            fontsize=label_fontsize,
            fontname="helv",
        )

        src_photo = fitz.open(str(photo_pdf))
        src_eye = fitz.open(str(eye_pdf))
        try:
            clip_photo = None
            clip_eye = None
            if crop_picture_pages:
                clip_photo = _content_clip_rect(src_photo.load_page(0))
                clip_eye = _content_clip_rect(src_eye.load_page(0))
            # Rotate both sub-pages 90 degrees to use space better.
            _show_pdf_page(pics_page, photo_rect, src_photo, clip=clip_photo, rotate=90)
            _show_pdf_page(pics_page, eye_rect, src_eye, clip=clip_eye, rotate=90)
        finally:
            src_photo.close()
            src_eye.close()

        # Odd page (right): finder chart.
        finder_page = doc.new_page(width=paper.width, height=paper.height)
        src_finder = fitz.open(str(finder_pdf))
        try:
            _show_pdf_page(finder_page, finder_rect, src_finder)
        finally:
            src_finder.close()


def build(
    *,
    out_path: Path,
    year: int,
    paper_name: str,
    title: str,
    subtitle: str,
    charts_dir: Path,
    finder_dir: Path,
    pictures_dir: Path,
    binding_margin_in: float,
    outer_margin_in: float,
    gutter_in: float,
    crop_picture_pages: bool,
    max_pages: Optional[int],
    seds_cache_path: Path,
    refresh_seds: bool,
) -> None:
    paper = _paper(paper_name)

    doc = fitz.open()
    try:
        _cover_page(
            doc,
            paper,
            title=title,
            subtitle=subtitle,
            finder_dir=finder_dir,
            binding_margin_in=binding_margin_in,
            seds_cache_path=seds_cache_path,
            refresh_seds=refresh_seds,
        )
        _add_monthly_charts(doc, paper, charts_dir=charts_dir, year=year, margin=outer_margin_in * 72.0)

        # Make sure the first pictures page for M1 is even (left-hand page),
        # so M1 finder chart lands on the following odd (right-hand) page.
        _ensure_next_page_is_even(doc, paper)

        _add_messier_two_page_spreads(
            doc,
            paper,
            finder_dir=finder_dir,
            pictures_dir=pictures_dir,
            binding_margin_in=binding_margin_in,
            outer_margin_in=outer_margin_in,
            gutter_in=gutter_in,
            label_fontsize=12,
            crop_picture_pages=crop_picture_pages,
        )

        # Duplex-friendly: ensure even pages.
        if doc.page_count % 2 == 1:
            doc.new_page(width=paper.width, height=paper.height)

        if max_pages is not None and doc.page_count > max_pages:
            raise SystemExit(f"Output would be {doc.page_count} pages, which exceeds {max_pages}")

        out_path.parent.mkdir(parents=True, exist_ok=True)
        doc.save(str(out_path), deflate=True)
    finally:
        doc.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="messier-observing-book.pdf")
    ap.add_argument("--year", type=int, default=2026)
    ap.add_argument("--paper", default="a4", help="letter or a4")
    ap.add_argument("--title", default="Messier Observing Book")
    ap.add_argument("--subtitle", default="Monthly sky charts + Messier finder charts with photos/sketches")

    ap.add_argument("--charts-dir", default="sky-charts-pdfs")
    ap.add_argument("--finder-dir", default="messier-finder-charts-pdfs")
    ap.add_argument("--pictures-dir", default="visual-guide-picture-pages")

    ap.add_argument("--binding-margin", type=float, default=0.75, help="Extra left margin (inches) for spiral binding")
    ap.add_argument("--outer-margin", type=float, default=0.25, help="Outer margin (inches)")
    ap.add_argument("--gutter", type=float, default=0.2, help="Spacing between columns/rows (inches)")
    ap.add_argument(
        "--crop-pictures",
        action=getattr(argparse, "BooleanOptionalAction"),
        default=True,
        help="Crop photo/eyepiece pages to content to reduce whitespace (default: true)",
    )
    ap.add_argument(
        "--max-pages",
        type=int,
        default=None,
        help="Optional safety limit; fail if output exceeds this many pages",
    )

    ap.add_argument(
        "--seds-cache",
        default="seds-12months-cache.json",
        help="Cache file for SEDS 12-month best-month mapping (default: seds-12months-cache.json)",
    )
    ap.add_argument(
        "--refresh-seds",
        action="store_true",
        help="Refresh SEDS mapping cache by downloading the monthly list pages",
    )

    args = ap.parse_args(argv)

    build(
        out_path=Path(args.out).expanduser().resolve(),
        year=args.year,
        paper_name=args.paper,
        title=args.title,
        subtitle=args.subtitle,
        charts_dir=Path(args.charts_dir),
        finder_dir=Path(args.finder_dir),
        pictures_dir=Path(args.pictures_dir),
        binding_margin_in=args.binding_margin,
        outer_margin_in=args.outer_margin,
        gutter_in=args.gutter,
        crop_picture_pages=args.crop_pictures,
        max_pages=args.max_pages,
        seds_cache_path=Path(args.seds_cache),
        refresh_seds=args.refresh_seds,
    )

    print(f"Wrote: {Path(args.out).expanduser().resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
