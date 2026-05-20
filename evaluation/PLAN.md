# FlowLiDAR on Tofino 1 — Evaluation Plan

The detailed plan for the experiments backing the BEP evaluation chapter.
This is the source of truth — if it disagrees with this document, the
document wins. Update it if the plan changes.

---

## 1. Claims the thesis defends

1. **FlowLiDAR works on real Tofino 1 hardware**, not just in simulation.
2. **The control plane is the dominant bottleneck on real hardware**, and a
   pure-C++ CP replaces the Python `bfrt-grpc` client.
3. **The lazy BF + sub-sketch CMS design can be characterized as a
   design-space trade-off on Tofino 1**: coverage vs accuracy vs SRAM vs
   stages.

Every chart and table below maps to one of these three claims.

---

## 2. Best ("baseline") variant

For all single-variant experiments and for the "best vs best" comparisons
(6.2, 6.3, 6.5):

**Best = `cpp_lazy_bf1m_cms256x1024`**
- BF: 3 × 1,048,576 × 1 bit (lazy, k=3)
- CMS: 256 sub-sketches × 1024 cols × 16 bit
- Total SRAM: 132 / 960 blocks (~14% of Tofino 1)

For the lazy-vs-traditional comparison the "best traditional" is
`cpp_traditional_bf1m_cms256x1024` (same dimensions, no lazy chain).

---

## 3. Full variant list (11)

| # | Variant | BF (k=3) | CMS | Status | Used in |
|---|---|---|---|---|---|
| 1 | `cpp_lazy_bf131k_cms64x1024` | 3×131K | 64×1024 | ✓ built | 6.4.1, 6.5 small |
| 2 | `cpp_lazy_bf262k_cms64x1024` | 3×262K | 64×1024 | ✓ built | 6.4.1 |
| 3 | `cpp_lazy_bf524k_cms64x1024` | 3×524K | 64×1024 | **NEW** | 6.4.1 |
| 4 | `cpp_lazy_bf1m_cms64x1024` | 3×1M | 64×1024 | **NEW** | 6.4.1 |
| 5 | `cpp_lazy_bf2m_cms64x1024` | 3×2M | 64×1024 | **NEW** (confirmed fits) | 6.4.1 |
| 6 | `cpp_lazy_bf1m_cms64x4096` | 3×1M | 64×4096 | **NEW** | 6.4.2 |
| 7 | `cpp_lazy_bf1m_cms128x2048` | 3×1M | 128×2048 | **NEW** | 6.4.2 |
| 8 | `cpp_lazy_bf1m_cms256x1024` | 3×1M | 256×1024 | ✓ built | **6.2, 6.3, 6.4.2, 6.4.3, 6.5** |
| 9 | `cpp_traditional_bf1m_cms256x1024` | 3×1M (no chain) | 256×1024 | **NEW** | 6.3, 6.5 |
| 10 | `cpp_traditional_bf131k_cms64x1024` | 3×131K (no chain) | 64×1024 | ✓ built | 6.6 |
| 11 | `cpp_lazy_bf262k_cms64x2048` | 3×262K | 64×2048 | ✓ built | 6.6 |

**Total: 6 new, 5 built.** Plus one Python CP for variant #8 (see §5).

Confirmed infeasible on Tofino 1:
- 256×2048 CMS (524K cells × 16-bit per row) — per-stage SRAM exhausted.

---

## 4. Experiments

### 4.1 Section 6.1 — Setup
Reference tables only (no measurements):

| Output | Type | Contents |
|---|---|---|
| **T1** | Table | Variants tested (11 rows: variant name, BF dims, CMS dims, total SRAM, stages, status) |
| **T2** | Table | Pcap characteristics (10 rows: name, time, packets, flows, mean pkts/flow, size-class distribution) |

T2 is produced by running `pcap_distribution_strict.sh` against each pcap.

---

### 4.2 Section 6.2 — Python CP vs C++ CP

| Goal | Show that the Python `bfrt-grpc` CP drops digests under sustained line-rate traffic, and that the C++ CP doesn't. |
| --- | --- |
| **Variant** | `cpp_lazy_bf1m_cms256x1024` (best) |
| **Pcap** | Pick 1 representative (e.g. pcap2) |
| **Epoch** | Fixed 10 s |
| **Speed sweep** | 10 Mbps, 100 Mbps, 500 Mbps, 1 Gbps, 2 Gbps, 5 Gbps, 10 Gbps (7 points) |
| **Runs per point** | 3 (averaged) |
| **Total runs** | 7 speeds × 2 CPs × 3 reps = **42 runs** |

**Output**:
- **C1** (chart, line, speed on x): coverage % vs speed; 2 lines (Python, C++)

---

### 4.3 Section 6.3 — Lazy vs traditional, consistency across pcaps

| Goal | Same hardware, same CP, same CMS — only the BF semantics differ. Show lazy consistently beats traditional on coverage and per-flow ARE. |
| --- | --- |
| **Variants** | `cpp_lazy_bf1m_cms256x1024` vs `cpp_traditional_bf1m_cms256x1024` |
| **Pcaps** | All 10 |
| **Epoch** | 10 s |
| **Speed** | 2 Gbps (representative line-rate) |
| **Chunks per pcap** | 5–6 (aggregated to mean ± std) |
| **Total runs** | 2 variants × 10 pcaps × ~6 chunks = **~120 runs** |

**Output**:
- **C3** (chart, line, pcaps on x): coverage %, 2 lines (lazy, traditional)
- **C5** (chart, line, pcaps on x): ARE, 2 lines

---

### 4.4 Section 6.4.1 — BF size sweep

| Goal | At fixed CMS (64×1024, the smallest), show how varying BF size affects coverage and per-flow ARE as traffic intensity grows. |
| --- | --- |
| **Variants** | 5 lazy BF sizes: 131K, 262K, 524K, 1M, 2M (variants #1, #2, #3, #4, #5) |
| **Pcaps** | 3 representative |
| **Epoch** | 10 s fixed |
| **Speed sweep** | 10 Mbps, 100 Mbps, 500 Mbps, 1 Gbps, 2 Gbps, 5 Gbps, 10 Gbps (7 points) |
| **Runs per point** | 3 (averaged) |
| **Total runs** | 5 variants × 3 pcaps × 7 speeds × 3 reps = **315 runs** |

**Output**:
- **C6** (chart, line, speed on x): coverage %, 5 lines (one per BF size)
- **C7** (chart, line, speed on x): ARE, 5 lines

---

### 4.5 Section 6.4.2 — CMS shape sweep at constant total CMS cells

| Goal | At fixed BF (1M) and fixed total CMS cells (262K), show whether layout shape (64-bucket vs 128-bucket vs 256-bucket) affects accuracy as traffic intensity grows. |
| --- | --- |
| **Variants** | 3 with 1M BF and same total CMS cells: 64×4096, 128×2048, 256×1024 (variants #6, #7, #8) |
| **Pcaps** | 3 representative |
| **Epoch** | 10 s fixed |
| **Speed sweep** | same 7 points |
| **Runs per point** | 3 |
| **Total runs** | 3 variants × 3 pcaps × 7 speeds × 3 reps = **189 runs** |

**Output**:
- **C8** (chart, line, speed on x): ARE, 3 lines (one per shape)
- **C9** (chart, line, speed on x): % exact buckets, 3 lines

---

### 4.6 Section 6.4.3 — Stress test (best variant, chunk size sweep)

| Goal | At the best variant, find the chunk size where sketch accuracy breaks down. |
| --- | --- |
| **Variant** | #8 (`cpp_lazy_bf1m_cms256x1024`) |
| **Pcaps** | All 10 |
| **Chunk sweep** | 1M, 2M, 5M, 10M, 20M, 30M packets (6 points) — chunks here = different click pkt counts |
| **Epoch** | Long enough to absorb the chunk + bulk read time |
| **Total runs** | 1 × 10 × 6 = **60 runs** |

**Output**:
- **C10** (chart, line, chunk on x): max sub-sketch load
- **C11** (chart, line, chunk on x): ARE
- **C12** (chart, line, chunk on x): coverage %
  Each has 10 faint per-pcap lines + 1 bold mean line.

---

### 4.7 Section 6.5 — Per-class error breakdown

| Goal | Show how each variant handles different flow size classes (mice vs elephants). |
| --- | --- |
| **Variants** | 3: lazy 131k (#1), lazy 1M (#8), traditional 1M (#9) |
| **Pcap** | 1 representative |
| **Speed** | 2 Gbps |
| **Chunks** | 5–6 (aggregated) |
| **Total runs** | 3 variants × 1 pcap × 6 chunks = **18 runs** |

**Output**:
- **C15** (chart, line, class on x): ARE, 3 lines (one per variant)
- **T4** (table): per-class flow count + AAE + ARE + % exact, per variant

Classes: 1-pkt / 2-pkt / 3-pkt / 4-10 / 11-100 / 101+

---

### 4.8 Section 6.6 — Resources on Tofino 1

No runtime measurements — pull straight from `bf-p4c` compile outputs.

**Output**:
- **T5** (table): for each variant, per-stage SRAM blocks + total + hash distribution units + MAU stages used

Pre-computed offline from `/tmp/build_<NAME>/<NAME>/tofino/pipe/logs/resources.json`.

---

## 5. Infrastructure to build

### 5.1 C++ CP additions (both `cpp_lazy_common/` and `cpp_traditional_common/`)

| Flag | Behaviour |
|---|---|
| `--csv-out FILE` | After each epoch, append per-flow estimates as CSV |
| `--epochs N` | Run N epochs then exit cleanly (default: forever) |

CSV format:
```
src_ip,dst_ip,proto,src_port,dst_port,digest_count,estimated_packets,solver_path
```
where `solver_path ∈ {alg4, alg5, exact, alg6, min}`.

### 5.2 Python CP (for 6.2 only)

`cpp_lazy_bf1m_cms256x1024/control_plane.py` — adapted from
`archive/hardware_version2/control_plane.py`. Same Alg 4/5 + solver
dispatch as the C++ CP for fair comparison. Same `--csv-out` and
`--epochs N` flags so the harness treats it identically.

### 5.3 Click chunking

`evaluation/harness/chunked_replay.click` on hotpot. Variant of the
existing `simple_pcap_replay.click` that sends exactly N packets then
exits. `$LIMIT` and `$RATE` configurable from command-line.

### 5.4 Per-flow truth dumper

`evaluation/harness/truth_csv.sh PCAP NPKTS OUT.csv` — uses tshark
similar to `pcap_distribution_strict.sh` but emits per-flow CSV:
```
key,true_pkts
```
where `key` is `src_ip|dst_ip|proto|sport|dport`.

### 5.5 Comparison script

`evaluation/harness/compare.py TRUTH.csv ESTIMATE.csv` — joins by
5-tuple, computes per-flow AAE / ARE / % exact / per-class breakdown,
appends one row to `evaluation/results/summary/summary.csv`.

### 5.6 Test harness

`evaluation/harness/run_experiment.sh` — orchestrates one or all
experiments. For each `(variant, pcap, chunk_size, speed)` test point:

1. Ensure switchd is up with the right P4 program (skip restart if already)
2. Trigger setup_table.py if first run for this variant
3. Start CP with `--csv-out` + `--epochs 1`
4. Start click with the right `--limit` and `--rate`
5. Wait for CP to exit (signals epoch end)
6. Call `compare.py` to derive metrics → append to `summary.csv`

### 5.7 Plot script

`evaluation/harness/plot.py` — reads `summary.csv`, emits one PNG per
chart C1..C15 into `evaluation/results/plots/`. Run after the full
sweep finishes (or after pilot runs, for iteration).

---

## 6. Results directory layout

```
evaluation/
├── PLAN.md                                  this file
├── harness/                                 scripts
│   ├── chunked_replay.click
│   ├── truth_csv.sh
│   ├── compare.py
│   ├── run_experiment.sh
│   └── plot.py
└── results/
    ├── truth/                               one CSV per (pcap, chunk_size, chunk_idx)
    │   ├── pcap1_chunk5M_idx0.csv
    │   ├── pcap1_chunk5M_idx1.csv
    │   └── ...
    ├── estimates/                           one CSV per (variant, pcap, chunk, run_id)
    │   ├── lazy_bf1m_cms256x1024/
    │   │   ├── pcap1_chunk5M_idx0_speed2G_run0.csv
    │   │   └── ...
    │   ├── lazy_bf131k_cms64x1024/
    │   └── ...
    ├── summary/
    │   └── summary.csv                      one row per test point with all metrics
    └── plots/                               PNG output of plot.py
        ├── C1_python_vs_cpp_coverage.png
        ├── C3_lazy_vs_trad_coverage.png
        └── ...
```

### summary.csv columns

```
experiment,variant,cp,pcap,chunk_pkts,chunk_idx,speed_mbps,run_id,
true_flows,visible_flows,coverage,
true_packets,est_packets,packet_acc,
AAE,ARE,pct_exact,
alg4_pct,alg5_pct,solver_pct,
exact_buckets,alg6_buckets,skipped_buckets,
max_load,bulk_read_s,bulk_clear_s,
hidden_flows,bf0_sat,bf1_sat,bf2_sat
```

---

## 7. Total runs and timing

| Section | Runs |
|---|---:|
| 6.2 Python vs C++ | 42 |
| 6.3 lazy vs traditional | 120 |
| 6.4.1 BF sweep | 315 |
| 6.4.2 CMS sweep | 189 |
| 6.4.3 Stress | 60 |
| 6.5 Per-class | 18 |
| **Total** | **~744 runs** |

At ~2 min per run with switchd-restart amortized = **~25 hours** of switch
time. Spread across 2-3 overnight runs is realistic.

If too many: cut design-space sweeps from 7 speed points to 5 (saves
~200 runs) and from 3 reps to 2 (saves ~150).

---

## 8. Build / run order

1. **Build 6 new P4 variants on local VM** to verify compilation (~1 hr)
2. **Adapt Python CP for the best variant** (~1 hr)
3. **Add `--csv-out` + `--epochs N` to both C++ cores** (~30 min)
4. **scp everything to switch + hotpot in one batch**
5. **Build all 6 P4 programs on switch** with bf-p4c (~30 min sequential)
6. **Write harness scripts** (truth dumper, click chunking, compare.py,
   run_experiment.sh) (~2 hr)
7. **Pilot run**: 1 variant × 1 pcap × 1 chunk × 1 speed → verify
   `summary.csv` looks right, comparison numbers match expectations
8. **Write plot.py** against the pilot row (~1 hr)
9. **Full sweep**: leave running overnight
10. **Render charts** + write the eval chapter

---

## 9. Deliverables for the thesis chapter

- 8 line charts (C1, C3, C5, C6, C7, C8, C9, C15)
- 3 stress chart panels (C10, C11, C12)
- 5 tables (T1 setup, T2 pcaps, T4 per-class, T5 resources, and one
  pseudo-table T3 if the headline summary belongs in a table rather than
  prose)

Total: **~12 figures, ~5 tables** for the evaluation chapter.
