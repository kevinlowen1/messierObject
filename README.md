# messierObjects

Builds a print-friendly “Messier Observing Book” PDF by combining:

- Monthly constellation sky charts (downloaded from Heavens-Above)
- Messier finder charts (downloaded from Sherwood Observatory)
- Per-object photo + eyepiece sketch pages (extracted from a local “Visual Guide to Messier objects” PDF)

The main output is a duplex-friendly PDF intended for spiral binding and printing.

## Setup

These scripts are written for Python 3 (they use `zoneinfo`, so Python 3.9+ is recommended).

Typical install (venv optional but recommended):

```bash
python -m venv .venv
source .venv/bin/activate
pip install pypdf pymupdf pillow reportlab
```

- `reportlab` is only required if you generate a cover in `combine_messier_findercharts.py`.

## Input sources

### 1) Messier finder charts (PDF)
- Source site: Sherwood Observatory
- Downloader parses a web page for PDF links and expects files named `M001.pdf` … `M110.pdf`.

### 2) Monthly sky charts (PDF)
- Source service: Heavens-Above sky chart endpoint
- The downloader requests a chart for the 15th of each month at 10:00 PM local time (default: US Eastern), including an explicit UTC offset to handle DST.

### 3) Visual Guide PDF (local file)
- Input file (default): `Visual_Guide_to_Messier-objects_HT-Vgy_2023_ENG.pdf`
- The processing script inverts it for print (dark → light) and extracts two pages per Messier object:
  - photograph page
  - eyepiece sketch page

### 4) Seasonal/best-month mapping (text)
- Source: SEDS “12 months of Messier” pages
- Used by the book builder to populate the cover table (best month / season). Cached locally in `seds-12months-cache.json`.

## Output files and folders

- `messier-finder-charts-pdfs/`
  - Individual finder charts: `M001.pdf` … `M110.pdf`
- `messier-finder-charts.pdf`
  - Optional combined finder charts PDF (with an auto-generated cover PDF alongside it)
- `sky-charts-pdfs/<year>/`
  - Monthly charts: `sky-chart-YYYY-MM.pdf`
- `Visual_Guide_to_Messier-objects_HT-Vgy_2023_ENG-inverted.pdf`
  - Inverted (rasterized) version of the visual guide for printing
- `visual-guide-picture-pages/`
  - Extracted per-object pages:
    - `M1_photograph.pdf` … `M110_photograph.pdf`
    - `M1_eyepiece.pdf` … `M110_eyepiece.pdf`
- `messier-observing-book.pdf`
  - Final observing book (cover + 12 sky charts + 110 objects laid out two-per-page)

## Scripts

### `download_messier_findercharts.py`
Downloads all Messier finder-chart PDFs from Sherwood Observatory into `messier-finder-charts-pdfs/`.

- Default page URL is baked in but overridable with `--page`.
- Verifies the expected set `M001.pdf` … `M110.pdf` exists locally.

Example:

```bash
python download_messier_findercharts.py
```

### `replace_messier_pdf.py`
Replaces a single Messier finder chart (`M###.pdf`) with a PDF from a URL and normalizes it for printing:

- transfers PDF rotation into content
- auto-rotates landscape pages to portrait
- scales/centers onto a target page size (default `a4`, optional `letter`)

Example:

```bash
python replace_messier_pdf.py --m 106 \
  --url https://example.com/M106_Finder_Chart.pdf
```

### `combine_messier_findercharts.py`
Combines the individual `M001.pdf` … `M110.pdf` files into a single print-friendly PDF.

- Can generate and prepend a simple cover page.
- Can reserve extra left margin for spiral binding.

Example:

```bash
python combine_messier_findercharts.py --out messier-finder-charts.pdf
```

### `download_monthly_sky_charts.py`
Downloads 12 monthly sky-chart PDFs from Heavens-Above into `sky-charts-pdfs/<year>/`.

Defaults are tuned for a specific location and US Eastern time.

Example:

```bash
python download_monthly_sky_charts.py --year 2026
```

### `process_visual_guide.py`
Inverts the visual guide PDF for printing and extracts per-object photo and eyepiece pages.

- Default behavior is to extract **all** Messier objects (M1..M110).
- Uses a text-based heuristic on the *original* PDF to locate each object’s first page, then extracts that page and the next page from the inverted PDF.

Example:

```bash
python process_visual_guide.py --dpi 150
```

### `build_messier_book.py`
Builds the final observing book PDF.

Inputs it expects to already exist:

- Monthly charts: `sky-charts-pdfs/<year>/sky-chart-YYYY-MM.pdf`
- Finder charts: `messier-finder-charts-pdfs/M001.pdf` … `M110.pdf`
- Extracted visual-guide pages:
  - `visual-guide-picture-pages/M1_photograph.pdf` … `M110_photograph.pdf`
  - `visual-guide-picture-pages/M1_eyepiece.pdf` … `M110_eyepiece.pdf`

It then creates:

- 1 cover page (includes a season table using SEDS mapping, cached in `seds-12months-cache.json`)
- 12 monthly sky charts
- 110 Messier objects laid out **two-per-page** (photo+sketch on left, finder chart on right)
- optional final blank page to ensure an even page count for duplex printing

Example:

```bash
python build_messier_book.py --year 2026 --paper a4 --out messier-observing-book.pdf
```

If you want to refresh the SEDS “best month” cache:

```bash
python build_messier_book.py --refresh-seds
```

## Recommended run order

If you want a full end-to-end rebuild:

1. Download finder charts
   ```bash
   python download_messier_findercharts.py
   ```

2. (Optional) Replace any problematic charts
   ```bash
   python replace_messier_pdf.py --m 106 --url https://example.com/M106_Finder_Chart.pdf
   ```

3. (Optional) Combine finder charts into one PDF for separate printing
   ```bash
   python combine_messier_findercharts.py --out messier-finder-charts.pdf
   ```

4. Download monthly sky charts for your target year/location
   ```bash
   python download_monthly_sky_charts.py --year 2026
   ```

5. Invert + extract photo/eyepiece pages from the visual guide
   ```bash
   python process_visual_guide.py
   ```

6. Build the final observing book
   ```bash
   python build_messier_book.py --year 2026 --paper a4 --out messier-observing-book.pdf
   ```

## How to adapt this project for a new site / new inputs

This repo is intentionally “script-driven”: filenames and URL patterns matter. The simplest adaptation strategy is to keep the *same on-disk file naming conventions* and adjust only the download/extraction scripts.

### A) New finder-chart website

Goal: end up with `messier-finder-charts-pdfs/M001.pdf` … `M110.pdf`.

Options:

- If the new site has a single index page with links:
  - Update `download_messier_findercharts.py`:
    - pass `--page <new URL>` if it’s just a different page
    - otherwise update `PAGE_URL` and/or the PDF URL filtering regex (it currently keys off `/M###.pdf`)
- If the PDFs have different names:
  - Either rename them to `M###.pdf`, or update the regex in `combine_messier_findercharts.py` and the expected paths in `build_messier_book.py`.

### B) New monthly sky-chart provider

Goal: end up with `sky-charts-pdfs/<year>/sky-chart-YYYY-MM.pdf`.

- If you can still fetch a PDF via URL parameters, you can modify `download_monthly_sky_charts.py`:
  - replace `BASE_URL`
  - update `_build_url()` parameters as required by the new endpoint
  - keep the existing output naming so `build_messier_book.py` continues to work

### C) New “visual guide” PDF

Goal: end up with:

- `visual-guide-picture-pages/M<n>_photograph.pdf`
- `visual-guide-picture-pages/M<n>_eyepiece.pdf`

What you might need to change in `process_visual_guide.py`:

- If the PDF’s page headers differ, update `_find_messier_photo_pages()` heuristics (it looks for pages whose text begins with something like `M 31 ...` and avoids index/description pages).
- If the photo and sketch are not on consecutive pages, update the extraction logic in `extract_all_messier_pages()`.
- If you don’t want inversion (or want vector extraction), disable `--invert` and implement a different extraction strategy.

### D) Layout / paper size changes

Most layout knobs are already command-line arguments in `build_messier_book.py`:

- `--paper a4|letter`
- `--binding-margin` (extra left margin)
- `--outer-margin`
- `--gutter`
- `--no-crop-pictures` (keeps original whitespace)

If you change filenames or directories, prefer using:

- `--charts-dir`
- `--finder-dir`
- `--pictures-dir`

…before editing code.

## Notes

- Dependencies used by the scripts include: `pypdf`, `PyMuPDF` (`fitz`), `Pillow`, and optionally `reportlab` (only needed for the finder-chart cover in `combine_messier_findercharts.py`).
- `process_visual_guide.py` rasterizes pages during inversion; that improves print reliability but removes selectable text.
