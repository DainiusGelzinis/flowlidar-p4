# evaluation/results/

All measured data from the evaluation experiments lives here. Three sub-trees:

```
results/
├── truth/        one CSV per pcap chunk — ground truth from tshark
├── estimates/    one CSV per (variant, pcap, chunk, run) — C++/Python CP output
├── summary/      one row per test point — aggregated metrics for the charts
└── plots/        PNG/PDF chart output from plot.py
```

## truth/

One CSV per pcap chunk, built once and reused across every variant test
that uses the same chunk.

Filename: `<pcap_short>_chunk<size>M_idx<chunk_idx>.csv`

Format (header + rows):

```
key,true_pkts
192.0.2.1|198.51.100.5|6|443|34567,42
...
```

`key` is the 5-tuple `src_ip|dst_ip|proto|sport|dport`, matching the
P4's `flow_digest_t` byte layout.

## estimates/

One CSV per `(variant, pcap, chunk, run)`. Grouped by variant for
sanity.

Filename: `<variant>/<pcap_short>_chunk<size>M_idx<chunk_idx>_speed<rate>_run<n>.csv`

Format:

```
key,digest_count,estimated_packets,solver_path
192.0.2.1|198.51.100.5|6|443|34567,3,41,exact
...
```

Written directly by the CP (`--csv-out FILE`).

## summary/

`summary.csv` — one row per test point. Columns:

```
experiment, variant, cp, pcap, chunk_pkts, chunk_idx, speed_mbps, run_id,
true_flows, visible_flows, coverage,
true_packets, est_packets, packet_acc,
AAE, ARE, pct_exact,
alg4_pct, alg5_pct, solver_pct,
exact_buckets, alg6_buckets, skipped_buckets,
max_load, bulk_read_s, bulk_clear_s,
hidden_flows, bf0_sat, bf1_sat, bf2_sat
```

Built by `compare.py` (one new row appended after each test point).

## plots/

PNG (and optionally PDF) for each chart in the plan. Produced by
`plot.py` from `summary.csv`. Naming:

- `C1_python_vs_cpp_coverage.png`
- `C3_lazy_vs_trad_coverage.png`
- `C5_lazy_vs_trad_ARE.png`
- `C6_bf_sweep_coverage.png`
- `C7_bf_sweep_ARE.png`
- `C8_cms_sweep_ARE.png`
- `C9_cms_sweep_pct_exact.png`
- `C10_stress_max_load.png`
- `C11_stress_ARE.png`
- `C12_stress_coverage.png`
- `C15_per_class_ARE.png`

Tables go to `plots/Tn_<name>.tex` (LaTeX) or `.md` (Markdown).

## Reproducing a single test point

```bash
# from the switch
~/dainius/evaluation/harness/run_experiment.sh \
    --variant lazy_bf1m_cms256x1024 \
    --pcap pcap2 \
    --chunk 5M \
    --idx 0 \
    --speed 2000
# appends one row to results/summary/summary.csv
# writes one CSV under results/estimates/lazy_bf1m_cms256x1024/
```

## Reproducing all charts

```bash
python3 evaluation/harness/plot.py
# rebuilds every PNG under results/plots/ from current summary.csv
```
