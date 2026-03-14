#!/usr/bin/env python3
"""Download 12 monthly sky-chart PDFs from Heavens-Above.

Generates a chart for the 15th of each month at 10:00 PM Eastern time
(America/New_York), correctly handling DST by computing both:
- `time`: UTC epoch milliseconds
- `utcOffset`: local offset from UTC in milliseconds (negative for US Eastern)

Default location matches the URL provided by the user.

Usage:
  python download_monthly_sky_charts.py
  python download_monthly_sky_charts.py --year 2026 --dest sky-charts-pdfs
  python download_monthly_sky_charts.py --target letter

Notes:
- The service endpoint is:
  https://www.heavens-above.com/SkyAndTelescope/StSkyChartPDF.ashx
- Output filenames are: sky-chart-YYYY-MM.pdf
"""

from __future__ import annotations

import argparse
import datetime as dt
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from zoneinfo import ZoneInfo


BASE_URL = "https://www.heavens-above.com/SkyAndTelescope/StSkyChartPDF.ashx"
DEFAULT_LAT = 26.87798
DEFAULT_LON = -80.16052
DEFAULT_LOCATION = "West Palm Beach, FL 33418"
DEFAULT_TZ = "America/New_York"


@dataclass(frozen=True)
class ChartRequest:
    year: int
    month: int
    local_dt: dt.datetime
    time_ms_utc: int
    utc_offset_ms: int


def _local_datetime(year: int, month: int, tz: ZoneInfo, day: int, hour: int) -> dt.datetime:
    # 15th at 10PM local time.
    return dt.datetime(year, month, day, hour, 0, 0, tzinfo=tz)


def _build_request(year: int, month: int, tz_name: str, day: int, hour: int) -> ChartRequest:
    tz = ZoneInfo(tz_name)
    local_dt = _local_datetime(year, month, tz, day=day, hour=hour)
    utc_dt = local_dt.astimezone(dt.timezone.utc)
    time_ms_utc = int(utc_dt.timestamp() * 1000)
    offset = local_dt.utcoffset()
    if offset is None:
        raise SystemExit(f"Could not determine UTC offset for {local_dt}")
    utc_offset_ms = int(offset.total_seconds() * 1000)
    return ChartRequest(
        year=year,
        month=month,
        local_dt=local_dt,
        time_ms_utc=time_ms_utc,
        utc_offset_ms=utc_offset_ms,
    )


def _build_url(
    req: ChartRequest,
    *,
    latitude: float,
    longitude: float,
    location: str,
    show_equator: bool,
    show_ecliptic: bool,
    show_star_names: bool,
    show_planet_names: bool,
    show_cons_names: bool,
    show_cons_lines: bool,
    show_cons_boundaries: bool,
    show_specials: bool,
    use_24h_clock: bool,
) -> str:
    params: dict[str, str] = {
        "time": str(req.time_ms_utc),
        "latitude": f"{latitude:.5f}",
        "longitude": f"{longitude:.5f}",
        "location": location,
        "utcOffset": str(req.utc_offset_ms),
        "showEquator": str(show_equator).lower(),
        "showEcliptic": str(show_ecliptic).lower(),
        "showStarNames": str(show_star_names).lower(),
        "showPlanetNames": str(show_planet_names).lower(),
        "showConsNames": str(show_cons_names).lower(),
        "showConsLines": str(show_cons_lines).lower(),
        "showConsBoundaries": str(show_cons_boundaries).lower(),
        "showSpecials": str(show_specials).lower(),
        "use24hClock": str(use_24h_clock).lower(),
    }
    return f"{BASE_URL}?{urllib.parse.urlencode(params, quote_via=urllib.parse.quote)}"


def _download_pdf(url: str, out_path: Path, *, timeout_s: float, retries: int, sleep_s: float) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_suffix(out_path.suffix + ".part")

    last_err: str | None = None
    for attempt in range(1, retries + 2):
        try:
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": "messierObjects-skychart-downloader/1.0",
                },
            )
            with urllib.request.urlopen(req, timeout=timeout_s) as resp:
                data = resp.read()

            # Basic validation.
            if not data.startswith(b"%PDF"):
                snippet = data[:200].decode("utf-8", errors="replace")
                raise RuntimeError(f"Response did not look like a PDF. First bytes: {snippet!r}")

            with open(tmp_path, "wb") as f:
                f.write(data)

            tmp_path.replace(out_path)
            return
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
            raise SystemExit(f"Failed downloading {url} -> {out_path}: {last_err}")


def main(argv: list[str] | None = None) -> int:
    now_year = dt.datetime.now(dt.timezone.utc).astimezone(ZoneInfo(DEFAULT_TZ)).year

    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=now_year, help="Year to download (default: current Eastern year)")
    ap.add_argument("--dest", default="sky-charts-pdfs", help="Destination folder")
    ap.add_argument("--tz", default=DEFAULT_TZ, help="IANA time zone name (default: America/New_York)")
    ap.add_argument("--day", type=int, default=15, help="Day-of-month (default: 15)")
    ap.add_argument("--hour", type=int, default=22, help="Hour in local time (default: 22 for 10PM)")
    ap.add_argument("--lat", type=float, default=DEFAULT_LAT, help="Latitude")
    ap.add_argument("--lon", type=float, default=DEFAULT_LON, help="Longitude")
    ap.add_argument("--location", default=DEFAULT_LOCATION, help="Location label")

    ap.add_argument("--timeout", type=float, default=60.0)
    ap.add_argument("--retries", type=int, default=2)
    ap.add_argument("--sleep", type=float, default=1.0)
    ap.add_argument("--overwrite", action="store_true")

    # Mirror the user-provided URL defaults (supports --foo / --no-foo).
    boolopt = getattr(argparse, "BooleanOptionalAction")
    ap.add_argument("--show-equator", action=boolopt, default=False)
    ap.add_argument("--show-ecliptic", action=boolopt, default=False)
    ap.add_argument("--show-star-names", action=boolopt, default=True)
    ap.add_argument("--show-planet-names", action=boolopt, default=False)
    ap.add_argument("--show-cons-names", action=boolopt, default=True)
    ap.add_argument("--show-cons-lines", action=boolopt, default=True)
    ap.add_argument("--show-cons-boundaries", action=boolopt, default=True)
    ap.add_argument("--show-specials", action=boolopt, default=True)
    ap.add_argument("--use-24h-clock", action=boolopt, default=True)

    args = ap.parse_args(argv)

    dest_dir = Path(args.dest).expanduser().resolve() / str(args.year)
    dest_dir.mkdir(parents=True, exist_ok=True)

    for month in range(1, 13):
        out_path = dest_dir / f"sky-chart-{args.year:04d}-{month:02d}.pdf"
        if out_path.exists() and not args.overwrite:
            print(f"Skip (exists): {out_path.name}")
            continue

        req = _build_request(args.year, month, args.tz, day=args.day, hour=args.hour)
        url = _build_url(
            req,
            latitude=args.lat,
            longitude=args.lon,
            location=args.location,
            show_equator=args.show_equator,
            show_ecliptic=args.show_ecliptic,
            show_star_names=args.show_star_names,
            show_planet_names=args.show_planet_names,
            show_cons_names=args.show_cons_names,
            show_cons_lines=args.show_cons_lines,
            show_cons_boundaries=args.show_cons_boundaries,
            show_specials=args.show_specials,
            use_24h_clock=args.use_24h_clock,
        )

        print(f"Downloading {args.year:04d}-{month:02d} (local {req.local_dt.isoformat()}) -> {out_path.name}")
        _download_pdf(url, out_path, timeout_s=args.timeout, retries=args.retries, sleep_s=args.sleep)

    print(f"Done: {dest_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
