#!/usr/bin/env python3
"""Download all Messier finder-chart PDFs from Sherwood Observatory.

- Extracts PDF links from the page HTML.
- Downloads into ./messier-finder-charts-pdfs/
- Verifies expected set M001..M110.

Usage:
  python download_messier_findercharts.py
  python download_messier_findercharts.py --dest ./out --retries 3
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path


PAGE_URL = "https://sherwood-observatory.org.uk/astronomy/finder-charts/messier-finder-charts/"
DEFAULT_DEST = "messier-finder-charts-pdfs"


class _LinkExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.hrefs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() != "a":
            return
        for k, v in attrs:
            if k.lower() == "href" and v:
                self.hrefs.append(v)


@dataclass(frozen=True)
class PdfLink:
    url: str
    filename: str


def _http_get_text(url: str, timeout_s: float = 30.0) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "messierObjects-downloader/1.0 (+https://github.com/)"
        },
    )
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        charset = resp.headers.get_content_charset() or "utf-8"
        return resp.read().decode(charset, errors="replace")


def _extract_pdf_links(page_url: str) -> list[PdfLink]:
    html = _http_get_text(page_url)

    parser = _LinkExtractor()
    parser.feed(html)

    pdf_urls: list[str] = []
    for href in parser.hrefs:
        if ".pdf" not in href.lower():
            continue
        pdf_urls.append(urllib.parse.urljoin(page_url, href))

    # Narrow down to Messier PDFs if present (M001..M110).
    messier_re = re.compile(r"/M(\d{3})\.pdf(?:$|\?)", re.IGNORECASE)
    messier = [u for u in pdf_urls if messier_re.search(urllib.parse.urlparse(u).path)]
    urls = messier if messier else pdf_urls

    # De-dupe while preserving order.
    seen: set[str] = set()
    deduped: list[str] = []
    for u in urls:
        if u in seen:
            continue
        seen.add(u)
        deduped.append(u)

    links: list[PdfLink] = []
    for u in deduped:
        path = urllib.parse.urlparse(u).path
        filename = os.path.basename(path)
        if not filename.lower().endswith(".pdf"):
            continue
        links.append(PdfLink(url=u, filename=filename))

    # Stable sort by Messier number if possible.
    def sort_key(link: PdfLink) -> tuple[int, str]:
        m = messier_re.search(urllib.parse.urlparse(link.url).path)
        if m:
            return (int(m.group(1)), link.filename)
        return (10**9, link.filename)

    links.sort(key=sort_key)
    return links


def _download_one(
    link: PdfLink,
    dest_dir: Path,
    timeout_s: float,
    retries: int,
    sleep_s: float,
    overwrite: bool,
) -> tuple[bool, str | None]:
    out_path = dest_dir / link.filename
    if out_path.exists() and not overwrite:
        return (True, None)

    tmp_path = out_path.with_suffix(out_path.suffix + ".part")

    last_err: str | None = None
    for attempt in range(1, retries + 2):
        try:
            req = urllib.request.Request(
                link.url,
                headers={
                    "User-Agent": "messierObjects-downloader/1.0 (+https://github.com/)"
                },
            )
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                if resp.status and resp.status >= 400:
                    raise urllib.error.HTTPError(
                        link.url, resp.status, resp.reason, resp.headers, None
                    )
                with open(tmp_path, "wb") as f:
                    while True:
                        chunk = resp.read(1024 * 256)
                        if not chunk:
                            break
                        f.write(chunk)

            tmp_path.replace(out_path)
            return (True, None)
        except Exception as e:  # noqa: BLE001
            last_err = f"{type(e).__name__}: {e}"
            try:
                if tmp_path.exists():
                    tmp_path.unlink()
            except OSError:
                pass

            if attempt <= retries:
                time.sleep(sleep_s)
                continue
            return (False, last_err)

    return (False, last_err)


def _expected_filenames() -> set[str]:
    return {f"M{n:03d}.pdf" for n in range(1, 111)}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--page", default=PAGE_URL)
    ap.add_argument("--dest", default=DEFAULT_DEST)
    ap.add_argument("--timeout", type=float, default=60.0)
    ap.add_argument("--retries", type=int, default=2)
    ap.add_argument("--sleep", type=float, default=1.0)
    ap.add_argument("--overwrite", action="store_true")
    args = ap.parse_args(argv)

    dest_dir = Path(args.dest).expanduser().resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)

    links = _extract_pdf_links(args.page)
    if not links:
        print("No PDF links found on the page.", file=sys.stderr)
        return 2

    expected = _expected_filenames()
    extracted_names = {l.filename for l in links}
    missing_on_page = sorted(expected - extracted_names)
    extra_on_page = sorted(extracted_names - expected)

    print(f"Found {len(links)} PDF link(s) on page")
    if missing_on_page:
        print(f"WARNING: page is missing {len(missing_on_page)} expected file(s): {', '.join(missing_on_page[:15])}{'...' if len(missing_on_page) > 15 else ''}")
    if extra_on_page:
        # This is fine; some pages include additional PDFs.
        print(f"Note: page includes {len(extra_on_page)} extra PDF(s) beyond M001..M110")

    failures: list[tuple[str, str]] = []
    downloaded = 0
    skipped = 0

    for idx, link in enumerate(links, start=1):
        out_path = dest_dir / link.filename
        if out_path.exists() and not args.overwrite:
            skipped += 1
            continue

        ok, err = _download_one(
            link,
            dest_dir=dest_dir,
            timeout_s=args.timeout,
            retries=args.retries,
            sleep_s=args.sleep,
            overwrite=args.overwrite,
        )
        if ok:
            downloaded += 1
        else:
            failures.append((link.url, err or "unknown error"))

        if idx % 10 == 0 or idx == len(links):
            print(f"Progress: {idx}/{len(links)} links processed")

    # Verify local files for M001..M110
    local = {p.name for p in dest_dir.glob("M*.pdf")}
    missing_local = sorted(expected - local)

    print("---")
    print(f"Destination: {dest_dir}")
    print(f"Downloaded: {downloaded}, Skipped(existing): {skipped}, Failures: {len(failures)}")
    print(f"Local Messier PDFs present: {len(local)}/110")
    if missing_local:
        print(f"Missing locally ({len(missing_local)}): {', '.join(missing_local[:20])}{'...' if len(missing_local) > 20 else ''}")

    if failures:
        print("---")
        print("Failures (first 10):")
        for u, e in failures[:10]:
            print(f"- {u} :: {e}")
        return 1

    if missing_local:
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
