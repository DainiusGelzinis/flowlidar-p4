# Prototype 5 — Equation Solver (Exact Counts via Postprocessing)

## Overview

Prototype 5 implements the full **§3.4 postprocessing pipeline** from the FlowLiDAR paper (Monterubbiano et al., ACM SIGMETRICS 2023). The data plane is identical to Prototype 4 (Lazy Updates BF + conditional CMS). All new functionality is in the control plane.

The key advancement over Prototype 4 is that instead of reporting `digest_count + min(cms_rows)` as an estimate, the control plane now:

1. Reads the BF register snapshot to identify flows whose exact count is already known from the digest count alone (**Algorithm 4**)
2. Removes flows with a zero CMS estimate, whose count is also exactly the digest count (**Algorithm 5**)
3. Sets up and solves the sparse linear system **Ax = b** for the remaining flows to recover their exact CMS packet counts (**equation solver**)
4. Falls back to **Algorithm 6** (approximate resolution) when the system is underdetermined

The result is exact per-flow packet counts for all flows — not estimates.

---

## What Was Added Over Prototype 4

| Component | Description |
|-----------|-------------|
| **BF hash replication** | Python CRC functions replicate the P4 BF hash polynomials, used to compute targeted BF cell reads |
| **Targeted BF register reads** | `_read_register_cell()` reads only the 3 cells needed per flow (18 reads for 6 flows) instead of scanning all 131,072 cells |
| **Algorithm 4** | BF preprocessing: queries BF snapshot per flow; any zero bit → count = digest_count |
| **Algorithm 5** | CMS preprocessing: zero CMS estimate → count = digest_count |
| **Equation solver** | Builds binary matrix A and counter vector b; solves Ax=b via `numpy.linalg.lstsq` |
| **Algorithm 6** | Approximate fallback for underdetermined systems (load factor > threshold) |
| **Method column in report** | Each flow is tagged with how its count was resolved: `alg4`, `alg5`, or `solver` |

---

## Algorithm

### Data Plane (unchanged from Prototype 4)

For every IPv4 packet arriving at the switch:

```
1. Extract 5-tuple (src_ip, dst_ip, proto, src_port, dst_port)
2. Compute 3 BF hash indices (17-bit) — stages 0–2
3. bf_0: always check-and-set; store old bit in b0 — stage 3
4. bf_1: check-and-set only if b0==1; store old bit in b1 — stage 4
5. bf_2: check-and-set only if b0==1 AND b1==1; store old bit in b2 — stage 5
6. If any bi == 0 → digest (new or partially-seen flow)
7. Compute 3 CMS hash indices (10-bit) — stage 6
8. CMS increment only if b0==b1==b2==1 — stages 7–9
9. Forward via IPv4 LPM
```

### Control Plane Postprocessing (new in Prototype 5)

At epoch end:

```
1. Read all 3 CMS register arrays (full snapshot)
2. For each known flow in flow_table:

   Algorithm 4 — BF preprocessing:
     Read BF bits at the 3 hash positions for this flow (targeted read)
     If any bit is 0:
       count = digest_count  ← exact (flow had ≤ k packets)
     Else:
       Add to set C  ← all bits set, flow may have CMS entries

   Algorithm 5 — CMS preprocessing:
     For each flow in C:
       cms_est = min(cms_row0[h0], cms_row1[h1], cms_row2[h2])
       If cms_est == 0:
         count = digest_count  ← exact (flow's CMS slots were empty)
       Else:
         Add to set C_final  ← needs equation solver

   Equation solver:
     For each flow in C_final, it contributes to 3 CMS counters.
     Build matrix A: A[eq_i][j] = 1 if flow j hashes to counter eq_i
     Build vector b: b[eq_i] = CMS counter value for that cell
     Solve Ax = b → x_j = CMS packet count for flow j
     Total for flow j = digest_count(j) + x_j

     If rank(A) < n → Algorithm 6 approximate fallback

3. Report per-flow counts with resolution method
4. Clear BF + CMS for next epoch
```

---

## Postprocessing in Detail

### Algorithm 4 — BF Preprocessing (§3.4.1)

With lazy updates, a flow with j packets sets exactly j BF bits (j ≤ k). So at epoch end:

- If `bf_0[h0] == 0` OR `bf_1[h1] == 0` OR `bf_2[h2] == 0`: the flow had fewer than k packets. Every packet was counted as a digest. Exact count = digest_count.
- If all three bits are 1: the flow had ≥ k packets and reached the CMS. Pass to Algorithm 5.

This step requires the Python control plane to replicate the exact same BF hash functions used in P4, so it can compute the same cell indices. The BF register reads are **targeted** — only the 3 specific cells per flow are fetched, not the entire 131,072-cell array.

### Algorithm 5 — CMS Preprocessing (§3.4.2)

For flows that passed Algorithm 4 (all BF bits set), check their CMS estimate:

- If `min(cms_row0, cms_row1, cms_row2) == 0`: the flow had exactly k packets. All k were sent as digests; none reached the CMS. Exact count = digest_count.
- If CMS estimate > 0: the flow has genuine CMS entries. Pass to the equation solver.

### Equation Solver — Ax = b (§3.4.2)

For the flows remaining in C_final, construct a sparse binary linear system:

**Variables:** `x = [x_1, ..., x_n]^T` where `x_j` is the CMS packet count (packets beyond the first k) for flow j.

**Equations:** For each unique CMS counter cell referenced by any flow in C_final, one equation is added:

```
sum of x_j for all flows j hashing to that cell = counter value
```

**Matrix A:** `A[i][j] = 1` if flow j contributes to counter equation i. Each flow contributes to exactly k=3 equations (one per CMS row). With no hash collisions, A has exactly k ones per column.

**Example** — 2 flows in C_final (A, B), no hash collisions, 3 CMS rows:

```
          flow_A  flow_B
row0,h0A: [ 1       0  ]  b = 9
row0,h0B: [ 0       1  ]  b = 3
row1,h1A: [ 1       0  ]  b = 9
row1,h1B: [ 0       1  ]  b = 3
row2,h2A: [ 1       0  ]  b = 9
row2,h2B: [ 0       1  ]  b = 3

Solution: x_A = 9, x_B = 3  → exact, unique
```

The system is solved with `numpy.linalg.lstsq`. The solution is exact when `rank(A) == n`, which holds when the load factor `n/m < 0.918` (k=3, see Table 2 in the paper).

### Algorithm 6 — Approximate Fallback (§3.4.3)

Triggered when `rank(A) < n` (more flows in C_final than independent equations, i.e., heavy hash collision or high load). Steps:

1. Sort equations by counter value `b_i` ascending
2. For each equation (smallest first), fix the variables it covers to `b_i / n_i` where `n_i` is the number of unfixed flows in that equation
3. Repeat until all free variables are fixed
4. Solve the now-determined reduced system

This minimises estimation error by fixing the least-contested counters first.

---

## Implementation Details

### Targeted BF Register Reads

Reading all 131,072 cells of each BF row (×3 rows = 393,216 reads) via bfrt gRPC takes several seconds — the same as the clearing operation. Since we only need the 3 specific hash positions per flow, we use `entry_get` with an explicit key:

```python
key = tbl.make_key([gc.KeyTuple('$REGISTER_INDEX', idx)])
for k, data in tbl.entry_get(target, [key], {'from_hw': True}):
    combined = {**k.to_dict(), **data.to_dict()}
    val = combined['SwitchIngress.bf_0.f1']
```

For 6 flows this is 18 targeted reads instead of 393,216, making BF preprocessing near-instant.

### Tofino bfrt Register Field Layout

A Tofino register `Register<bit<1>, bit<17>>(131072)` named `bf_0` exposes its value in the **key** dict of `entry_get`, not the data dict:

```
key  = {'SwitchIngress.bf_0.f1': [1, 0, 0, 0], ...}
data = {'$REGISTER_INDEX': {'value': 119916}}
```

The value is a list (one element per pipeline stage copy). Index `[0]` gives the value for the first pipe. The control plane merges both dicts and always takes `val[0]` when the result is a list.

### BF Hash Replication in Python

The P4 BF hash polynomials and their crcmod equivalents (confirmed empirically):

| Array | P4 CRCPolynomial | crcmod |
|-------|-----------------|--------|
| bf_0 | poly=0x04C11DB7, rev=true, init=0xFFFFFFFF, residue=0xFFFFFFFF | `mkCrcFun(0x104C11DB7, rev=True, initCrc=0x00000000, xorOut=0xFFFFFFFF)` |
| bf_1 | poly=0x04C11DB7, rev=false, init=0xFFFFFFFF, residue=0xFFFFFFFF | `mkCrcFun(0x104C11DB7, rev=False, initCrc=0x00000000, xorOut=0xFFFFFFFF)` |
| bf_2 | poly=0x1EDC6F41, rev=true, init=0xFFFFFFFF, residue=0xFFFFFFFF | `mkCrcFun(0x11EDC6F41, rev=True, initCrc=0x00000000, xorOut=0xFFFFFFFF)` |

Mapping formula: `crcmod initCrc = P4_init XOR P4_residue`, `crcmod xorOut = P4_residue`.

### CRC → crcmod Mapping (General Formula)

```
crcmod poly    = 0x1<P4_poly>  (prepend leading 1 bit)
crcmod rev     = P4_reversed
crcmod initCrc = P4_init XOR P4_residue
crcmod xorOut  = P4_residue
```

---

## Parameters

### Bloom Filter

| Parameter | Value |
|-----------|-------|
| k (arrays) | 3 |
| m (bits per array) | 131,072 (2^17) |
| Total BF memory | 48 KB |

### Count-Min Sketch

| Parameter | Value |
|-----------|-------|
| k (rows) | 3 |
| m (cells per row) | 1,024 (2^10) |
| Counter width | 16 bits |
| Total CMS memory | 6 KB |
| Exact-solve threshold (k=3) | load factor < 0.918 → < 942 flows in C_final |

---

## Stage Allocation (unchanged from Prototype 4)

```
Stage  0 : tbl_hash0    — BF idx0 (17-bit)
Stage  1 : tbl_hash1    — BF idx1 (17-bit)
Stage  2 : tbl_hash2    — BF idx2 (17-bit)
Stage  3 : tbl_bf0      — bf_0 always check-and-set; result → b0
Stage  4 : tbl_bf1      — bf_1 check-and-set only if b0==1
Stage  5 : tbl_bf2      — bf_2 check-and-set only if b0==1 AND b1==1
Stage  6 : tbl_cms_hash — CMS idx0/1/2 combined (30 bits ≤ 32-bit limit)
Stage  7 : tbl_cms_0    — CMS row 0 increment, only if b0==b1==b2==1
Stage  8 : tbl_cms_1    — CMS row 1 increment, only if b0==b1==b2==1
Stage  9 : tbl_cms_2    — CMS row 2 increment, only if b0==b1==b2==1
Stage 10 : free
Stage 11 : free
```

---

## File Structure

```
prototype5/
├── prototype5.p4       # P4-16 data plane (identical to prototype4)
├── build.sh            # Build script (cmake + make)
├── setup_table.py      # Adds LPM + conditional BF/CMS table entries (bfshell)
├── reset_epoch.py      # Clears BF + CMS registers (bfshell)
├── control_plane.py    # Full postprocessing: Alg 4/5, solver, Alg 6
├── test_packet.py      # Scapy test: same traffic as prototype4
├── debug_bf.py         # Debug: scans BF registers and matches Python predictions
└── PLAN.md             # Design plan with algorithm descriptions
```

---

## How to Run

### Prerequisites

- SDE 9.13.4 at `$SDE` / `$SDE_INSTALL`
- veth interfaces (once per boot):
  ```bash
  sudo $SDE_INSTALL/bin/veth_setup.sh
  ```
- Python packages:
  ```bash
  pip3 install --upgrade protobuf crcmod numpy
  ```

---

### Step 0 — Kill stale processes

```bash
sudo pkill -f tofino-model; sudo pkill -f bf_switchd; sleep 2
```

---

### Step 1 — Build (only after P4 changes)

```bash
cd /home/student/Desktop/flowlidar/prototype5
./build.sh
```

Success ends with:
```
[100%] Built target prototype5-tofino
Install the project...
```

---

### Step 2 — Terminal A: Start the Tofino model

```bash
sudo -E $SDE/run_tofino_model.sh -p prototype5
```

Wait for:
```
Blocking on message from CPU
```

---

### Step 3 — Terminal B: Start switchd

```bash
sudo -E $SDE/run_switchd.sh -p prototype5
```

Wait for:
```
bfruntime gRPC server started on 0.0.0.0:50052
```

---

### Step 4 — Terminal B: Add table entries (bfshell prompt)

```
bfrt_python /home/student/Desktop/flowlidar/prototype5/setup_table.py
```

Expected output:
```
IPv4 LPM entry added: 10.0.0.1/32 -> port 1
tbl_bf1: entry (b0=1) -> run_bf1
tbl_bf2: entry (b0=1, b1=1) -> run_bf2
tbl_cms_0: entry (1,1,1) -> do_cms_inc_0
tbl_cms_1: entry (1,1,1) -> do_cms_inc_1
tbl_cms_2: entry (1,1,1) -> do_cms_inc_2

Setup complete. Run control_plane.py to receive flow digests and CMS reports.
```

---

### Step 5 — Terminal C: Start the control plane

```bash
python3 /home/student/Desktop/flowlidar/prototype5/control_plane.py --epoch 30
```

Expected output:
```
========================================================================
  FlowLiDAR Prototype 5 — Control Plane (Equation Solver)
  Connecting to localhost:50052 ...
  Epoch length : 30.0s
========================================================================
Connected. Waiting for packets...
```

---

### Step 6 — Terminal D: Send test packets

```bash
sudo python3 /home/student/Desktop/flowlidar/prototype5/test_packet.py
```

This takes ~10 seconds. Digests appear in Terminal C as they arrive:

```
[   1] NEW FLOW  10.1.0.1:1000 -> 10.0.0.1:80  TCP  (digest #1)
...
[  15] NEW FLOW  10.1.0.6:6000 -> 10.0.0.1:53  UDP  (digest #2)
```

---

### Step 7 — Epoch report (after 30s or Ctrl-C)

```
========================================================================
  EPOCH 1 END  —  6 flows detected by BF
========================================================================
  Reading CMS registers...
  Reading BF registers (targeted)...

  --- Algorithm 4: BF preprocessing ---
  10.1.0.4:4000->10.0.0.1:443 TCP  bf=(1,1,0)  -> exact=2 (digest only)
  10.1.0.5:5000->10.0.0.1:53  UDP  bf=(1,1,0)  -> exact=2 (digest only)
  10.1.0.6:6000->10.0.0.1:53  UDP  bf=(1,1,0)  -> exact=2 (digest only)
  Flows resolved by Alg4: 3  Flows remaining for CMS: 3

  --- Algorithm 5: CMS preprocessing ---
  10.1.0.3:3000->10.0.0.1:80  TCP  CMS=0  -> exact=3 (digest only)
  Flows resolved by Alg5: 1  Flows remaining for solver: 2

  --- Equation solver (Ax=b, 6x2 system) ---
  rank=2  n=2  load=0.002
  System uniquely determined. Residual=0.0000

  Flow                                         Digests  CMS/Solve  Total  Method
  -------------------------------------------- -------  ---------  -----  ------
  10.1.0.1:1000 -> 10.0.0.1:80 TCP                   3          9     12  solver
  10.1.0.2:2000 -> 10.0.0.1:80 TCP                   3          3      6  solver
  10.1.0.3:3000 -> 10.0.0.1:80 TCP                   3          0      3    alg5
  10.1.0.4:4000 -> 10.0.0.1:443 TCP                  2          0      2    alg4
  10.1.0.5:5000 -> 10.0.0.1:53 UDP                   2          0      2    alg4
  10.1.0.6:6000 -> 10.0.0.1:53 UDP                   2          0      2    alg4

  Flows reported: 6/6

  Clearing BF + CMS registers for next epoch...
========================================================================
```

All 6 flows are reported with exact counts. The Method column shows which algorithm resolved each flow.

---

## Understanding the Test Results

| Flow | Packets | digest_count | BF at epoch end | CMS est. | Resolved by | Total |
|------|---------|--------------|-----------------|----------|-------------|-------|
| A | 12 | 3 | (1,1,1) | 9 | solver | 12 |
| B | 6  | 3 | (1,1,1) | 3 | solver | 6  |
| C | 3  | 3 | (1,1,1) | 0 | alg5   | 3  |
| D | 2  | 2 | (1,1,0) | — | alg4   | 2  |
| E | 2  | 2 | (1,1,0) | — | alg4   | 2  |
| F | 2  | 2 | (1,1,0) | — | alg4   | 2  |

**Flow D/E/F:** 2 packets → lazy BF sets bf_0 and bf_1 only. bf_2 stays 0. Algorithm 4 sees a zero bit → count = digest_count = 2. Exact.

**Flow C:** 3 packets = exactly k. Lazy BF sets all 3 bits. Algorithm 4 passes it (all bits 1). Algorithm 5 checks CMS: all 3 CMS counters for C are 0 (no packet from C ever reached the CMS, since the 3rd packet set bf_2 and triggered a digest instead of a CMS increment). count = digest_count = 3. Exact.

**Flow A and B:** More than k packets. All 3 BF bits set and CMS > 0. Passed to the equation solver. The 6×2 linear system is overdetermined with no hash collisions, so the solution is unique and exact. x_A = 9, x_B = 3.

---

### Manual Epoch Reset

In Terminal B at the `bfshell>` prompt:

```
bfrt_python /home/student/Desktop/flowlidar/prototype5/reset_epoch.py
```

---

## What's Next

The paper also describes a **Differential Flow Detector** (Algorithm 3, §3.2): a pair of BFs (oldBF + currentBF) that reduces control-plane bandwidth by only reporting FlowIDs not seen in the previous epoch. This is an optional bandwidth optimisation that does not affect counting accuracy.

Scaled parameters from the paper's evaluation: 4×128K BF and 64×1K CMS. The larger CMS ensures the equation system stays well below the 0.918 load factor threshold at realistic flow counts (~60K–900K active flows per epoch), keeping exact-solve reliable.
