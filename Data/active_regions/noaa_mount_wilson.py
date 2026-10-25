"""
=============================================================================
NOAA Solar Region Summary (SRS) - Mount Wilson Classification
=============================================================================
Downloads the daily SRS files from NOAA and extracts, for every active region
listed in Section I ("Regions with Sunspots"), its position, area, McIntosh
and Mount Wilson classifications, building a daily time series.

Data source:
  https://www.ngdc.noaa.gov/stp/space-weather/swpc-products/daily_reports/solar_region_summaries/

Outputs
  1. mount_wilson_dataset.csv   one row per active region per observation day
  2. mount_wilson_summary.csv   one row per observation day with regions
  3. srs_day_status.csv         one row per requested report date: what happened
                                (parsed / no regions / missing / error ...)

Columns of mount_wilson_dataset.csv
  date          - Observation date (YYYY-MM-DD): the day at whose 24:00 UT the
                  positions are valid. The SRS issued on day D (00:30 UT)
                  describes day D-1; see `date_source`.
  report_date   - Date in the SRS file name (issue date)
  date_source   - 'header' if `date` was read from "Locations Valid at DD/2400Z",
                  'assumed' if it was set to report_date - 1 day
  noaa_number   - NOAA region number as printed in the SRS (4 digits, modulo 10000)
  noaa_full     - Full NOAA number (+10000 for regions numbered after the
                  9999 -> 0000 wrap of June 2002), for matching external catalogs
  location      - Heliographic position (e.g., N14E23)
  lat, lon      - Heliographic latitude and central-meridian distance in degrees
                  (north and west positive)
  lo            - Carrington longitude
  area          - Spot area in millionths of the solar hemisphere
  z_class       - McIntosh class, normalised case (e.g. 'Ekc')
  mcintosh_z, mcintosh_p, mcintosh_c - its three components
  ll            - Longitudinal extent (degrees)
  nn            - Number of sunspots
  mag_type_raw  - Mount Wilson type as printed in the report
  mag_type      - Normalised Mount Wilson type (α, β, βγ, βγδ, ...)
  complexity    - Ordinal complexity value (see below)
  is_delta      - True for δ configurations (βδ, γδ, βγδ)

Mount Wilson complexity scale (ordinal, unchanged; its order is under review):
  α → 1   β → 2   βδ → 3   βγ, γ → 4   γδ, βγδ → 5

Usage:
  python noaa_mount_wilson.py --start 1996-01-01 --end 2026-07-31
=============================================================================
"""

from __future__ import annotations

import logging
import re
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

try:
    from tqdm import tqdm
except ImportError:  # progress bar is optional
    def tqdm(it, **kwargs):
        return it

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

BASE_URL = (
    "https://www.ngdc.noaa.gov/stp/space-weather/swpc-products/"
    "daily_reports/solar_region_summaries"
)

START_DATE = date(1996, 1, 1)
END_DATE = date.today()

HERE = Path(__file__).resolve().parent   # scripts read and write in their own folder by default
CACHE_DIR = HERE / "srs_cache"
OUTPUT_CSV = HERE / "mount_wilson_dataset.csv"
OUTPUT_SUMMARY = HERE / "mount_wilson_summary.csv"
OUTPUT_STATUS = HERE / "srs_day_status.csv"

REQUEST_DELAY = 0.3   # seconds between requests (only when downloading)
MAX_RETRIES = 3       # attempts per file for network errors and HTTP 5xx

NOAA_WRAP_DATE = date(2002, 6, 1)   # region numbers wrapped 9999 -> 0000 in June 2002

# ---------------------------------------------------------------------------
# Mount Wilson normalisation
# ---------------------------------------------------------------------------

CANONICAL = {
    "alpha": ("α", 1),
    "alfa": ("α", 1),
    "beta": ("β", 2),
    "beta-delta": ("βδ", 3),
    "gamma": ("γ", 4),
    "beta-gamma": ("βγ", 4),
    "gamma-delta": ("γδ", 5),
    "beta-gamma-delta": ("βγδ", 5),
}
# for partial matches, try the longest names first ('beta-gamma-delta' before 'beta')
_PARTIAL_ORDER = sorted(CANONICAL, key=len, reverse=True)


def normalize_mag_type(raw: str) -> tuple[str, int | None]:
    """'Beta-Gamma-Delta' / 'BETA-GAMMA-DELTA' -> ('βγδ', 5)."""
    if not raw or pd.isna(raw):
        return ("Unknown", None)
    cleaned = raw.strip().lower().replace(" ", "-")
    if cleaned in CANONICAL:
        return CANONICAL[cleaned]
    for key in _PARTIAL_ORDER:
        if key in cleaned:
            return CANONICAL[key]
    return (raw.strip(), None)


def normalize_mcintosh(z: str) -> str:
    """McIntosh class with normalised case: Zurich class upper, p and c lower.
    The SRS printed the 2nd letter in upper case until 2000 and in lower case after."""
    z = z.strip()
    return z[:1].upper() + z[1:].lower() if z else z


def full_noaa_number(n: int, obs: date) -> int:
    """Undo the modulo-10000 numbering of the SRS after the June 2002 wrap."""
    return n + 10000 if (obs >= NOAA_WRAP_DATE and n < 9000) else n


def parse_location(loc: str) -> tuple[int | None, int | None]:
    """'N14E23' -> (14, -23); 'S09W46' -> (-9, 46). West and north positive.
    A corrupted digit ('N15W0*', seen in the report of 2024-10-19) gives None."""
    m = re.match(r"([NS])([\d*]{2})([EW])([\d*]{2,3})", loc)
    num = lambda t: None if "*" in t else int(t)
    lat, lon = num(m.group(2)), num(m.group(4))
    lat = None if lat is None else lat * (1 if m.group(1) == "N" else -1)
    lon = None if lon is None else lon * (1 if m.group(3) == "W" else -1)
    return lat, lon


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
                    datefmt="%H:%M:%S")
logger = logging.getLogger(__name__)


def build_url(d: date) -> str:
    return f"{BASE_URL}/{d.year}/{d.month:02d}/{d.strftime('%Y%m%d')}SRS.txt"


def download_srs(d: date, session: requests.Session) -> tuple[str | None, str, bool]:
    """
    Returns (text, status, downloaded):
      status = 'ok' | 'missing_404' | 'http_<code>' | 'network_error'
    (after parsing, a report can also be marked 'superseded' when another report
    describes the same observation day)
      downloaded = True if the file was fetched now (not read from the cache).
    Failed downloads are NOT cached, so a later run retries them.
    """
    cache_path = CACHE_DIR / str(d.year) / f"{d.strftime('%Y%m%d')}SRS.txt"
    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8", errors="replace"), "ok", False

    url = build_url(d)
    status = "network_error"
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, timeout=30)
            if resp.status_code == 200:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_bytes(resp.content)
                return resp.text, "ok", True
            if resp.status_code == 404:
                return None, "missing_404", True
            status = f"http_{resp.status_code}"
            logger.warning(f"{d}: HTTP {resp.status_code} (attempt {attempt})")
        except requests.RequestException as e:
            status = "network_error"
            logger.warning(f"{d}: network error: {e} (attempt {attempt})")
        time.sleep(2 ** attempt)   # back off after any failure
    return None, status, True


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

# Some reports write the section numbers with the digit 1 instead of the letter I
SECTION_I = re.compile(r"^[I1]\.\s+Regions\s+with\s+Sunspots", re.IGNORECASE)
SECTION_END = re.compile(r"^([I1]A|II|11)\.", re.IGNORECASE)
VALID_AT = re.compile(r"Valid\s+at\s+(\d{1,2})/(\d{4})Z", re.IGNORECASE)
DATA_LINE = re.compile(
    r"^(\d{3,5})\s+"               # NOAA number
    r"([NS][\d*]{2}[EW][\d*]{2,3})\s+"   # location ("*" = corrupted digit in a few reports)
    r"(\d{1,3})\s+"                # Carrington longitude
    r"(\d{1,5})\s+"                # area
    r"(\S+)\s+"                    # McIntosh class
    r"(\d{1,3})"                   # LL
    r"(?:\s+(\d{1,3}))?"            # NN (blank in a few reports)
    r"(?:\s+(\D.*?))?\s*$"          # Mount Wilson type (blank in a few reports)
)


def observation_date(report: date, valid_day: int | None) -> tuple[date, str]:
    """Date at whose 24:00 UT the positions are valid.
    Uses the day of month in 'Valid at DD/2400Z' (searching report-1 ... report-3,
    then report itself); falls back to report - 1 day."""
    if valid_day is not None:
        for k in (1, 2, 3, 0):
            cand = report - timedelta(days=k)
            if cand.day == valid_day:
                return cand, "header"
    return report - timedelta(days=1), "assumed"


def parse_srs(text: str, report: date) -> tuple[list[dict], dict]:
    """Parse Section I. Returns (records, info) where info describes the file."""
    records, unparsed = [], []
    in_section = header_seen = said_none = False
    valid_day = None

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if SECTION_I.match(line):
            in_section = True
            m = VALID_AT.search(line)
            valid_day = int(m.group(1)) if m else None
            continue
        if in_section and SECTION_END.match(line):
            break
        if not in_section or not line:
            continue
        if re.match(r"^Nmbr", line, re.IGNORECASE):
            header_seen = True
            continue
        if re.match(r"^None\b", line, re.IGNORECASE):
            said_none = True
            continue
        if not header_seen:
            continue
        m = DATA_LINE.match(line)
        if not m:
            unparsed.append(line)
            continue
        records.append(m)

    obs, source = observation_date(report, valid_day)
    out = []
    for m in records:
        raw_mag = (m.group(8) or "").strip()
        mag, comp = normalize_mag_type(raw_mag)
        z = normalize_mcintosh(m.group(5))
        lat, lon = parse_location(m.group(2))
        n = int(m.group(1))
        out.append({
            "date": obs.isoformat(),
            "report_date": report.isoformat(),
            "date_source": source,
            "noaa_number": n,
            "noaa_full": full_noaa_number(n, obs),
            "location": m.group(2),
            "lat": lat,
            "lon": lon,
            "lo": int(m.group(3)),
            "area": int(m.group(4)),
            "z_class": z,
            "mcintosh_z": z[:1],
            "mcintosh_p": z[1:2],
            "mcintosh_c": z[2:3],
            "ll": int(m.group(6)),
            "nn": int(m.group(7)) if m.group(7) else None,
            "mag_type_raw": raw_mag,
            "mag_type": mag,
            "complexity": comp,
            "is_delta": "δ" in mag,
        })

    if not in_section:
        status = "no_section_I"
    elif out:
        status = "parsed"
    elif said_none:
        status = "no_regions"
    else:
        status = "empty_section"
    info = dict(file_status=status, obs_date=obs.isoformat(), date_source=source,
                n_regions=len(out), n_unparsed=len(unparsed),
                unparsed_example=unparsed[0] if unparsed else "")
    return out, info


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def generate_date_range(start: date, end: date) -> list[date]:
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def build_dataset(start: date, end: date) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Download (or read from cache) and parse every SRS between start and end.
    Returns (records, day_status)."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": "SolarResearchBot/1.0 (educational use)"})

    all_records, status_rows = [], []
    dates = generate_date_range(start, end)
    logger.info(f"Processing {len(dates)} report dates ({start} -> {end})")

    for d in tqdm(dates, desc="SRS", unit="day"):
        text, dl_status, downloaded = download_srs(d, session)
        if text is None:
            status_rows.append(dict(report_date=d.isoformat(), file_status=dl_status,
                                    obs_date=(d - timedelta(days=1)).isoformat(),
                                    date_source="assumed", n_regions=0, n_unparsed=0,
                                    unparsed_example=""))
        else:
            records, info = parse_srs(text, d)
            all_records.extend(records)
            status_rows.append(dict(report_date=d.isoformat(), **info))
        if downloaded:
            time.sleep(REQUEST_DELAY)

    status = pd.DataFrame(status_rows)
    df = pd.DataFrame(all_records)

    # Two reports describing the same observation day: keep one, so that the
    # regions of that day are not counted twice. Preference: the report issued
    # the day after the observation (the regular case), else the latest one.
    ok = status.file_status.isin(["parsed", "no_regions", "empty_section"])
    dup_obs = status[ok & status.obs_date.duplicated(keep=False)]
    for obs, grp in dup_obs.groupby("obs_date"):
        expected = (date.fromisoformat(obs) + timedelta(days=1)).isoformat()
        keep = expected if expected in set(grp.report_date) else grp.report_date.max()
        drop = [r for r in grp.report_date if r != keep]
        status.loc[status.report_date.isin(drop), "file_status"] = "superseded"
        if not df.empty:
            df = df[~df.report_date.isin(drop)]
        logger.info(f"Observation date {obs} in reports {sorted(grp.report_date)}: kept {keep}")

    if not df.empty:
        df["date"] = pd.to_datetime(df["date"])
        df = df.sort_values(["date", "noaa_full"]).reset_index(drop=True)
    return df, status


def build_summary(df: pd.DataFrame) -> pd.DataFrame:
    """Daily summary (observation days with at least one region)."""
    if df.empty:
        return pd.DataFrame()
    return (
        df.groupby("date")
        .agg(
            n_active_regions=("noaa_full", "count"),
            total_area=("area", "sum"),
            max_complexity=("complexity", "max"),
            mean_complexity=("complexity", "mean"),
            n_delta=("is_delta", "sum"),
            n_beta_gamma_delta=("mag_type", lambda x: (x == "βγδ").sum()),
            n_beta_gamma=("mag_type", lambda x: (x == "βγ").sum()),
            n_gamma_delta=("mag_type", lambda x: (x == "γδ").sum()),
            n_complex_gt3=("complexity", lambda x: (pd.to_numeric(x, errors="coerce") > 3).sum()),
        )
        .reset_index()
    )


def print_report(df: pd.DataFrame, status: pd.DataFrame) -> None:
    print("\n" + "=" * 64)
    print("SRS DATASET REPORT")
    print("=" * 64)
    print("Report dates by status:")
    for s, n in status["file_status"].value_counts().items():
        print(f"  {s:16s}: {n:6d}")
    dupe = status[status.file_status.isin(["parsed", "no_regions", "empty_section"])]["obs_date"].duplicated().sum()
    print(f"Observation-date source: {status['date_source'].value_counts().to_dict()}")
    print(f"Observation dates appearing in more than one report: {dupe}")
    bad = status[status.n_unparsed > 0]
    print(f"Reports with unparsed lines in Section I: {len(bad)} "
          f"({int(status.n_unparsed.sum())} lines)")
    for r in bad.head(15).itertuples():
        print(f"  {r.report_date}: {r.unparsed_example}")
    errors = status[status.file_status.str.startswith(("http_", "network"))]
    if len(errors):
        print(f"Download errors (re-run to retry): {len(errors)}  e.g. {errors.report_date.head(5).tolist()}")
    if df.empty:
        return
    print(f"\nPeriod (observation dates): {df['date'].min().date()} -> {df['date'].max().date()}")
    print(f"Observation days with regions: {df['date'].nunique()}")
    print(f"Unique regions (noaa_full): {df['noaa_full'].nunique()}")
    print(f"Total records: {len(df)}")
    print(f"Records with unknown magnetic type: {df['complexity'].isna().sum()}")
    print(f"Records with blank spot count (NN): {df['nn'].isna().sum()}")
    odd = status[status.file_status.isin(["no_section_I", "empty_section"])]
    if len(odd):
        print(f"Reports to inspect by hand (no_section_I / empty_section): {odd.report_date.tolist()}")
    print("\nMount Wilson type distribution:")
    for t, n in df["mag_type"].value_counts().items():
        print(f"  {t:8s}: {n:6d}  ({100 * n / len(df):.1f}%)")
    print(f"δ configurations: {int(df['is_delta'].sum())}")
    print("=" * 64)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Download NOAA SRS reports and build the Mount Wilson dataset")
    parser.add_argument("--start", default=START_DATE.isoformat(), help="first report date (YYYY-MM-DD)")
    parser.add_argument("--end", default=END_DATE.isoformat(), help="last report date (YYYY-MM-DD)")
    parser.add_argument("--output", default=str(OUTPUT_CSV))
    parser.add_argument("--summary", default=str(OUTPUT_SUMMARY))
    parser.add_argument("--status", default=str(OUTPUT_STATUS))
    args = parser.parse_args()

    df, status = build_dataset(date.fromisoformat(args.start), date.fromisoformat(args.end))
    status.to_csv(args.status, index=False)
    logger.info(f"Day status saved to: {args.status}  ({len(status)} rows)")
    if df.empty:
        logger.error("Empty dataset. Check the connection or the date range.")
        raise SystemExit(1)
    df.to_csv(args.output, index=False)
    logger.info(f"Dataset saved to: {args.output}  ({len(df)} rows)")
    summary = build_summary(df)
    summary.to_csv(args.summary, index=False)
    logger.info(f"Daily summary saved to: {args.summary}  ({len(summary)} rows)")
    print_report(df, status)
