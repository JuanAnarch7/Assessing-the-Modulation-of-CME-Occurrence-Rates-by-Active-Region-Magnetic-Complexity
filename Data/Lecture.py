"""
=============================================================================
Lecture.py — Read and clean the SOHO/LASCO CDAW CME catalog
=============================================================================
Input : CDAW text catalog (univ_all-style .txt), one CME per line:
        Date Time CPA Width V_lin V2_init V2_final V2_20R Accel Mass KE MPA Remarks
Output:
  1. datos_procesados_<tag>.csv        event-level table (one row per CME)
  2. lasco_gaps_<tag>.csv              observing gaps detected from the catalog
  3. lasco_monthly_coverage_<tag>.csv  fraction of each month covered by data

Fixes with respect to the previous version
  - Remarks are read in full (previously only the first word was kept, so
    "Very Poor Event" became "Very").
  - Values flagged with '*' (uncertain acceleration / mass / energy) are kept
    as numbers, with a boolean flag, instead of being turned into NaN.
  - Halo CMEs ("Halo" in the CPA column) get CPA = NaN plus is_halo = True.
  - Malformed lines are reported, not silently dropped.
  - Date and time are combined into a single timestamp column `t`.
  - Second-order speeds equal to 0 (not computable in CDAW) are set to NaN.
  - Observing gaps: an interval between consecutive CMEs is flagged as a
    data gap when observing no CME for that long is improbable under the
    local CME rate (Poisson, p < GAP_P). The local rate is measured in the
    ±RATE_WINDOW days around the interval, excluding the interval itself.
    Months then get a coverage fraction; the monthly builder should set CME
    counts to NaN where coverage < MIN_COVERAGE and normalise the rest by
    coverage (snippet at the end).

Column names of the event table keep the legacy Spanish names used by
master_dataset_builder.py (Fecha, Hora, Central, Ancho, Rapidez, ...); new
columns are in English. They will be unified in the pipeline refactor.

Usage:
    python Lecture.py --input Soho_Lasco_2026_02_28.txt --tag 2026_02_28
=============================================================================
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

GAP_P = 1e-6          # flag an empty interval if P(no CME | local rate) < GAP_P
                      # (strict: CMEs are clustered, so short lulls are commoner than Poisson)
GAP_MIN_DAYS = 3.0    # never flag intervals shorter than this
RATE_WINDOW = 30.0    # days on each side used to estimate the local rate
MIN_COVERAGE = 0.5    # monthly builder: NaN below this; coverage-normalise above it

DATE_RE = re.compile(r"^\s*(\d{4}/\d{2}/\d{2})\s+(\d{2}:\d{2}:\d{2})\s+(.*)$")
N_NUMERIC = 10        # CPA ... MPA, after date and time


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

def parse_value(tok: str) -> tuple[float, bool]:
    """'12.3*' -> (12.3, True); '----' or '*****' -> (nan, False); 'Halo' -> (nan, False)."""
    flagged = tok.endswith("*")
    core = tok.rstrip("*")
    if core == "" or set(core) <= {"-"} or core.lower() == "halo":
        return np.nan, False
    try:
        return float(core), flagged
    except ValueError:
        return np.nan, False


def parse_catalog(path: Path) -> tuple[pd.DataFrame, list[tuple[int, str]]]:
    rows, bad = [], []
    with open(path, encoding="latin-1") as fh:
        for ln, line in enumerate(fh, 1):
            m = DATE_RE.match(line)
            if not m:
                continue  # header or blank line
            date, time, rest = m.groups()
            toks = rest.split()
            if len(toks) < N_NUMERIC:
                bad.append((ln, line.rstrip()))
                continue
            vals = [parse_value(t) for t in toks[:N_NUMERIC]]
            rows.append({
                "Fecha": date.replace("/", "-"), "Hora": time,
                "Central": vals[0][0], "Ancho": vals[1][0], "Rapidez": vals[2][0],
                "Col4": vals[3][0], "Col5": vals[4][0], "Col6": vals[5][0],
                "Aceleracion": vals[6][0], "Masa": vals[7][0], "Energia": vals[8][0],
                "MPA": vals[9][0], "Comentarios": " ".join(toks[N_NUMERIC:]),
                "is_halo": toks[0].lower() == "halo",
                "accel_uncertain": vals[6][1],
                "mass_uncertain": vals[7][1] or vals[8][1],
            })
    df = pd.DataFrame(rows)
    # 2nd-order speeds (initial, final, at 20 Rsun): CDAW writes 0 when not computable
    df[["Col4", "Col5", "Col6"]] = df[["Col4", "Col5", "Col6"]].replace(0, np.nan)
    df["t"] = pd.to_datetime(df["Fecha"] + " " + df["Hora"], errors="coerce")
    low = df["Comentarios"].str.lower()
    df["quality"] = np.select(
        [low.str.contains("very poor"), low.str.contains("poor")],
        ["very_poor", "poor"], default="normal")
    df["only_c2"] = low.str.contains("only c2")
    return df.sort_values("t").reset_index(drop=True), bad


# ---------------------------------------------------------------------------
# Observing gaps and monthly coverage
# ---------------------------------------------------------------------------

def detect_gaps(t: pd.Series) -> pd.DataFrame:
    """Flag empty intervals that are improbable under the local Poisson rate."""
    ts = t.dropna().sort_values().to_numpy()
    days = (ts - ts[0]) / np.timedelta64(1, "D")
    dt = np.diff(days)
    rows = []
    for i in np.where(dt >= GAP_MIN_DAYS)[0]:
        a, b = days[i], days[i + 1]
        lo, hi = a - RATE_WINDOW, b + RATE_WINDOW
        n_in = np.sum((days >= lo) & (days <= a)) + np.sum((days >= b) & (days <= hi))
        span = (a - max(lo, days[0])) + (min(hi, days[-1]) - b)
        rate = n_in / span if span > 0 else np.nan
        p = float(np.exp(-rate * dt[i])) if np.isfinite(rate) else np.nan
        if p < GAP_P:
            rows.append(dict(start=pd.Timestamp(ts[i]), end=pd.Timestamp(ts[i + 1]),
                             days=dt[i], local_rate_per_day=rate, p_no_cme=p))
    return pd.DataFrame(rows, columns=["start", "end", "days", "local_rate_per_day", "p_no_cme"])


def monthly_coverage(gaps: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    out = []
    for m in pd.period_range(start, end, freq="M"):
        m0, m1 = m.start_time, m.end_time + pd.Timedelta(seconds=1)
        total = (m1 - m0) / pd.Timedelta(days=1)
        lost = sum(max((min(m1, g.end) - max(m0, g.start)) / pd.Timedelta(days=1), 0.0)
                   for g in gaps.itertuples())
        out.append(dict(yearmonth=str(m), coverage=1 - lost / total, gap_days=lost))
    return pd.DataFrame(out)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    ap = argparse.ArgumentParser(description="Read and clean the CDAW CME catalog")
    ap.add_argument("--input", required=True, help="CDAW .txt catalog")
    ap.add_argument("--tag", default="2026_02_28", help="suffix for output files")
    ap.add_argument("--outdir", default=".")
    a = ap.parse_args()
    out = Path(a.outdir); out.mkdir(parents=True, exist_ok=True)

    df, bad = parse_catalog(Path(a.input))
    gaps = detect_gaps(df["t"])
    first, last = df["t"].min(), df["t"].max()
    cov = monthly_coverage(gaps, f"{first.year}-01", last.strftime("%Y-%m"))

    df.to_csv(out / f"datos_procesados_{a.tag}.csv", index=False)
    gaps.to_csv(out / f"lasco_gaps_{a.tag}.csv", index=False, float_format="%.4g")
    cov.to_csv(out / f"lasco_monthly_coverage_{a.tag}.csv", index=False, float_format="%.4f")

    # ---- Report: check these numbers before committing ----
    print(f"Events parsed: {len(df)}   ({first} -> {last})")
    print(f"Malformed lines: {len(bad)}")
    for ln, txt in bad[:10]:
        print(f"  line {ln}: {txt}")
    print(f"Halo (CPA = 'Halo'): {df.is_halo.sum()}   width = 360: {(df.Ancho == 360).sum()}")
    print("Quality:", df["quality"].value_counts().to_dict())
    print(f"Speed missing: {df.Rapidez.isna().sum()}   accel uncertain (*): {df.accel_uncertain.sum()}"
          f"   mass/KE uncertain (*): {df.mass_uncertain.sum()}")
    print(f"\nObserving gaps detected (p < {GAP_P}): {len(gaps)}")
    if len(gaps):
        print(gaps.to_string(index=False))
    low = cov[cov.coverage < MIN_COVERAGE]
    print(f"\nMonths with coverage < {MIN_COVERAGE}: {len(low)}")
    if len(low):
        print(low.to_string(index=False))


if __name__ == "__main__":
    main()


# ---------------------------------------------------------------------------
# Snippet for master_dataset_builder.py (after the monthly CME counts):
#
#   cov = pd.read_csv("lasco_monthly_coverage_2026_02_28.csv")
#   master = master.merge(cov, on="yearmonth", how="left")
#   cme_cols = [c for c in master.columns if c.startswith("count_cmes_")]
#   master["coverage"] = master["coverage"].fillna(1.0)
#   master.loc[master["coverage"] < 0.5, cme_cols] = np.nan        # SOHO outages
#   # keep raw counts for count models (use log(coverage) as offset) and add
#   # coverage-normalised counts for correlations:
#   for c in cme_cols:
#       master[c + "_norm"] = master[c] / master["coverage"]
#   # sensitivity check: repeat the analysis with a 0.8 threshold
# ---------------------------------------------------------------------------
