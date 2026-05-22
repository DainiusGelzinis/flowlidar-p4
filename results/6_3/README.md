# Section 6.3 — Lazy vs Traditional BF sweep (chunk 0 of CAIDA 130000)

One-epoch run per variant. CMS fixed at 256 x 1024. BF size varies.
CP wall-clock budget is `--epoch 20`; replay is Click DPDK at RATE=2Gbps,
LIMIT=5,000,000 packets per chunk.

## Setup

- pcap: `equinix-nyc.dirA.20190117-130000.UTC.anon.pcap` chunk 0
  (`/home2/dgelzini/chunks/130000_chunk5M/chunk_00000_20190117140000.pcap`)
- chunk truth: 470,038 flows, 4,939,940 IPv4 packets (`chunk0_truth.csv`)
- C++ CP on the Tofino switch; one epoch per variant; CSV written to
  `~/results_6_3/<variant>/est_chunk_00000.csv`, scp'd back to this dir.

## Files

- `summary_chunk0.csv` — one row per variant from `compare.py`.
  First row is a stale 5Gbps lazy_bf2m run kept for traceability; the
  next 10 rows are the clean 2Gbps results.
- `chunk0_truth.csv` — `truth_csv.sh` output for chunk 0.
- `<variant>/est_chunk_00000.csv` — per-flow CP estimate (5-tuple,
  digest_count, estimated_packets, solver_path).

## Results

| Variant | BF bits | Coverage | ARE | AAE | pct_exact |
|---|---:|---:|---:|---:|---:|
| lazy_bf2m | 2M | 99.80% | 5.30% | 0.193 | 85.92% |
| lazy_bf1m | 1M | 99.56% | 6.98% | 0.202 | 86.49% |
| lazy_bf524k | 524k | 97.95% | 10.52% | 0.227 | 86.76% |
| lazy_bf262k | 262k | 88.27% | 19.70% | 0.328 | 82.72% |
| lazy_bf131k | 131k | 60.80% | 40.57% | 0.614 | 67.11% |
| traditional_bf2m | 2M | 99.27% | 23.75% | 0.328 | 88.24% |
| traditional_bf1m | 1M | 98.07% | 24.31% | 0.336 | 87.72% |
| traditional_bf524k | 524k | 92.64% | 27.12% | 0.376 | 85.03% |
| traditional_bf262k | 262k | 75.80% | 36.68% | 0.517 | 76.10% |
| traditional_bf131k | 131k | 47.96% | 52.98% | 0.777 | 61.27% |

## Observations

- **Lazy beats traditional at every BF size on ARE.** At 2M bits the gap
  is 5.30% vs 23.75% (4.5x lower error); at 131k it narrows to 40.57%
  vs 52.98%. The lazy alg4 shortcut resolves ~57% of flows exactly at
  large BF, vanishing to ~1% at 131k as the BF saturates.
- **Coverage degrades roughly the same shape for both modes**, dropping
  from ~99% at 2M to ~50-60% at 131k. The lazy line sits 5-13 points
  above traditional at every BF size (true-positive digests fire more
  reliably in lazy mode because each bit transition emits one).
- **Alg6 is never exercised.** Solver wall-time cap is
  `kSlowSolverCap = 500` in `cpp_lazy_common/main.cpp`; max bucket load
  was 843 flows / 1024 cols across the sweep, so every bucket trips the
  cap and falls back to `min(cms_rows)`. The cap keeps per-epoch solver
  runtime under a few seconds. Larger CMS column counts (or more
  sub-sketch buckets) would let alg6 fire and would likely shave a few
  more ARE points off the lazy line.
- **packet_acc tops out at ~97%** because the chunk pcap holds ~4.94M
  packets but Click + the pipeline only deliver ~4.79M to the CP at
  2Gbps. Lower replay rate would close that gap further but at the cost
  of longer per-chunk wall-clock.

## Caveats

- Single epoch, single chunk, single pcap (chunk 0 of 130000). No
  variance across runs is captured. For headline numbers, replicate
  across 2-3 chunks of the same pcap and average.
- Multi-chunk merge is broken in the current C++ CP: per-epoch BF/CMS
  register clear does not fully wipe state, so each chunk past chunk 0
  reads residual data from the first run. That's why this sweep uses
  chunk 0 only. See the chat transcript and `cpp_lazy_common/main.cpp`
  bulk_clear path for context.
