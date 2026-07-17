"""
=============================================================================
NOAA Solar Region Summary (SRS) - Mount Wilson Classification
=============================================================================
Download the daily SRS files from NOAA/SWPC and extract the
Mount Wilson magnetic classification for each active region to construct a time series.

Data source:
  https://www.ngdc.noaa.gov/stp/space-weather/swpc-products/daily_reports/solar_region_summaries/

Columns in the resulting dataset:
  date          - Report date (YYYY-MM-DD)
  noaa_number   - NOAA active region number
  location      - Heliographic position (e.g., N14E23)
  lo            - Carrington longitude
  area          - Area in millionths of the solar disk
  z_class       - Modified Zurich classification (McIntosh)
  ll            - Longitudinal extent (degrees)
  nn            - Number of sunspots
  mag_type      - Mount Wilson magnetic classification (α, β, βγ, βγδ, etc.)
  complexity    - Numerical complexity value (see below)

Mount Wilson complexity scale (ordinal, from lowest to highest):
  α    → 1
  β    → 2
  βδ   → 3
  βγ   → 4
  γ    → 4
  γδ   → 5
  βγδ  → 5

=============================================================================
"""

import os
import re
import time
import logging
import requests
import pandas as pd
from datetime import date, timedelta
from pathlib import Path
from tqdm import tqdm

# ---------------------------------------------------------------------------
# Configuración
# ---------------------------------------------------------------------------

BASE_URL = (
    "https://www.ngdc.noaa.gov/stp/space-weather/swpc-products/"
    "daily_reports/solar_region_summaries"
)

# Range of Dates of Interest 
START_DATE = date(2010, 1, 1)
END_DATE   = date(2010, 2, 28)

# Directory where the downloaded .txt files will be saved
CACHE_DIR  = Path("srs_cache")

# Output Files
OUTPUT_CSV     = Path("mount_wilson_dataset.csv")
OUTPUT_SUMMARY = Path("mount_wilson_summary.csv")

# Pause between requests (seconds)
REQUEST_DELAY = 0.3

# Retry Attempts in Case of an HTTP Error
MAX_RETRIES = 3

# ---------------------------------------------------------------------------
# Mount Wilson Magnetic Complexity Scale
# ---------------------------------------------------------------------------

COMPLEXITY_MAP = {
    "alpha":          1,
    "alfa":           1,
    "α":              1,
    "a":              1,

    "beta":           2,
    "β":              2,
    "b":              2,

    "beta-delta":     3,
    "betadelta":      3,
    "βδ":             3,
    "bd":             3,

    "gamma":          4,
    "γ":              4,
    "g":              4,

    "beta-gamma":     4,
    "betagamma":      4,
    "βγ":             4,
    "bg":             4,

    "gamma-delta":    5,
    "gammadelta":     5,
    "γδ":             5,
    "gd":             5,

    "beta-gamma-delta":  5,
    "betagammadelta":    5,
    "βγδ":               5,
    "bgd":               5,
}

def normalize_mag_type(raw: str) -> tuple[str, int | None]:
    """
    Normalizes the raw magnetic type from the SRS to the standard format
    and returns (normalized_type, complexity_value).

    The SRS reports types such as: ‘Alpha’, ‘Beta’, ‘Beta-Gamma’, 'Beta-Gamma-Delta'
    
    """
    if not raw or pd.isna(raw):
        return ("Unknown", None)

    cleaned = raw.strip().lower().replace(" ", "-")

    # Normalización canónica
    canonical = {
        "alpha":              ("α",   1),
        "alfa":               ("α",   1),
        "beta":               ("β",   2),
        "beta-delta":         ("βδ",  3),
        "gamma":              ("γ",   4),
        "beta-gamma":         ("βγ",  4),
        "gamma-delta":        ("γδ",  5),
        "beta-gamma-delta":   ("βγδ", 5),
    }

    if cleaned in canonical:
        return canonical[cleaned]

    # Intentar coincidencia parcial
    for key, val in canonical.items():
        if key in cleaned:
            return val

    return (raw.strip(), None)


# ---------------------------------------------------------------------------
# Downloading SRS Files
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def build_url(d: date) -> str:
    """Builds the SRS file URL for a given date."""
    return f"{BASE_URL}/{d.year}/{d.month:02d}/{d.strftime('%Y%m%d')}SRS.txt"


def download_srs(d: date, session: requests.Session) -> str | None:
    """
    Download the NOAA SRS file for date `d`.
    Use the local cache to avoid re-downloads.
    Return the content as text, or `None` if it does not exist or the download fails.
    """
    cache_path = CACHE_DIR / str(d.year) / f"{d.strftime('%Y%m%d')}SRS.txt"

    
    if cache_path.exists():
        return cache_path.read_text(encoding="utf-8", errors="replace")

    url = build_url(d)
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            resp = session.get(url, timeout=30)
            if resp.status_code == 200:
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                cache_path.write_bytes(resp.content)
                return resp.text
            elif resp.status_code == 404:
                return None   
            else:
                logger.warning(f"{d}: HTTP {resp.status_code} (intento {attempt})")
        except requests.RequestException as e:
            logger.warning(f"{d}: Error de red: {e} (intento {attempt})")
            time.sleep(2 ** attempt)

    return None

# ---------------------------------------------------------------------------
# Parsing SRS Files
# ---------------------------------------------------------------------------

def parse_srs(text: str, report_date: date) -> list[dict]:
    """
    Parse the text of an SRS file and extract the regions from Section I
    (Regions with Sunspots) along with their Mount Wilson classification.

    Data line format (fixed columns):
      Nmbr  Location  Lo    Area    Z    LL   NN   Mag Type
      4415  S18W46    015   0040    Hsx  02   01   Alpha
    """
    records = []

    # Search section I: Regions with Sunspots
    in_section = False
    header_seen = False

    for line in text.splitlines():
        line = line.strip()

        # Detect the start of Section I
        if re.match(r"^I\.\s+Regions with Sunspots", line, re.IGNORECASE):
            in_section = True
            continue

        # Detect the end of the section I ( any line thah begins with  I o II o IA)
        if in_section and re.match(r"^(IA?|II)\.", line, re.IGNORECASE):
            break

        if not in_section:
            continue

        # Avoid heading line
        if re.match(r"^Nmbr", line, re.IGNORECASE):
            header_seen = True
            continue

        if not header_seen:
            continue

        # Intentar parsear línea de datos
        # Ejemplo: 3615 S13W14 215 0810 Fkc 16 54 Beta-Gamma-Delta
        m = re.match(
            r"^(\d{3,5})\s+"          # Número NOAA
            r"([NS]\d{2}[EW]\d{2,3})\s+"  # Ubicación
            r"(\d{1,3})\s+"           # Longitud Carrington
            r"(\d{1,5})\s+"           # Area
            r"(\S+)\s+"               # Clasificación Z (McIntosh)
            r"(\d{1,3})\s+"           # LL
            r"(\d{1,3})\s+"           # NN
            r"(.+)$",                 # Tipo magnético (Mount Wilson)
            line
        )
        if m:
            raw_mag = m.group(8).strip()
            norm_mag, complexity = normalize_mag_type(raw_mag)

            records.append({
                "date":         report_date.isoformat(),
                "noaa_number":  int(m.group(1)),
                "location":     m.group(2),
                "lo":           int(m.group(3)),
                "area":         int(m.group(4)),
                "z_class":      m.group(5),
                "ll":           int(m.group(6)),
                "nn":           int(m.group(7)),
                "mag_type_raw": raw_mag,
                "mag_type":     norm_mag,
                "complexity":   complexity,
            })

    return records


# ---------------------------------------------------------------------------
# Main Pipeline 
# ---------------------------------------------------------------------------

def generate_date_range(start: date, end: date) -> list[date]:
    
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


def build_dataset(start: date = START_DATE, end: date = END_DATE) -> pd.DataFrame:
    """
    Download and parse all SRS files between “start” and “end.”
    Returns a DataFrame containing all records.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    dates = generate_date_range(start, end)

    all_records = []
    missing_days = 0

    session = requests.Session()
    session.headers.update({"User-Agent": "SolarResearchBot/1.0 (educational use)"})

    logger.info(f"Processing {len(dates)} días ({start} → {end})")

    for d in tqdm(dates, desc="Downloading SRS", unit="day"):
        text = download_srs(d, session)
        if text is None:
            missing_days += 1
        else:
            records = parse_srs(text, d)
            all_records.extend(records)
        time.sleep(REQUEST_DELAY)

    logger.info(f"Days with no data: {missing_days} / {len(dates)}")
    logger.info(f"Total Records for Active Regions: {len(all_records)}")

    if not all_records:
        logger.warning("No se encontraron registros. Verifica la conexión o el rango de fechas.")
        return pd.DataFrame()

    df = pd.DataFrame(all_records)
    df["date"] = pd.to_datetime(df["date"])
    df.sort_values(["date", "noaa_number"], inplace=True)
    df.reset_index(drop=True, inplace=True)

    return df


def build_summary(df: pd.DataFrame) -> pd.DataFrame:
    """
    Create a daily summary: number of active regions,
    maximum and average complexity per day.
    """
    if df.empty:
        return pd.DataFrame()

    summary = (
        df.groupby("date")
        .agg(
            n_active_regions=("noaa_number", "count"),
            max_complexity=("complexity", "max"),
            mean_complexity=("complexity", "mean"),
            n_beta_gamma_delta=("mag_type", lambda x: (x == "βγδ").sum()),
            n_beta_gamma=("mag_type", lambda x: (x == "βγ").sum()),
            n_gamma_delta=("mag_type", lambda x: (x == "γδ").sum()),
            n_complex_gt3=(   # Regiones con complejidad > 3
                "complexity",
                lambda x: (pd.to_numeric(x, errors="coerce") > 3).sum()
            ),
        )
        .reset_index()
    )
    return summary

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        description="Download NOAA SRS data and build Mount Wilson classification dataset"
    )
    parser.add_argument(
        "--start", default=START_DATE.isoformat(),
        help=f"Start date (YYYY-MM-DD), default: {START_DATE}"
    )
    parser.add_argument(
        "--end", default=END_DATE.isoformat(),
        help=f"End date (YYYY-MM-DD), default: {END_DATE}"
    )
    parser.add_argument(
        "--output", default=str(OUTPUT_CSV),
        help=f"Output CSV path, default: {OUTPUT_CSV}"
    )
    parser.add_argument(
        "--summary", default=str(OUTPUT_SUMMARY),
        help=f"Daily summary CSV path, default: {OUTPUT_SUMMARY}"
    )
    args = parser.parse_args()
    start_date = date.fromisoformat(args.start)
    end_date   = date.fromisoformat(args.end)
    # ---- Build full dataset ----
    df = build_dataset(start_date, end_date)
    if df.empty:
        logger.error("Empty dataset. Aborting.")
        exit(1)
    # ---- Save full dataset ----
    output_path = Path(args.output)
    df.to_csv(output_path, index=False)
    logger.info(f"Dataset saved to: {output_path}  ({len(df)} rows)")
    # ---- Build and save daily summary ----
    summary = build_summary(df)
    summary_path = Path(args.summary)
    summary.to_csv(summary_path, index=False)
    logger.info(f"Daily summary saved to: {summary_path}  ({len(summary)} rows)")
    # ---- Quick statistics ----
    print("\n" + "="*60)
    print("DATASET STATISTICS")
    print("="*60)
    print(f"  Period:               {df['date'].min().date()} → {df['date'].max().date()}")
    print(f"  Days with data:       {df['date'].nunique()}")
    print(f"  Unique regions:       {df['noaa_number'].nunique()}")
    print(f"  Total records:        {len(df)}")
    print()
    print("  Mount Wilson type distribution:")
    dist = df["mag_type"].value_counts()
    for t, n in dist.items():
        print(f"    {t:12s}: {n:6d}  ({100*n/len(df):.1f}%)")
    print()
    print("  Complexity distribution:")
    comp_dist = df["complexity"].value_counts().sort_index()
    labels = {1: "α", 2: "β", 3: "βδ", 4: "βγ/γ", 5: "βγδ/γδ"}
    for c, n in comp_dist.items():
        print(f"    {c} ({labels.get(c,'?'):8s}): {n:6d}  ({100*n/len(df):.1f}%)")
    print("="*60)



