#!/usr/bin/env python3
"""3-trace load-sweep line charts with error bars (130000 + 130100 + 130200).

For each metric, plots mean across the 3 CAIDA traces with std-dev error
bars. Mirrors plot_load_sweep_1to16M.py's metric set: coverage, ARE, AAE,
exact-rate, alg6 share, hidden-flow share. Output: plots_multitrace/.
"""

import csv
import os
import statistics

import matplotlib.pyplot as plt

plt.rcParams.update({
    "font.size":        15,
    "axes.titlesize":   17,
    "axes.labelsize":   16,
    "xtick.labelsize":  14,
    "ytick.labelsize":  14,
    "legend.fontsize":  14,
})

HERE = os.path.dirname(os.path.abspath(__file__))
OUT  = os.path.join(HERE, "plots_multitrace")
os.makedirs(OUT, exist_ok=True)

# Each trace's summary lives in a different file because the original
# 130000 sweep predated the per-trace directory layout.
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

# rows[(mode_short, load, trace)] = row dict
rows = {}
for trace, path in SUMMARIES.items():
    with open(path) as f:
        for r in csv.DictReader(f):
            # variant cell is "<variant_name>,load=N[,trace=T]"
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

# Sanity print
print("rows loaded:")
for mode in MODES:
    for n in LOADS:
        present = [t for t in SUMMARIES if (mode, n, t) in rows]
        print(f"  {mode:>11} {n//1_000_000:>2}M  traces: {present}")


def collect_stats(mode, key, scale=1.0):
    """Return (means, stds) across the 3 traces, one entry per load."""
    means, stds = [], []
    for n in LOADS:
        vals = []
        for t in SUMMARIES:
            r = rows.get((mode, n, t))
            if r is not None:
                vals.append(float(r[key]) * scale)
        means.append(statistics.mean(vals))
        stds.append(statistics.stdev(vals) if len(vals) > 1 else 0.0)
    return means, stds


def collect_hidden_share(mode):
    means, stds = [], []
    for n in LOADS:
        vals = []
        for t in SUMMARIES:
            r = rows.get((mode, n, t))
            if r is not None:
                vals.append(100.0 * int(r["hidden_flows"]) / int(r["true_flows"]))
        means.append(statistics.mean(vals))
        stds.append(statistics.stdev(vals) if len(vals) > 1 else 0.0)
    return means, stds


def make_plot(mlazy, slazy, mtrad, strad, ylabel, fname,
              log_y=False, ylim=None):
    fig, ax = plt.subplots(figsize=(5.6, 3.6))
    ax.plot(XLABELS, mlazy, marker="o", linewidth=2,
            label="Lazy BF",     color="#1f77b4")
    ax.plot(XLABELS, mtrad, marker="s", linewidth=2,
            label="Standard BF", color="#d62728")
    if log_y:
        ax.set_yscale("log")
    if ylim is not None:
        ax.set_ylim(*ylim)
    ax.set_xlabel("traffic load (packets)")
    ax.set_ylabel(ylabel, fontsize=14)
    ax.grid(True, which="both", linestyle=":", alpha=0.4)
    ax.legend()
    fig.tight_layout(pad=0.2)
    out_path = os.path.join(OUT, fname)
    fig.savefig(out_path, dpi=160)
    plt.close(fig)
    print(f"[wrote] {out_path}")


# ---- 6 metrics ----

ml, sl = collect_stats("lazy",        "ARE", 100.0)
mt, st = collect_stats("traditional", "ARE", 100.0)
make_plot(ml, sl, mt, st, "Average relative error (%)", "are.png")

ml, sl = collect_stats("lazy",        "AAE")
mt, st = collect_stats("traditional", "AAE")
make_plot(ml, sl, mt, st, "Average absolute error", "aae.png")

ml, sl = collect_stats("lazy",        "pct_exact", 100.0)
mt, st = collect_stats("traditional", "pct_exact", 100.0)
make_plot(ml, sl, mt, st, "Flows reconstructed exactly (%)", "pct_exact.png",
          ylim=(0, 105))

ml, sl = collect_stats("lazy",        "alg6_pct", 100.0)
mt, st = collect_stats("traditional", "alg6_pct", 100.0)
make_plot(ml, sl, mt, st, "Approx solver buckets (%)", "approx_solver_share.png",
          ylim=(0, 105))

ml, sl = collect_hidden_share("lazy")
mt, st = collect_hidden_share("traditional")
make_plot(ml, sl, mt, st, "Hidden flows (% of true)", "hidden_share.png")


# ---- Headline aggregated table ----
print()
hdr = f"{'load':>6}  {'mode':>12}  {'cov%':>10}  {'ARE%':>12}  {'AAE':>12}  {'exact%':>11}  {'alg6%':>11}  {'hidden%':>11}"
print(hdr)
print("-" * len(hdr))
for n, lab in zip(LOADS, XLABELS):
    for mode in ("lazy", "traditional"):
        cv = [float(rows[(mode, n, t)]["coverage"]) * 100 for t in SUMMARIES if (mode, n, t) in rows]
        ar = [float(rows[(mode, n, t)]["ARE"])      * 100 for t in SUMMARIES if (mode, n, t) in rows]
        ae = [float(rows[(mode, n, t)]["AAE"])             for t in SUMMARIES if (mode, n, t) in rows]
        ex = [float(rows[(mode, n, t)]["pct_exact"]) * 100 for t in SUMMARIES if (mode, n, t) in rows]
        a6 = [float(rows[(mode, n, t)]["alg6_pct"]) * 100 for t in SUMMARIES if (mode, n, t) in rows]
        hd = [100.0 * int(rows[(mode, n, t)]["hidden_flows"]) / int(rows[(mode, n, t)]["true_flows"])
              for t in SUMMARIES if (mode, n, t) in rows]
        def fmt(xs):
            if len(xs) <= 1:
                return f"{xs[0]:.2f}±0.00"
            return f"{statistics.mean(xs):.2f}±{statistics.stdev(xs):.2f}"
        print(f"{lab:>6}  {mode:>12}  {fmt(cv):>10}  {fmt(ar):>12}  "
              f"{fmt(ae):>12}  {fmt(ex):>11}  {fmt(a6):>11}  {fmt(hd):>11}")
