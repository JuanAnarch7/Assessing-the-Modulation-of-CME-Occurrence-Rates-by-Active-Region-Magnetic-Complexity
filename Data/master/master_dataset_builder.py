"""
=============================================================================
Master Dataset Builder — monthly CME, active-region, flare and sunspot data
=============================================================================
Joins the outputs of the four source folders of Data/ into one monthly table:

  ../cme/datos_procesados_TAG.csv            CME events (CDAW)
  ../cme/lasco_monthly_coverage_TAG.csv      LASCO observing coverage per month
  ../active_regions/ar_features_monthly.csv  active-region features (SRS)
  ../flares/flares_monthly.csv               flare features (SWPC GOES list)
  ../sunspot_number/SN_m_tot_V2.0.csv        SILSO monthly sunspot number

Outputs (this folder)
  master_monthly.csv          one row per calendar month
  master_monthly_columns.csv  data dictionary: column, source, unit, description

Processing
  1. CME monthly counts by angular width, linear speed and the combined
     "filtered" criterion (same definitions as the previous master), plus
     narrow CMEs (< 20°). Each count is also given for CMEs of normal CDAW
     quality only (suffix `_hq`, excluding "Poor" and "Very Poor" events).
  2. LASCO coverage. Months with coverage < MIN_COVERAGE get NaN in every CME
     count (no observations). For the other months, `*_norm` = count / coverage
     corrects partially observed months; raw counts are kept for count models
     (use log(coverage) as offset).
  3. Sunspot number, provisional flag, 13-month smoothed sunspot number (SN13,
     SILSO formula), solar cycle number from the SN13 minima, and two
     solar-cycle phase definitions: the hand-set limits of the previous
     analysis (`phase_repo`) and an objective one from SN13 (`phase_sn13`:
     maximum = first..last month with SN13 >= SN13_MAX_FRACTION × cycle maximum).
  4. Active-region and flare features are merged as produced by their builders.
  5. END_MONTH = last month covered by all sources (CDAW, SRS, flares, SILSO),
     unless given with --end.
  6. Quality flags and diagnostics.

Usage
  python master_dataset_builder.py [--cme-tag 2026_07_31] [--start 1996-01] [--end YYYY-MM]
=============================================================================
"""

from __future__ import annotations

import argparse
import csv
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
DATA = HERE.parent

DEFAULT_CME_TAG = "2026_07_31"
START_MONTH = "1996-01"
MIN_COVERAGE = 0.5          # LASCO coverage below this -> CME counts NaN
SN13_MAX_FRACTION = 0.8     # maximum phase: SN13 >= 0.8 × cycle maximum

# CME filtered subpopulation (as in the previous master)
MIN_SPEED, MIN_WIDTH, MAX_WIDTH = 750, 120, 360

# Hand-set phase limits used by the previous analysis scripts
PHASES_REPO = [("23", "rising", "1996-08", "1999-12"), ("23", "maximum", "2000-01", "2002-12"),
               ("23", "declining", "2003-01", "2008-12"), ("24", "rising", "2009-01", "2011-11"),
               ("24", "maximum", "2011-12", "2014-11"), ("24", "declining", "2014-12", "2019-12"),
               ("25", "rising", "2020-01", "2022-12"), ("25", "maximum", "2023-01", "2025-12")]

CME_SUBPOPS = {   # name: (description, mask function on the event table)
    "all":          ("All CMEs", lambda w, v: pd.Series(True, index=w.index)),
    "narrow":       ("Width < 20°", lambda w, v: w < 20),
    "normal":       ("Width 20°–120°", lambda w, v: (w >= 20) & (w <= 120)),
    "partial_halo": ("Width > 120° and < 360°", lambda w, v: (w > 120) & (w < 360)),
    "halo":         ("Width = 360° (full halo)", lambda w, v: w == 360),
    "slow":         ("Linear speed 0–600 km/s", lambda w, v: (v >= 0) & (v < 600)),
    "moderate":     ("Linear speed 600–1000 km/s", lambda w, v: (v >= 600) & (v < 1000)),
    "fast":         ("Linear speed 1000–1500 km/s", lambda w, v: (v >= 1000) & (v < 1500)),
    "extreme":      ("Linear speed ≥ 1500 km/s", lambda w, v: v >= 1500),
    "filtered":     (f"Speed ≥ {MIN_SPEED} km/s and width {MIN_WIDTH}°–{MAX_WIDTH}°",
                     lambda w, v: (v >= MIN_SPEED) & (w >= MIN_WIDTH) & (w <= MAX_WIDTH)),
}


def months(start: str, end: str) -> pd.Index:
    return pd.period_range(start, end, freq="M").astype(str)


def smooth13(s: pd.Series) -> pd.Series:
    """SILSO 13-month running mean (half weights at both ends)."""
    w = np.r_[0.5, np.ones(11), 0.5] / 12.0
    return s.rolling(13, center=True).apply(lambda v: np.dot(v, w), raw=True)


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------

def load_cme(tag: str, idx: pd.Index, log: dict) -> pd.DataFrame:
    ev = pd.read_csv(DATA / "cme" / f"datos_procesados_{tag}.csv", parse_dates=["t"], low_memory=False)
    ev["yearmonth"] = ev["t"].dt.to_period("M").astype(str)
    w, v = ev["Ancho"].astype(float), ev["Rapidez"].astype(float)
    hq = ev["quality"].eq("normal")
    cols = {}
    for name, (_, fn) in CME_SUBPOPS.items():
        mask = fn(w, v).fillna(False)
        cols[f"count_cmes_{name}"] = ev[mask].groupby("yearmonth").size()
        cols[f"count_cmes_{name}_hq"] = ev[mask & hq].groupby("yearmonth").size()
    out = pd.DataFrame(cols).reindex(idx).fillna(0)
    cov = pd.read_csv(DATA / "cme" / f"lasco_monthly_coverage_{tag}.csv").set_index("yearmonth")
    out["lasco_coverage"] = cov["coverage"].reindex(idx)
    out["lasco_gap_days"] = cov["gap_days"].reindex(idx)
    last = ev["t"].max()
    full_last = last.to_period("M") if last.day >= last.days_in_month - 1 else last.to_period("M") - 1
    log["cme_events"] = len(ev)
    log["cme_last_complete_month"] = str(full_last)
    return out


def apply_coverage(df: pd.DataFrame, log: dict) -> pd.DataFrame:
    df = df.copy()
    count_cols = [c for c in df.columns if c.startswith("count_cmes_")]
    df["lasco_coverage"] = df["lasco_coverage"].fillna(1.0)
    no_obs = df["lasco_coverage"] < MIN_COVERAGE
    df.loc[no_obs, count_cols] = np.nan
    for c in count_cols:
        df[c + "_norm"] = df[c] / df["lasco_coverage"]
    log["months_without_lasco"] = df.index[no_obs].tolist()
    log["months_partial_lasco"] = df.index[(~no_obs) & (df["lasco_coverage"] < 1)].tolist()
    return df


def load_sunspots(idx: pd.Index, log: dict) -> pd.DataFrame:
    folder = DATA / "sunspot_number"
    path = next((p for p in [folder / "SN_m_tot_V2.0.csv", folder / "SN_m_tot_V2.0.txt"] if p.exists()), None)
    if path is None:
        raise FileNotFoundError(f"No SILSO file (SN_m_tot_V2.0.csv/.txt) in {folder}")
    sep = ";" if path.suffix == ".csv" else r"\s+"
    sn = pd.read_csv(path, sep=sep, header=None, engine="python",
                     names=["year", "month", "decimal", "sn", "sd", "nobs", "definitive"])
    sn["yearmonth"] = sn["year"].astype(int).astype(str) + "-" + sn["month"].astype(int).astype(str).str.zfill(2)
    sn["sn"] = sn["sn"].where(sn["sn"] >= 0)
    sn = sn.set_index("yearmonth")
    sn["sn13"] = smooth13(sn["sn"])          # on the full series, so the window is complete at 1996
    log["silso_file"] = path.name
    log["silso_last_month"] = sn.index[-1]
    log["silso_provisional"] = sn.index[sn["definitive"] == 0].tolist()
    out = pd.DataFrame({
        "sunspot_number": sn["sn"],
        "sunspot_number_sd": sn["sd"].where(sn["sd"] >= 0),
        "sunspot_provisional": sn["definitive"].eq(0),
        "sn13": sn["sn13"],
    }).reindex(idx)
    return out, sn


def cycle_and_phases(df: pd.DataFrame, sn_full: pd.DataFrame, log: dict) -> pd.DataFrame:
    s = sn_full["sn13"].dropna()
    s = s[s.index >= "1994-01"]
    windows = {"23": ("1995-01", "1998-12"), "24": ("2007-06", "2010-06"), "25": ("2018-06", "2021-06")}
    # SN13 is given to 0.1; when the minimum value repeats (1996-05 and 1996-08 both 11.2),
    # take the last month at the minimum, as SILSO dates the start of cycle 23 to 1996-08
    minima = {}
    for c, (a, b) in windows.items():
        seg = s[a:b]
        minima[c] = seg[seg <= seg.min() + 0.05].index.max()
    log["sn13_minima"] = minima
    ym = df.index.to_series()
    cyc = pd.Series("22", index=df.index)
    for c, m in minima.items():
        cyc[ym >= m] = c
    df["solar_cycle"] = cyc.astype(int)

    # objective phases from SN13
    ph = pd.Series("", index=df.index, dtype=object)
    order = list(minima)
    maxima = {}
    for i, c in enumerate(order):
        a = minima[c]
        b = minima[order[i + 1]] if i + 1 < len(order) else s.index[-1]
        seg = s[a:b]
        hi = seg[seg >= SN13_MAX_FRACTION * seg.max()]
        m0, m1 = hi.index.min(), hi.index.max()
        maxima[c] = (seg.idxmax(), round(float(seg.max()), 1), m0, m1)
        in_cycle = df["solar_cycle"].astype(str) == c
        ph[in_cycle & (ym < m0)] = "rising"
        ph[in_cycle & (ym >= m0) & (ym <= m1)] = "maximum"
        # declining only once SN13 has dropped below the threshold after the maximum
        ph[in_cycle & (ym > m1) & (m1 < s.index[-1])] = "declining"
    ph[df["solar_cycle"] == 22] = "declining"
    log["sn13_maxima"] = maxima
    df["phase_sn13"] = ph.replace("", np.nan)

    rep = pd.Series(np.nan, index=df.index, dtype=object)
    for c, name, a, b in PHASES_REPO:
        rep[(ym >= a) & (ym <= b)] = name
    df["phase_repo"] = rep
    return df


def load_csv(path: Path, idx: pd.Index, rename: dict | None = None) -> pd.DataFrame:
    d = pd.read_csv(path)
    d["yearmonth"] = d["yearmonth"].astype(str).str[:7]
    d = d.set_index("yearmonth").rename(columns=rename or {})
    return d.reindex(idx)


# ---------------------------------------------------------------------------
# Dictionary, flags, diagnostics
# ---------------------------------------------------------------------------

def dictionary(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for c in df.columns:
        if c == "yearmonth":
            rows.append((c, "—", "YYYY-MM", "Calendar month"))
            continue
        if c.startswith("count_cmes_"):
            core = c[len("count_cmes_"):]
            norm = core.endswith("_norm"); core = core[:-5] if norm else core
            hq = core.endswith("_hq"); core = core[:-3] if hq else core
            desc = CME_SUBPOPS[core][0] + (", normal CDAW quality only" if hq else "")
            desc += (" — divided by LASCO coverage" if norm else " — monthly count") + f"; NaN if coverage < {MIN_COVERAGE}"
            rows.append((c, "cme", "CMEs per month", desc))
        elif c.startswith("lasco_"):
            rows.append((c, "cme", "fraction" if "coverage" in c else "days",
                         "LASCO observing coverage of the month" if "coverage" in c else "Days of the month in LASCO observing gaps"))
        elif c in ("sunspot_number", "sunspot_number_sd", "sunspot_provisional", "sn13"):
            d = {"sunspot_number": "SILSO monthly mean total sunspot number (v2.0)",
                 "sunspot_number_sd": "Standard deviation of the daily input values",
                 "sunspot_provisional": "True if SILSO marks the month as provisional",
                 "sn13": "13-month smoothed sunspot number (SILSO formula)"}[c]
            rows.append((c, "sunspot_number", "—", d))
        elif c in ("solar_cycle", "phase_sn13", "phase_repo"):
            d = {"solar_cycle": "Solar cycle number (boundaries at the SN13 minima)",
                 "phase_sn13": f"rising / maximum / declining; maximum = SN13 ≥ {SN13_MAX_FRACTION} × cycle maximum",
                 "phase_repo": "rising / maximum / declining, hand-set limits of the previous analysis"}[c]
            rows.append((c, "sunspot_number", "—", d))
        elif c.startswith("flag_"):
            rows.append((c, "master", "bool", FLAG_DESC[c]))
        elif c in AR_COLS:
            rows.append((c, "active_regions", *AR_DESC.get(_base(c), ("", "see active_regions/README.md"))))
        else:
            rows.append((c, "flares", *FLARE_DESC.get(_base(c), ("", "see flares/README.md"))))
    return pd.DataFrame(rows, columns=["column", "source", "unit", "description"])


def _base(c: str) -> str:
    for suf in ("_daily_mean",):
        if c.endswith(suf):
            return c[: -len(suf)] + "*"
    return c[:-3] + "W" if c[-3:] in ("w30", "w60") else (c[:-4] + "W" if c.endswith("w120") else c)


AR_DESC = {
    "srs_usable_days": ("days", "SRS reports usable in the month (parsed or 'None')"),
    "n_days": ("days", "Calendar days in the month"),
    "srs_coverage": ("fraction", "srs_usable_days / n_days"),
    "n_regions": ("regions", "Active regions observed in the month (region-months)"),
    "n_new_regions": ("regions", "Regions first observed in the month (unique regions)"),
    "n_high_complexity": ("regions", "Regions with peak Mount Wilson complexity ≥ 4 (βγ, γ, γδ, βγδ)"),
    "n_delta": ("regions", "Regions with a δ configuration in the month"),
    "n_long_lived": ("regions", "Regions visible ≥ 7 days"),
    "n_mid_lived": ("regions", "Regions visible 2–6 days"),
    "n_short_lived": ("regions", "Regions visible ≤ 1 day"),
    "area_sum": ("µHem × days", "Σ daily spot area"),
    "area_delta": ("µHem × days", "Σ daily area of δ regions"),
    "area_complex": ("µHem × days", "Σ daily area of regions with complexity ≥ 4"),
    "complexity_area_sum": ("µHem × days", "Φ_proxy = Σ daily complexity × area"),
    "area_center": ("µHem × days", "Σ daily area at |central-meridian distance| ≤ 45°"),
    "area_limb": ("µHem × days", "Σ daily area at |central-meridian distance| > 45°"),
    "area_sum*": ("µHem", "Mean daily spot area (area_sum / srs_usable_days)"),
    "area_delta*": ("µHem", "Mean daily area of δ regions"),
    "area_complex*": ("µHem", "Mean daily area of regions with complexity ≥ 4"),
    "complexity_area_sum*": ("µHem", "Mean daily Φ_proxy"),
    "area_center*": ("µHem", "Mean daily area at |lon| ≤ 45°"),
    "area_limb*": ("µHem", "Mean daily area at |lon| > 45°"),
    "frac_delta_area": ("fraction", "area_delta / area_sum"),
}
FLARE_DESC = {
    "n_flares_C": ("flares", "C-class flares (classic GOES scale)"),
    "n_flares_M": ("flares", "M-class flares (classic GOES scale)"),
    "n_flares_X": ("flares", "X-class flares (classic GOES scale)"),
    "n_flares_MX": ("flares", "M- and X-class flares"),
    "flare_index": ("C1 units", "Σ peak flux of flares ≥ C1 / 1e-6 W m⁻²"),
    "flare_index_MX": ("C1 units", "Σ peak flux of M and X flares / 1e-6 W m⁻²"),
    "max_flux_classic": ("W m⁻²", "Peak flux of the largest flare (classic scale)"),
    "n_MX_matched_region": ("flares", "M/X flares matched to an SRS region"),
    "n_MX_no_region": ("flares", "M/X flares without NOAA region in the SWPC list"),
    "n_MX_delta": ("flares", "M/X flares from δ regions"),
    "n_MX_high_complexity": ("flares", "M/X flares from regions with complexity ≥ 4"),
    "n_flaring_regions_MX": ("regions", "Regions producing at least one M/X flare"),
    "n_MX_limb": ("flares", "M/X flares at |lon| > 45°"),
    "n_MX_eruptive_W": ("flares", "M/X flares with a CME of width ≥ W° in [t_start − 30 min, + 120 min]"),
    "n_MX_chance_W": ("flares", "Expected chance flare–CME coincidences (width ≥ W°)"),
    "n_MX_assessed_W": ("flares", "M/X flares outside LASCO gaps (assessed for a CME)"),
    "frac_MX_delta": ("fraction", "n_MX_delta / n_MX_matched_region"),
    "frac_MX_no_region": ("fraction", "n_MX_no_region / n_flares_MX"),
    "goes_scale_published": ("—", "Scale of the published GOES classes (classic / true); all counts use the classic scale"),
}

FLAG_DESC = {
    "flag_no_lasco": f"LASCO coverage < {MIN_COVERAGE}: CME counts set to NaN",
    "flag_partial_lasco": f"LASCO coverage between {MIN_COVERAGE} and 1: use *_norm counts",
    "flag_srs_incomplete": "SRS coverage < 0.9 (missing daily reports); use *_daily_mean area features",
    "flag_sunspot_provisional": "SILSO value provisional",
    "flag_flare_region_gap": "More than half of the month's M/X flares have no NOAA region in the SWPC list",
}
AR_COLS: set = set()


def add_flags(df: pd.DataFrame) -> pd.DataFrame:
    df["flag_no_lasco"] = df["lasco_coverage"] < MIN_COVERAGE
    df["flag_partial_lasco"] = (df["lasco_coverage"] >= MIN_COVERAGE) & (df["lasco_coverage"] < 1)
    df["flag_srs_incomplete"] = df["srs_coverage"] < 0.9
    df["flag_sunspot_provisional"] = df["sunspot_provisional"].fillna(False).astype(bool)
    df["flag_flare_region_gap"] = (df["frac_MX_no_region"] > 0.5) & (df["n_flares_MX"] >= 3)
    return df


def diagnostics(df: pd.DataFrame, log: dict) -> None:
    print("=" * 70)
    print("MASTER DATASET REPORT")
    print("=" * 70)
    print(f"Months: {len(df)}  ({df.index[0]} -> {df.index[-1]})   columns: {df.shape[1]}")
    print(f"End month: {df.index[-1]}  (last complete month per source: {log['ends']})")
    print(f"CME events read: {log['cme_events']}")
    print(f"Months without LASCO observations (CME counts NaN): {log['months_without_lasco']}")
    print(f"Partially observed months (use *_norm): {len(log['months_partial_lasco'])}")
    print(f"SILSO file: {log['silso_file']}; provisional months in range: "
          f"{[m for m in log['silso_provisional'] if m <= df.index[-1]]}")
    print(f"SN13 minima: {log['sn13_minima']}")
    print("SN13 maxima (month, value, maximum-phase start, end):")
    for c, v in log["sn13_maxima"].items():
        print(f"  cycle {c}: {v}")
    print("Phases (phase_sn13) per cycle, months:")
    print(pd.crosstab(df["solar_cycle"], df["phase_sn13"]).to_string())
    print("\nChecks:")
    w = df[["count_cmes_narrow", "count_cmes_normal", "count_cmes_partial_halo", "count_cmes_halo"]].sum(1)
    ok = df["count_cmes_all"].isna() | (w <= df["count_cmes_all"])
    print(f"  width classes (narrow + normal + partial halo + halo) <= all CMEs: {'OK' if ok.all() else 'FAIL'}")
    s = df["n_long_lived"] + df["n_mid_lived"] + df["n_short_lived"]
    print(f"  persistence classes sum to n_regions: {'OK' if (s == df['n_regions']).all() else 'FAIL'}")
    hq = (df["count_cmes_all_hq"] <= df["count_cmes_all"]) | df["count_cmes_all"].isna()
    print(f"  high-quality counts <= all counts: {'OK' if hq.all() else 'FAIL'}")
    print("\nFlags (months):", {k: int(df[k].sum()) for k in FLAG_DESC})
    nan = df.isna().sum()
    print("\nColumns with NaN (months):")
    print(nan[nan > 0].sort_values(ascending=False).head(15).to_string())
    print("=" * 70)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Build the monthly master dataset")
    ap.add_argument("--cme-tag", default=DEFAULT_CME_TAG)
    ap.add_argument("--start", default=START_MONTH)
    ap.add_argument("--end", default=None, help="last month YYYY-MM (default: last month covered by all sources)")
    ap.add_argument("--outdir", default=str(HERE))
    a = ap.parse_args()
    log: dict = {}

    ar_path = DATA / "active_regions" / "ar_features_monthly.csv"
    fl_path = DATA / "flares" / "flares_monthly.csv"
    ar_raw = pd.read_csv(ar_path)
    fl_raw = pd.read_csv(fl_path)
    wide = months(a.start, "2100-12")
    _, sn_full = load_sunspots(wide[:1], log)
    cme_probe = pd.read_csv(DATA / "cme" / f"datos_procesados_{a.cme_tag}.csv", usecols=["t"], parse_dates=["t"])
    last = cme_probe["t"].max()
    cme_end = str(last.to_period("M") if last.day >= last.days_in_month - 1 else last.to_period("M") - 1)
    ar_ok = ar_raw[ar_raw["n_usable_days"] > 0]["yearmonth"].max()
    log["ends"] = {"cme": cme_end, "active_regions": ar_ok, "flares": fl_raw["yearmonth"].max(),
                   "sunspot_number": sn_full.index[-1]}
    end = a.end or min(log["ends"].values())
    idx = months(a.start, end)

    cme = apply_coverage(load_cme(a.cme_tag, idx, log), log)
    sn, sn_full = load_sunspots(idx, log)
    ar = load_csv(ar_path, idx, rename={"n_usable_days": "srs_usable_days", "n_days": "n_days"})
    fl = load_csv(fl_path, idx, rename={"scale_published": "goes_scale_published"})
    AR_COLS.update(ar.columns)

    master = pd.concat([sn, cme, ar, fl], axis=1)
    master.index.name = "yearmonth"
    master = cycle_and_phases(master, sn_full, log)
    master = add_flags(master)

    lead = ["sunspot_number", "sn13", "solar_cycle", "phase_sn13", "phase_repo"]
    master = master[lead + [c for c in master.columns if c not in lead]]
    out = Path(a.outdir)
    master.reset_index().to_csv(out / "master_monthly.csv", index=False, float_format="%.4f",
                                quoting=csv.QUOTE_MINIMAL)
    dictionary(master.reset_index()).to_csv(out / "master_monthly_columns.csv", index=False)
    diagnostics(master, log)
    print(f"Saved {out / 'master_monthly.csv'} ({len(master)} rows x {master.shape[1] + 1} columns) "
          f"and master_monthly_columns.csv")


if __name__ == "__main__":
    main()
