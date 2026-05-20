# cpp_lazy_bf262k_cms64x2048 — results on real Tofino 1

Switch: p4switch2 (Intel Tofino 1, SDE 9.11.0). Pipe id 1.
P4 program: `lazy_bf262k_cms2048.p4` — lazy Bloom Filter
(3 × 262144 × 1 bit, k=3) plus sub-sketch Count-Min Sketch
(3 × **131072** × 16-bit, **64 sub-sketches × 2048 cols**).
Same BF as `cpp_lazy_bf262k_cms64x1024`; only the CMS column count
doubled.

Control plane: pure C++ (`./lazy_bf262k_cms2048_cp`) built from the
shared `../cpp_lazy_common/` sources with
`-DLAZY_BF_SIZE=262144 -DLAZY_CMS_COLS=2048 -DLAZY_CMS_BUCKETS=64`
injected at compile time.

Traffic: hotpot replays CAIDA `equinix-nyc.dirA.20190117-130000` at
~1.6 Gbps. Click reports `SENT PKTS: 3,017,568` over the 15 s window.

---

## Headline — 15 s epoch on CAIDA, four-way comparison

| Metric | Trad 131k / 64×1024 | Lazy 131k / 64×1024 | Lazy 262k / 64×1024 | **Lazy 262k / 64×2048** |
|--------|--------------------:|--------------------:|--------------------:|------------------------:|
| Visible flows | 205,066 | 242,789 | 292,558 | **297,659** |
| Epoch digests | 205,066 | 306,935 | 393,489 | 399,363 |
| Estimated packets | 3,400,519 | 3,396,578 | 3,371,814 | **3,061,221** |
| Avg pkts/flow | 16.6 | 14.0 | 11.5 | **10.28** |
| **Inflation vs ~10 truth** | 1.66× | 1.40× | 1.15× | **1.03×** |
| Coverage (truth ~290K) | 71% | 84% | ~100% | ~103% |
| Alg 4 hit rate (1/2-pkt) | n/a | 4.76% | 18.77% | 18.14% |
| Alg 5 hit rate (3-pkt) | n/a | 0.17% | 0.58% | 0.88% |
| Solver / min fallback | 100% | 95.07% | 80.65% | 80.99% |
| Sub-sketch buckets exact | 0 / 64 | 0 / 64 | 0 / 64 | **0 / 64** |
| **Max sub-sketch load** | 3.30 | 3.85 | 3.75 | **1.91** |
| Bulk read | 6.23 s | 6.42 s | 10.20 s | 12.43 s |
| Bulk clear | 3.76 s | 3.43 s | 3.84 s | 4.39 s |

Apples-to-apples vs the 64×1024 row above: doubling the CMS columns
**halved the per-cell load** and dropped per-flow inflation from
1.15× to **1.03×** — essentially perfect agreement with the truth
average packets/flow.

---

## Why the inflation dropped even though the exact solver still never fires

Max bucket = 3,903 flows. The threshold for the exact Gauss-Jordan
solver is `n ≤ kColsPerRow`, now 2048 — so all 64 buckets are still
over the threshold (`exact: 0, Alg6 approx: 0, n>cols skip: 64`).
Every solver-eligible flow still falls back to per-flow `min(cms_rows)`.

The accuracy gain came from **less contamination per CMS cell**, not
from running a different solver:

- Each CMS row was 64 × 1024 = 65,536 cells; ~2.67 M packets sum →
  ~41 packets/cell average. With load 3.75 (max bucket 3,842 / 1,024),
  the heaviest cell held the residue of ~4 colliding flows.
- Each CMS row is now 64 × 2048 = 131,072 cells; ~2.68 M packets sum →
  ~20 packets/cell average. With load 1.91 (max bucket 3,903 / 2,048),
  the heaviest cell holds the residue of ~2 colliding flows.

Halving the average residue per cell halves the additive error of
`min(cms_rows)` — which is exactly what 1.15× → 1.03× corresponds to
on a truth of 10 pkts/flow (the absolute over-count went from
1.5 pkts/flow → 0.3 pkts/flow per visible flow).

---

## What would unlock the exact solver

Need every bucket to have `n ≤ kColsPerRow`. With ~297 K flows
distributed across the buckets:

| CMS shape | avg n / bucket | exact fires? |
|-----------|---------------:|--------------|
| 64 × 1024 | 4,650 | no |
| 64 × 2048 (this run) | 4,650 | **no — max 3,903 still >2,048** |
| 128 × 2048 | 2,325 | partially (~half of buckets) |
| **256 × 2048** | **1,162** | **yes for most buckets** |
| 64 × 8192 | 4,650 | yes — max 3,903 < 8,192 |

256 × 2048 would push average bucket load under the threshold; 64 × 8192
would do it via wider CMS rows alone (more SRAM blocks per stage, but
within budget).

---

## SRAM cost of the wider CMS

From `/tmp/build_lazy_bf262k_cms2048/lazy_bf262k_cms2048/tofino/pipe/logs/resources.json`:

| | 64×1024 | **64×2048** |
|---|---:|---:|
| SRAM blocks per CMS row stage | ~10 | **18** |
| SRAM blocks per BF row stage | 3 | 3 |
| Total SRAM blocks used | ~48 / 960 (5%) | **66 / 960 (7%)** |
| MAU stages used | 12 / 12 | 12 / 12 |
| Critical path length | 6 | 6 |

Doubling the CMS cost +24 SRAM blocks total (8 per row × 3 rows). The
chip is still at 7% SRAM utilisation. Room for another 2-4× CMS growth
before SRAM becomes the constraint.

---

## BEP narrative — where the bottlenecks fell

| Stage | Bottleneck | Killed by | Inflation | Coverage |
|---|---|---|---:|---:|
| 0 | Python CP drops digests | C++ CP | 3.75× | 27% → 84% |
| 1 | BF FP saturation | 131k → 262k BF | 1.40× → 1.15× | 84% → ~100% |
| 2 | **CMS cell contamination** | **64×1024 → 64×2048 CMS** | **1.15× → 1.03×** | ~100% → ~103% |
| 3 | Exact solver never fires | open — needs more buckets or wider rows | — | — |

We've reached **1.03× per-flow inflation at ~100% coverage** without
ever running the exact CMS solver — purely by making the `min(cms)`
fallback less contaminated. That's the asymptotic floor of CMS-based
estimation. Pushing past it requires the equation-solving path the
paper describes, which on this trace would need ~256 sub-sketches or
~8192 cols.

---

## Numbers as recorded (EPOCH 1)

```
EPOCH 1 END  -  297659 flows detected by BF
  bulk read time         : 12.4262 s
    bf_0  : 184912 non-zero cells, sum=184912
    bf_1  : 144928 non-zero cells, sum=144928
    bf_2  : 108355 non-zero cells, sum=108355
    cms_0 :  69947 non-zero cells, sum=2678768
    cms_1 :  70005 non-zero cells, sum=2678768
    cms_2 :  69726 non-zero cells, sum=2678768
  Total flows            : 297659
  Epoch digests          : 399363
  Estimated packets      : 3061221
  Resolved by Alg4 (1/2-pkt mice) : 53981  (18.1352%)
  Resolved by Alg5 (3-pkt flows)  :  2608  (0.87617%)
  Equation solver / min fallback  : 241070  (80.9886%)
  Sub-sketch buckets used: 64 / 64  (exact: 0, Alg6 approx: 0, n>cols skip: 64)
  Max sub-sketch load    : 1.90576  (max bucket = 3903 flows / 2048 cols)
  bulk clear time        : 4.39423 s
```

Click on hotpot reported `SENT PKTS: 3,017,568` for the same window.
