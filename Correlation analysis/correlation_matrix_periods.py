"""
correlation_matrix_periods.py
==============================
Generates Spearman correlation matrices between solar activity / Active Region
(AR) variables (rows) and CME subpopulations (columns) for broad analysis
periods (full period and each solar cycle).

Outputs:
- CSV per period in correlation_matrices/
- Heatmap PNGs per period
- Grouped bar chart summaries per period
- Optional consolidated Excel workbook (if openpyxl is available)
"""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import spearmanr


BASE_DIR = Path(__file__).resolve().parent
CSV_PATH = BASE_DIR / "master_monthly.csv"
OUT_DIR = BASE_DIR / "correlation_matrices"
OUT_DIR.mkdir(exist_ok=True)

# Analysis periods
PERIODS = {
    "full_period": ("1996-01", "2026-02"),
    "SC_23": ("1996-01", "2008-12"),
    "SC_24": ("2009-01", "2019-12"),
    "SC_25": ("2020-01", "2026-02"),
}

# Input variables (matrix rows)
VARIABLES = [
    ("n_total", "N active regions"),
    ("n_alta_complejidad", "N high complexity"),
    ("complexity_area_sum", "Area x complexity"),
    ("n_large", "N large"),
    ("n_small", "N medium"),
    ("n_ephemeral", "N ephemeral"),
]

# CME subpopulations (matrix columns)
SUBPOPULATIONS = [
    ("count_cmes_all", "All"),
    ("count_cmes_normal", "Normal"),
    ("count_cmes_partial_halo", "Partial Halo"),
    ("count_cmes_halo", "Halo"),
    ("count_cmes_slow", "Slow"),
    ("count_cmes_moderate", "Moderate"),
    ("count_cmes_fast", "Fast"),
    ("count_cmes_extreme", "Extreme"),
    ("count_cmes_filtered", "Filtered"),
]


def load_data(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    df = pd.read_csv(path)
    if "yearmonth" not in df.columns:
        raise KeyError("Column 'yearmonth' does not exist in master_monthly.csv")

    df = df.copy()
    df["yearmonth"] = df["yearmonth"].astype(str).str[:7]
    df["yearmonth_dt"] = pd.to_datetime(df["yearmonth"], format="%Y-%m")
    return df


def build_correlation_matrix(df: pd.DataFrame, period_name: str, start: str, end: str) -> pd.DataFrame:
    start_dt = pd.Timestamp(start)
    end_dt = pd.Timestamp(end)

    period_df = df[(df["yearmonth_dt"] >= start_dt) & (df["yearmonth_dt"] <= end_dt)].copy()

    matrix = pd.DataFrame(index=[var for var, _ in VARIABLES], columns=[sub for sub, _ in SUBPOPULATIONS], dtype=float)
    matrix.index.name = "variable"
    matrix.columns.name = "subpopulation"

    missing_cols = []
    for var_name, _ in VARIABLES:
        if var_name not in period_df.columns:
            missing_cols.append(var_name)

    for sub_name, _ in SUBPOPULATIONS:
        if sub_name not in period_df.columns:
            missing_cols.append(sub_name)

    if missing_cols:
        missing_cols = sorted(set(missing_cols))
        print(f"[warn] {period_name}: missing columns -> {missing_cols}")

    for var_name, _ in VARIABLES:
        for sub_name, _ in SUBPOPULATIONS:
            if var_name not in period_df.columns or sub_name not in period_df.columns:
                matrix.loc[var_name, sub_name] = np.nan
                continue

            valid = period_df[[var_name, sub_name]].dropna()
            if len(valid) < 3:
                corr = np.nan
            else:
                corr, _ = spearmanr(valid[var_name].to_numpy(), valid[sub_name].to_numpy())

            matrix.loc[var_name, sub_name] = corr

    return matrix


def plot_correlation_matrix(matrix: pd.DataFrame, period_name: str) -> None:
    fig, ax = plt.subplots(figsize=(12, 6.5))
    fig.patch.set_facecolor("white")

    subpop_order = [sub_name for sub_name, _ in SUBPOPULATIONS]
    subpop_labels = [label for _, label in SUBPOPULATIONS]
    data = matrix.copy().reindex(columns=subpop_order).astype(float)
    cmap = plt.cm.coolwarm

    img = ax.imshow(data, cmap=cmap, vmin=-1, vmax=1)
    ax.set_title(f"Spearman Correlation\n{period_name}", pad=10, fontsize=12)
    ax.set_xlabel("CME Subpopulations")
    ax.set_ylabel("Solar Activity / AR Variables")

    ax.set_xticks(np.arange(len(data.columns)))
    ax.set_xticklabels(subpop_labels, rotation=30, ha="right")
    ax.set_yticks(np.arange(len(data.index)))
    ax.set_yticklabels(data.index)

    for i in range(data.shape[0]):
        for j in range(data.shape[1]):
            value = data.iloc[i, j]
            if np.isnan(value):
                text = "NaN"
                color = "black"
            else:
                text = f"{value:.3f}"
                color = "white" if abs(value) > 0.6 else "black"
            ax.text(j, i, text, ha="center", va="center", fontsize=8, color=color)

    cbar = fig.colorbar(img, ax=ax, fraction=0.046, pad=0.04)
    cbar.set_label("Spearman's rho")

    plt.tight_layout()
    out_path = OUT_DIR / f"{period_name}_heatmap.png"
    fig.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out_path}")


def plot_bar_summary(matrices: dict) -> None:
    for period_name, matrix in matrices.items():
        fig, ax = plt.subplots(figsize=(12, 5.5))
        x = np.arange(len(matrix.columns))
        width = 0.8 / len(matrix.index)

        for i, row_name in enumerate(matrix.index):
            values = matrix.loc[row_name].astype(float).to_numpy()
            offset = (i - (len(matrix.index) - 1) / 2) * width
            ax.bar(x + offset, values, width=width, label=row_name)

        ax.set_title(f"Correlations by variable - {period_name}")
        ax.set_xticks(x)
        ax.set_xticklabels(matrix.columns, rotation=30, ha="right")
        ax.set_ylabel("Spearman's rho")
        ax.axhline(0, color="black", linewidth=0.8)
        ax.set_ylim(-1, 1)
        ax.legend(ncol=2, fontsize=8)
        plt.tight_layout()

        out_path = OUT_DIR / f"{period_name}_barplot.png"
        fig.savefig(out_path, dpi=300, bbox_inches="tight")
        plt.close(fig)
        print(f"Saved: {out_path}")


def save_outputs(matrices: dict) -> None:
    for name, matrix in matrices.items():
        csv_path = OUT_DIR / f"{name}.csv"
        matrix.to_csv(csv_path)
        print(f"Saved: {csv_path}")

    for name, matrix in matrices.items():
        plot_correlation_matrix(matrix, name)

    plot_bar_summary(matrices)

    # Optional: an Excel workbook with all sheets if openpyxl is available
    try:
        import openpyxl  # noqa: F401
    except ImportError:
        print("openpyxl is not installed; Excel file was skipped.")
    else:
        excel_path = OUT_DIR / "correlation_matrices_periods.xlsx"
        with pd.ExcelWriter(excel_path) as writer:
            for name, matrix in matrices.items():
                matrix.to_excel(writer, sheet_name=name[:31])
        print(f"Saved: {excel_path}")


def main() -> None:
    df = load_data(CSV_PATH)
    matrices = {}

    for period_name, (start, end) in PERIODS.items():
        print(f"\nProcessing {period_name} ({start} -> {end})")
        matrix = build_correlation_matrix(df, period_name, start, end)
        matrices[period_name] = matrix
        print(matrix.round(3))

    save_outputs(matrices)
    print(f"\nDone. Files are located in: {OUT_DIR}")


if __name__ == "__main__":
    main()
