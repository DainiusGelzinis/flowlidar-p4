#!/usr/bin/env python3
"""3-trace load-sweep line charts — mean only, no error bars.

Same metrics as plot_multitrace.py but cleaner lines for slide-ready
figures. Reads 130000/130100/130200 summaries, plots the per-load
mean across the 3 traces. Output: plots_multitrace_mean/.
"""

import csv
import os
import statistics

import matplotlib.pyplot as plt

HERE = os.path.dirname(os.path.abspath(__file__))
OUT  = os.path.join(HERE, "plots_multitrace_mean")
os.makedirs(OUT, exist_ok=True)

SUMMARIES = {
    "130000": os.path.join(HERE, "130000_summary.csv"),
    "130100": os.path.join(HERE, "130100", "summary.csv"),
    "130200": os.path.join(HERE, "130200", "summary.csv"),
}

LOADS = [1_000_000, 2_000_000, 4_000_000, 8_000_000, 16_000_000]
XLABELS = ["1M", "2M", "4M", "8M", "16M"]

MODES = {
    "lazy":        "lazy_bf2m_cms64x1024",
    "traditional": "traditional_bf2m_cms64x1024",
}

rows = {}
for trace, path in SUMMARIES.items():
    with open(path) as f:
        for r in csv.DictReader(f):
            parts = r["variant"].split(",")
            variant_full = parts[0]
            load = None
            for p in parts[1:]:
                if p.startswith("load="):
                    load = int(p.split("=", 1)[1])
            mode_short = next((k for k, v in MODES.items() if v == variant_full), None)
            if mode_short is None or load is None:
                continue
            rows[(mode_short, load, trace)] = r


def collect_mean(mode, key, scale=1.0):
    out = []
    for n in LOADS:
        vals = []
        for t in SUMMARIES:
            r = rows.get((mode, n, t))
            if r is not None:
                vals.append(float(r[key]) * scale)
        out.append(statistics.mean(vals))
    return out


def collect_hidden_share(mode):
    out = []
    for n in LOADS:
        vals = []
        for t in SUMMARIES:
            r = rows.get((mode, n, t))
            if r is not None:
                vals.append(100.0 * int(r["hidden_flows"]) / int(r["true_flows"]))
        out.append(statistics.mean(vals))
    return out


def make_plot(y_lazy, y_trad, ylabel, fname, log_y=False, ylim=None):
    fig, ax = plt.subplots(figsize=(5.6, 3.6))
    ax.plot(XLABELS, y_lazy, marker="o", linewidth=2, label="Lazy BF",     color="#1f77b4")
    ax.plot(XLABELS, y_trad, marker="s", linewidth=2, label="Standard BF", color="#d62728")
    if log_y:
        ax.set_yscale("log")
    if ylim is not None:
        ax.set_ylim(*ylim)
    ax.set_xlabel("traffic load (packets)")
    ax.set_ylabel(ylabel)
    ax.grid(True, which="both", linestyle=":", alpha=0.4)
    ax.legend()
    fig.tight_layout()
    out_path = os.path.join(OUT, fname)
    fig.savefig(out_path, dpi=160)
    plt.close(fig)
    print(f"[wrote] {out_path}")


make_plot(collect_mean("lazy", "coverage", 100.0),
          collect_mean("traditional", "coverage", 100.0),
          "Coverage (%)", "coverage.png", ylim=(90, 101))

make_plot(collect_mean("lazy", "ARE", 100.0),
          collect_mean("traditional", "ARE", 100.0),
          "Average relative error (%)", "are.png")

make_plot(collect_mean("lazy", "AAE"),
          collect_mean("traditional", "AAE"),
          "Average absolute error (packets)", "aae.png")

make_plot(collect_mean("lazy", "pct_exact", 100.0),
          collect_mean("traditional", "pct_exact", 100.0),
          "Flows reconstructed exactly (%)", "pct_exact.png", ylim=(0, 105))

make_plot(collect_mean("lazy", "alg6_pct", 100.0),
          collect_mean("traditional", "alg6_pct", 100.0),
          "Approx solver buckets (%)", "approx_solver_share.png", ylim=(0, 105))

make_plot(collect_hidden_share("lazy"),
          collect_hidden_share("traditional"),
          "Hidden flows (% of true)", "hidden_share.png")
