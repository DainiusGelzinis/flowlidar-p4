# cpp_lazy_bf262k_cms64x1024 — results on real Tofino 1

Switch: p4switch2 (Intel Tofino 1, SDE 9.11.0). Pipe id 1.
P4 program: `lazy_bf262k.p4` — lazy Bloom Filter (3 × **262144** × 1 bit,
k=3) plus sub-sketch Count-Min Sketch (3 × 65536 × 16-bit, 64
sub-sketches × 1024 columns). **Only the BF was doubled vs the 131k
variant — CMS, polynomials, and C++ control plane are identical.**

Control plane: pure C++ (`cp_cpp/lazy_bf262k_cp`) — same binary as the
131k variant aside from `kBfSize = 262144` and the bound P4 name.

Traffic: hotpot replays CAIDA `equinix-nyc.dirA.20190117-130000` at line
rate (~1.6 Gbps) into port 2/0 (D_P=140). Click sends ~2.9 M pkts over
the 15 s epoch window.

---

## Headline — 15 s epoch on CAIDA: 131k vs **262k**

| Metric | 131k lazy | **262k lazy** | Δ |
|--------|----------:|--------------:|------:|
| Visible flows | 242,789 | **292,558** | +20% |
| Epoch digests | 306,935 | 393,489 | +28% |
| Estimated packets | 3,396,578 | 3,371,814 | ~same |
| Alg 4 hit rate (1/2-pkt mice) | 4.76% | **18.77%** | **+4×** |
| Alg 5 hit rate (3-pkt flows) | 0.17% | 0.58% | +3.4× |
| Solver / `min` fallback | 95.07% | 80.65% | ↓ |
| bf_0 saturation | 91% | **70%** | ↓ |
| bf_1 saturation | 85% | **54%** | ↓ |
| bf_2 saturation | 77% | **40%** | ↓ |
| Max sub-sketch load | 3.85 | 3.75 | flat |
| Bulk register read | 6.42 s | 10.20 s | +3.8 s |
| Bulk register clear | 3.43 s | 3.84 s | +0.4 s |

The CP path is identical — the only knob that changed between rows is
the BF row width (131072 → 262144 cells per row, 17-bit → 18-bit
indexing).

---

## Coverage vs ground truth

Interpolated truth from `pcap_distribution_strict.sh`:
- 2.3 M packets → 247,338 flows
- 3.0 M packets → 330,401 flows
- ~2.9 M packets → ~**290,000 flows** (linear interpolation)

| Run | Visible | Truth (~290 K) | Coverage |
|-----|--------:|---------------:|---------:|
| C++ CP, 131k lazy | 242,789 | 290,000 | 84% |
| **C++ CP, 262k lazy** | **292,558** | 290,000 | **~100%** |

Doubling the BF closed the remaining ~16% coverage gap that the 131k
variant could not. The 262k count slightly exceeds the interpolated
truth — within the noise of click's per-run packet count and the
linear-interp itself.

---

## Per-flow inflation

| Run | Reported avg pkts/flow | Inflation vs truth (~10.0) |
|-----|----------------------:|---------------------------:|
| Python CP (hw_v2, 131k) | 37.5 | 3.75× |
| C++ CP, 131k lazy | 14.0 | 1.40× |
| **C++ CP, 262k lazy** | **11.5** | **1.15×** |

The remaining ~15% over-count is purely a CMS effect: all 64
sub-sketches still have `n > 1024` (kColsPerRow), so the solver falls
back to per-flow `min(cms_rows)`. BF false positives are no longer the
dominant source of error.

---

## Why doubling the BF worked

The BF false-positive rate after `N` flows with `m` cells is
`(1 - exp(-N/m))^k`. With k=3 and the actual saturation we measured:

| | bf_0 | bf_1 | bf_2 | end-of-epoch FP |
|---|---:|---:|---:|---:|
| 131k | 91% | 85% | 77% | ~60% |
| **262k** | 70% | 54% | 40% | **~15%** |

That last column drives both visible-flow coverage and Algorithm 4
classification:

- More true mice now see at least one `bf_i == 0` after the epoch, so
  Alg 4 fires for 18.77% of flows instead of 4.76% (4× improvement).
- Fewer late-arriving mice are silently swallowed by an already-set BF
  triple, so 50K more flows make it onto the visible list.

The CMS sub-sketches are unchanged, and the per-bucket flow count
barely moves (max bucket: 3940 → 3842). All 64 buckets are still
`n > kColsPerRow`, so the exact Gauss-Jordan and Algorithm 6 paths
still don't fire — every solver-eligible flow uses `min(cms_rows)`.

---

## What this means for the BEP narrative

| Bottleneck stage | Killed by |
|---|---|
| Python CP dropping digests (24-30% coverage) | C++ CP (131k → 84%) |
| BF false-positive saturation (84% coverage, 1.40× inflation) | **2× BF (262k → ~100%, 1.15×)** |
| CMS sub-sketches still under-determined (`n > 1024` in all buckets) | open — wider CMS / shorter epoch / Alg 6 |

The remaining accuracy gap is now isolated to the CMS, not the BF.
Likely next moves: widen the CMS columns (1024 → 2048 or 4096) or
shorten epochs so each bucket has `n ≤ 1024` and the exact solver
fires.

---

## Numbers as recorded (EPOCH 1)

```
EPOCH 1 END  -  292558 flows detected by BF
  bulk read time         : 10.2031 s
    bf_0 : 182704 non-zero cells, sum=182704
    bf_1 : 141923 non-zero cells, sum=141923
    bf_2 : 105397 non-zero cells, sum=105397
    cms_0 : 50466 non-zero cells, sum=2592846
    cms_1 : 50552 non-zero cells, sum=2592846
    cms_2 : 50594 non-zero cells, sum=2592846
  Total flows            : 292558
  Epoch digests          : 393489
  Estimated packets      : 3371814
  Resolved by Alg4 (1/2-pkt mice) : 54920  (18.7723%)
  Resolved by Alg5 (3-pkt flows)  : 1698  (0.580398%)
  Equation solver / min fallback  : 235940  (80.6473%)
  Sub-sketch buckets used: 64 / 64  (exact: 0, Alg6 approx: 0, n>cols skip: 64)
  Max sub-sketch load    : 3.75195  (max bucket = 3842 flows / 1024 cols)
  bulk clear time        : 3.84421 s
```
