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

### 4.3 Section 6.3 — Lazy vs traditional BF, swept over BF size [DONE, 1 chunk]

| Goal | At fixed CMS, show how lazy vs traditional BF compare across BF sizes. Lazy should sit below traditional on ARE at every operating point, and the gap should narrow only when the BF saturates. |
| --- | --- |
| **Variants (10)** | Lazy: `cpp_lazy_bf{131k,262k,524k,1m,2m}_cms256x1024` (5)<br>Traditional: `cpp_traditional_bf{131k,262k,524k,1m,2m}_cms256x1024` (5) |
| **Pcap** | 1 (CAIDA 130000, chunk 0 of 5M packets) |
| **Epoch** | 20 s (covers replay + bulk read at this load) |
| **Speed** | 2 Gbps (Click DPDK actual rate ~2.0 Gbps with no per-link drops) |
| **Chunks per variant** | 1 |
| **Total runs** | 10 variants × 1 chunk = **10 runs** |
| **Status** | **DONE** — see `results/6_3/summary_chunk0.csv` (commit 8b86bc8) |

**Output**:
- **C3** (chart, line, BF bits on x [log scale]): coverage %, 2 lines (lazy, traditional)
- **C5** (chart, line, BF bits on x [log scale]): ARE, 2 lines

**Future (optional, stability):** repeat the 10 runs on chunks 1 and 2 of the same pcap; restart switchd between chunks to dodge the per-epoch register-clear bug in the C++ CP. Adds 20 runs, ~1.5 h of switch time.

---

### 4.4 Section 6.4 — CMS column sweep at fixed BF=1M, fixed 64 buckets [PENDING, 1 chunk]

| Goal | At fixed BF (lazy 1M) and fixed bucket count (64), show how the column count per CMS row drives accuracy. Larger column counts spread flows across more cells, lowering bucket collision pressure on the equation solver. |
| --- | --- |
| **Variants (3)** | `cpp_lazy_bf1m_cms64x1024` (built)<br>`cpp_lazy_bf1m_cms64x2048` (needs to be built)<br>`cpp_lazy_bf1m_cms64x4096` (built) |
| **Pcap** | 1 (CAIDA 130000, chunk 0 of 5M packets — same as 6.3) |
| **Epoch** | 20 s |
| **Speed** | 2 Gbps |
| **Chunks per variant** | 1 |
| **Total runs** | 3 variants × 1 chunk = **3 runs** |
| **Status** | **PENDING** |

**Output**:
- **C6** (chart, line, CMS columns on x [log scale]): ARE, 1 line at fixed 64 buckets
- **C7** (chart, line, CMS columns on x [log scale]): coverage %, 1 line
- **C8** (chart, line, CMS columns on x [log scale]): per-bucket max load (shows how many flows pile into the worst bucket as columns grow)

**Future (optional, stability):** repeat on chunks 1 and 2. Adds 6 runs.

---

### 4.5 Section 6.5 — CMS bucket sweep at fixed BF=1M, fixed total CMS memory [PENDING, 1 chunk]

| Goal | At fixed BF (lazy 1M) and fixed total CMS cells (~256K), show whether splitting the same memory into more, narrower buckets vs fewer, wider buckets affects accuracy. This isolates the layout/shape effect from the memory-budget effect. |
| --- | --- |
| **Variants (3)** | `cpp_lazy_bf1m_cms64x4096` (262144 cells, 64 buckets × 4096 cols)<br>`cpp_lazy_bf1m_cms128x2048` (262144 cells, 128 buckets × 2048 cols)<br>`cpp_lazy_bf1m_cms256x1024` (262144 cells, 256 buckets × 1024 cols) |
| **Pcap** | 1 (CAIDA 130000, chunk 0 of 5M packets) |
| **Epoch** | 20 s |
| **Speed** | 2 Gbps |
| **Chunks per variant** | 1 |
| **Total runs** | 3 variants × 1 chunk = **3 runs** |
| **Status** | **PENDING** (cms256x1024 result reusable from 6.3 lazy_bf1m row) |

**Output**:
- **C9** (chart, line, bucket count on x [log scale]): ARE, 1 line at fixed 256K total cells
- **C10** (chart, line, bucket count on x [log scale]): coverage %, 1 line
- **C11** (chart, line, bucket count on x [log scale]): % exact-solved buckets (alg6 + exact), 1 line. Shows when the smaller per-bucket load brings buckets back under the `kSlowSolverCap = 500` ceiling and alg6/exact actually fires.

**Future (optional, stability):** repeat on chunks 1 and 2. Adds 6 runs.

---

### 4.6 Section 6.4.3 — Stress test (best variant, chunk size sweep) [DEFERRED]

Originally planned: 1 variant × 10 pcaps × 6 chunk sizes × ~1 chunk = 60 runs.

**Status: DEFERRED** until the per-epoch BF/CMS register clear in `cpp_lazy_common/main.cpp` is fixed. Currently each epoch past the first reads residual state from the first run, so chunk-size sweeps reduce to a 1-chunk result.

Workaround if revived: restart switchd between every chunk (slow, ~5 min per data point including reload + setup_table.py).

---

### 4.7 Section 6.6 — Per-class error breakdown [REUSE 6.3 DATA]

| Goal | Show how each variant handles different flow size classes (mice vs elephants). |
| --- | --- |
| **Variants** | 3: lazy 131k (#1), lazy 1M (#8), traditional 1M (#9) |
| **Pcap** | 1 (CAIDA 130000, chunk 0) |
| **Source** | Per-class numbers (`AAE_1pkt`, `ARE_1pkt`, ..., `ARE_101plus`) are already in `results/6_3/summary_chunk0.csv` for every variant in 6.3. **No new runs needed**; pure plotting. |

**Output**:
- **C15** (chart, line, class on x): ARE, 3 lines (one per variant)
- **T4** (table): per-class flow count + AAE + ARE + % exact, per variant

Classes: 1-pkt / 2-pkt / 3-pkt / 4-10 / 11-100 / 101+

---

### 4.8 Section 6.7 — Resources on Tofino 1

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

## 7. Total runs and timing (revised, 1-chunk strategy)

| Section | Runs | Status |
|---|---:|---|
| 6.2 Python vs C++ | 42 | pending |
| 6.3 Lazy vs traditional × BF size | 10 | **DONE** |
| 6.4 CMS column sweep (fixed BF=1M, 64 buckets) | 3 | pending |
| 6.5 CMS bucket sweep (fixed BF=1M, fixed total memory) | 3 | pending (1 row reusable from 6.3) |
| 6.4.3 Stress (chunk-size sweep) | 0 | **DEFERRED** (CP bug) |
| 6.6 Per-class breakdown | 0 | **reuses 6.3 data** |
| 6.7 Resources (parsed from compile outputs) | 0 | pending |
| **Total remaining** | **~50 runs** | |

Future-stability budget: 2 additional chunks per variant in 6.3/6.4/6.5 →
+32 runs (16 variants × 2 extra chunks). Each chunk needs switchd
restart between runs, so budget ~5 min per chunk including reload +
setup_table.py = ~3 hours of switch time. Optional.

Most of the remaining 50 runs is 6.2 (Python vs C++, 42 runs across 7
speed points × 2 CPs × 3 reps). The new CMS sweeps (6.4, 6.5) together
add only 5 net new runs (cms64x1024, cms64x2048, cms64x4096, cms128x2048,
plus reuse cms256x1024 from 6.3).

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

## 9. Deliverables for the thesis chapter (revised)

Charts:
- **C1** (6.2): Python vs C++ coverage, speed on x
- **C3, C5** (6.3): lazy vs traditional coverage + ARE, BF bits on x [log]
- **C6, C7, C8** (6.4): CMS column sweep ARE, coverage, max load, columns on x [log]
- **C9, C10, C11** (6.5): CMS bucket sweep ARE, coverage, % exact-solved, buckets on x [log]
- **C15** (6.6): per-class ARE, class on x

Tables:
- **T1** (6.1): variants tested (~16 rows: BF dims, CMS dims, total SRAM, stages, status)
- **T2** (6.1): pcap characteristics (10 rows: name, packets, flows, mean pkts/flow)
- **T4** (6.6): per-class flow count + AAE + ARE + % exact per variant
- **T5** (6.7): per-variant per-stage SRAM blocks + hash units + MAU stages

Total: **~9 figures, 4 tables** for the evaluation chapter. The
chunk-size stress test (originally C10/C11/C12 in 6.4.3) is deferred
pending the CP register-clear bug fix.
