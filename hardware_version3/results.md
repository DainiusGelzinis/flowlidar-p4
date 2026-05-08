# FlowLiDAR Prototype 7 (Hardware Version 3) — Epoch 1 Results on Real Tofino 1

Same setup as `hardware_version2/`, only the Bloom Filter is doubled:
- 3 × **262144** × 1 bit (was 3 × 131072 in prototype6 / hw_v2)
- 18-bit BF index (was 17-bit)
- CMS sub-sketches unchanged (64 × 1024 cells per row)

Switch: p4switch2 (Tofino 1, SDE 9.11.0)
Traffic: hotpot replaying CAIDA `equinix-nyc.dirA.20190117-130000` at 1 Gbps
Pipe id: 1
There is a ~2 s startup delay between launching the control plane and click,
so effective traffic time ≈ epoch − 2 s.

---

## Epoch 1 results

| Run | Epoch | Effective traffic | Flows | Digests | Est. packets | Alg4 | Alg5 | Solver | Max load | Under-det |
|-----|-------|-------------------|-------|---------|-------------:|------|------|--------|----------|-----------|
| 5s  | 5s    | ~3s               | 13,861 |  18,050 |   319,608 | 44.0% |  7.8% | 48.2% | 0.130 | 0 |
| 15s | 15s   | ~13s              | 76,522 | 109,934 | 2,295,120 | 40.2% | 11.5% | 48.3% | 0.647 | 0 |

All sub-systems exact-solved (`underdetermined: 0`) in every run.

---

## Ground truth (tshark, exact 5-tuple count)

### 15s window — first 2,300,000 packets

| Class | Count | % |
|-------|-------|---|
| 1-pkt | 171,792 | 65.1% |
| 2-pkt |  24,874 |  9.4% |
| 3-pkt |  11,688 |  4.4% |
| 4-10 pkt |  37,752 | 14.3% |
| 11-100 pkt |  14,784 |  5.6% |
| 101+ pkt |   3,162 |  1.2% |
| **Total flows** | **264,052** | |
| **Avg pkts/flow** | **8.71** | |

**FlowLiDAR equivalents (no FP):** Alg4 candidates 74.5%, Alg5 4.4%, Solver 21.1%

---

## Truth vs hw_v3 — coverage and accuracy (15 s run)

| Metric | Truth | hw_v3 measured |
|--------|------:|---------------:|
| Total flows | 264,052 | 76,522 |
| **Coverage** | — | **29.0%** |
| Hidden flows | — | 187,530 (**71.0%**) |
| Total packets | 2,300,000 | 2,295,120 (**−0.2%**) |
| Avg pkts/flow | 8.71 | 30.0 |
| **Per-flow inflation** | — | **3.44×** |
| Alg4 candidates | 74.5% (true mice) | 40.2% reported |
| Alg5 candidates | 4.4% | 11.5% reported |
| Solver candidates | 21.1% | 48.3% reported |

---

## Comparison vs hardware_version2 (Run A, 15 s)

| Metric | hw_v2 Run A | **hw_v3** | Δ |
|--------|------------:|----------:|---|
| Coverage | 23.7% | **29.0%** | **+5.3 pp** (+22% rel.) |
| Per-flow inflation | 4.13× | **3.44×** | **−17%** |
| Alg4 reported | 13.8% | **40.2%** | +26 pp |
| Solver % reported | 75.9% | 48.3% | −28 pp |
| Max sub-sketch load | 0.987 | 0.647 | −34% |
| Total packets sent | 2,942,966 | 2,295,120 | hw_v3 sent ~22% less (click variance) |
| Total packet est. accuracy | −2% | −0.2% | both excellent |

---

## Interpretation

1. **Doubling the BF helped, but not as much as theory predicted.** A 2× larger
   BF should drop the false-positive rate by ~3× at our load — that would have
   pushed coverage from ~24% to ~75%. We only got 29%.

2. **Total packet count remains essentially exact** (−0.2%). The CMS-based
   packet estimator is trustworthy regardless of BF saturation.

3. **Mice classifier now firing at all.** Alg4 went from 13.8% to 40.2% of
   reported flows — the bigger BF is enough to keep many mice visible during
   their first packet. But we're still well below the truth (74.5% are mice),
   meaning ~half the mice are still hidden.

4. **The gap between measured (71% hidden) and theoretical (~25% hidden)** is
   the headline anomaly. Most likely cause: BF hash poly0 and poly1 share the
   *same generator polynomial* `0x04C11DB7` (only the bit reversal differs),
   so the two hashes are correlated. Effective k ≈ 2 instead of 3.

5. **Sub-sketch load is comfortable** (0.647 vs hw_v2's 0.987). The CMS is no
   longer near-saturated and Algorithm 6 fallback is never needed.

---

## Implications for the next prototype

- **Replace BF poly1** with a genuinely different generator polynomial
  (e.g. `0xA833982B` / CRC-32D). One-line change in the P4 file plus the
  matching crcmod entry in `control_plane.py`. Expected effect: coverage
  jumps toward 50–60% if hash correlation was the dominant problem.
- If poly1 fix alone doesn't move coverage materially, the next levers are
  (in order of expected impact): ping-pong epochs (Algorithm 3), shorter
  epoch length, k=4 BF rows.
