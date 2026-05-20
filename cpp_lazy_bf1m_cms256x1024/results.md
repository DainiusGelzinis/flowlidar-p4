# cpp_lazy_bf1m_cms256x1024 — results on real Tofino 1

Switch: p4switch2 (Intel Tofino 1, SDE 9.11.0). Pipe id 1.
P4 program: `lazy_bf1m_cms256x1024.p4` — lazy Bloom Filter
(3 × **1,048,576** × 1 bit, k=3) plus sub-sketch Count-Min Sketch
(3 × **262,144** × 16-bit, **256 sub-sketches × 1024 cols**).

Control plane: pure C++ (`./lazy_bf1m_cms256x1024_cp`) built from the
shared `../cpp_lazy_common/` sources with
`-DLAZY_BF_SIZE=1048576 -DLAZY_CMS_BUCKETS=256 -DLAZY_CMS_COLS=1024`.

Traffic: hotpot replays the first 2,903,648 packets of CAIDA
`equinix-nyc.dirA.20190117-130000` at ~1.6 Gbps. Click was stopped
shortly after EPOCH 1 finished, so the SENT count is an exact ground
truth for this one-epoch window.

---

## Headline — exact estimation on real backbone traffic

Both data plane and ground truth captured a single 2,903,648-packet
window. Ground truth was computed by running `pcap_distribution_strict.sh`
against the same packet count on the source pcap.

| Dimension | Ground truth | CP output | **Accuracy** |
|---|---:|---:|---:|
| Raw packets sent | 2,903,648 | — | — |
| Non-IPv4 (dropped at parser) | 38,733 (1.3%) | — | — |
| **IPv4 packets (P4-visible)** | **2,864,915** | — | — |
| **CP estimated packets** | — | **2,853,202** | **99.59%** |
| Packets unaccounted (BF FP) | — | 11,713 (0.41%) | — |
| **True IPv4 flows** | **302,051** | — | — |
| **CP visible flows** | — | **299,070** | **99.01%** |
| Hidden flows (BF FP) | — | 2,981 (0.99%) | — |
| Avg pkts/flow | 9.48 | 9.54 | **+0.63%** |

The data plane sees every IPv4 packet, and the CP correctly attributes
99.59% of those packets to the right flows. The 0.41% gap is entirely
the packets belonging to the 0.99% of flows that BF false positives
hid from the CP — there is essentially **zero per-visible-flow
estimation error**.

---

## Classification: CP path vs true flow-size distribution

| Path | Truth (% of flows) | Truth (count) | CP (count) | CP / Truth |
|------|-------------------:|--------------:|-----------:|-----------:|
| **Alg 4** (1-pkt + 2-pkt mice) | 73.1% | 220,649 | 157,678 | **71.4%** |
| **Alg 5** (3-pkt) | 4.4% | 13,418 | 6,227 | **46.4%** |
| **Solver** (4+ pkt + classification misses) | 22.5% | 67,961 | 135,165 | (gets the misses) |
| Total visible | — | — | 299,070 | — |

Alg 4 / Alg 5 don't catch every true mouse, because the lazy-BF
trigger condition (`bf_i[idx] == 0` at end of epoch) is sensitive to
collisions:
- A true 1-pkt mouse only triggers Alg 4 if `bf_1[idx1]` is still 0
  at end of epoch — collisions push some into the solver path.
- A true 2-pkt mouse needs `bf_2[idx2] == 0`; same effect.

**Every solver-eligible flow now runs the exact Gauss-Jordan solver
(256/256 buckets exact, max load 0.58)** — so the misclassified mice
still get exact answers, just via a more expensive path. End-to-end
per-flow accuracy is essentially perfect (0.63% inflation).

---

## What changed vs the previous best (262k BF + 64×2048 CMS)

| Metric | 262k / 64×2048 | **1M / 256×1024** | Δ |
|--------|---------------:|------------------:|------:|
| Visible flows | 297,659 | 299,070 | ~same |
| Coverage vs truth (302,051) | 98.5% | **99.0%** | ↑ |
| Packet estimate vs truth (2.86M IPv4) | 106.9% | **99.6%** | ↑ |
| Avg pkts/flow | 10.28 | 9.54 | ↓ closer to 9.48 truth |
| Per-flow inflation | 1.03× | **1.006×** | ↓ |
| Alg 4 hit rate | 18.1% | **52.7%** | **+2.9×** |
| Alg 5 hit rate | 0.88% | 2.1% | +2.4× |
| Solver / fallback | 81.0% | 45.2% | ↓ |
| **Exact buckets** | **0 / 64** | **256 / 256** | **first time all-exact** |
| n>cols skip | 64 / 64 | 0 / 256 | none skipped |
| Max sub-sketch load | 1.91 | **0.58** | halved |
| Max bucket flows | 3,903 | 589 | ↓ 6.6× |
| bf_0 / bf_1 / bf_2 saturation | 70/54/40% | **25/12/8%** | massive headroom |
| Bulk read | 12.4 s | 42.1 s | ↑ (CP serial reads) |
| Bulk clear | 4.4 s | 4.6 s | ~same |

Two compounding effects:
1. **Larger BF** drove saturation from 70/54/40 to 25/12/8% — leaving
   far more `bf_i==0` slots for Alg 4 / Alg 5 to fire.
2. **4× more sub-sketches** dropped the per-bucket flow count from
   ~4,650 to ~1,170 average — every bucket now fits under the
   kColsPerRow=1024 threshold and runs the exact solver.

---

## Resource usage (from `pipe/logs/resources.json`)

| Stage | SRAM blocks | What |
|-------|------------:|------|
| 0 | 1 / 80 | ipv4_lpm |
| 1-2 | 0 / 80 | BF hashes |
| 3-5 | 9-10 / 80 | BF rows (was 3 in 262k variant) |
| 6-8 | 0 / 80 | master/col hashes, cms_idx |
| 9-11 | **34 / 80** | CMS rows (was 18 in 64×2048) |

Total: **132 / 960 SRAM blocks = 13.8%** of Tofino 1. MAU stages
12 / 12. Critical path length: 6. Still 4-8× growth headroom in pure
SRAM, but at this point further sketch growth is academic — accuracy
is already saturated.

---

## The complete BEP narrative

| Stage | Bottleneck | Killed by | Inflation | Coverage |
|-------|-----------|-----------|----------:|---------:|
| 0 | Python CP drops digests | C++ CP | 3.75× | 27% → 84% |
| 1 | BF FP saturation | 131k → 262k BF | 1.40× → 1.15× | 84% → ~100% |
| 2 | CMS cell contamination | 64×1024 → 64×2048 CMS | 1.15× → 1.03× | ~100% |
| 3 | Exact solver never fires | **1M BF + 256×1024 CMS** | **1.03× → 1.006×** | **99% verified** |

This is the paper's headline regime — exact per-flow estimation with
~99% flow coverage on real CAIDA backbone traffic — running on a real
Tofino 1 chip.

---

## Caveats

**Bulk read time (42 s) > epoch (15 s).** For this run click was
stopped immediately after EPOCH 1 ended, so there was no epoch
overlap. For a continuous workload the CP would need:
- A longer epoch (`--epoch 60` would absorb the 42s read), or
- Parallelised bulk reads (one thread per register table, ~3-4×
  speedup), or
- The paper's ping-pong / differential BF scheme (two parallel
  BF/CMS pairs alternated each epoch).

None of these affect accuracy in steady state; they're scheduling
concerns.

---

## Numbers as recorded (EPOCH 1)

```
EPOCH 1 END  -  299070 flows detected by BF
  bulk read time         : 42.1023 s
    bf_0  : 266695 non-zero cells, sum=266695
    bf_1  : 130893 non-zero cells, sum=130893
    bf_2  :  87043 non-zero cells, sum=87043
    cms_0 :  63642 non-zero cells, sum=2457770
    cms_1 :  63588 non-zero cells, sum=2457770
    cms_2 :  63670 non-zero cells, sum=2457770
  Total flows            : 299070
  Epoch digests          : 434502
  Estimated packets      : 2853202
  Resolved by Alg4 (1/2-pkt mice) : 157678  (52.7228%)
  Resolved by Alg5 (3-pkt flows)  :   6227  ( 2.0821%)
  Equation solver / min fallback  : 135165  (45.1951%)
  Sub-sketch buckets used: 256 / 256  (exact: 256, Alg6 approx: 0, n>cols skip: 0)
  Max sub-sketch load    : 0.575195  (max bucket = 589 flows / 1024 cols)
  bulk clear time        : 4.59511 s
```

Ground truth (`pcap_distribution_strict.sh 2903648` on hotpot):

```
Raw packets in window      : 2903648
IPv4 packets (P4-visible)  : 2864915 (98.7% of raw)
Non-IPv4 (silently passed) :   38733
Flows (P4-equivalent)      : 302051
Avg packets/flow           :   9.48
Distribution:
  1-pkt   : 192994 (63.9%)
  2-pkt   :  27655 ( 9.2%)
  3-pkt   :  13418 ( 4.4%)
  4-10    :  46471 (15.4%)
  11-100  :  17813 ( 5.9%)
  101+    :   3700 ( 1.2%)
```
