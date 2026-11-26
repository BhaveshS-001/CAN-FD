#!/usr/bin/env python3
"""Illustrative data-center cooling control simulation.

This is a synthetic, lumped-parameter demonstration. It is NOT calibrated to
the Zenodo experiment, Epoch AI facility estimates, or a real data center.
Use measured data and a validated thermal model before making performance claims.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def simulate(it_load_pct: float, ambient_c: float, aggressiveness: float,
             hours: int = 24) -> pd.DataFrame:
    """Compare fixed and adaptive cooling under the same synthetic IT load."""
    if not 0 < it_load_pct <= 100:
        raise ValueError("it_load_pct must be in (0, 100].")
    if not 10 <= ambient_c <= 50:
        raise ValueError("ambient_c must be between 10 and 50 °C.")
    if not 0.0 <= aggressiveness <= 1.0:
        raise ValueError("aggressiveness must be between 0 and 1.")

    t = np.arange(hours)
    # Deterministic daily workload shape, scaled to the requested mean load.
    shape = 0.72 + 0.20 * np.sin((t - 8) * np.pi / 12) + 0.08 * np.sin((t - 15) * np.pi / 6)
    load = np.clip((it_load_pct / 100.0) * shape / 0.72, 0.20, 1.0)

    # Illustrative algebraic response curves; coefficients are assumptions,
    # not measured equipment parameters or a CFD/thermodynamic plant model.
    fixed_temp = ambient_c - 7.5 + 18.0 * load - 2.8
    adaptive_target = 23.5 + max(0.0, ambient_c - 30.0) * 0.12
    adaptive_temp = (
        adaptive_target
        + np.maximum(0.0, load - 0.65) * 7.0
        + (ambient_c - 32.0) * 0.07
        + (1.0 - aggressiveness) * 2.4
    )

    fixed_cooling_kw = 18.0 + 32.0 * load + max(0.0, ambient_c - 25.0) * 1.15
    adaptive_cooling_kw = (
        18.0 + 32.0 * load
        + max(0.0, ambient_c - 25.0) * 1.15 * (0.60 + 0.40 * aggressiveness)
        + np.maximum(0.0, 27.0 - adaptive_temp) * 1.8
    )

    return pd.DataFrame({
        "hour": t,
        "it_load_fraction": load,
        "fixed_inlet_temp_c": fixed_temp,
        "adaptive_inlet_temp_c": adaptive_temp,
        "fixed_cooling_power_kw": fixed_cooling_kw,
        "adaptive_cooling_power_kw": adaptive_cooling_kw,
    })


def summarize(df: pd.DataFrame, it_load_pct: float) -> pd.DataFrame:
    fixed_e = df["fixed_cooling_power_kw"].mean() * len(df)
    adaptive_e = df["adaptive_cooling_power_kw"].mean() * len(df)
    fixed_it_kw = 100.0 * it_load_pct / 100.0
    adaptive_it_kw = fixed_it_kw
    return pd.DataFrame([
        {
            "strategy": "fixed",
            "peak_inlet_temp_c": df["fixed_inlet_temp_c"].max(),
            "mean_cooling_power_kw": df["fixed_cooling_power_kw"].mean(),
            "cooling_energy_kwh": fixed_e,
            "hours_above_27c": int((df["fixed_inlet_temp_c"] > 27.0).sum()),
            "illustrative_pue": 1.0 + df["fixed_cooling_power_kw"].mean() / fixed_it_kw,
        },
        {
            "strategy": "adaptive_rule_based",
            "peak_inlet_temp_c": df["adaptive_inlet_temp_c"].max(),
            "mean_cooling_power_kw": df["adaptive_cooling_power_kw"].mean(),
            "cooling_energy_kwh": adaptive_e,
            "hours_above_27c": int((df["adaptive_inlet_temp_c"] > 27.0).sum()),
            "illustrative_pue": 1.0 + df["adaptive_cooling_power_kw"].mean() / adaptive_it_kw,
        },
    ])


def make_figures(df: pd.DataFrame, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(9, 4.8))
    ax.plot(df.hour, df.fixed_inlet_temp_c, label="Fixed cooling", lw=2)
    ax.plot(df.hour, df.adaptive_inlet_temp_c, label="Adaptive rule-based", lw=2)
    ax.axhline(27.0, color="tab:red", ls="--", label="Illustrative 27 °C threshold")
    ax.set(xlabel="Hour of day", ylabel="Rack inlet temperature (°C)",
           title="Synthetic 24-hour rack inlet temperature")
    ax.set_xticks(range(0, 24, 2)); ax.grid(alpha=.25); ax.legend()
    fig.tight_layout(); fig.savefig(out_dir / "temperature_comparison.png", dpi=180); plt.close(fig)

    fig, ax = plt.subplots(figsize=(9, 4.8))
    ax.plot(df.hour, df.fixed_cooling_power_kw, label="Fixed cooling", lw=2)
    ax.plot(df.hour, df.adaptive_cooling_power_kw, label="Adaptive rule-based", lw=2)
    ax.set(xlabel="Hour of day", ylabel="Cooling power (kW)",
           title="Synthetic cooling-power profile")
    ax.set_xticks(range(0, 24, 2)); ax.grid(alpha=.25); ax.legend()
    fig.tight_layout(); fig.savefig(out_dir / "cooling_power_comparison.png", dpi=180); plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--it-load", type=float, default=70.0, help="Mean IT load percentage (default: 70)")
    parser.add_argument("--ambient", type=float, default=32.0, help="Ambient temperature in °C (default: 32)")
    parser.add_argument("--aggressiveness", type=float, default=0.65, help="Adaptive cooling effort, 0..1 (default: 0.65)")
    parser.add_argument("--output", type=Path, default=Path("results"))
    args = parser.parse_args()

    df = simulate(args.it_load, args.ambient, args.aggressiveness)
    summary = summarize(df, args.it_load)
    args.output.mkdir(parents=True, exist_ok=True)
    df.to_csv(args.output / "thermotwin_hourly_simulation.csv", index=False)
    summary.to_csv(args.output / "thermotwin_summary.csv", index=False)
    make_figures(df, args.output / "figures")

    fixed = summary.iloc[0]
    adaptive = summary.iloc[1]
    reduction = (fixed.cooling_energy_kwh - adaptive.cooling_energy_kwh) / fixed.cooling_energy_kwh * 100.0
    print(summary.to_string(index=False, float_format=lambda x: f"{x:.2f}"))
    print(f"Illustrative cooling-energy change vs fixed: {reduction:.2f}%")
    print("WARNING: synthetic model outputs only; do not report as measured facility savings.")


if __name__ == "__main__":
    main()
