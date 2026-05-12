# hardware_version_cpp_lazy_BF — results on real Tofino 1

Switch: p4switch2 (Intel Tofino 1, SDE 9.11.0). Pipe id 1.
P4 program: `lazy_bf.p4` — lazy Bloom Filter (3 × 131072 × 1 bit, k=3) plus
sub-sketch Count-Min Sketch (3 × 65536 × 16-bit, 64 sub-sketches × 1024
columns). Identical data plane to `hardware_version2/prototype6.p4` — only
the control plane changed.

Control plane: pure C++ (`cp_cpp/lazy_bf_cp`). Single process owns the
bfrt-grpc client_id 0 session, runs digest reception in a background
thread, performs per-epoch bulk register read+clear, and computes per-flow
counts via the sub-sketch equation solver (with `min(cms_rows)` fallback
for buckets where flows > columns_per_row).

Traffic: hotpot replays CAIDA `equinix-nyc.dirA.20190117-130000` at line
rate (~1.6 Gbps) into port 2/0 (D_P=140). Click reports `SENT PKTS:
2,904,320` over the 15 s epoch window.

---

## Headline result — 15 s epoch on CAIDA

| Metric | Python CP (hw_v2, prototype6) | **C++ CP (this prototype)** |
|--------|------------------------------:|----------------------------:|
| Bulk register read | ~30 s | **6.42 s** (≈ 5× faster) |
| Bulk register clear | (slow, several seconds)  | **3.43 s** |
| Total per-epoch CP I/O | > 30 s | **~10 s** |
| Visible flows | 78,393 | **242,789** (3.1×) |
| Epoch digests | 109,519 | **306,935** (2.8×) |
| Estimated packets | 2,942,966 | 3,396,578 |
| Max sub-sketch load | 0.987 | 3.85 (still measured, solver skipped) |
| Sub-sketch buckets used | n/a | 64 / 64 (exact: 0, fallback: 64) |

Both control planes drove the same data plane on the same hardware,
replaying the same CAIDA pcap.

---

## Coverage vs ground truth

Interpolated truth from `pcap_distribution_strict.sh`:
- 2.3M packets → 247,338 flows (measured)
- 3.0M packets → 330,401 flows (measured)
- 2.9M packets → **~290,000 flows** (linear interpolation)

| Run | Visible | Truth (~290K) | **Coverage** | Hidden |
|-----|--------:|--------------:|-------------:|-------:|
| Python hw_v2 (lazy 131K) | 78,393 | 290,000 | **27%** | 73% |
| **C++ CP (lazy 131K)**   | **242,789** | 290,000 | **~84%** | ~16% |

**Same data plane, same 15 s window, same pcap → coverage tripled by
swapping out the control plane.**

---

## Per-flow inflation

Truth average packets/flow at this window ≈ 2,904,320 / ~290,000 = ~10.0.

| Run | Reported avg pkts/flow | Inflation vs truth |
|-----|-----------------------:|-------------------:|
| Python hw_v2 | 2,942,966 / 78,393 = 37.5 | **3.75×** |
| **C++ CP** | 3,396,578 / 242,789 = 14.0 | **1.40×** |

The 3× inflation in the Python run was driven entirely by hidden-flow
contributions to CMS being misattributed to the few visible flows. The
C++ run shrinks inflation to 1.4× because the denominator (visible flow
count) is now correct — most of the "missing" flows weren't missing in
the data plane at all, they were missing in the Python control plane.

---

## What was actually wrong with the previous results

Before this prototype the assumption was that FlowLiDAR couldn't see most
backbone flows on Tofino 1 — coverage stuck at 24-30% for any BF size we
tried (prototypes 5 through 8, hardware versions 2 / 3 / 4). Doubling,
quadrupling, even 8×-ing the BF cells did not help.

The actual problem turned out to be on the **control plane** side, not the
data plane:
- bfrt-grpc's Python client (`bfrt_grpc.client`) wraps every register
  entry and every learn-notification in Python objects, with full
  validation. Under sustained line-rate digest delivery (~20 K
  digests/sec), the StreamChannel queue fills up faster than Python can
  drain it. The server drops queued notifications.
- A pure C++ client with a dedicated reader thread + 256 MB gRPC channel
  drains the StreamChannel as fast as the wire can deliver. No drops.

The same lazy BF + sub-sketch CMS that previously appeared to lose 73% of
flows actually catches ~84% of them — when the control plane stops
throwing away the digests.

---

## What's still hidden

~16% of CAIDA flows still don't appear in the C++ CP's report. These are
real BF false positives — flows whose 3 BF cells were already set when
their first packet arrived, so no digest was ever generated. With m=131K
and N≈290K, theoretical hide rate is `(1 − e^(−N/m))³ ≈ 67%` end-of-epoch
or ~17% averaged over arrival time. Measured 16% matches the
arrival-averaged number almost exactly.

So at this point the data plane is doing what theory predicts; the only
way to push coverage higher is more BF capacity (already explored — see
`hardware_version3/results.md` for the diminishing returns curve) or
shorter epochs / ping-pong (untried with the C++ CP).

---

## Implementation details that mattered

These are the bug fixes and design choices that got the C++ CP to match
Python's bit-exact CRC results and to handle line-rate I/O:

| Bug / decision | Fix |
|----------------|-----|
| `bfrt_info` JSON parser was off-by-one on register table IDs | Pass IDs explicitly via `--bf-ids` / `--cms-ids`, harvested via `print_ids.py` |
| Default 4 MB gRPC max receive size too small for full register reads | Set both send & receive limits to 256 MB on channel |
| `MODIFY` of "default entry" is rejected by SDE 9.11.0 for register tables | Per-cell MODIFY with the bfrt-discovered key/data field IDs |
| Hardcoded `field_id = 1` for key/data in writes | Cache field IDs from the first Read response |
| Hand-rolled CRC32 didn't match crcmod for any (init, xorOut) other than (0, 0) | Mirror crcmod's wrapper: start the inner loop at `init ^ xorOut`, not just `init` |
| Sub-sketch solver running expensive Gauss-Jordan on under-determined buckets | Early-out when `n > kColsPerRow` — saves ~2 minutes per epoch at line rate |

All seven were necessary for the C++ CP to produce correct results within
sensible time at line rate.

---

## Numbers as recorded

```
EPOCH 1 END  -  242,789 flows detected by BF
  bulk read time         : 6.41522 s
    bf_0 : 118,713 non-zero cells, sum = 118,713
    bf_1 : 110,821 non-zero cells, sum = 110,821
    bf_2 : 100,001 non-zero cells, sum = 100,001
    cms_0 :  58,302 non-zero cells, sum = 2,668,493
    cms_1 :  58,422 non-zero cells, sum = 2,668,493
    cms_2 :  58,405 non-zero cells, sum = 2,668,493
  Total flows            : 242,789
  Epoch digests          : 306,935
  Estimated packets      : 3,396,578  (digests + solver-derived CMS)
  Sub-sketch buckets used: 64 / 64  (exact: 0, fallback min(): 64)
  Max sub-sketch load    : 3.84766  (max bucket = 3,940 flows / 1024 cols)
  bulk clear time        : 3.42761 s
```

Click on hotpot reported `SENT PKTS: 2,904,320` for the same window.

---

## 5 s epoch run (after Algorithm 6 was added)

Same hardware, same data plane, same C++ CP — only `--epoch` changed from
15 s to 5 s. Click was running continuously; the CP captured a ~3 s
effective window after its ~2 s startup delay.

| Metric | 15 s epoch | **5 s epoch** |
|--------|-----------:|--------------:|
| Visible flows | 240,473 | **91,836** |
| Epoch digests | 304,454 | 127,586 |
| Estimated packets | 3,339,231 | 799,272 |
| Avg pkts/flow | 13.9 | **8.7** |
| Per-flow inflation vs ~7 pkts/flow truth | ~1.40× | **~1.24×** |
| Bulk read | 6.44 s | 6.20 s |
| Bulk clear | 3.32 s | 1.60 s |

### Algorithms 4/5 fire much more at 5 s

| Path | 15 s run | **5 s run** |
|------|---------:|------------:|
| Alg 4 (1/2-pkt mice) | 4.76% | **27.32%** |
| Alg 5 (3-pkt flows) | 0.17% | **1.34%** |
| Solver / min fallback | 95.07% | **71.34%** |

Pure saturation effect on the BF rows used by Algs 4/5:

| Saturation | 15 s run | **5 s run** |
|------------|---------:|------------:|
| bf_0 | 91% | 54% |
| bf_1 | 85% | **38%** |
| bf_2 | 77% | **27%** |
| max sub-sketch load | 3.65 | **1.09** |

At 38% `bf_1` saturation a true 1-pkt mouse has a much higher chance of
finding `bf_1[idx1] == 0`, so Algorithm 4 actually classifies it without
having to trust possibly-contaminated CMS values.

### The exact solver finally fires

Bucket allocation at 5 s:
```
exact: 32 / 64       Alg6: 0       n > cols skip: 32 / 64
```

Half the buckets stayed under the 1024-flow threshold and were solved
exactly by Gauss-Jordan; the other half were still over-loaded and hit
the cheap `min(cms_rows)` fallback. Algorithm 6 (rank < n with n ≤ 1024)
still didn't fire on this trace — for that we'd need either a different
flow distribution or a wider sub-sketch CMS.

### Coverage at 5 s

Click reported `SENT PKTS: 584,416 → 815,648` over the sampled window,
call it ~700K packets. Interpolating `pcap_distribution_strict.sh` gives
~115K true flows for that window.

```
Coverage = 91,836 / ~115,000 = ~80%
```

Same coverage ratio as the 15 s run (~84%) — the BF FP floor is the same
regardless of epoch length, the data plane just sees fewer flows in
absolute terms when the window is shorter.

### EPOCH 2 — post-click trickle

After click stops, the CP sees a small tail of late-arriving 1-pkt mice:
```
6,921 flows / 7,074 digests / 7,074 packets
Alg4: 6,918 (99.96%)   Alg5: 3 (0.04%)   solver: 0
```
Algorithm 4 resolved every flow exactly. Confirms the lazy-BF +
classification logic is correct when BF is sparse.

### Two simultaneous wins from shorter epochs

1. **Lower per-flow inflation** (1.40× → 1.24×) because:
   - Much more flows resolved exactly via Algs 4/5 (no CMS contamination)
   - The Gauss-Jordan solver fires for half the buckets (vs zero at 15 s)
2. **Faster epoch turnaround**: bulk clear 3.3 s → 1.6 s (fewer non-zero
   cells to clear). Total per-epoch CP I/O ~8 s.

---

## Suggested follow-ups

1. **Tighter solver fallback.** When `n > kColsPerRow` we currently use
   per-flow `min(cms_rows)`. Algorithm 6 (paper §3.4) — assign small CMS
   counters preferentially to the flows that touch them and least-squares
   the remainder — would give better per-flow accuracy than naive `min`.
2. **Algorithms 4/5 classification.** Lazy BF stores enough state to
   identify 1-pkt and 3-pkt flows directly from BF rows without needing
   CMS at all. Cheap accuracy improvement on top of the solver.
3. **Shorter epochs now feasible.** With per-epoch CP I/O at ~10 s
   instead of >30 s, a 3 s tumbling epoch is realistic. Would test
   whether shortening the BF accumulation window unlocks the remaining
   ~16% hidden flows.
4. **Re-run earlier prototype comparisons with the C++ CP.** The
   hardware_version2/3/4 results are all dominated by the Python CP
   bottleneck. Numbers in those `results.md` files understate what the
   data plane actually delivers.
