"""
=============================================================================
flares_builder.py — clean the SWPC GOES flare list and build flare features
=============================================================================
Inputs (default paths relative to Data/)
  flares/raw/flares_swpc_hek_raw.csv              SWPC flare list from the HEK
  active_regions/mount_wilson_dataset.csv          daily region records (SRS)
  cme/datos_procesados_TAG.csv                     CDAW CME events
  cme/lasco_gaps_TAG.csv                           LASCO observing gaps

Outputs (in Data/flares/)
  flare_events.csv     one row per flare: cleaned class on the classic GOES
                       scale, source region and its properties, CME association
  flares_monthly.csv   monthly flare features for the master dataset

Processing
  1. Classes. Parse `fl_goescls` (A/B/C/M/X + number). Rows without a valid
     class (missing, or 'SF' = optical subflare) are dropped and counted.
  2. Duplicates. The HEK holds the list twice for part of the period
     (ingestions 'SECstandard' and 'SWPC'). Rows with the same start and peak
     time are one flare; the kept row is the one with a valid class, a NOAA
     region, a real position and the newer ingestion, in that order.
  3. GOES scale. Classes from GOES-15 and earlier include the 0.7 SWPC
     scaling ("classic" scale); later ones are true fluxes. Comparison with
     the catalogue of Plutino et al. (2023) gives a ratio of 0.707 until
     2020-01 and ~1.0 from 2020-03-11, so classes from SCALE_CHANGE onward are
     multiplied by 0.7. `flux_classic` is used for all classes and counts;
     `flux_true` = flux_classic / 0.7.
  4. Positions. Heliographic (0, 0) is a placeholder for "unknown" in the
     list (72 % of rows) and is set to NaN.
  5. Source region. Flares with a NOAA number are matched to the SRS record
     of that region on the flare day or within ±MATCH_DAYS days (nearest
     day). The flare inherits area, Mount Wilson type, complexity, δ flag,
     McIntosh class, position and persistence of its region.
  6. CME association. A flare is eruptive at width threshold W if a CME
     with width ≥ W first appears in LASCO C2 within
     [t_start − 30 min, t_start + 120 min]. The CME recorded for the flare
     (time, speed, width, quality) is the widest one in that window (ties:
     the fastest), since flare positions are mostly unavailable. The chance probability of that
     coincidence is estimated by shifting the flare time by ±1…±5 days.
     Flares inside a LASCO observing gap get NaN.
  7. Monthly features, by month of the flare peak (see column list in the
     README).

Usage
  python flares_builder.py [--cme-tag 2026_07_31] [--start 1996-01] [--end 2026-07]
=============================================================================
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
DATA = HERE.parent

SCALE_CHANGE = pd.Timestamp("2020-03-01")   # first day with true-flux classes (see docstring)
CLASSIC_FACTOR = 0.7
MATCH_DAYS = 2
WIN_BEFORE = pd.Timedelta(minutes=30)
WIN_AFTER = pd.Timedelta(minutes=120)
SHIFT_DAYS = [-5, -4, -3, -2, -1, 1, 2, 3, 4, 5]
WIDTHS = (30, 60, 120)
STREAM_RANK = {"SWPC": 0, "SWPCstandard": 1, "SECstandard": 2}   # lower = preferred
CLASS_LETTER = {"A": 1e-8, "B": 1e-7, "C": 1e-6, "M": 1e-5, "X": 1e-4}


# ---------------------------------------------------------------------------
# 1–4: cleaning
# ---------------------------------------------------------------------------

def parse_class(c) -> float:
    m = re.match(r"^\s*([ABCMX])(\d+(?:\.\d*)?)\s*$", str(c))   # "X17." occurs for large flares
    return CLASS_LETTER[m.group(1)] * float(m.group(2)) if m else np.nan


def letter(flux: float) -> str:
    if not np.isfinite(flux):
        return ""
    for k, v in (("X", 1e-4), ("M", 1e-5), ("C", 1e-6), ("B", 1e-7)):
        if flux >= v:
            return k
    return "A"


def clean_flares(path: Path, log: dict) -> pd.DataFrame:
    f = pd.read_csv(path)
    log["raw_rows"] = len(f)
    f["flux_published"] = f["fl_goescls"].map(parse_class)
    f["stream"] = f["kb_archivid"].astype(str).str.extract(r"FL_([A-Za-z]+)_")[0]
    f["t_start"] = pd.to_datetime(f["event_starttime"])
    f["t_peak"] = pd.to_datetime(f["event_peaktime"])
    f["t_end"] = pd.to_datetime(f["event_endtime"])
    placeholder = (f["hgs_x"] == 0) & (f["hgs_y"] == 0)
    f["flare_lon"] = f["hgs_x"].where(~placeholder).astype(float)
    f["flare_lat"] = f["hgs_y"].where(~placeholder).astype(float)
    f["noaa_full"] = f["ar_noaanum"].where(f["ar_noaanum"] > 0)

    # duplicates: same start and peak time
    f["_rank"] = list(zip(f["flux_published"].isna(), f["noaa_full"].isna(),
                          f["flare_lon"].isna(), f["stream"].map(STREAM_RANK).fillna(9)))
    f = f.sort_values(["t_start", "t_peak", "_rank"])
    grp = f.groupby(["t_start", "t_peak"])
    n_cls = grp["flux_published"].transform(lambda s: s.dropna().nunique())
    log["duplicate_rows_removed"] = int(f.duplicated(["t_start", "t_peak"]).sum())
    log["duplicate_groups_with_different_class"] = int(
        (n_cls > 1)[~f.duplicated(["t_start", "t_peak"])].sum())
    f = f.drop_duplicates(["t_start", "t_peak"], keep="first").drop(columns="_rank")

    bad = f["flux_published"].isna()
    log["invalid_class_dropped"] = int(bad.sum())
    log["invalid_class_examples"] = f.loc[bad, "fl_goescls"].astype(str).value_counts().head(5).to_dict()
    f = f[~bad].copy()

    # scale homogenisation
    after = f["t_peak"] >= SCALE_CHANGE
    f["scale_published"] = np.where(after, "true", "classic")
    f["flux_classic"] = np.where(after, f["flux_published"] * CLASSIC_FACTOR, f["flux_published"])
    f["flux_true"] = f["flux_classic"] / CLASSIC_FACTOR
    f["class_classic"] = f["flux_classic"].map(letter)
    f["class_changed_by_rescaling"] = f["class_classic"] != f["fl_goescls"].astype(str).str[0]
    log["rows_after_scale_change"] = int(after.sum())
    return f.sort_values("t_peak").reset_index(drop=True)


# ---------------------------------------------------------------------------
# 5: source region
# ---------------------------------------------------------------------------

def attach_regions(f: pd.DataFrame, srs_path: Path, log: dict) -> pd.DataFrame:
    srs = pd.read_csv(srs_path, parse_dates=["date"])
    life = srs.groupby("noaa_full")["date"].agg(lambda x: (x.max() - x.min()).days + 1)
    srs["persistence_days"] = srs["noaa_full"].map(life)
    keep = ["noaa_full", "date", "area", "mag_type", "complexity", "is_delta", "z_class",
            "lat", "lon", "persistence_days"]
    srs = srs[keep]

    f = f.copy()
    f["flare_day"] = f["t_peak"].dt.normalize()
    cand = f[["noaa_full", "flare_day"]].reset_index().dropna(subset=["noaa_full"])
    cand["noaa_full"] = cand["noaa_full"].astype(int)
    m = cand.merge(srs, on="noaa_full", how="inner")
    m["dd"] = (m["date"] - m["flare_day"]).dt.days
    m = m[m["dd"].abs() <= MATCH_DAYS]
    # nearest day; on ties prefer the same day, then the previous day
    m["_k"] = m["dd"].abs() * 10 + (m["dd"] > 0)
    m = m.sort_values(["index", "_k"]).drop_duplicates("index")
    m = m.set_index("index")
    cols = ["area", "mag_type", "complexity", "is_delta", "z_class", "lat", "lon", "persistence_days", "dd"]
    for c in cols:
        f["ar_" + c] = m[c].reindex(f.index)
    f = f.rename(columns={"ar_dd": "ar_day_offset"})
    f["region_status"] = np.select(
        [f["noaa_full"].isna(), f["ar_area"].notna()],
        ["no_region", "matched"], default="region_not_in_srs")
    f["lon_best"] = f["flare_lon"].fillna(f["ar_lon"])
    log["region_status"] = f["region_status"].value_counts().to_dict()
    mx = f["class_classic"].isin(["M", "X"])
    log["region_status_MX"] = f.loc[mx, "region_status"].value_counts().to_dict()
    return f.drop(columns="flare_day")


# ---------------------------------------------------------------------------
# 6: CME association
# ---------------------------------------------------------------------------

def in_gap(t: pd.Series, gaps: pd.DataFrame) -> np.ndarray:
    out = np.zeros(len(t), dtype=bool)
    for g in gaps.itertuples():
        out |= ((t >= g.start) & (t <= g.end)).to_numpy()
    return out


def window_bounds(tf: np.ndarray, tc: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    lo = np.searchsorted(tc, tf - WIN_BEFORE.to_timedelta64(), side="left")
    hi = np.searchsorted(tc, tf + WIN_AFTER.to_timedelta64(), side="right")
    return lo, hi


def any_cme(tf: np.ndarray, tc: np.ndarray) -> np.ndarray:
    lo, hi = window_bounds(tf, tc)
    return hi > lo


def widest_cme(tf: np.ndarray, tc: np.ndarray, width: np.ndarray, speed: np.ndarray) -> np.ndarray:
    """Index of the widest CME in the window of each flare (ties: fastest), or -1."""
    lo, hi = window_bounds(tf, tc)
    out = np.full(len(tf), -1)
    key = width * 1e4 + np.nan_to_num(speed, nan=0.0)
    for i in np.where(hi > lo)[0]:
        out[i] = lo[i] + int(np.argmax(key[lo[i]:hi[i]]))
    return out


def attach_cmes(f: pd.DataFrame, cme_path: Path, gaps_path: Path, log: dict) -> pd.DataFrame:
    cme = pd.read_csv(cme_path, parse_dates=["t"]).sort_values("t").reset_index(drop=True)
    gaps = pd.read_csv(gaps_path, parse_dates=["start", "end"])
    f = f.copy()
    gap = in_gap(f["t_start"], gaps)
    tf = f["t_start"].to_numpy()
    for w in WIDTHS:
        sel = cme[cme["Ancho"] >= w].reset_index(drop=True)
        tc = sel["t"].to_numpy()
        er = any_cme(tf, tc).astype(float)
        chance = np.mean([any_cme(tf + np.timedelta64(k, "D"), tc) for k in SHIFT_DAYS], axis=0)
        er[gap] = np.nan
        chance[gap] = np.nan
        f[f"eruptive_w{w}"] = er
        f[f"chance_w{w}"] = chance
        if w == WIDTHS[0]:
            idx = widest_cme(tf, tc, sel["Ancho"].to_numpy(float), sel["Rapidez"].to_numpy(float))
            ok = idx >= 0
            f["cme_t"] = pd.NaT
            f.loc[ok, "cme_t"] = sel["t"].to_numpy()[idx[ok]]
            for src, dst in [("Rapidez", "cme_speed"), ("Ancho", "cme_width"), ("quality", "cme_quality")]:
                vals = np.full(len(f), np.nan, dtype=object)
                vals[ok] = sel[src].to_numpy()[idx[ok]]
                f[dst] = vals
            f.loc[gap, ["cme_speed", "cme_width", "cme_quality"]] = np.nan
    f["in_lasco_gap"] = gap
    log["flares_in_lasco_gaps"] = int(gap.sum())
    return f


# ---------------------------------------------------------------------------
# 7: monthly features
# ---------------------------------------------------------------------------

def monthly(f: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    f = f.copy()
    f["yearmonth"] = f["t_peak"].dt.to_period("M").astype(str)
    mx = f["class_classic"].isin(["M", "X"])
    big = f["flux_classic"] >= 1e-6
    g = f.groupby("yearmonth")
    gm = f[mx].groupby("yearmonth")
    out = pd.DataFrame({
        "n_flares_C": f[f.class_classic == "C"].groupby("yearmonth").size(),
        "n_flares_M": f[f.class_classic == "M"].groupby("yearmonth").size(),
        "n_flares_X": f[f.class_classic == "X"].groupby("yearmonth").size(),
        "flare_index": f[big].groupby("yearmonth")["flux_classic"].sum() / 1e-6,
        "flare_index_MX": gm["flux_classic"].sum() / 1e-6,
        "max_flux_classic": g["flux_classic"].max(),
        "n_MX_matched_region": gm["region_status"].apply(lambda s: int((s == "matched").sum())),
        "n_MX_no_region": gm["region_status"].apply(lambda s: int((s == "no_region").sum())),
        "n_MX_delta": gm["ar_is_delta"].apply(lambda s: int((s == True).sum())),  # noqa: E712
        "n_MX_high_complexity": gm["ar_complexity"].apply(lambda s: int((s >= 4).sum())),
        "n_flaring_regions_MX": gm["noaa_full"].nunique(),
        "n_MX_limb": gm["lon_best"].apply(lambda s: int((s.abs() > 45).sum())),
    })
    for w in WIDTHS:
        out[f"n_MX_eruptive_w{w}"] = gm[f"eruptive_w{w}"].sum(min_count=1)
        out[f"n_MX_chance_w{w}"] = gm[f"chance_w{w}"].sum(min_count=1)
        out[f"n_MX_assessed_w{w}"] = gm[f"eruptive_w{w}"].count()
    idx = pd.period_range(start, end, freq="M").astype(str)
    out = out.reindex(idx)
    count_cols = [c for c in out.columns if c.startswith("n_") or c.startswith("flare_index")]
    out[count_cols] = out[count_cols].fillna(0)
    out["n_flares_MX"] = out["n_flares_M"] + out["n_flares_X"]
    out["frac_MX_delta"] = out["n_MX_delta"] / out["n_MX_matched_region"].replace(0, np.nan)
    out["frac_MX_no_region"] = out["n_MX_no_region"] / out["n_flares_MX"].replace(0, np.nan)
    out["scale_published"] = np.where(pd.PeriodIndex(idx, freq="M").start_time >= SCALE_CHANGE, "true", "classic")
    out.index.name = "yearmonth"
    first = ["n_flares_C", "n_flares_M", "n_flares_X", "n_flares_MX", "flare_index", "flare_index_MX",
             "max_flux_classic"]
    return out[first + [c for c in out.columns if c not in first]].reset_index()


# ---------------------------------------------------------------------------
# Report and main
# ---------------------------------------------------------------------------

def report(f: pd.DataFrame, mon: pd.DataFrame, log: dict) -> None:
    print("=" * 66)
    print("FLARES BUILDER REPORT")
    print("=" * 66)
    print(f"Raw rows: {log['raw_rows']}")
    print(f"Duplicate rows removed: {log['duplicate_rows_removed']} "
          f"(groups whose copies differ in class: {log['duplicate_groups_with_different_class']})")
    print(f"Rows without a valid class dropped: {log['invalid_class_dropped']} {log['invalid_class_examples']}")
    print(f"Flares kept: {len(f)}  ({f.t_peak.min()} -> {f.t_peak.max()})")
    print(f"Published on the true-flux scale (from {SCALE_CHANGE.date()}), rescaled ×0.7: "
          f"{log['rows_after_scale_change']}; class letter changed: {int(f.class_changed_by_rescaling.sum())}")
    print("Flares by class (classic scale):", f["class_classic"].value_counts().reindex(list("ABCMX")).fillna(0).astype(int).to_dict())
    print("Source region, all flares:", log["region_status"])
    print("Source region, M/X flares:", log["region_status_MX"])
    m = f[f.region_status == "matched"]
    print(f"Matched day offset (flare day − SRS day): {m['ar_day_offset'].value_counts().sort_index().to_dict()}")
    print(f"Flares inside LASCO gaps (no CME assessment): {log['flares_in_lasco_gaps']}")
    print("\nValidation — chance-corrected eruptive fraction by class (W ≥ 60°):")
    bins = [1e-6, 1e-5, 2e-5, 5e-5, 1e-4, 1]
    labs = ["C", "M1-M2", "M2-M5", "M5-X1", ">=X1"]
    v = f.assign(b=pd.cut(f.flux_classic, bins, labels=labs, right=False)).dropna(subset=["b", "eruptive_w60"])
    t = v.groupby("b", observed=True).agg(n=("eruptive_w60", "size"), p_obs=("eruptive_w60", "mean"),
                                            p_chance=("chance_w60", "mean"))
    t["p_corrected"] = (t.p_obs - t.p_chance) / (1 - t.p_chance)
    print(t.round(3).to_string())
    print("\nM/X flares per year and fraction of δ source regions:")
    y = mon.assign(year=mon.yearmonth.str[:4]).groupby("year")[["n_flares_M", "n_flares_X", "n_MX_delta",
                                                                  "n_MX_matched_region"]].sum()
    y["frac_delta"] = (y.n_MX_delta / y.n_MX_matched_region).round(2)
    print(y.astype({"n_flares_M": int, "n_flares_X": int}).T.to_string())
    print("=" * 66)


def main():
    ap = argparse.ArgumentParser(description="Clean the SWPC flare list and build flare features")
    ap.add_argument("--flares", default=str(HERE / "raw" / "flares_swpc_hek_raw.csv"))
    ap.add_argument("--srs", default=str(DATA / "active_regions" / "mount_wilson_dataset.csv"))
    ap.add_argument("--cme-tag", default="2026_07_31")
    ap.add_argument("--start", default="1996-01")
    ap.add_argument("--end", default="2026-07")
    ap.add_argument("--outdir", default=str(HERE))
    a = ap.parse_args()
    out = Path(a.outdir)
    cme_path = DATA / "cme" / f"datos_procesados_{a.cme_tag}.csv"
    gaps_path = DATA / "cme" / f"lasco_gaps_{a.cme_tag}.csv"

    log: dict = {}
    f = clean_flares(Path(a.flares), log)
    f = f[(f.t_peak >= f"{a.start}-01") & (f.t_peak < pd.Period(a.end, freq="M").end_time)]
    f = attach_regions(f, Path(a.srs), log)
    f = attach_cmes(f, cme_path, gaps_path, log)
    mon = monthly(f, a.start, a.end)

    cols = ["t_start", "t_peak", "t_end", "fl_goescls", "scale_published", "flux_published", "flux_classic",
            "flux_true", "class_classic", "noaa_full", "region_status", "flare_lat", "flare_lon", "lon_best",
            "ar_day_offset", "ar_area", "ar_mag_type", "ar_complexity", "ar_is_delta", "ar_z_class", "ar_lat",
            "ar_lon", "ar_persistence_days", "in_lasco_gap"]
    cols += [c for w in WIDTHS for c in (f"eruptive_w{w}", f"chance_w{w}")]
    cols += ["cme_t", "cme_speed", "cme_width", "cme_quality", "stream", "kb_archivid"]
    f[cols].to_csv(out / "flare_events.csv", index=False, float_format="%.6g")
    mon.to_csv(out / "flares_monthly.csv", index=False, float_format="%.6g")
    report(f, mon, log)
    print(f"Saved {out / 'flare_events.csv'} ({len(f)} rows) and {out / 'flares_monthly.csv'} ({len(mon)} rows)")


if __name__ == "__main__":
    main()
