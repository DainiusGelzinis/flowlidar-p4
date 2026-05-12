# Prototype 4 — Lazy Updates Bloom Filter + Count-Min Sketch

## Overview

Prototype 4 replaces the Standard Bloom Filter from Prototype 3 with the **Lazy Updates BF** (Algorithm 2 from the FlowLiDAR paper, Monterubbiano et al., ACM SIGMETRICS 2023). The CMS remains unchanged.

The key difference: instead of setting all k BF bits at once on the first packet, the Lazy BF sets **one bit per packet** sequentially. The first k packets of each flow each generate a digest. Only packets k+1 and beyond — when all bits are already set — are silently counted by the CMS. The total estimate is `digest_count + min(cms_rows)`.

---

## What Was Added Over Prototype 3

| Component | Description |
|-----------|-------------|
| **Conditional BF tables** | `tbl_bf1` (fires if b0==1), `tbl_bf2` (fires if b0==1 AND b1==1) — lazy sequential bit-set |
| **Conditional CMS tables** | `tbl_cms_0/1/2` fire only when b0==b1==b2==1 (all bits already set = known flow) |
| **Metadata fields b0/b1/b2** | Cross-stage BF read-back values passed via `metadata_t` |
| **Updated control plane** | Estimate = `digest_count + min(cms_rows)` (digest_count was always 1 in prototype 3) |

---

## Algorithm

For every IPv4 packet arriving at the switch:

```
1. Extract 5-tuple (src_ip, dst_ip, proto, src_port, dst_port)
2. Compute 3 BF hash indices (h0..h2, 17-bit) — stages 0–2
3. bf_0: always check-and-set bf_0[h0], store old value in b0 — stage 3
4. bf_1: only if b0==1, check-and-set bf_1[h1], store old value in b1 — stage 4
5. bf_2: only if b0==1 AND b1==1, check-and-set bf_2[h2], store old value in b2 — stage 5
6. If b0==0 OR b1==0 OR b2==0 → digest (new or partially-seen flow)
7. Compute 3 CMS hash indices (c0..c2, 10-bit) — stage 6
8. CMS increment: only if b0==1 AND b1==1 AND b2==1 — stages 7–9
9. Forward packet via IPv4 LPM
```

At epoch end the control plane:

```
1. Collects all digest notifications; counts per-flow digest count (1–k per flow)
2. Reads cms_0, cms_1, cms_2 register arrays via bfrt gRPC
3. For each known flow: recompute CMS indices, take min(row0, row1, row2)
4. Report per-flow estimate = digest_count + CMS estimate
5. Clear BF + CMS registers for the next epoch
```

---

## Parameters

### Bloom Filter

| Parameter | Value |
|-----------|-------|
| k (hash functions / lazy steps) | 3 |
| m (bits per array) | 131,072 (2^17) |
| Total BF memory | 48 KB |

### Count-Min Sketch (unchanged from Prototype 3)

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
Stage  0 : tbl_hash0      — BF idx0 (17-bit)
Stage  1 : tbl_hash1      — BF idx1 (17-bit)
Stage  2 : tbl_hash2      — BF idx2 (17-bit)
Stage  3 : tbl_bf0        — bf_0 always check-and-set; result → b0
Stage  4 : tbl_bf1        — bf_1 check-and-set only if b0==1; else b1=0
Stage  5 : tbl_bf2        — bf_2 check-and-set only if b0==1 AND b1==1; else b2=0
Stage  6 : tbl_cms_hash   — CMS idx0/1/2 combined (30 bits ≤ 32-bit limit)
Stage  7 : tbl_cms_0      — CMS row 0 increment, only if b0==b1==b2==1
Stage  8 : tbl_cms_1      — CMS row 1 increment, only if b0==b1==b2==1
Stage  9 : tbl_cms_2      — CMS row 2 increment, only if b0==b1==b2==1
Stage 10 : free
Stage 11 : free
```

---

## Implementation Details

### Conditional RegisterAction via Table Match

Tofino does not support conditional RegisterAction execution directly. Instead, each conditional BF/CMS operation is wrapped in a match-action table keyed on the relevant metadata bits. A missing match hit takes the default `skip_*` action which leaves the bit at 0.

```p4
action run_bf1() { ig_md.b1 = bf_check_set_1.execute(ig_md.idx1); }
action skip_bf1() { ig_md.b1 = 0; }

@stage(4) table tbl_bf1 {
    key            = { ig_md.b0 : exact; }
    actions        = { run_bf1; skip_bf1; }
    default_action = skip_bf1;
    size           = 2;
}
```

The control plane adds a single entry `b0=1 → run_bf1` via `setup_table.py`. No entry for `b0=0` means the default fires and bf_1 is skipped.

### Digest Condition

A digest fires whenever any bit was zero before this packet set it:

```p4
if (ig_md.b0 == 0) { ig_dprsr_md.digest_type = 1; }
else if (ig_md.b1 == 0) { ig_dprsr_md.digest_type = 1; }
else if (ig_md.b2 == 0) { ig_dprsr_md.digest_type = 1; }
```

This means each flow generates exactly k=3 digest notifications (one per newly-set bit), not just 1 as in Prototype 3.

### Estimate Formula

```
total_packets = digest_count + min(cms_row0, cms_row1, cms_row2)
```

`digest_count` tracks how many digests were received for a flow (1 to k). For flows with ≤ k total packets, CMS = 0 and the estimate equals the digest count exactly.

### Tofino Digest Deduplication

The Tofino model coalesces rapid same-flow digest messages. To reliably receive all k=3 digests per flow, `test_packet.py` spaces digest-generating packets with a 1.5 s gap (`DIGEST_GAP`), exceeding the model's dedup window.

---

## File Structure

```
prototype4/
├── prototype4.p4       # P4-16 data plane (Lazy BF + conditional CMS, Tofino/TNA)
├── build.sh            # Build script (cmake + make)
├── setup_table.py      # Adds LPM entry + conditional BF/CMS table entries (run via bfshell)
├── reset_epoch.py      # Clears BF + CMS registers (run via bfshell)
├── control_plane.py    # Standalone Python: digests + epoch CMS report
└── test_packet.py      # Scapy test: verifies lazy BF digests and CMS counts
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
cd /home/student/Desktop/flowlidar/prototype4
./build.sh
```

Success ends with:
```
[100%] Built target prototype4-tofino
Install the project...
```

---

### Step 2 — Terminal A: Start the Tofino model

```bash
sudo -E $SDE/run_tofino_model.sh -p prototype4
```

Wait for:
```
Blocking on message from CPU
```

---

### Step 3 — Terminal B: Start switchd

```bash
sudo -E $SDE/run_switchd.sh -p prototype4
```

Wait for:
```
bfruntime gRPC server started on 0.0.0.0:50052
```

---

### Step 4 — Terminal B: Add forwarding and conditional table entries

At the `bfshell>` prompt in the same terminal:

```
bfrt_python /home/student/Desktop/flowlidar/prototype4/setup_table.py
```

Output ends with:
```
Setup complete. Run control_plane.py to receive flow digests and CMS reports.
```

---

### Step 5 — Terminal C: Start the control plane

```bash
python3 /home/student/Desktop/flowlidar/prototype4/control_plane.py --epoch 30
```

Output:
```
========================================================================
  FlowLiDAR Prototype 4 — Control Plane (Lazy BF)
  Connecting to localhost:50052 ...
  Epoch length : 30.0s
========================================================================
Connected. Waiting for packets...
```

---

### Step 6 — Terminal D: Send test packets

```bash
sudo python3 /home/student/Desktop/flowlidar/prototype4/test_packet.py
```

**Expected output in Terminal C** as packets arrive (15 total digests):

```
[   1] NEW FLOW  10.1.0.1:1000 -> 10.0.0.1:80  TCP  (digest #1)
[   2] NEW FLOW  10.1.0.2:2000 -> 10.0.0.1:80  TCP  (digest #1)
...
[   9] NEW FLOW  10.1.0.1:1000 -> 10.0.0.1:80  TCP  (digest #3)
[  10] NEW FLOW  10.1.0.2:2000 -> 10.0.0.1:80  TCP  (digest #3)
...
[  15] NEW FLOW  10.1.0.6:6000 -> 10.0.0.1:53  UDP  (digest #2)
```

**At epoch end** (after 30 s, or press Ctrl-C for immediate):

```
========================================================================
  EPOCH 1 END  —  6 flows detected by BF
========================================================================
  Reading CMS registers...

  Flow                                         Digests  CMS est.  Total
  -------------------------------------------- -------  --------  -----
  10.1.0.1:1000 -> 10.0.0.1:80 TCP                   3         9     12
  10.1.0.2:2000 -> 10.0.0.1:80 TCP                   3         3      6
  10.1.0.3:3000 -> 10.0.0.1:80 TCP                   3         0      3
  10.1.0.4:4000 -> 10.0.0.1:443 TCP                  2         0      2
  10.1.0.5:5000 -> 10.0.0.1:53 UDP                   2         0      2
  10.1.0.6:6000 -> 10.0.0.1:53 UDP                   2         0      2

  Clearing BF + CMS registers for next epoch...
========================================================================
```

Flows with ≤ k=3 total packets have CMS = 0 — all packets were counted as digests. Only Flows A (12 packets) and B (6 packets) have non-zero CMS estimates.

---

### Manual Epoch Reset (optional)

To clear BF + CMS without waiting for the timer, run in Terminal B at `bfshell>`:

```
bfrt_python /home/student/Desktop/flowlidar/prototype4/reset_epoch.py
```

---

## What's Next

**Prototype 5** implements the **control-plane equation solver** (§3.4 of the paper): using the digest sequence to set up a linear system Ax=b and solve for exact per-flow packet counts, eliminating CMS approximation error entirely.
