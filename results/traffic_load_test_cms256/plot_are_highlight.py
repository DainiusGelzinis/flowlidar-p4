#!/usr/bin/env python3
"""ARE vs load (CMS256), 3-trace mean, with vertical highlights at 4M and 16M.
Recomputes the means from the per-trace summaries and writes a slide-ready PDF
directly into the presentation figs/ directory.
"""
import csv, statistics, os
import matplotlib.pyplot as plt

HERE   = os.path.dirname(os.path.abspath(__file__))
TRACES = ["130000", "130100", "130200"]
LOADS  = [1_000_000, 2_000_000, 4_000_000, 8_000_000, 16_000_000]
XLAB   = ["1M", "2M", "4M", "8M", "16M"]

data = {}
for t in TRACES:
    with open(os.path.join(HERE, t, "summary.csv")) as f:
        for r in csv.DictReader(f):
            v = r["variant"]
            mode = "lazy" if v.startswith("lazy") else "std"
            load = int(v.split("load=")[1].split(",")[0])
            data.setdefault((mode, load), []).append(float(r["ARE"]) * 100)

lazy = [statistics.mean(data[("lazy", L)]) for L in LOADS]
std  = [statistics.mean(data[("std",  L)]) for L in LOADS]
print("lazy:", [f"{x:.2f}" for x in lazy])
print("std :", [f"{x:.2f}" for x in std])

x = list(range(len(LOADS)))
plt.rcParams.update({"font.size": 14, "axes.labelsize": 15,
                     "xtick.labelsize": 13, "ytick.labelsize": 13,
                     "legend.fontsize": 13})
fig, ax = plt.subplots(figsize=(6.4, 4.2))

# vertical highlight lines at 4M (idx 2) and 16M (idx 4)
for idx in (2, 4):
    ax.axvline(x[idx], color="black", ls=":", lw=1.2, alpha=0.45, zorder=0)

ax.plot(x, std,  "-s", color="#d62728", lw=2.4, ms=7, label="Standard BF")
ax.plot(x, lazy, "-o", color="#1f77b4", lw=2.4, ms=7, label="Lazy BF")

ax.set_xticks(x); ax.set_xticklabels(XLAB)
ax.set_xlabel("Traffic load (packets per epoch)")
ax.set_ylabel("Average relative error (%)")
ax.grid(True, axis="y", ls=":", alpha=0.4)
ax.legend(loc="upper left")

# annotate the highlighted points
def ann(idx, vals, dy):
    for v, color in [(std[idx], "#d62728"), (lazy[idx], "#1f77b4")]:
        ax.annotate(f"{v:.0f}%" if v >= 10 else f"{v:.1f}%",
                    (x[idx], v), textcoords="offset points", xytext=(8, dy),
                    color=color, fontsize=12, fontweight="bold")
ann(4, None, 6)   # annotate values at 16M only

fig.tight_layout(pad=0.3)
OUT = "/home/student/Desktop/BEP_Presentation/TUe_presentation_template/figs/load_are.pdf"
fig.savefig(OUT)
print("[wrote]", OUT)
