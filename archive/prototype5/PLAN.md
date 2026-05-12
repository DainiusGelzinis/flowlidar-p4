# Prototype 5 — Equation Solver (Exact Counts via Ax=b)

## Goal

Add the full §3.4 postprocessing pipeline from the paper to the control plane:
- **Algorithm 4** — BF preprocessing: identify flows whose exact count = digest_count
- **Algorithm 5** — CMS preprocessing: remove zero-CMS flows from the equation system
- **Equation solver** — build sparse linear system Ax=b, solve for exact CMS contributions
- **Algorithm 6** — approximate fallback when the system is underdetermined

The data plane (P4) is **identical to prototype4**. All changes are in the control plane.

---

## What the Paper Says (§3.4)

At epoch end the control plane has:
- A set D of FlowIDs received via digest, with per-flow digest_count (1 to k)
- A snapshot of the CMS counters (already read in prototype4)
- NEW: a snapshot of the BF register arrays

The three postprocessing stages narrow down the set of flows that need equation solving:

### Algorithm 4 — BF Preprocessing (lazy updates variant)

```
For each flow x in D:
    Query x in the BF snapshot (check all k bit positions)
    If any position is 0:
        count(x) = digest_count(x)   ← exact, flow had ≤ k packets total
    Else:
        Add x to set C               ← all bits set, flow may be in CMS
```

With lazy updates, a flow with j ≤ k packets sets exactly j BF bits.
So "any bit is 0" means the flow never reached the CMS — its full count
is captured by its digest_count alone.

### Algorithm 5 — CMS Preprocessing

```
For each flow x in C:
    Compute CMS estimate = min(cms_row0[h0(x)], cms_row1[h1(x)], cms_row2[h2(x)])
    If estimate == 0:
        count(x) = digest_count(x)   ← flow's CMS slots are empty, exact count known
        Remove x from C
```

A CMS estimate of 0 means no packets from this flow reached the CMS
(consistent with having exactly k packets, all sent as digests).

### Equation Solver — Ax=b

For flows remaining in C after preprocessing:

**Variables:** x = [x_1, ..., x_n]^T where x_j = CMS packet count for flow j

**Equations:** for each unique CMS counter cell referenced by any flow in C,
the counter value b_i = sum of x_j for all flows j that hash to that cell.

**Matrix A:** A[i][j] = 1 if flow j contributes to counter i (i.e., flow j
hashes to the CMS cell corresponding to equation i in at least one row).

**System:** Ax = b  →  solve for x  →  total(j) = digest_count(j) + x_j

The system is exactly solvable when the load factor n/m < 0.918 (k=3),
which corresponds to fewer than ~940 flows competing for 1024 CMS cells.

### Algorithm 6 — Approximate Fallback (when underdetermined)

Used when rank(A) < n (more flows than independent equations):

```
Sort equations by b_i ascending
l = number of free variables = n - rank(A)
For each equation i (smallest b_i first):
    Get variables x_a ... x_p that appear in equation i
    Fix x_a ... x_p = b_i / n_i   (n_i = count of variables in equation i)
    l = l - n_i
    If l == 0: break
Solve the now-determined reduced system
```

This minimises error by fixing the smallest counters first (least ambiguity).

---

## Key Implementation Choice: Targeted BF Register Reads

Reading all 131,072 BF cells per row (×3 rows) takes several seconds — same
as the clear operation in prototype4. Since we only need to check the BF
positions for flows in D (at most a few hundred), we instead do **targeted
reads**: read only the specific cell indices needed.

```python
# Read one BF cell
idx = bf_hash_index_for_flow(flow_key)   # recompute using same CRC as data plane
tbl = bfrt_info.table_get('pipe.SwitchIngress.bf_0')
key = tbl.make_key([gc.KeyTuple('$REGISTER_INDEX', idx)])
for _, data in tbl.entry_get(target, [key], {'from_hw': True}):
    val = data.to_dict().get('SwitchIngress.bf_0.f1', 0)
```

For 6 flows × 3 rows = 18 reads instead of 393,216. Near-instant.

---

## BF Hash Replication in Python

The control plane must replicate the same BF CRC functions used in P4.
From prototype2/3/4 these are confirmed working:

```python
_bf_fn0 = crcmod.mkCrcFun(0x104C11DB7, rev=True,  initCrc=0x00000000, xorOut=0xFFFFFFFF)
_bf_fn1 = crcmod.mkCrcFun(0x104C11DB7, rev=False, initCrc=0x00000000, xorOut=0xFFFFFFFF)
_bf_fn2 = crcmod.mkCrcFun(0x11EDC6F41, rev=True,  initCrc=0x00000000, xorOut=0xFFFFFFFF)

BF_SIZE = 131072  # 2^17

def bf_indices(flow_key):
    data = _flow_bytes(*flow_key)
    return (
        _bf_fn0(data) & (BF_SIZE - 1),
        _bf_fn1(data) & (BF_SIZE - 1),
        _bf_fn2(data) & (BF_SIZE - 1),
    )
```

**Important:** confirm these match the CRCPolynomial declarations in prototype5.p4
using the same empirical approach as prototype3's debug_cms.py if needed.

---

## Matrix Construction

```
flows_C = [f1, f2, ..., fn]       # flows needing equation solving

counter_map = {}                   # (row, cell) -> equation index
A rows built as: for each unique (row, cell) pair referenced by any flow in C,
                 create one equation row.

A[eq_i][j] = 1  if flow j hashes to the cell for equation eq_i
b[eq_i]    = cms_snapshot[row][cell]   for that (row, cell)
```

Example with 2 flows (A, B), no hash collisions:
```
          flow_A  flow_B
row0,h0A: [ 1       0  ]  b = 9
row0,h0B: [ 0       1  ]  b = 3
row1,h1A: [ 1       0  ]  b = 9
row1,h1B: [ 0       1  ]  b = 3
row2,h2A: [ 1       0  ]  b = 9
row2,h2B: [ 0       1  ]  b = 3

Solution: x_A = 9, x_B = 3  (exact, unique)
```

---

## Expected Test Outcome

Same traffic as prototype4 (same test_packet.py). The algorithms produce:

| Stage | Flow | Why |
|-------|------|-----|
| Alg 4 | D, E, F | bf_2 bit = 0 (2 packets, only bf_0+bf_1 set) → count = digest_count = 2 |
| Alg 5 | C | bf bits all 1 (3 packets = k), but CMS = 0 → count = digest_count = 3 |
| Solver | A, B | In CMS; x_A=9, x_B=3 from equation solve |

Final report:
```
Flow A: digest=3  solver=9   total=12  (exact)
Flow B: digest=3  solver=3   total=6   (exact)
Flow C: digest=3  alg5=0     total=3   (exact)
Flow D: digest=2  alg4       total=2   (exact)
Flow E: digest=2  alg4       total=2   (exact)
Flow F: digest=2  alg4       total=2   (exact)
```

All 6 flows exact. Algorithm 6 not triggered (system is overdetermined, n=2 << m=1024).

---

## File Structure

```
prototype5/
├── PLAN.md             ← this file
├── prototype5.p4       ← identical to prototype4.p4 (rename internal references only)
├── build.sh            ← identical to prototype4/build.sh, name updated
├── setup_table.py      ← identical to prototype4/setup_table.py, name updated
├── reset_epoch.py      ← identical to prototype4/reset_epoch.py, name updated
├── control_plane.py    ← main change: BF snapshot + Alg 4/5/6 + solver
└── test_packet.py      ← identical to prototype4/test_packet.py
```

---

## Control Plane Architecture

```
process_epoch()
│
├── [existing] read_cms_snapshot()          — reads all CMS rows
│
├── [NEW] read_bf_bits(flow_key)             — targeted BF cell reads for each flow
│
├── [NEW] algorithm4_bf_preprocess()
│         Input:  flow_table (digest counts), BF snapshot
│         Output: resolved (exact count known), C (needs CMS)
│
├── [NEW] algorithm5_cms_preprocess()
│         Input:  C, CMS snapshot
│         Output: resolved updated, C_final (needs solver)
│
├── [NEW] solve_cms_exact(C_final)
│         Input:  C_final, CMS snapshot
│         Output: x vector (CMS counts per flow)
│         Method: np.linalg.lstsq(A, b)
│         Check:  if residual > threshold → fall through to Algorithm 6
│
├── [NEW] algorithm6_approximate(C_final)   — fallback if underdetermined
│         Input:  A, b, rank(A), n
│         Output: x vector (approximate)
│
└── print report: per-flow digest / CMS-solver / total / method used
```

---

## New Python Dependency

```bash
pip3 install numpy
```

scipy is not required — numpy's `np.linalg.lstsq` handles sparse systems of
this scale (n ≤ few thousand flows) efficiently enough. If performance becomes
an issue with larger flows, `scipy.sparse.linalg.lsqr` can be substituted.

---

## How to Build and Run

### Step 0 — Kill stale processes
```bash
sudo pkill -f tofino-model; sudo pkill -f bf_switchd; sleep 2
```

### Step 1 — Build
```bash
cd /home/student/Desktop/flowlidar/prototype5
./build.sh
```

### Step 2 — Terminal A: Tofino model
```bash
sudo -E $SDE/run_tofino_model.sh -p prototype5
```

### Step 3 — Terminal B: switchd
```bash
sudo -E $SDE/run_switchd.sh -p prototype5
```

### Step 4 — Terminal B: setup tables (bfshell prompt)
```
bfrt_python /home/student/Desktop/flowlidar/prototype5/setup_table.py
```

### Step 5 — Terminal C: control plane
```bash
pip3 install numpy   # first time only
python3 /home/student/Desktop/flowlidar/prototype5/control_plane.py --epoch 30
```

### Step 6 — Terminal D: send test packets
```bash
sudo python3 /home/student/Desktop/flowlidar/prototype5/test_packet.py
```

---

## Expected Control Plane Output

```
[   1] NEW FLOW  10.1.0.1:1000 -> 10.0.0.1:80  TCP  (digest #1)
...
[  15] NEW FLOW  10.1.0.6:6000 -> 10.0.0.1:53  UDP  (digest #2)

========================================================================
  EPOCH 1 END  —  6 flows detected by BF
========================================================================
  Reading CMS registers...
  Reading BF registers (targeted)...

  --- Algorithm 4: BF preprocessing ---
  10.1.0.4:4000->10.0.0.1:443 TCP  bf_2=0  -> exact count=2 (digest only)
  10.1.0.5:5000->10.0.0.1:53  UDP  bf_2=0  -> exact count=2 (digest only)
  10.1.0.6:6000->10.0.0.1:53  UDP  bf_2=0  -> exact count=2 (digest only)
  Flows remaining for CMS: 3

  --- Algorithm 5: CMS preprocessing ---
  10.1.0.3:3000->10.0.0.1:80  TCP  CMS=0   -> exact count=3 (digest only)
  Flows remaining for solver: 2

  --- Equation solver (Ax=b, 6x2 system) ---
  rank=2, n=2  -> system uniquely determined
  Solution: A=9, B=3

  Flow                                         Digests  CMS/Solver  Total  Method
  -------------------------------------------- -------  ----------  -----  ------
  10.1.0.1:1000 -> 10.0.0.1:80 TCP                   3           9     12  solver
  10.1.0.2:2000 -> 10.0.0.1:80 TCP                   3           3      6  solver
  10.1.0.3:3000 -> 10.0.0.1:80 TCP                   3           0      3  alg5
  10.1.0.4:4000 -> 10.0.0.1:443 TCP                  2           0      2  alg4
  10.1.0.5:5000 -> 10.0.0.1:53 UDP                   2           0      2  alg4
  10.1.0.6:6000 -> 10.0.0.1:53 UDP                   2           0      2  alg4

  Exact results: 6/6 flows
  Clearing BF + CMS registers for next epoch...
========================================================================
```

---

## Verifying Correctness

The test is self-verifying: ground truth is known from what test_packet.py sends.
All 6 flows must show exact counts (12, 6, 3, 2, 2, 2). The "Method" column
confirms which algorithm resolved each flow. Algorithm 6 should never trigger
with only 2 flows in the solver and 1024 CMS cells.

To force Algorithm 6 to trigger (for testing), reduce CMS_SIZE to 4 in
control_plane.py — this makes the system underdetermined and exercises the
approximate fallback path.
