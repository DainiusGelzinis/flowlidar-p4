# cpp_traditional_bf131k_cms64x1024 — results on real Tofino 1

Switch: p4switch2 (Intel Tofino 1, SDE 9.11.0). Pipe id 1.
P4 program: `traditional_bf.p4` — **traditional** Bloom Filter (3 × 131072
× 1 bit, k=3, all 3 rows unconditionally check-and-set on every packet)
plus sub-sketch Count-Min Sketch (3 × 65536 × 16-bit, 64 sub-sketches ×
1024 columns). **Only the BF semantics changed vs the 131k lazy variant
— BF / CMS sizes, polynomials, master hash, and C++ CP are identical.**

Control plane: pure C++ (`cp_cpp/traditional_bf_cp`) — Algorithms 4 / 5
are disabled (traditional BF leaves identical state for a 1-pkt mouse
and an N-pkt elephant), so every visible flow goes straight to the
sub-sketch equation solver, which falls back to per-flow `min(cms_rows)`
whenever the bucket is under-determined (`n > kColsPerRow`).

Traffic: hotpot replays CAIDA `equinix-nyc.dirA.20190117-130000` at line
rate (~1.6 Gbps). Click sends ~2.9 M pkts over the 15 s epoch window.

---

## Headline — 15 s epoch on CAIDA, three-way comparison

| Metric | Lazy 131k | **Trad 131k** | Lazy 262k |
|--------|----------:|--------------:|----------:|
| Visible flows | 242,789 | **205,066** | 292,558 |
| Epoch digests | 306,935 | **205,066** | 393,489 |
| Digests per visible flow | 1.26 | **1.00** | 1.34 |
| Estimated packets | 3,396,578 | 3,400,519 | 3,371,814 |
| Avg pkts/flow | 14.0 | **16.6** | 11.5 |
| Inflation vs ~10 pkts/flow | 1.40× | **1.66×** | 1.15× |
| Coverage (truth ~290 K) | 84% | **71%** | ~100% |
| bf_0 saturation | 91% | 92% | 70% |
| bf_1 saturation | 85% | **92%** | 54% |
| bf_2 saturation | 77% | **92%** | 40% |
| CMS sum per row | 2.67 M | **2.94 M** | 2.59 M |
| Max sub-sketch load | 3.85 | 3.30 | 3.75 |
| Bulk read | 6.42 s | 6.23 s | 10.20 s |
| Bulk clear | 3.43 s | 3.76 s | 3.84 s |

All three runs share the same data plane shape (sub-sketch CMS, master
hash, polynomials) and the same C++ CP. Only the BF update rule and the
BF row width differ between rows.

---

## Coverage: traditional loses ~13 percentage points vs lazy at the same BF size

| Run | Visible | Truth (~290 K) | Coverage |
|-----|--------:|---------------:|---------:|
| C++ CP, **Trad 131k** | 205,066 | 290,000 | **71%** |
| C++ CP, Lazy 131k     | 242,789 | 290,000 | 84% |
| C++ CP, Lazy 262k     | 292,558 | 290,000 | ~100% |

Reason: lazy's bf_1 / bf_2 only fire on the 2nd / 3rd packet of a
flow whose previous rows already collided, so they saturate slowly
(85% / 77%) — many late-arriving mice still find at least one
`bf_i == 0` slot and produce a digest. Traditional flips all 3 bits on
every packet, so all 3 rows saturate uniformly to ~92% and ~78% of
late-arriving flows hit an already-1 triple and stay invisible.

End-of-epoch false-positive rate `(saturation)^3`:

| | bf_0 | bf_1 | bf_2 | end-of-epoch (s_0 · s_1 · s_2) |
|---|---:|---:|---:|---:|
| Trad 131k | 92% | **92%** | **92%** | **~78%** |
| Lazy 131k | 91% | 85% | 77% | ~60% |
| Lazy 262k | 70% | 54% | 40% | ~15% |

---

## Per-flow inflation: traditional is also the worst

| Run | Reported avg pkts/flow | Inflation vs truth (~10.0) |
|-----|----------------------:|---------------------------:|
| **C++ CP, Trad 131k** | **16.6** | **1.66×** |
| C++ CP, Lazy 131k     | 14.0 | 1.40× |
| C++ CP, Lazy 262k     | 11.5 | 1.15× |

Two effects compound:

1. **Fewer flows in the denominator** — coverage gap directly inflates
   the average.
2. **No Algs 4 / 5 cheap classification** — traditional CMS pushes 100%
   of flows through the lossy `min(cms_rows)` fallback. Lazy 131k
   handles 4.76% via Alg 4 + 0.17% via Alg 5; lazy 262k handles
   18.77% + 0.58%.

---

## CMS accounting differs by BF rule

CMS row sum (per row, three rows agree):

| Run | CMS sum | Counted packets |
|-----|--------:|-----------------|
| Trad 131k | 2.94 M | 2nd packet onwards of every visible flow + every hidden-flow packet |
| Lazy 131k | 2.67 M | 4th packet onwards of every visible flow + every hidden-flow packet |

In traditional, the gate `b0 = b1 = b2 = 1` is met starting with the
2nd packet of a flow (1st packet sets all 3 bits, 2nd packet sees them
already set). In lazy, the chain has to fully lock in first: bf_0 → bf_1
→ bf_2, so the gate only fires from the 4th packet onwards. That's
why traditional's CMS sum is ~10% higher despite having FEWER visible
flows.

---

## What the C++ CP printed (EPOCH 1)

```
EPOCH 1 END  -  205066 flows detected by BF
  bulk read time         : 6.22806 s
    bf_0 : 119851 non-zero cells, sum=119851
    bf_1 : 120056 non-zero cells, sum=120056
    bf_2 : 120099 non-zero cells, sum=120099
    cms_0 : 62424 non-zero cells, sum=2938154
    cms_1 : 62437 non-zero cells, sum=2938154
    cms_2 : 62469 non-zero cells, sum=2938154
  Total flows            : 205066
  Epoch digests          : 205066
  Estimated packets      : 3400519
  Equation solver / min fallback  : 205066  (100%)
  Sub-sketch buckets used: 64 / 64  (exact: 0, Alg6 approx: 0, n>cols skip: 64)
  Max sub-sketch load    : 3.30078  (max bucket = 3380 flows / 1024 cols)
  bulk clear time        : 3.76016 s
```

`Epoch digests == Total flows` confirms the design: traditional BF
fires exactly one digest per visible flow.

---

## Takeaway

At identical BF size + identical CMS + identical control plane, **lazy
beats traditional on both axes the BEP cares about** (coverage and
per-flow accuracy). The lazy chain isn't just an optimisation that
saves digests — it materially reduces per-row BF saturation (since
bf_1 / bf_2 only get touched on collision events) and unlocks
Algorithms 4 / 5, which are CMS-free and therefore immune to the
hidden-flow contamination that drives most of the remaining inflation
in the `min(cms_rows)` fallback path.

This run is the apples-to-apples baseline that justifies using the
lazy BF as the default in the rest of the report.
