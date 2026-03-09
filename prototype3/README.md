# Prototype 3 — Bloom Filter + Count-Min Sketch

## Overview

Prototype 3 extends the Bloom Filter from Prototype 2 with a **Count-Min Sketch (CMS)** for per-flow packet counting in the data plane. Together they implement the complete **data-plane side of Algorithm 1** from the FlowLiDAR paper (Monterubbiano et al., ACM SIGMETRICS 2023).

The BF detects new flows and notifies the control plane via digest. The CMS counts every packet from every flow at line rate. At epoch boundaries the control plane reads both structures and reports per-flow packet count estimates.

---

## What Was Added Over Prototype 2

| Component | Description |
|-----------|-------------|
| **3 CMS register arrays** | `Register<bit<16>, bit<10>>(1024)` — 16-bit counter, 1K cells per row |
| **3 CRC hash functions** | CRC32D, CRC32/Q, CRC32/POSIX — distinct from BF polynomials for independence |
| **RegisterActions** | Unconditional atomic increment (`val = val + 1`) |
| **Combined CMS hash stage** | All 3 × 10-bit indices computed in one action (30 bits ≤ 32-bit pathway limit) |
| **control_plane.py extended** | Reads CMS registers at epoch end, computes min estimate per flow, clears all registers |

---

## Algorithm

For every IPv4 packet arriving at the switch:

```
1. Extract 5-tuple (src_ip, dst_ip, proto, src_port, dst_port)
2. Compute 3 BF hash indices (h0..h2, 17-bit) — stages 0–2
3. Atomically check-and-set bf_0[h0], bf_1[h1], bf_2[h2] — stages 3–5
   - If ANY returned old value was 0 → new flow → trigger digest
4. Compute 3 CMS hash indices (c0..c2, 10-bit) — stage 6
5. Atomically increment cms_0[c0], cms_1[c1], cms_2[c2] — stages 7–9
6. Forward packet via IPv4 LPM
```

At epoch end the control plane:

```
1. Collects all FlowIDs received via digest during the epoch
2. Reads cms_0, cms_1, cms_2 register arrays via bfrt gRPC
3. For each known flow: recompute CMS indices, take min(row0, row1, row2)
4. Report per-flow packet count estimates
5. Clear BF + CMS registers for the next epoch
```

---

## Parameters

### Bloom Filter (unchanged from Prototype 2)

| Parameter | Value |
|-----------|-------|
| k (hash functions) | 3 |
| m (bits per array) | 131,072 (2^17) |
| Total BF memory | 48 KB |

### Count-Min Sketch

| Parameter | Value | Note |
|-----------|-------|------|
| k (rows) | 3 | Matches BF k |
| m (cells per row) | 1,024 (2^10) | 10-bit addressing |
| Counter width | 16 bits | Saturates at 65,535 packets/epoch |
| Total CMS memory | 3 × 1K × 2B = 6 KB | — |

### CMS Hash Polynomials

| Row | Name | Polynomial | Reversed | Init | Residue |
|-----|------|------------|----------|------|---------|
| cms_0 | CRC32D | 0xA833982B | Yes | 0xFFFFFFFF | 0xFFFFFFFF |
| cms_1 | CRC32/Q | 0x814141AB | No | 0x00000000 | 0x00000000 |
| cms_2 | CRC32/POSIX | 0x04C11DB7 | No | 0x00000000 | 0xFFFFFFFF |

---

## Stage Allocation (Tofino 1, 12 ingress MAU stages)

```
Stage  0 : tbl_hash0      — BF idx0 (17-bit, CRC32)
Stage  1 : tbl_hash1      — BF idx1 (17-bit, CRC32/BZIP2)
Stage  2 : tbl_hash2      — BF idx2 (17-bit, CRC32C)
Stage  3 : bf_check_set_0 — BF row 0 check-and-set RegisterAction
Stage  4 : bf_check_set_1 — BF row 1 check-and-set RegisterAction
Stage  5 : bf_check_set_2 — BF row 2 check-and-set RegisterAction
Stage  6 : tbl_cms_hash   — CMS idx0/1/2 combined (30 bits ≤ 32-bit limit)
Stage  7 : cms_inc_0      — CMS row 0 increment RegisterAction
Stage  8 : cms_inc_1      — CMS row 1 increment RegisterAction
Stage  9 : cms_inc_2      — CMS row 2 increment RegisterAction
Stage 10 : free
Stage 11 : free
```

---

## Implementation Details

### CMS Hash: Combined Stage

Three 10-bit CMS indices sum to 30 bits, which fits within the 32-bit immediate pathway limit. All three `hash.get()` calls are combined into a single keyless table action at `@stage(6)`, avoiding the extra stages the BF hashes require (one per hash there, due to 17-bit × 2 = 34 > 32).

If the compiler rejects this with an immediate-pathway error, split into two tables at stages 6 and 7, shifting the CMS increments to stages 8–10.

### Control-Plane CRC Mapping

Tofino's `CRCPolynomial(poly, reversed, msb, extended, init, residue)` maps to crcmod as:

```
crcmod initCrc = P4_init XOR P4_residue
crcmod xorOut  = P4_residue
```

This was determined empirically by comparing Python-predicted indices against hardware register values with `debug_cms.py`.

### Epoch Clear Performance

Clearing registers via bfrt gRPC writes zeros to every cell individually in batches of 128. The BF rows (131,072 cells each) dominate — expect a few seconds of clearing time per epoch. This happens after the report is printed so it does not affect measurement accuracy.

---

## File Structure

```
prototype3/
├── prototype3.p4       # P4-16 data plane (BF + CMS, Tofino/TNA)
├── build.sh            # Build script (cmake + make)
├── setup_table.py      # Adds LPM forwarding entry (run via bfshell)
├── reset_epoch.py      # Clears BF + CMS registers (run via bfshell)
├── control_plane.py    # Standalone Python: digests + epoch CMS report
├── test_packet.py      # Scapy test: verifies BF suppression and CMS counts
└── debug_cms.py        # Debug: scans raw CMS registers, compares with Python CRC predictions
```

---

## How to Run

### Prerequisites

- SDE 9.13.4 at `$SDE` / `$SDE_INSTALL`
- veth interfaces created (once per boot):
  ```bash
  sudo $SDE_INSTALL/bin/veth_setup.sh
  ```
- Python packages:
  ```bash
  pip3 install --upgrade protobuf crcmod
  ```

---

### Step 0 — Kill stale processes

```bash
sudo pkill -f tofino-model; sudo pkill -f bf_switchd; sleep 2
```

---

### Step 1 — Build (only after code changes)

```bash
cd /home/student/Desktop/flowlidar/prototype3
./build.sh
```

Success ends with:
```
[100%] Built target prototype3-tofino
Install the project...
```

---

### Step 2 — Terminal A: Start the Tofino model

```bash
sudo -E $SDE/run_tofino_model.sh -p prototype3
```

Wait for:
```
CLI listening on port 8000
```

---

### Step 3 — Terminal B: Start switchd

```bash
sudo -E $SDE/run_switchd.sh -p prototype3
```

Wait for:
```
bfruntime gRPC server started on 0.0.0.0:50052
```

---

### Step 4 — Terminal B: Add forwarding table entry

At the `bfshell>` prompt in the same terminal:

```
bfrt_python /home/student/Desktop/flowlidar/prototype3/setup_table.py
```

Output ends with:
```
Setup complete. Run control_plane.py to receive flow digests and CMS reports.
```

---

### Step 5 — Terminal C: Start the control plane

```bash
python3 /home/student/Desktop/flowlidar/prototype3/control_plane.py --epoch 30
```

Output:
```
================================================================
  FlowLiDAR Prototype 3 — Control Plane
  Connecting to localhost:50052 ...
  Epoch length : 30.0s
================================================================
Connected. Waiting for packets...
```

---

### Step 6 — Terminal D: Send test packets

```bash
sudo python3 /home/student/Desktop/flowlidar/prototype3/test_packet.py
```

**Expected output in Terminal C** as packets arrive:

```
[   1] NEW FLOW  10.1.0.1:1000 -> 10.0.0.1:80  TCP  (digest #1)
[   2] NEW FLOW  10.1.0.2:2000 -> 10.0.0.1:80  TCP  (digest #1)
[   3] NEW FLOW  10.1.0.3:3000 -> 10.0.0.1:80  TCP  (digest #1)
[   4] NEW FLOW  10.1.0.4:4000 -> 10.0.0.1:443 TCP  (digest #1)
[   5] NEW FLOW  10.1.0.5:5000 -> 10.0.0.1:53  UDP  (digest #1)
[   6] NEW FLOW  10.1.0.6:6000 -> 10.0.0.1:53  UDP  (digest #1)
```

Exactly 6 notifications — subsequent packets from the same flows are suppressed by the BF.

**At epoch end** (after 30 s, or press Ctrl-C for immediate):

```
================================================================
  EPOCH 1 END  —  6 flows detected by BF
================================================================
  Reading CMS registers...

  Flow                                         Digests  CMS est.
  -------------------------------------------- -------  --------
  10.1.0.1:1000 -> 10.0.0.1:80 TCP                   1        12
  10.1.0.2:2000 -> 10.0.0.1:80 TCP                   1         6
  10.1.0.3:3000 -> 10.0.0.1:80 TCP                   1         3
  10.1.0.4:4000 -> 10.0.0.1:443 TCP                  1         2
  10.1.0.5:5000 -> 10.0.0.1:53 UDP                   1         2
  10.1.0.6:6000 -> 10.0.0.1:53 UDP                   1         2

  Clearing BF + CMS registers for next epoch...
================================================================
```

With only 6 flows and 1K counters per row, hash collisions are negligible (~0.5% per row), so estimates are exact.

---

### Manual Epoch Reset (optional)

To clear BF + CMS without waiting for the timer, run in Terminal B at `bfshell>`:

```
bfrt_python /home/student/Desktop/flowlidar/prototype3/reset_epoch.py
```

---

### Debugging CMS Register Values

If CMS estimates look wrong, use the debug script **before** the epoch timer clears the registers:

```bash
python3 /home/student/Desktop/flowlidar/prototype3/debug_cms.py
```

This prints:
1. Raw bfrt dict structure for the first few register entries
2. All non-zero cells in each CMS row (actual hardware state)
3. Python-predicted indices for each test flow (should match Part 2)

---

## What's Next

**Prototype 4** adds the **Lazy Bloom Filter** (Algorithm 2 from the paper), replacing the Standard BF with a structure that avoids the false-positive problem at high flow rates by deferring bit-set operations.
