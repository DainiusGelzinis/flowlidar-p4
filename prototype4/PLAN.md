# Prototype 4 — Lazy Updates Bloom Filter (Algorithm 2)

## Goal

Replace the Standard BF (Algorithm 1) with the **Lazy Updates BF (Algorithm 2)**
from the paper. This is the central innovation of FlowLiDAR that:

1. Reduces the false positive rate by setting fewer bits per flow
2. Eliminates the need for CMS counters for flows with ≤ k packets
3. Enables the control plane to reconstruct exact counts for small flows
   directly from the digest count — no equation solving needed for those

---

## Algorithm 2 vs Algorithm 1

### Algorithm 1 (Standard BF — Prototype 3)

```
For packet with FlowID x:
  h0 = bf_hash0(x);  h1 = bf_hash1(x);  h2 = bf_hash2(x)
  b0 = bf_0[h0];  bf_0[h0] = 1       ← always check-and-set all 3
  b1 = bf_1[h1];  bf_1[h1] = 1
  b2 = bf_2[h2];  bf_2[h2] = 1
  if (b0 == 0 OR b1 == 0 OR b2 == 0):
      send digest                      ← new flow — 1 digest ever
  else:
      increment CMS[h_cms_i(x)]       ← known flow — all subsequent packets
```

First packet: sets all 3 bits, sends 1 digest.
Second packet: all 3 bits already 1, goes straight to CMS.

### Algorithm 2 (Lazy Updates BF — Prototype 4)

```
For packet with FlowID x:
  h0 = bf_hash0(x);  h1 = bf_hash1(x);  h2 = bf_hash2(x)
  b0 = bf_0[h0]
  if b0 == 0:
      bf_0[h0] = 1                     ← set ONLY bit 0
      send digest                      ← packet 1 of new flow
  else:
      b1 = bf_1[h1]                    ← only check if b0 was 1
      if b1 == 0:
          bf_1[h1] = 1                 ← set ONLY bit 1
          send digest                  ← packet 2
      else:
          b2 = bf_2[h2]                ← only check if b0,b1 were 1
          if b2 == 0:
              bf_2[h2] = 1             ← set ONLY bit 2
              send digest              ← packet 3
          else:
              increment CMS[h_cms_i(x)]  ← packet 4+ (truly known)
```

Packet 1: sets only bit 0, sends digest.
Packet 2: bit 0 is 1, sets only bit 1, sends digest.
Packet 3: bits 0,1 are 1, sets only bit 2, sends digest.
Packet 4+: all 3 bits are 1, goes to CMS.

**Key property:** flows with ≤ k=3 packets never touch the CMS.
Their exact count = number of digests received on the control plane.

---

## Why This Reduces False Positives

With k=3 flows, a flow with n=1 packet inserts 1 bit (not 3). Table 1 from the
paper shows ~39% of flows have exactly 1 packet. This means the BF fills ~40%
slower, giving a significantly lower false positive rate at the same memory size.

The false positive probability for the lazy BF is:
```
P_a(i) ≈ ∏_{j=1}^{k} (1 - e^{-i·l(j)/m})
```
where l(j) = fraction of flows with j or more packets (Eq. 3 in the paper).
This is strictly lower than the standard BF formula for any non-trivial traffic.

---

## P4 Implementation Plan

### Challenge: Sequential Dependency

In Algorithm 2, whether to check bf_1 depends on the result of checking bf_0.
This is a data dependency: you cannot pipeline these checks unconditionally.

In Prototype 3, all three `bf_check_set_i.execute()` calls are unconditional.
In Prototype 4, execution of bf_1 and bf_2 must be conditional on prior results.

### Solution: Conditional Table Execution

Tofino can conditionally execute a RegisterAction by placing it inside a table
that matches on metadata from a previous stage. If the match misses (no default
action that calls execute), the register is not touched.

```p4
// Stage 3: ALWAYS execute bf_0 — returns old bit, unconditionally sets to 1
RegisterAction<bit<1>, bit<17>, bit<1>>(bf_0) bf_lazy_0 = {
    void apply(inout bit<1> val, out bit<1> rv) {
        rv = val;
        val = 1;
    }
};
action run_bf0() { ig_md.b0 = bf_lazy_0.execute(ig_md.idx0); }
@stage(3) table tbl_bf0 { ... }   // no key, always applied

// Stage 4: execute bf_1 ONLY if b0 == 1
RegisterAction<bit<1>, bit<17>, bit<1>>(bf_1) bf_lazy_1 = {
    void apply(inout bit<1> val, out bit<1> rv) {
        rv = val;
        val = 1;
    }
};
action run_bf1() { ig_md.b1 = bf_lazy_1.execute(ig_md.idx1); }
action skip_bf1() { ig_md.b1 = 0; }   // b0 was 0, already found new flow
@stage(4) table tbl_bf1 {
    key = { ig_md.b0 : exact; }
    actions = { run_bf1; skip_bf1; }
    // entry: b0=1 → run_bf1;  default_action: skip_bf1
}

// Stage 5: execute bf_2 ONLY if b0 == 1 AND b1 == 1
action run_bf2() { ig_md.b2 = bf_lazy_2.execute(ig_md.idx2); }
action skip_bf2() { ig_md.b2 = 0; }
@stage(5) table tbl_bf2 {
    key = { ig_md.b0 : exact; ig_md.b1 : exact; }
    actions = { run_bf2; skip_bf2; }
    // entry: b0=1, b1=1 → run_bf2;  default_action: skip_bf2
}
```

The `skip_bf1` and `skip_bf2` actions set the metadata bit to 0. This ensures
the digest and CMS logic downstream sees the correct signal:

```
send digest    if NOT (b0==1 AND b1==1 AND b2==1)   [same condition as Alg 1]
increment CMS  if      b0==1 AND b1==1 AND b2==1    [same condition as Alg 1]
```

The bit-set logic differs (only the first-zero bit is set), but the downstream
logic is identical to Prototype 3. The setup_table.py must add the two entries
to tbl_bf1 and tbl_bf2.

### Stage Allocation

```
Stage  0 : tbl_hash0       — BF idx0 (17-bit, CRC32)
Stage  1 : tbl_hash1       — BF idx1 (17-bit, CRC32/BZIP2)
Stage  2 : tbl_hash2       — BF idx2 (17-bit, CRC32C)
Stage  3 : tbl_bf0         — always: check-and-set bf_0, store b0
Stage  4 : tbl_bf1         — conditional on b0==1: check-and-set bf_1
Stage  5 : tbl_bf2         — conditional on b0==1 AND b1==1: check-and-set bf_2
Stage  6 : tbl_cms_hash    — CMS idx0/1/2 combined
Stage  7 : cms_inc_0       — conditional on b0==b1==b2==1
Stage  8 : cms_inc_1       — conditional
Stage  9 : cms_inc_2       — conditional
Stage 10 : free
Stage 11 : free
```

Same 10 stages as Prototype 3. The paper reports +3 stages on Tofino 2 due to
stricter dependency scheduling; on Tofino 1 the conditional tables may be placed
in the same stages as the RegisterActions.

### CMS Increment — Conditional Execution

In Prototype 3 the CMS is incremented unconditionally (all packets).
In Prototype 4 it must only fire when b0==b1==b2==1. Wrap each `cms_inc_i`
inside a table that matches on the "all known" condition:

```p4
action do_cms_inc_0() { cms_inc_0.execute(ig_md.cms_idx0); }
action nop_cms_0() {}
table tbl_cms_0 {
    key = { ig_md.b0 : exact; ig_md.b1 : exact; ig_md.b2 : exact; }
    actions = { do_cms_inc_0; nop_cms_0; }
    // entry: 1,1,1 → do_cms_inc_0;  default_action: nop_cms_0
}
```

### setup_table.py Changes

In addition to the LPM route, setup_table.py must now add:
- 1 entry to tbl_bf1: key=(b0=1) → action run_bf1
- 1 entry to tbl_bf2: key=(b0=1, b1=1) → action run_bf2
- 1 entry each to tbl_cms_0/1/2: key=(1,1,1) → action do_cms_inc_i

---

## Control Plane Changes

### Exact Count Formula

With the lazy BF, the control plane estimate for each flow becomes:

```
exact_count = digest_count + min(cms_0[i0], cms_1[i1], cms_2[i2])
```

This works because:
- The first k=3 packets each generate a digest (digest_count captures them)
- Packets 4+ go to the CMS (cms estimate captures them)
- Together they sum to the exact total with no collision bias on the digest part

This is a simple one-line change to the epoch report in `process_epoch()`:

```python
estimate = digest_count + min(counts)   # was: min(counts)
```

No equation solver needed for correct results on these test flows.

---

## File Structure

```
prototype4/
├── PLAN.md             ← this file
├── prototype4.p4       # Lazy BF (Algorithm 2) + CMS — conditional execution
├── build.sh            # cmake + make (same pattern as prototype3)
├── setup_table.py      # LPM route + tbl_bf1/bf2/cms_0/1/2 entries
├── reset_epoch.py      # Clears bf_0..2 and cms_0..2 (same as prototype3)
├── control_plane.py    # Epoch report: estimate = digest_count + min(cms rows)
└── test_packet.py      # Verifies lazy BF: expects up to k=3 digests per flow
```

---

## Expected Test Outcomes

The test packet sequence (same as prototype3) sends:
- Test 1: 1 packet each for 6 flows
- Test 2: 10 more for Flow A  (total A = 11 after Test 2)
- Test 3: 4 more for Flow B   (total B = 5)
- Test 4: 1 more for Flow C   (total C = 2)
- Test 5: 1 each for all 6 flows (re-send)

Final totals: A=12, B=6, C=3, D=2, E=2, F=2

### Digest Notifications (Terminal C)

With lazy BF (k=3), each new flow generates a digest for each of its first
k=3 packets. Expected notifications:

```
[   1] NEW FLOW  10.1.0.1:1000 -> 10.0.0.1:80  TCP  (digest #1)  ← A pkt 1
[   2] NEW FLOW  10.1.0.2:2000 -> 10.0.0.1:80  TCP  (digest #1)  ← B pkt 1
[   3] NEW FLOW  10.1.0.3:3000 -> 10.0.0.1:80  TCP  (digest #1)  ← C pkt 1
[   4] NEW FLOW  10.1.0.4:4000 -> 10.0.0.1:443 TCP  (digest #1)  ← D pkt 1
[   5] NEW FLOW  10.1.0.5:5000 -> 10.0.0.1:53  UDP  (digest #1)  ← E pkt 1
[   6] NEW FLOW  10.1.0.6:6000 -> 10.0.0.1:53  UDP  (digest #1)  ← F pkt 1
[   7] NEW FLOW  10.1.0.1:1000 -> 10.0.0.1:80  TCP  (digest #2)  ← A pkt 2
[   8] NEW FLOW  10.1.0.1:1000 -> 10.0.0.1:80  TCP  (digest #3)  ← A pkt 3
[   9] NEW FLOW  10.1.0.2:2000 -> 10.0.0.1:80  TCP  (digest #2)  ← B pkt 2
[  10] NEW FLOW  10.1.0.2:2000 -> 10.0.0.1:80  TCP  (digest #3)  ← B pkt 3
[  11] NEW FLOW  10.1.0.3:3000 -> 10.0.0.1:80  TCP  (digest #2)  ← C pkt 2
[  12] NEW FLOW  10.1.0.3:3000 -> 10.0.0.1:80  TCP  (digest #3)  ← C pkt 3 (Test 5)
[  13] NEW FLOW  10.1.0.4:4000 -> 10.0.0.1:443 TCP  (digest #2)  ← D pkt 2 (Test 5)
[  14] NEW FLOW  10.1.0.5:5000 -> 10.0.0.1:53  UDP  (digest #2)  ← E pkt 2 (Test 5)
[  15] NEW FLOW  10.1.0.6:6000 -> 10.0.0.1:53  UDP  (digest #2)  ← F pkt 2 (Test 5)
```

Total: **15 digests** (vs 6 in Prototype 3).

- Flows A, B: digest_count = 3 (packets 1–3 each generated a digest)
- Flow C: digest_count = 3 (pkt1=Test1, pkt2=Test4, pkt3=Test5)
- Flows D, E, F: digest_count = 2 (only 2 packets total, 2 bits set, never reach 3)

### Epoch Report

```
================================================================
  EPOCH 1 END  —  6 flows detected by BF
================================================================
  Reading CMS registers...

  Flow                                         Digests  CMS est.   Total
  -------------------------------------------- -------  --------   -----
  10.1.0.1:1000 -> 10.0.0.1:80 TCP                   3         9      12
  10.1.0.2:2000 -> 10.0.0.1:80 TCP                   3         3       6
  10.1.0.3:3000 -> 10.0.0.1:80 TCP                   3         0       3
  10.1.0.4:4000 -> 10.0.0.1:443 TCP                  2         0       2
  10.1.0.5:5000 -> 10.0.0.1:53 UDP                   2         0       2
  10.1.0.6:6000 -> 10.0.0.1:53 UDP                   2         0       2
================================================================
```

Key observations that prove the lazy BF is working:
1. **Digest count reaches 3** for A, B, C (not 1 as in prototype3)
2. **CMS count = 0** for flows C, D, E, F — they never touched the CMS
3. **Total = digest + CMS** is exact for all flows
4. Flow C's 3rd digest arrives during Test 5, not Test 4

### CMS Register Verification (debug_cms.py)

After sending packets but before the epoch clears:
- `cms_0`, `cms_1`, `cms_2` should each have exactly **2 non-zero cells**
  (only Flows A and B have > k=3 packets and thus have CMS counts)
- Flow A: 9 at each of its 3 CMS indices
- Flow B: 3 at each of its 3 CMS indices
- Flows C, D, E, F: **all zeros** in the CMS

This is the strongest proof of correctness: 4 out of 6 flows leave no trace
in the CMS because all their packets were counted via digest.

---

## What This Prototype Does NOT Yet Include

- **BF preprocessing (Algorithm 4):** querying the BF snapshot to identify
  flows whose count is purely from digests. Prototype 4 uses digest_count
  directly, which is correct for this test but not for real traffic where
  flows with < k packets may have collided in the BF.

- **Equation solver (Algorithm 5 + §3.4.2):** not needed for exact results
  on 6 test flows, but required for correctness under hash collisions.
  Planned for Prototype 5.

- **Scaled-up parameters:** the paper's full implementation uses 4×128K BF
  and 64×1K CMS. Prototype 4 keeps k=3, m=128K BF and 3×1K CMS to match
  the hardware budget and keep tests simple.

---

## Verification Checklist

- [ ] Build succeeds (no compiler errors on conditional table structure)
- [ ] 15 digest notifications received (not 6)
- [ ] Flows A, B, C show digest_count = 3
- [ ] Flows D, E, F show digest_count = 2
- [ ] CMS non-zero cells: exactly 2 flows (A and B) with counts 9 and 3
- [ ] Flows C, D, E, F show CMS count = 0
- [ ] Total estimate = digest_count + cms_min = exact for all 6 flows
- [ ] Re-running test_packet.py after reset: same 15 digests (BF cleared)
