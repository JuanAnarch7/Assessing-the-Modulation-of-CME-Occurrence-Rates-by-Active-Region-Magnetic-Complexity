"""
correlation_lag_variables.py
=============================
Computes Spearman correlations between solar activity / AR variables
(lagged 1 to 12 months) and CME subpopulations, for each phase of each
solar cycle.

Outputs:
- Long-format CSV with results per period, lag, variable, and subpopulation.
- CSVs per period and lag.
- Summary image showing how the correlation changes with lag within each
  cycle phase.
"""

from pathlib import Path

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import numpy as np
import pandas as pd
from scipy.stats import spearmanr


BASE_DIR = Path(__file__).resolve().parent
CSV_PATH = BASE_DIR / "master_monthly.csv"
OUT_DIR = BASE_DIR / "correlation_lag_outputs"
OUT_DIR.mkdir(exist_ok=True)

LAGS = range(1, 13)

PERIODS = [
    ("CS23_rising", "1996-08", "1999-12"),
    ("CS23_maximum", "2000-01", "2002-12"),
    ("CS23_declining", "2003-01", "2008-12"),
    ("CS24_rising", "2009-01", "2011-11"),
    ("CS24_maximum", "2011-12", "2014-11"),
    ("CS24_declining", "2014-12", "2019-12"),
    ("CS25_rising", "2020-01", "2022-12"),
    ("CS25_maximum", "2023-01", "2025-12"),
]

VARIABLES = [
    ("n_total", r"$N_{AR}$"),
    ("n_alta_complejidad", r"$N_{\beta\gamma\delta}$"),
    ("complexity_area_sum", r"$\Phi_{proxy}$"),
    ("n_large", r"$N_{L}$"),
    ("n_small", r"$N_{S}$"),
    ("n_ephemeral", r"$N_{E}$"),
]

SUBPOPULATIONS = [
    ("count_cmes_all", r"$\mathcal{C}_{all}$"),
    ("count_cmes_normal", r"$\mathcal{C}_{N}$"),
    ("count_cmes_partial_halo", r"$\mathcal{C}_{PH}$"),
    ("count_cmes_halo", r"$\mathcal{C}_{H}$"),
    ("count_cmes_slow", r"$\mathcal{C}_{slow}$"),
    ("count_cmes_moderate", r"$\mathcal{C}_{mod}$"),
    ("count_cmes_fast", r"$\mathcal{C}_{fast}$"),
    ("count_cmes_extreme", r"$\mathcal{C}_{ext}$"),
    ("count_cmes_filtered", r"$\mathcal{C}_{fil}$"),
]

# ---------------------------------------------------------------------------
# Global style (applied once when the module is imported)
# ---------------------------------------------------------------------------
plt.rcParams.update(
    {
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "axes.edgecolor": "#4d4d4d",
        "axes.labelcolor": "#222222",
        "axes.titlelocation": "left",
        "axes.titleweight": "bold",
        "axes.titlepad": 12,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "xtick.direction": "in",
        "ytick.direction": "in",
        "xtick.color": "#4d4d4d",
        "ytick.color": "#4d4d4d",
        "font.size": 10.5,
        "font.family": "DejaVu Sans",
        "legend.frameon": False,
        "savefig.facecolor": "white",
    }
)

MARKERS = ["o", "s", "^", "D", "P", "X"]
SERIES_COLORS = plt.cm.tab10(np.linspace(0, 1, len(VARIABLES)))


def load_data(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    df = pd.read_csv(path)
    if "yearmonth" not in df.columns:
        raise KeyError("Column 'yearmonth' does not exist in master_monthly.csv")

    df = df.copy()
    df["yearmonth"] = df["yearmonth"].astype(str).str[:7]
    df["yearmonth_dt"] = pd.to_datetime(df["yearmonth"], format="%Y-%m")
    df = df.sort_values("yearmonth_dt").reset_index(drop=True)
    return df


def compute_lagged_correlations_for_period(
    df: pd.DataFrame,
    period_name: str,
    start: str,
    end: str,
    lag: int,
) -> tuple[pd.DataFrame, list[dict]]:
    start_dt = pd.Timestamp(start)
    end_dt = pd.Timestamp(end)
    period_df = df[(df["yearmonth_dt"] >= start_dt) & (df["yearmonth_dt"] <= end_dt)].copy()

    matrix = pd.DataFrame(
        index=[var for var, _ in VARIABLES],
        columns=[sub for sub, _ in SUBPOPULATIONS],
        dtype=float,
    )
    matrix.index.name = "variable"
    matrix.columns.name = "subpopulation"

    rows: list[dict] = []

    for var_name, var_label in VARIABLES:
        if var_name not in period_df.columns:
            continue

        lagged_series = period_df[var_name].shift(lag)

        for sub_name, sub_label in SUBPOPULATIONS:
            if sub_name not in period_df.columns:
                continue

            valid = pd.DataFrame({"x": lagged_series, "y": period_df[sub_name]}).dropna()
            if len(valid) < 3:
                rho_val = np.nan
                p_val = np.nan
                n_valid = int(len(valid))
            else:
                try:
                    rho_val, p_val = spearmanr(
                        valid["x"].astype(float).to_numpy(),
                        valid["y"].astype(float).to_numpy(),
                    )
                except Exception:
                    rho_val = np.nan
                    p_val = np.nan
                n_valid = int(len(valid))

            matrix.loc[var_name, sub_name] = rho_val
            rows.append(
                {
                    "period": period_name,
                    "period_start": start,
                    "period_end": end,
                    "lag_months": lag,
                    "variable": var_name,
                    "variable_label": var_label,
                    "subpopulation": sub_name,
                    "subpopulation_label": sub_label,
                    "rho": float(rho_val) if not np.isnan(rho_val) else np.nan,
                    "p_value": float(p_val) if not np.isnan(p_val) else np.nan,
                    "n_valid": n_valid,
                }
            )

    return matrix, rows


def save_period_outputs(period_name: str, period_rows: list[dict], lag_matrices: dict[int, pd.DataFrame]) -> None:
    long_df = pd.DataFrame(period_rows)
    long_path = OUT_DIR / f"{period_name}_lagged_correlations.csv"
    long_df.to_csv(long_path, index=False)
    print(f"Saved: {long_path}")

    for lag, matrix in lag_matrices.items():
        out_path = OUT_DIR / f"{period_name}_lag_{lag:02d}.csv"
        matrix.to_csv(out_path)
        print(f"Saved: {out_path}")


def _draw_cell_grid(ax, n_rows: int, n_cols: int) -> None:
    """Draws thin white lines between cells of an imshow-based heatmap."""
    ax.set_xticks(np.arange(-0.5, n_cols, 1), minor=True)
    ax.set_yticks(np.arange(-0.5, n_rows, 1), minor=True)
    ax.grid(which="minor", color="white", linewidth=1.6)
    ax.tick_params(which="minor", bottom=False, left=False)


def _distribute_label_positions(values: list[float], min_sep: float, y_min: float, y_max: float) -> list[float]:
    """Pushes vertical label positions apart so they don't overlap,
    while preserving the relative order of the original values."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    positions = [0.0] * len(values)
    last = None
    for idx in order:
        v = values[idx]
        placed = v if last is None else max(v, last + min_sep)
        last = placed
        positions[idx] = placed

    # If pushing upward went out of range, compress from top to bottom.
    overflow = positions[order[-1]] - y_max
    if overflow > 0:
        for idx in order:
            positions[idx] -= overflow
        last = None
        for idx in order:
            v = positions[idx]
            placed = v if last is None else max(v, last + min_sep)
            last = placed
            positions[idx] = placed

    return [min(max(p, y_min), y_max) for p in positions]


def plot_variable_facets_heatmap(period_name: str, lag_matrices: dict[int, pd.DataFrame]) -> None:
    """Grid of mini-heatmaps, one per variable, showing subpopulation x lag
    without averaging any axis (all values are exact, straight from
    compute_lagged_correlations_for_period)."""
    if not lag_matrices:
        return

    lag_order = sorted(lag_matrices)
    sub_names = [s for s, _ in SUBPOPULATIONS]
    sub_labels = [lbl for _, lbl in SUBPOPULATIONS]
    n_subs = len(SUBPOPULATIONS)
    n_lags = len(lag_order)
    n_vars = len(VARIABLES)

    n_cols = 3
    n_rows_grid = int(np.ceil(n_vars / n_cols))

    fig, axes = plt.subplots(
        n_rows_grid, n_cols, figsize=(4.9 * n_cols, 3.3 * n_rows_grid), sharex=True, sharey=True
    )
    axes = np.atleast_2d(axes)
    #fig.suptitle(
    #    f"{period_name} - exact correlation by subpopulation and lag (not averaged)",
    #    fontsize=13.5,
    #    fontweight="bold",
    #    x=0.02,
    #    ha="left",
    #)

    cmap = plt.get_cmap("coolwarm").copy()
    cmap.set_bad("#e6e6e6")
    img = None

    for idx, (var_name, var_label) in enumerate(VARIABLES):
        ax = axes.flat[idx]
        mat = np.array(
            [[lag_matrices[lag].loc[var_name, sub] for lag in lag_order] for sub in sub_names],
            dtype=float,
        )
        masked = np.ma.masked_invalid(mat)
        img = ax.imshow(masked, cmap=cmap, vmin=-1, vmax=1, aspect="auto")
        ax.set_title(var_label, fontsize=12.5, loc="center")
        ax.set_xticks(range(n_lags))
        ax.set_xticklabels(lag_order, fontsize=7.5)
        ax.set_yticks(range(n_subs))
        ax.set_yticklabels(sub_labels, fontsize=8)
        _draw_cell_grid(ax, n_subs, n_lags)
        ax.tick_params(which="major", direction="in")

    # Hide extra axes if n_vars does not fully fill the grid.
    for extra_idx in range(n_vars, n_rows_grid * n_cols):
        axes.flat[extra_idx].axis("off")

    for col in range(n_cols):
        bottom_ax = axes[-1, col]
        if not bottom_ax.get_visible():
            # If the last row of that column ended up empty, use the previous visible row.
            for row in range(n_rows_grid - 1, -1, -1):
                if axes[row, col].get_visible():
                    axes[row, col].tick_params(labelbottom=True)
                    break

    fig.subplots_adjust(left=0.09, right=0.9, wspace=0.12, hspace=0.3, top=0.88, bottom=0.1)
    fig.text(0.5, 0.02, "Lag (months)", ha="center", va="center", fontsize=12)
    fig.text(0.02, 0.5, "Subpopulation", ha="center", va="center", fontsize=12, rotation="vertical")
    cax = fig.add_axes([0.925, 0.15, 0.014, 0.65])
    cbar = fig.colorbar(img, cax=cax)
    cbar.set_label("Correlation coefficient (rho)", fontsize=9.5)
    cbar.ax.tick_params(direction="in", length=3)

    out_path = OUT_DIR / f"{period_name}_variable_facets_heatmap.png"
    fig.savefig(out_path, dpi=600, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out_path}")


def plot_period_lag_summaries(period_name: str, lag_matrices: dict[int, pd.DataFrame]) -> None:
    if not lag_matrices:
        return

    first_matrix = next(iter(lag_matrices.values()))
    lag_order = sorted(lag_matrices)
    n_rows, n_cols = first_matrix.shape

    mean_array = np.stack([lag_matrices[lag].astype(float).to_numpy() for lag in lag_order], axis=0)
    mean_matrix = np.nanmean(mean_array, axis=0)
    mean_df = pd.DataFrame(mean_matrix, index=first_matrix.index, columns=first_matrix.columns)

    # Explicit layout: heatmap | colorbar | scatter, with its own axes
    # for each. This avoids the overlap caused by mixing constrained_layout
    # with tight_layout.
    fig = plt.figure(figsize=(18, 7.2))
    gs = fig.add_gridspec(1, 3, width_ratios=[1.0, 0.04, 1.35], wspace=0.55)
    ax0 = fig.add_subplot(gs[0, 0])
    cax = fig.add_subplot(gs[0, 1])
    ax1 = fig.add_subplot(gs[0, 2])

    # --- Left panel: mean correlation heatmap ---
    cmap = plt.get_cmap("coolwarm").copy()
    cmap.set_bad("#e6e6e6")
    masked = np.ma.masked_invalid(mean_df.to_numpy(dtype=float))
    img1 = ax0.imshow(masked, cmap=cmap, vmin=-1, vmax=1, aspect="auto")
    ax0.set_title(f"{period_name} - mean correlation matrix\nby lag (1-12 months)", fontsize=12)
    ax0.set_xlabel("CME Subpopulations")
    ax0.set_ylabel("Variables")
    ax0.set_xticks(np.arange(n_cols))
    ax0.set_xticklabels([label for _, label in SUBPOPULATIONS], rotation=35, ha="right")
    ax0.set_yticks(np.arange(n_rows))
    ax0.set_yticklabels([label for _, label in VARIABLES])
    _draw_cell_grid(ax0, n_rows, n_cols)

    for i in range(n_rows):
        for j in range(n_cols):
            value = mean_df.iloc[i, j]
            text = f"{value:.2f}" if not np.isnan(value) else "-"
            color = "white" if not np.isnan(value) and abs(value) > 0.6 else "#1a1a1a"
            ax0.text(j, i, text, ha="center", va="center", fontsize=8.3, color=color)

    cbar = fig.colorbar(img1, cax=cax)
    cbar.set_label("Correlation coefficient (rho)", fontsize=9.5)
    cbar.ax.tick_params(direction="in", length=3)

    # --- Right panel: scatter by lag with labels at the end of each series ---
    x_offsets = np.linspace(-0.15, 0.15, len(VARIABLES))
    end_targets = []  # (var_label, color, x_last, y_last)

    for idx, (var_name, var_label) in enumerate(VARIABLES):
        x_vals, y_vals = [], []
        for lag in lag_order:
            value = lag_matrices[lag].loc[var_name].mean()
            if not np.isnan(value):
                x_vals.append(lag + x_offsets[idx])
                y_vals.append(value)
        if not x_vals:
            continue
        ax1.plot(x_vals, y_vals, color=SERIES_COLORS[idx], linewidth=0.9, alpha=0.35, zorder=1)
        ax1.scatter(
            x_vals,
            y_vals,
            s=42,
            marker=MARKERS[idx % len(MARKERS)],
            color=SERIES_COLORS[idx],
            edgecolor="black",
            linewidth=0.5,
            alpha=0.9,
            zorder=2,
        )
        end_targets.append((var_label, SERIES_COLORS[idx], x_vals[-1], y_vals[-1]))

    ax1.axhline(0, color="#999999", linewidth=0.9, linestyle="--", zorder=0)
    for lag in lag_order[::2]:
        ax1.axvspan(lag - 0.5, lag + 0.5, color="#f2f2f2", zorder=0)

    #ax1.set_title(f"{period_name} - exact correlation by lag", fontsize=12)
    ax1.set_xlabel("Lag (months)")
    ax1.set_ylabel("Correlation value (rho)")
    max_lag = max(lag_order)
    label_x = max_lag + 1.0
    ax1.set_xticks(list(lag_order))
    ax1.set_xlim(min(lag_order) - 0.5, max_lag + 3.4)
    ax1.set_ylim(-1, 1)
    ax1.yaxis.set_minor_locator(mticker.MultipleLocator(0.25))
    ax1.tick_params(which="both", direction="in")
    ax1.grid(axis="y", alpha=0.25, zorder=0)

    # "Inline" labels: one per series, anchored to its last point,
    # with vertical positions spread out so they don't overlap.
    if end_targets:
        raw_y = [t[3] for t in end_targets]
        placed_y = _distribute_label_positions(raw_y, min_sep=0.09, y_min=-0.95, y_max=0.95)
        for (var_label, color, x_last, y_last), y_text in zip(end_targets, placed_y):
            ax1.plot([x_last, label_x - 0.15], [y_last, y_text], color=color, linewidth=0.7, alpha=0.6, zorder=1)
            ax1.text(
                label_x,
                y_text,
                var_label,
                color=color,
                fontsize=9.5,
                fontweight="bold",
                va="center",
                ha="left",
            )

    out_path = OUT_DIR / f"{period_name}_lag_summary.png"
    fig.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out_path}")


def plot_summary(summary_df: pd.DataFrame) -> None:
    pivot = summary_df.pivot(index="period", columns="lag", values="mean_abs_rho")
    pivot = pivot.reindex(index=[name for name, _, _ in PERIODS], columns=list(LAGS))
    n_rows, n_cols = pivot.shape

    fig = plt.figure(figsize=(13, 6.8))
    gs = fig.add_gridspec(1, 2, width_ratios=[1.0, 0.035], wspace=0.15)
    ax = fig.add_subplot(gs[0, 0])
    cax = fig.add_subplot(gs[0, 1])

    cmap = plt.get_cmap("coolwarm").copy()
    cmap.set_bad("#e6e6e6")
    masked = np.ma.masked_invalid(pivot.to_numpy(dtype=float))
    img = ax.imshow(masked, cmap=cmap, vmin=0, vmax=1, aspect="auto")
    #ax.set_title("Mean correlation magnitude by lag, per phase/cycle", fontsize=12.5)
    ax.set_xlabel("Lag (months)")
    ax.set_ylabel("Period")
    ax.set_xticks(np.arange(n_cols))
    ax.set_xticklabels(pivot.columns)
    ax.set_yticks(np.arange(n_rows))
    ax.set_yticklabels(pivot.index)
    _draw_cell_grid(ax, n_rows, n_cols)

    for i in range(n_rows):
        for j in range(n_cols):
            value = pivot.iloc[i, j]
            text = f"{value:.2f}" if not np.isnan(value) else "-"
            color = "white" if not np.isnan(value) and value > 0.6 else "#1a1a1a"
            ax.text(j, i, text, ha="center", va="center", fontsize=8.3, color=color)

    cbar = fig.colorbar(img, cax=cax)
    cbar.set_label("Mean |rho|", fontsize=9.5)
    cbar.ax.tick_params(direction="in", length=3)

    out_path = OUT_DIR / "period_lag_sensitivity_summary.png"
    fig.savefig(out_path, dpi=300, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved: {out_path}")


def main() -> None:
    df = load_data(CSV_PATH)
    print(f"Observations loaded: {len(df)}")

    all_rows: list[dict] = []
    summary_rows: list[dict] = []

    for period_name, start, end in PERIODS:
        print(f"\nProcessing {period_name} ({start} -> {end})")
        period_rows: list[dict] = []
        lag_matrices: dict[int, pd.DataFrame] = {}

        for lag in LAGS:
            matrix, rows = compute_lagged_correlations_for_period(df, period_name, start, end, lag)
            lag_matrices[lag] = matrix
            period_rows.extend(rows)

        save_period_outputs(period_name, period_rows, lag_matrices)
        plot_period_lag_summaries(period_name, lag_matrices)
        plot_variable_facets_heatmap(period_name, lag_matrices)
        all_rows.extend(period_rows)

        for lag in LAGS:
            lag_rows = [row for row in period_rows if row["lag_months"] == lag]
            if lag_rows:
                rho_values = [row["rho"] for row in lag_rows]
                summary_rows.append(
                    {
                        "period": period_name,
                        "lag": lag,
                        "mean_abs_rho": float(np.nanmean(np.abs(rho_values))),
                        "mean_rho": float(np.nanmean(rho_values)),
                    }
                )

    summary_df = pd.DataFrame(summary_rows)
    summary_path = OUT_DIR / "period_lag_summary.csv"
    summary_df.to_csv(summary_path, index=False)
    print(f"Saved: {summary_path}")

    all_df = pd.DataFrame(all_rows)
    all_path = OUT_DIR / "all_periods_lagged_correlations.csv"
    all_df.to_csv(all_path, index=False)
    print(f"Saved: {all_path}")

    plot_summary(summary_df)
    print(f"\nDone. Results are located in: {OUT_DIR}")


if __name__ == "__main__":
    main()
