# Prototype 2 — Standard Bloom Filter with Flow Digest

## Overview

Prototype 2 extends the IPv4 LPM forwarder from Prototype 1 with the **Standard
Bloom Filter** described in Algorithm 1 of the FlowLiDAR paper (Monterubbiano
et al., ACM SIGMETRICS 2023).

The data plane detects **new flows** at line rate and notifies the control plane
via a **digest** mechanism.  Already-seen flows are suppressed entirely in
hardware — zero control-plane overhead per packet.

---

## What Was Added Over Prototype 1

| Component | Description |
|-----------|-------------|
| **3 BF register arrays** | `Register<bit<1>, bit<17>>(131072)` — one bit per cell, 128K cells per array |
| **3 CRC hash functions** | Different CRC32 polynomials (CRC32, CRC32/BZIP2, CRC32C) produce independent 17-bit indices |
| **RegisterActions** | Atomic check-and-set: reads old bit value, then unconditionally sets it to 1 |
| **flow_digest_t struct** | Carries the 5-tuple (src IP, dst IP, protocol, src port, dst port) to the control plane |
| **Digest** | `Digest<flow_digest_t>()` in the deparser triggers a gRPC notification to the control plane |
| **metadata_t extended** | Added `src_port`, `dst_port`, and three 17-bit hash indices `idx0`–`idx2` |
| **Hash stage tables** | Three keyless tables (`tbl_hash0`–`tbl_hash2`), each `@stage` annotated, to stay within Tofino's 32-bit immediate-pathway limit per stage |
| **control_plane.py** | Standalone Python script receiving and printing flow digests over gRPC |
| **reset_epoch.py** | Clears all 3 BF arrays to start a new measurement epoch (run via bfshell) |

---

## Algorithm

This implements **Algorithm 1 (Standard BF)** from the paper.

For every IPv4 packet arriving at the switch:

```
1. Extract 5-tuple (src_ip, dst_ip, proto, src_port, dst_port)
2. Compute 3 independent hash indices h0..h2 over the 5-tuple
3. Atomically check-and-set bf_0[h0], bf_1[h1], bf_2[h2]
   - Each RegisterAction returns the OLD value (0 = absent, 1 = present)
   - Unconditionally writes 1 (marks as present)
4. If ANY returned value was 0 → new flow → trigger digest to control plane
   If ALL returned values were 1 → known flow → suppress (no action)
5. Forward packet via IPv4 LPM (same as Prototype 1)
```

The control plane receives the 5-tuple and records it.

---

## Bloom Filter Parameters

| Parameter | Value | Note |
|-----------|-------|------|
| k (hash functions) | 3 | Reduced from paper's k=4 to free 2 MAU stages for CMS (Prototype 3) |
| m (bits per array) | 131,072 (2^17) | Paper Section 5 |
| Total BF memory | 3 × 128 Kbits = 48 KB | — |
| Hash index width | 17 bits | log2(131072) |

### Why k=3 instead of k=4

The paper specifies k=4, but Tofino 1 has only 12 ingress MAU stages. Each
`RegisterAction.execute()` consumes one stage exclusively (stateful ALU
constraint). With k=4 BF arrays + 4 CMS rows, all 12 stages are consumed with
zero slack, leaving no room for future additions (e.g. Lazy BF in Prototype 4).

Reducing to k=3 frees 2 stages (1 hash + 1 register execute), giving the
following budget for Prototype 3 onwards:

```
Stage  0 : tbl_hash0  (LPM table shares via TCAM)
Stage  1 : tbl_hash1
Stage  2 : tbl_hash2
Stage  3 : bf_check_set_0.execute()
Stage  4 : bf_check_set_1.execute()
Stage  5 : bf_check_set_2.execute()
Stage  6 : cms_inc_0.execute()   ← Prototype 3
Stage  7 : cms_inc_1.execute()   ← Prototype 3
Stage  8 : cms_inc_2.execute()   ← Prototype 3
Stage  9 : cms_inc_3.execute()   ← Prototype 3
Stage 10 : free
Stage 11 : free
```

### False Positives

A false positive occurs when a **new** flow has all 3 of its hash positions
already set to 1 by previously-seen flows.  The BF then treats it as known and
**suppresses** the digest — the control plane misses that flow for this epoch.

False negatives are **impossible**: once a flow's 3 bits are set, every
subsequent packet from that flow is correctly suppressed.

Approximate false positive rate with n flows inserted:

```
p ≈ (1 - e^(-3n / 131072))^3
```

| Flows (n) | k=3 (this impl) | k=4 (paper) | Better |
|-----------|-----------------|-------------|--------|
| 1,000     | ~0.001%         | ~0.00008%   | k=4    |
| 10,000    | ~0.86%          | ~0.48%      | k=4    |
| 27,000    | ~8%             | ~8%         | equal (crossover) |
| 50,000    | ~32%            | ~38%        | k=3    |

At low-to-moderate loads k=4 wins because four independent checks give stronger
discrimination.  Above ~27K flows per epoch k=3 wins because it sets fewer bits
per flow and therefore fills the filter more slowly — the optimal k at that load
is `(m/n)·ln2 = (131072/50000)·0.693 ≈ 1.82`, so k=3 is closer to optimal
than k=4.  In practice, the epoch reset is the primary mechanism for keeping
n — and therefore the FP rate — low.

---

## Implementation Details

### Tofino Constraint: 32-bit Immediate Pathway

The Tofino compiler limits hash output through the "immediate" pathway to **32
bits per MAU stage**.  With 17-bit indices, only one hash fits per stage
(17 ≤ 32; 2 × 17 = 34 > 32).

Putting all four `hash.get()` calls inline in one block caused the compiler
error:

```
error: number of bits required to go through the immediate pathway 56 is
greater than the available bits 32
```

**Fix:** each hash is computed in its own keyless table action annotated with
`@stage(0)` through `@stage(2)`.  The result is stored in metadata
(`ig_md.idx0`–`ig_md.idx2`) and consumed by the RegisterActions in later
stages.

### Condition Constraint: One Operand Must Be Constant

ANDing multiple runtime 1-bit values in a single condition:

```p4
if ((b0 & b1 & b2) == 0) { ... }  // compiler error
```

was rejected as "condition too complex".  **Fix:** three separate comparisons,
each comparing one runtime value to the constant `0`:

```p4
if (b0 == 0) { ig_dprsr_md.digest_type = 1; }
if (b1 == 0) { ig_dprsr_md.digest_type = 1; }
if (b2 == 0) { ig_dprsr_md.digest_type = 1; }
```

### Digest Mechanism

`Digest<flow_digest_t>()` is declared in the deparser.  Setting
`ig_dprsr_md.digest_type = 1` in the ingress control triggers the deparser to
pack and send the flow 5-tuple to the control plane via the bfruntime gRPC
channel on port 50052.

---

## File Structure

```
prototype2/
├── prototype2.p4       # P4-16 data plane program (Tofino/TNA)
├── build.sh            # Build script (cmake + make)
├── setup_table.py      # Adds LPM forwarding entry (run via bfshell)
├── reset_epoch.py      # Clears all 3 BF arrays (run via bfshell)
├── control_plane.py    # Standalone Python: receives flow digest notifications
└── test_packet.py      # Scapy test: sends packets, verifies BF behaviour
```

Shared files (from project root):
```
common/
├── headers.p4          # Ethernet, IPv4, TCP, UDP header definitions
└── util.p4             # TofinoIngressParser, EmptyEgress*, etc.
```

---

## How to Run

### Prerequisites

- SDE 9.13.4 at `$SDE` / `$SDE_INSTALL` (set in shell config, verified with `echo $SDE`)
- veth interfaces created (run once per boot):
  ```bash
  sudo $SDE_INSTALL/bin/veth_setup.sh
  ```
- `protobuf` Python package version ≥ 3.20 (needed by control_plane.py):
  ```bash
  pip3 install --upgrade protobuf
  ```

---

### Step 0 — Kill stale processes

Always run this before starting a new session:

```bash
sudo pkill -f tofino-model; sudo pkill -f bf_switchd; sleep 2
```

---

### Step 1 — Build (only needed after code changes)

```bash
cd /home/student/Desktop/flowlidar/prototype2
./build.sh
```

A successful build ends with:
```
[100%] Built target prototype2-tofino
Install the project...
```

---

### Step 2 — Terminal A: Start the Tofino model

```bash
sudo -E $SDE/run_tofino_model.sh -p prototype2
```

Wait for:
```
Blocking on message from CPU
```

---

### Step 3 — Terminal B: Start switchd

```bash
sudo -E $SDE/run_switchd.sh -p prototype2
```

Wait for:
```
bfruntime gRPC server started on 0.0.0.0:50052
```

---

### Step 4 — Terminal B: Add forwarding table entry

At the `bfshell>` prompt in the same terminal:

```
bfrt_python /home/student/Desktop/flowlidar/prototype2/setup_table.py
```

This adds the route `10.0.0.1/32 → port 1`.  Output ends with:
```
Setup complete. Run control_plane.py to receive flow digests.
```

---

### Step 5 — Terminal C: Start the control plane

```bash
python3 /home/student/Desktop/flowlidar/prototype2/control_plane.py
```

The script connects to switchd on port 50052 and blocks, printing a line for
each new-flow digest it receives.

---

### Step 6 — Terminal D: Send test packets

```bash
sudo python3 /home/student/Desktop/flowlidar/prototype2/test_packet.py
```

Expected output in **Terminal C**:

```
[   1] NEW FLOW  10.1.0.1:1000 -> 10.0.0.1:80  TCP  (seen 1x)
[   2] NEW FLOW  10.1.0.2:2000 -> 10.0.0.1:80  TCP  (seen 1x)
[   3] NEW FLOW  10.1.0.3:3000 -> 10.0.0.1:80  TCP  (seen 1x)
[   4] NEW FLOW  10.1.0.4:4000 -> 10.0.0.1:443  TCP  (seen 1x)
[   5] NEW FLOW  10.1.0.5:5000 -> 10.0.0.1:53  UDP  (seen 1x)
[   6] NEW FLOW  10.1.0.6:6000 -> 10.0.0.1:53  UDP  (seen 1x)
```

6 total notifications — repeated flows are correctly suppressed.

---

### Epoch Reset

To clear the BF and start a new measurement epoch, run in Terminal B at the
`bfshell>` prompt:

```
bfrt_python /home/student/Desktop/flowlidar/prototype2/reset_epoch.py
```

After a reset, all previously-seen flows will be reported as new again.

---

## What's Next

**Prototype 3** adds a **Count-Min Sketch** to count packets per flow in the
data plane.  Together with the BF, this allows the control plane to reconstruct
exact per-flow packet counts at epoch boundaries.
