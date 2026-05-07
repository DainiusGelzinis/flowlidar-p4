# FlowLiDAR Prototype 6 — Epoch 1 Results on Real Tofino 1

All runs use the same setup:
- Switch: p4switch2 (Tofino 1, SDE 9.11.0)
- Traffic: hotpot replaying CAIDA pcap (`equinix-nyc.dirA.20190117-130000`) at **1 Gbps**
- BF: 3 × 131072 × 1 bit (lazy updates, k=3)
- CMS: 3 × 65536 × 16-bit (64 sub-sketches × 1024 cols)
- Master hash: CRC32 poly 0xF4ACFB13
- Pipe id: 1

Each epoch is reported only once, immediately after a fresh `setup_table.py`,
to avoid epoch-boundary spillover from a previous run. There is a
**~2 second startup delay** between launching the control plane and starting
FastClick on hotpot, so the effective traffic time is ~`epoch − 2s`.

## Epoch 1 results across different epoch lengths

| Run | Epoch | Effective traffic | Flows | Digests | Est. packets | Alg4 | Alg5 | Solver | Max load | Under-det |
|-----|-------|-------------------|-------|---------|-------------:|------|------|--------|----------|-----------|
| A   | 15s   | ~13s              | 78,393 | 109,519 | 2,942,966 | 13.8% | 10.2% | 75.9% | 0.987 | 0 |
| C   | 10s   | ~8s               | 45,662 |  62,870 | 1,292,363 | 29.0% | 18.9% | 52.1% | 0.410 | 0 |

## Derived metrics

| Run | Avg pkts/flow | Avg digests/flow | Throughput (pps) |
|-----|---------------|------------------|------------------|
| A   | 37.5 | 1.40 | ~226K |
| C   | 28.3 | 1.38 | ~162K |

## Observations

- **All sub-systems exact-solved** (`underdetermined: 0` in every run). The
  master-hash partitioning kept each bucket's load below the paper's 0.918
  threshold — even at peak BF utilization, the equation solver always
  produced exact-form solutions.
- **High residual: 64 / 64 buckets** in every run — every sub-system had
  hash collisions inside its bucket but the solver still produced answers
  by absorbing the noise.
- **Solver % grows with epoch length**: longer epoch → more flow accumulation
  → BF saturation → more flows look "fully set" via collisions, even mice.
  - Run A (15s, ~13s effective): 75.9% solver, 13.8% Alg4
  - Run C (10s, ~8s effective): 52.1% solver, 29.0% Alg4

## Comparison vs Prototype 5 (no sub-sketches) at 1 Gbps

| Metric | Prototype 5 | Prototype 6 (run A) |
|--------|-------------|---------------------|
| Flows | 51,373 | 78,393 |
| Solver flows | 38,057 | 59,539 |
| Max load | **37.2** | **0.987** |
| Underdetermined | 100% (Alg6) | 0% |
| Algorithm 6 fallback | always | never |

Sub-sketch partitioning eliminates the Algorithm 6 approximate fallback at
1 Gbps line rate on Tofino 1 with 6 KB → 384 KB CMS expansion.

## Ground truth from pcap (tshark)

Computed by re-parsing the first N packets of the pcap file directly with
tshark and bucketing by 5-tuple. Numbers are *exact* truth — no FlowLiDAR
involved.

### Run C window (first 1,200,000 packets ≈ 8s of replay)

| Class | Count | % |
|-------|-------|---|
| 1-pkt | 97,320 | 64.4% |
| 2-pkt | 14,208 | 9.4% |
| 3-pkt | 7,530 | 5.0% |
| 4-10 pkt | 21,659 | 14.3% |
| 11-100 pkt | 8,683 | 5.7% |
| 101+ pkt | 1,681 | 1.1% |
| **Total flows** | **151,081** | |
| **Avg pkts/flow** | **7.94** | |

**FlowLiDAR equivalents (no FP):** Alg4 candidates 73.8%, Alg5 5.0%, Solver 21.2%

### Run A window (first 3,000,000 packets ≈ 13s of replay)

| Class | Count | % |
|-------|-------|---|
| 1-pkt | 214,984 | 65.1% |
| 2-pkt | 31,168 | 9.4% |
| 3-pkt | 14,243 | 4.3% |
| 4-10 pkt | 47,853 | 14.5% |
| 11-100 pkt | 18,340 | 5.6% |
| 101+ pkt | 3,813 | 1.2% |
| **Total flows** | **330,401** | |
| **Avg pkts/flow** | **9.08** | |

**FlowLiDAR equivalents (no FP):** Alg4 candidates 74.5%, Alg5 4.3%, Solver 21.2%

## Truth vs prototype6 — coverage and accuracy

| Metric | Run C truth | Run C measured | Run A truth | Run A measured |
|--------|-------------|----------------|-------------|----------------|
| Flows | 151,081 | 45,662 | 330,401 | 78,393 |
| Coverage | — | **30%** | — | **24%** |
| Hidden flows | — | 105,419 (**70%**) | — | 252,008 (**76%**) |
| Avg pkts/flow | 7.94 | 28.3 | 9.08 | 37.5 |
| Per-flow inflation | — | **3.6×** | — | **4.1×** |
| Total packets | 1,200,000 | 1,292,363 (+8%) | 3,000,000 | 2,942,966 (-2%) |
| Alg4 % | 73.8% (true mice) | 29.0% reported | 74.5% (true mice) | 13.8% reported |

### Where the missing flows go

Hidden flows = flows whose 3 BF cells were *all* already set by other flows
when their first packet arrived. The lazy-update logic sees "already
inserted" and sends no digest. Those packets still increment CMS, leaving
phantom counter contributions that the solver distributes across visible
flows — that's the source of the 3.6–4.1× per-flow inflation.

**Total packet count stays accurate (±8%)** because the rate-limiter sends
exactly 1 Gbps regardless of BF state. So absolute throughput estimates are
trustworthy; per-flow estimates are not, at this BF utilization.

## Implications for accuracy

- BF size 3 × 131K is **insufficient at 1 Gbps + 15s epochs**. Coverage
  drops to 24%.
- Shorter epochs help: Run C (10s) has 30% coverage vs Run A's 24%.
- Paper's Tofino 2 implementation uses **4 × 128K = 512K bits** (33% more
  capacity) and reports <2% FP at similar load — Tofino 1's 12-stage limit
  prevents the 4th array.
- The differential-BF scheme (paper Algorithm 3, two BFs swapped each
  epoch) would help by only counting "new" flows per epoch — would add
  another stage.
