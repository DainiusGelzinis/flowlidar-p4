#!/usr/bin/env python3
"""Build a per-stage MAU resource table for a Tofino-compiled variant.

Reads resources.json from a bf-p4c log directory and emits:
  - a Markdown table to stdout
  - a per-stage CSV
  - a stacked-bar PNG of SRAM and TCAM usage per stage
"""

import json
import csv
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
VARIANT = sys.argv[1] if len(sys.argv) > 1 else "lazy_bf2m_cms64x1024"
SRC = os.path.join(HERE, VARIANT, "resources.json")
OUT_DIR = os.path.join(HERE, VARIANT)

# Tofino 1 per-pipe resource budget (per Intel datasheet).
TOFINO1 = {
    "stages_per_pipe":  12,
    "srams_per_stage":  80,    # 8 rows x 10 cols
    "tcams_per_stage":  24,    # 2 cols x 12 rows
    "map_rams_per_stage": 48,
    "logical_tables_per_stage": 16,
    "hash_distribution_units_per_stage": 6,
    "meter_alus_per_stage": 4,
}

with open(SRC) as f:
    d = json.load(f)

stages = d["resources"]["mau"]["mau_stages"]
n_stages = len(stages)

# Per-stage usage extraction.
def n_used(field, sub):
    return len(field.get(sub, [])) if isinstance(field, dict) else 0

rows = []
totals = {"srams": 0, "tcams": 0, "map_rams": 0, "logical_tables": 0,
          "hash_distribution_units": 0, "meter_alus": 0, "statistic_alus": 0,
          "tables_n": 0}

for i, s in enumerate(stages):
    stage_no = s.get("stage_number", i)
    sr   = n_used(s.get("rams") or {},  "srams")
    tc   = n_used(s.get("tcams") or {}, "tcams")
    mr   = n_used(s.get("map_rams") or {}, "maprams")
    lt   = len((s.get("logical_tables") or {}).get("ids", []))
    hdu  = n_used(s.get("hash_distribution_units") or {}, "units")
    malu = n_used(s.get("meter_alus") or {}, "meters")
    salu = n_used(s.get("statistic_alus") or {}, "stats")
    rows.append({
        "stage": stage_no,
        "srams": sr,
        "tcams": tc,
        "map_rams": mr,
        "logical_tables": lt,
        "hash_dist_units": hdu,
        "meter_alus": malu,
        "statistic_alus": salu,
    })
    totals["srams"]                   += sr
    totals["tcams"]                   += tc
    totals["map_rams"]                += mr
    totals["logical_tables"]          += lt
    totals["hash_distribution_units"] += hdu
    totals["meter_alus"]              += malu
    totals["statistic_alus"]          += salu

# --- Markdown table ---
print(f"# Tofino 1 resource usage — `{VARIANT}`")
print()
print(f"Compiled with bf-p4c {d.get('compiler_version', '?')} on {d.get('build_date', '?')}.")
print()
print("## Per-stage breakdown")
print()
print("| Stage | SRAMs | TCAMs | Map RAMs | Logical tables | Hash dist | Meter ALUs | Stat ALUs |")
print("|---:|---:|---:|---:|---:|---:|---:|---:|")
for r in rows:
    print(f"| {r['stage']} | {r['srams']} | {r['tcams']} | {r['map_rams']} | {r['logical_tables']} | {r['hash_dist_units']} | {r['meter_alus']} | {r['statistic_alus']} |")
print(f"| **Total** | **{totals['srams']}** | **{totals['tcams']}** | **{totals['map_rams']}** | **{totals['logical_tables']}** | **{totals['hash_distribution_units']}** | **{totals['meter_alus']}** | **{totals['statistic_alus']}** |")
print()
sram_pct = 100.0 * totals['srams'] / (n_stages * TOFINO1["srams_per_stage"])
tcam_pct = 100.0 * totals['tcams'] / (n_stages * TOFINO1["tcams_per_stage"])
print("## Pipe-budget utilisation")
print()
print(f"- **Stages used:** {n_stages} of {TOFINO1['stages_per_pipe']} ({100*n_stages/TOFINO1['stages_per_pipe']:.1f}%)")
print(f"- **SRAMs:** {totals['srams']} of {n_stages*TOFINO1['srams_per_stage']} stage-blocks "
      f"= {sram_pct:.1f}% of the {n_stages}-stage budget, "
      f"{100*totals['srams']/(TOFINO1['stages_per_pipe']*TOFINO1['srams_per_stage']):.1f}% of one full pipe.")
print(f"- **TCAMs:** {totals['tcams']} of {n_stages*TOFINO1['tcams_per_stage']} stage-blocks "
      f"= {tcam_pct:.1f}% of the {n_stages}-stage budget.")
print(f"- **Map RAMs:** {totals['map_rams']}")
print(f"- **Logical tables:** {totals['logical_tables']}")
print(f"- **Hash distribution units:** {totals['hash_distribution_units']}")

# --- Save CSV ---
csv_path = os.path.join(OUT_DIR, "per_stage.csv")
with open(csv_path, "w") as f:
    w = csv.DictWriter(f, fieldnames=rows[0].keys())
    w.writeheader()
    for r in rows:
        w.writerow(r)
print(f"\n[wrote] {csv_path}", file=sys.stderr)

# --- Stacked bar plot ---
try:
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(7, 3.6))
    xs = [r["stage"] for r in rows]
    sr = [r["srams"] for r in rows]
    tc = [r["tcams"] for r in rows]
    mr = [r["map_rams"] for r in rows]
    ax.bar(xs, sr, label=f"SRAMs (max {TOFINO1['srams_per_stage']}/stage)", color="#1f77b4")
    ax.bar(xs, tc, bottom=sr, label=f"TCAMs (max {TOFINO1['tcams_per_stage']}/stage)", color="#ff7f0e")
    ax.bar(xs, mr, bottom=[a+b for a,b in zip(sr, tc)], label="Map RAMs", color="#2ca02c")
    ax.axhline(TOFINO1["srams_per_stage"], linestyle="--", color="#1f77b4", alpha=0.4,
               label=f"SRAM budget ({TOFINO1['srams_per_stage']})")
    ax.set_xlabel("MAU stage")
    ax.set_ylabel("Blocks used")
    ax.set_xticks(xs)
    ax.grid(True, axis="y", linestyle=":", alpha=0.4)
    ax.legend(loc="upper right", fontsize=8)
    ax.set_title(f"Per-stage MAU resource usage — {VARIANT}")
    fig.tight_layout()
    plot_path = os.path.join(OUT_DIR, "per_stage.png")
    fig.savefig(plot_path, dpi=160)
    print(f"[wrote] {plot_path}", file=sys.stderr)
except ImportError:
    print("(matplotlib not available, skipping plot)", file=sys.stderr)
