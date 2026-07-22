"""
correlacion_matriz_fases_ciclos.py
=================================
Genera matrices de correlación de Spearman entre variables de actividad solar/AR
(y filas) y subpoblaciones de CME (columnas) para fases específicas de los ciclos solares.

Periodos incluidos:
- Ciclo solar 23
  - ascenso: 1996-08 a 1999-12
  - maximo: 2000-01 a 2002-12
  - descenso: 2003-01 a 2008-12
- Ciclo solar 24
  - ascenso: 2009-01 a 2011-11
  - maximo: 2011-12 a 2014-11
  - descenso: 2014-12 a 2019-12
- Ciclo solar 25
  - ascenso: 2020-01 a 2022-12
  - maximo: 2023-01 a 2025-12

Salidas:
- CSV por periodo en correlation_matrices_fases/
- Heatmaps PNG por periodo
"""

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from scipy.stats import spearmanr


BASE_DIR = Path(__file__).resolve().parent
CSV_PATH = BASE_DIR / "master_monthly.csv"
OUT_DIR = BASE_DIR / "correlation_matrices_fases"
OUT_DIR.mkdir(exist_ok=True)

# Reproducibilidad y bootstrap
SEED = 42
N_BOOT = 2000
BLOCK_LEN = 12
CI_ALPHA = 0.95

# Periodos de análisis por fase de ciclo solar
PERIODS = [
    ("CS23_ascenso", "1996-08", "1999-12"),
    ("CS23_maximo", "2000-01", "2002-12"),
    ("CS23_descenso", "2003-01", "2008-12"),
    ("CS24_ascenso", "2009-01", "2011-11"),
    ("CS24_maximo", "2011-12", "2014-11"),
    ("CS24_descenso", "2014-12", "2019-12"),
    ("CS25_ascenso", "2020-01", "2022-12"),
    ("CS25_maximo", "2023-01", "2025-12"),
]

VARIABLES = [
    ("n_total", r"$N_{AR}$"),
    ("n_high_complexity", r"$N_{\beta\gamma\delta}$"),
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

VARIABLE_LABELS = {var_name: label for var_name, label in VARIABLES}
SUBPOPULATION_LABELS = {sub_name: label for sub_name, label in SUBPOPULATIONS}

COMPOSITE_LAYOUT = {
    "CS23_ascenso": (0, 0),
    "CS23_maximo": (0, 1),
    "CS23_descenso": (0, 2),
    "CS24_ascenso": (1, 0),
    "CS24_maximo": (1, 1),
    "CS24_descenso": (1, 2),
    "CS25_ascenso": (2, 0),
    "CS25_maximo": (2, 1),
}
ROW_LABELS = {0: "Cycle 23", 1: "Cycle 24", 2: "Cycle 25"}
COL_LABELS = {0: "Rising", 1: "Maximum", 2: "Declining"}


def load_data(path: Path) -> pd.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"No se encontró el archivo: {path}")

    df = pd.read_csv(path)
    if "yearmonth" not in df.columns:
        raise KeyError("La columna 'yearmonth' no existe en master_monthly.csv")

    df = df.copy()
    df["yearmonth"] = df["yearmonth"].astype(str).str[:7]
    df["yearmonth_dt"] = pd.to_datetime(df["yearmonth"], format="%Y-%m")
    return df


def _pair_seed(period_name: str, var_name: str, sub_name: str) -> int:
    key = f"{SEED}|{period_name}|{var_name}|{sub_name}".encode("utf-8")
    return int(__import__("hashlib").sha256(key).hexdigest(), 16) % (2**31)


def block_bootstrap_ci(x: np.ndarray, y: np.ndarray, period_name: str, var_name: str, sub_name: str) -> tuple[float, float]:
    n = len(x)
    if n < 1:
        return np.nan, np.nan

    rng = np.random.default_rng(_pair_seed(period_name, var_name, sub_name))
    n_blocks = int(np.ceil(n / BLOCK_LEN))
    start_max = max(1, n - BLOCK_LEN + 1)
    starts = np.arange(start_max)
    boot_rhos = np.empty(N_BOOT)

    for i in range(N_BOOT):
        idx_starts = rng.choice(starts, size=n_blocks, replace=True)
        idx = np.concatenate([np.arange(s, s + BLOCK_LEN) for s in idx_starts])[:n]
        rho, _ = spearmanr(x[idx], y[idx])
        boot_rhos[i] = rho

    lo = np.nanpercentile(boot_rhos, (1 - CI_ALPHA) / 2 * 100)
    hi = np.nanpercentile(boot_rhos, (1 + CI_ALPHA) / 2 * 100)
    return float(lo), float(hi)


def build_correlation_matrix(df: pd.DataFrame, period_name: str, start: str, end: str) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    start_dt = pd.Timestamp(start)
    end_dt = pd.Timestamp(end)

    period_df = df[(df["yearmonth_dt"] >= start_dt) & (df["yearmonth_dt"] <= end_dt)].copy()

    rho_matrix = pd.DataFrame(
        index=[var for var, _ in VARIABLES],
        columns=[sub for sub, _ in SUBPOPULATIONS],
        dtype=float,
    )
    rho_matrix.index.name = "variable"
    rho_matrix.columns.name = "subpoblacion"

    p_matrix = rho_matrix.copy()
    ci_lo_matrix = rho_matrix.copy()
    ci_hi_matrix = rho_matrix.copy()

    missing_cols = []
    for var_name, _ in VARIABLES:
        if var_name not in period_df.columns:
            missing_cols.append(var_name)

    for sub_name, _ in SUBPOPULATIONS:
        if sub_name not in period_df.columns:
            missing_cols.append(sub_name)

    if missing_cols:
        missing_cols = sorted(set(missing_cols))
        print(f"[warn] {period_name}: columnas faltantes -> {missing_cols}")

    for var_name, _ in VARIABLES:
        for sub_name, _ in SUBPOPULATIONS:
            if var_name not in period_df.columns or sub_name not in period_df.columns:
                rho_matrix.loc[var_name, sub_name] = np.nan
                p_matrix.loc[var_name, sub_name] = np.nan
                ci_lo_matrix.loc[var_name, sub_name] = np.nan
                ci_hi_matrix.loc[var_name, sub_name] = np.nan
                continue

            valid = period_df[[var_name, sub_name]].dropna()
            if len(valid) < 3:
                rho_val = np.nan
                p_val = np.nan
                ci_lo = np.nan
                ci_hi = np.nan
            else:
                x = valid[var_name].astype(float).to_numpy()
                y = valid[sub_name].astype(float).to_numpy()
                rho_val, p_val = spearmanr(x, y)
                ci_lo, ci_hi = block_bootstrap_ci(x, y, period_name, var_name, sub_name)

            rho_matrix.loc[var_name, sub_name] = rho_val
            p_matrix.loc[var_name, sub_name] = p_val
            ci_lo_matrix.loc[var_name, sub_name] = ci_lo
            ci_hi_matrix.loc[var_name, sub_name] = ci_hi

    return rho_matrix, p_matrix, ci_lo_matrix, ci_hi_matrix


def plot_correlation_matrix(matrix: pd.DataFrame, period_name: str, show_labels: bool = False) -> None:
    fig, ax = plt.subplots(figsize=(12.6, 7.2))
    fig.patch.set_facecolor("white")

    subpop_order = [sub_name for sub_name, _ in SUBPOPULATIONS]
    subpop_labels = [SUBPOPULATION_LABELS.get(sub_name, sub_name) for sub_name in subpop_order]
    data = matrix.copy().reindex(columns=subpop_order).astype(float)
    cmap = plt.cm.coolwarm

    img = ax.imshow(data, cmap=cmap, vmin=-1, vmax=1)

    if show_labels:
        #ax.set_xlabel("CME Subpopulation")
        #ax.set_ylabel("Ar features")
        #ax.set_xticks(np.arange(len(data.columns)))
        #ax.set_xticklabels(subpop_labels, rotation=0, ha="center", fontsize=22)
        ax.set_yticks(np.arange(len(data.index)))
        ax.set_yticklabels([VARIABLE_LABELS.get(var_name, var_name) for var_name in data.index], fontsize=22)
    else:
        ax.set_xticks([])
        ax.set_yticks([])

    for i in range(data.shape[0]):
        for j in range(data.shape[1]):
            value = data.iloc[i, j]
            if np.isnan(value):
                text = "NaN"
                color = "black"
            else:
                text = f"{value:.3f}"
                color = "white" if abs(value) > 0.6 else "black"
            ax.text(j, i, text, ha="center", va="center", fontsize=12, color=color)

    #if show_labels:
        #cbar = fig.colorbar(img, ax=ax, fraction=0.046, pad=0.04)
        #cbar.set_label("ρ de Spearman")

    plt.tight_layout()
    out_path = OUT_DIR / f"{period_name}_heatmap.png"
    fig.savefig(out_path, dpi=600, bbox_inches="tight")
    plt.close(fig)
    print(f"Guardado: {out_path}")


def load_composite_matrix_from_csv(period_name: str) -> pd.DataFrame:
    csv_path = OUT_DIR / f"{period_name}.csv"
    if not csv_path.exists():
        raise FileNotFoundError(f"No se encontró el CSV para la figura compuesta: {csv_path}")

    df = pd.read_csv(csv_path, index_col=0)
    rho_cols = [col for col in df.columns if col.startswith("rho_")]
    if not rho_cols:
        raise ValueError(f"El archivo {csv_path} no contiene columnas rho_*")

    rho_df = df[rho_cols].copy()
    rho_df.columns = [col.replace("rho_", "", 1) for col in rho_df.columns]

    var_order = [var_name for var_name, _ in VARIABLES]
    subpop_order = [sub_name for sub_name, _ in SUBPOPULATIONS]
    return rho_df.reindex(index=var_order, columns=subpop_order).astype(float)


def save_composite_pdf(results: dict) -> None:
    fig, axes = plt.subplots(3, 3, figsize=(12, 8.5), squeeze=False)
    fig.patch.set_facecolor("white")

    cmap = plt.cm.coolwarm
    norm = plt.Normalize(vmin=-1, vmax=1)

    for period_name in results:
        if period_name not in COMPOSITE_LAYOUT:
            continue

        row, col = COMPOSITE_LAYOUT[period_name]
        ax = axes[row, col]
        data = load_composite_matrix_from_csv(period_name)

        im = ax.imshow(data.to_numpy(), cmap=cmap, norm=norm)
        ax.set_aspect("equal", adjustable="box")

        var_labels = [VARIABLE_LABELS.get(var_name, var_name) for var_name in data.index]
        subpop_labels = [SUBPOPULATION_LABELS.get(sub_name, sub_name) for sub_name in data.columns]

        ax.set_xticks(np.arange(len(data.columns)))
        ax.set_yticks(np.arange(len(data.index)))

        if row == axes.shape[0] - 1 or (row == 1 and col == 2):
            ax.set_xticklabels(subpop_labels, rotation=45, ha="right", fontsize=7)
        else:
            ax.set_xticklabels([])

        if col == 0:
            ax.set_yticklabels(var_labels, fontsize=7)
        else:
            ax.set_yticklabels([])

        ax.tick_params(axis="both", which="both", length=0)

        for i in range(data.shape[0]):
            for j in range(data.shape[1]):
                value = data.iloc[i, j]
                if np.isnan(value):
                    text = "NaN"
                    color = "black"
                else:
                    text = f"{value:.3f}"
                    color = "white" if abs(value) > 0.6 else "black"
                ax.text(j, i, text, ha="center", va="center", fontsize=5.5, color=color)

        for spine in ax.spines.values():
            spine.set_visible(False)

    empty_ax = axes[2, 2]
    empty_ax.axis("off")

    cbar_ax = fig.add_axes([0.92, 0.24, 0.02, 0.6])
    cbar = fig.colorbar(im, cax=cbar_ax)
    cbar.set_label("Spearman's ρ", fontsize=10)

    row_y_positions = [0.79 - row_idx * 0.26 for row_idx in ROW_LABELS.keys()]
    for row_idx, label in ROW_LABELS.items():
        y_pos = row_y_positions[row_idx] - 0.02
        fig.text(0.04, y_pos, label, rotation=90, ha="center", va="center", fontsize=11)

    col_x_positions = [0.20 + col_idx * 0.27 for col_idx in COL_LABELS.keys()]
    for col_idx, label in COL_LABELS.items():
        x_pos = col_x_positions[col_idx] + 0.01
        fig.text(x_pos, 0.91, label, ha="center", va="center", fontsize=11)

    fig.suptitle("Correlation matrices by phase and solar cycle", fontsize=14, y=0.96)
    fig.subplots_adjust(left=0.09, right=0.90, bottom=0.10, top=0.90, wspace=0.06, hspace=0.04)

    out_path = OUT_DIR / "composite_phase_matrices.pdf"
    fig.savefig(out_path, dpi=600, bbox_inches="tight")
    plt.close(fig)
    print(f"Guardado: {out_path}")


def save_outputs(results: dict) -> None:
    SHOW_LABELS = True

    for name, (rho_matrix, p_matrix, ci_lo_matrix, ci_hi_matrix) in results.items():
        combined = pd.concat(
            {"rho": rho_matrix, "p_value": p_matrix, "ci_lo": ci_lo_matrix, "ci_hi": ci_hi_matrix},
            axis=1,
        )
        combined.columns = [f"{stat}_{sub}" for stat, sub in combined.columns]
        csv_path = OUT_DIR / f"{name}.csv"
        combined.to_csv(csv_path)
        print(f"Guardado: {csv_path}")

    for name, (rho_matrix, _, _, _) in results.items():
        plot_correlation_matrix(rho_matrix, name, show_labels=SHOW_LABELS)

    save_composite_pdf(results)


def main() -> None:
    df = load_data(CSV_PATH)
    results = {}

    for period_name, start, end in PERIODS:
        print(f"\nProcesando {period_name} ({start} → {end})")
        rho_matrix, p_matrix, ci_lo_matrix, ci_hi_matrix = build_correlation_matrix(df, period_name, start, end)
        results[period_name] = (rho_matrix, p_matrix, ci_lo_matrix, ci_hi_matrix)
        print(rho_matrix.round(3))

    save_outputs(results)
    print(f"\nListo. Los archivos quedaron en: {OUT_DIR}")


if __name__ == "__main__":
    main()
