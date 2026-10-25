"""
=============================================================================
download_flares_hek.py — NOAA/SWPC GOES flare list from the HEK (via SunPy)
=============================================================================
Queries the Heliophysics Events Knowledgebase (HEK) month by month for flare
events (event type FL) reported by NOAA/SWPC (FRM_NAME = 'SWPC'), i.e. the
GOES X-ray flare list with NOAA region numbers and, when available, flare
positions. Each month is cached, so the script can be interrupted and resumed;
months that failed are retried on the next run.

Outputs
  hek_cache/YYYY-MM.csv              one file per month (raw HEK columns kept; not versioned)
  raw/hek_download_status.csv        month, status (ok / empty / error), n_events
  raw/flares_swpc_hek_raw.csv        all months concatenated (input of flares_builder.py)

Requirements: pip install "sunpy[net]" pandas

Usage:
  python download_flares_hek.py --start 1996-01 --end 2026-07
  python download_flares_hek.py --start 1996-01 --end 2026-07 --retry-empty
=============================================================================
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent   # scripts read and write in their own folder by default
CACHE_DIR = HERE / "hek_cache"
STATUS_FILE = HERE / "raw" / "hek_download_status.csv"
OUTPUT_FILE = HERE / "raw" / "flares_swpc_hek_raw.csv"
MAX_RETRIES = 3

# HEK columns we try to keep (absent ones are skipped without error)
WANTED = [
    "event_starttime", "event_peaktime", "event_endtime",
    "fl_goescls", "fl_peakflux", "fl_peakfluxunit",
    "ar_noaanum",
    "hgs_x", "hgs_y", "hgc_x", "hgc_y", "hpc_x", "hpc_y",
    "frm_name", "frm_identifier", "frm_institute",
    "obs_observatory", "obs_instrument", "obs_channelid",
    "kb_archivid",
]


# ---------------------------------------------------------------------------
# Query
# ---------------------------------------------------------------------------

def query_month(t0: str, t1: str) -> pd.DataFrame:
    """HEK query for SWPC flares between t0 and t1 (ISO strings)."""
    from sunpy.net import Fido, attrs as a   # imported here so the rest is testable without sunpy

    res = Fido.search(a.Time(t0, t1), a.hek.EventType("FL"), a.hek.FRM.Name == "SWPC")
    tab = res["hek"]
    out = {}
    for col in WANTED:
        if col not in tab.colnames:
            continue
        values = tab[col]
        if hasattr(values, "isot"):            # astropy Time column
            out[col] = list(values.isot)
        else:
            out[col] = [None if (v is None or str(v) in ("--", "")) else v for v in list(values)]
    return pd.DataFrame(out)


def month_ranges(start: str, end: str) -> list[tuple[str, str, str]]:
    months = pd.period_range(start, end, freq="M")
    return [(str(m), m.start_time.strftime("%Y-%m-%dT00:00:00"),
             (m.end_time + pd.Timedelta(seconds=1)).strftime("%Y-%m-%dT00:00:00")) for m in months]


def download(start: str, end: str, retry_empty: bool = False, delay: float = 1.0,
             query=query_month) -> pd.DataFrame:
    CACHE_DIR.mkdir(exist_ok=True)
    STATUS_FILE.parent.mkdir(exist_ok=True)
    status = (pd.read_csv(STATUS_FILE, dtype=str).set_index("month")
              if STATUS_FILE.exists() else pd.DataFrame(columns=["status", "n_events"]).rename_axis("month"))
    for month, t0, t1 in month_ranges(start, end):
        cache = CACHE_DIR / f"{month}.csv"
        prev = status["status"].get(month) if len(status) else None
        if cache.exists() and prev == "ok":
            continue
        if cache.exists() and prev == "empty" and not retry_empty:
            continue
        for attempt in range(1, MAX_RETRIES + 1):
            try:
                df = query(t0, t1)
                df.to_csv(cache, index=False)
                status.loc[month, ["status", "n_events"]] = ["ok" if len(df) else "empty", str(len(df))]
                print(f"{month}: {len(df):5d} events")
                break
            except Exception as e:  # network or HEK error
                print(f"{month}: error (attempt {attempt}): {e}")
                status.loc[month, ["status", "n_events"]] = ["error", "0"]
                time.sleep(5 * attempt)
        status.sort_index().to_csv(STATUS_FILE)
        time.sleep(delay)

    files = [CACHE_DIR / f"{m}.csv" for m, _, _ in month_ranges(start, end)]
    frames = []
    for f in files:
        if f.exists() and f.stat().st_size > 0:
            try:
                frames.append(pd.read_csv(f))
            except pd.errors.EmptyDataError:
                pass
    raw = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return raw


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------

def report(raw: pd.DataFrame) -> None:
    print("\n" + "=" * 64)
    print("HEK / SWPC FLARE LIST — DOWNLOAD REPORT")
    print("=" * 64)
    st = pd.read_csv(STATUS_FILE) if STATUS_FILE.exists() else pd.DataFrame()
    if len(st):
        print("Months by status:", st["status"].value_counts().to_dict())
        bad = st[st.status != "ok"]["month"].tolist()
        if bad:
            print(f"Months not ok (re-run to retry; use --retry-empty for empty ones): {bad[:24]}"
                  + (" ..." if len(bad) > 24 else ""))
    if raw.empty:
        print("No events.")
        return
    t = pd.to_datetime(raw["event_peaktime"], errors="coerce")
    cls = raw["fl_goescls"].astype(str).str[:1].str.upper()
    print(f"Events: {len(raw)}   ({t.min()} -> {t.max()})")
    print("Columns kept:", list(raw.columns))
    tab = pd.crosstab(t.dt.year, cls)
    print("\nEvents per year and GOES class letter (check coverage and the scale change):")
    print(tab.to_string())
    if "ar_noaanum" in raw:
        ar = pd.to_numeric(raw["ar_noaanum"], errors="coerce")
        has = ar.notna() & (ar > 0)
        print(f"\nWith NOAA region number: {has.mean():.1%}   (M/X only: {has[cls.isin(['M', 'X'])].mean():.1%})")
    for c in ["obs_observatory", "obs_instrument", "obs_channelid", "frm_identifier"]:
        if c in raw:
            print(f"\n{c}: first year, last year and number of events per value")
            g = raw.assign(year=t.dt.year).groupby(c)["year"].agg(["min", "max", "size"])
            print(g.to_string())
    dup = raw.duplicated(subset=["event_peaktime", "fl_goescls"]).sum()
    print(f"\nDuplicated (peak time, class) pairs: {dup}")
    print("=" * 64)


def main():
    ap = argparse.ArgumentParser(description="Download the SWPC GOES flare list from the HEK")
    ap.add_argument("--start", default="1996-01", help="first month YYYY-MM")
    ap.add_argument("--end", default="2026-07", help="last month YYYY-MM")
    ap.add_argument("--retry-empty", action="store_true", help="re-query months that returned 0 events")
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between monthly queries")
    a = ap.parse_args()
    raw = download(a.start, a.end, a.retry_empty, a.delay)
    raw.to_csv(OUTPUT_FILE, index=False)
    print(f"\nSaved {OUTPUT_FILE} ({len(raw)} rows)")
    report(raw)


if __name__ == "__main__":
    main()
