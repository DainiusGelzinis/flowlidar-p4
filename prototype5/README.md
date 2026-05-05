## How to Run

### Prerequisites

```bash
# veth interfaces (once per boot)
sudo $SDE_INSTALL/bin/veth_setup.sh

# Python dependencies
pip3 install --upgrade protobuf crcmod numpy scapy
```

### Step 0 — Kill Any Stale Processes

```bash
sudo pkill -f tofino-model; sudo pkill -f bf_switchd; sleep 2
```

### Step 1 — Build (only needed after P4 changes)

```bash
cd /home/student/Desktop/flowlidar/prototype5
./build.sh
```

### Step 2 — Terminal A: Start the Tofino Model

```bash
sudo -E $SDE/run_tofino_model.sh -p prototype5
```

Wait for:
```
Blocking on message from CPU
```

### Step 3 — Terminal B: Start switchd

```bash
sudo -E $SDE/run_switchd.sh -p prototype5
```

Wait for:
```
bfruntime gRPC server started on 0.0.0.0:50052
```

### Step 4 — Terminal B: Configure Tables (at the bfshell prompt)

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

### Step 5 — Terminal C: Start the Control Plane

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

### Step 6 — Terminal D: Send Test Packets

```bash
sudo python3 /home/student/Desktop/flowlidar/prototype5/test_packet.py
```

As packets arrive, Terminal C prints digest notifications in real time:
```
[   1] NEW FLOW  10.1.0.1:1000 -> 10.0.0.1:80  TCP  (digest #1)
[   2] NEW FLOW  10.1.0.2:2000 -> 10.0.0.1:80  TCP  (digest #1)
...
[  15] NEW FLOW  10.1.0.6:6000 -> 10.0.0.1:53  UDP  (digest #2)
```

### Step 7 — Read the Epoch Report (after 30 s or press Ctrl-C)

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

### Manual Epoch Reset

To clear BF + CMS without waiting for the timer (useful when debugging):
```
bfrt_python /home/student/Desktop/flowlidar/prototype5/reset_epoch.py
```

### BF Register Debug (run before the epoch timer clears registers)

```bash
python3 /home/student/Desktop/flowlidar/prototype5/debug_bf.py
```

---

## 11. Understanding the Test Results

### Per-Flow Trace Through the Pipeline

**Flow D, E, F — 2 packets each:**

| Packet # | BF state before | Action | BF state after | Digest? | CMS? |
|----------|----------------|--------|----------------|---------|------|
| 1 | (0, 0, 0) | run_bf0 sets bf_0; skip_bf1 (b0=0); skip_bf2 (b0=0) | (1, 0, 0) | b0=0 → YES (#1) | no |
| 2 | (1, 0, 0) | run_bf0 finds bf_0=1; run_bf1 sets bf_1 (b0=1); skip_bf2 (b1=0) | (1, 1, 0) | b1=0 → YES (#2) | no |

At epoch end: bf_2=0 → Algorithm 4: count = digest_count = **2**. Exact.

**Flow C — 3 packets (= k):**

| Packet # | BF state before | b0/b1/b2 returned | Digest? | CMS? |
|----------|----------------|-------------------|---------|------|
| 1 | (0,0,0) | b0=0 | YES (#1) | no |
| 2 | (1,0,0) | b0=1, b1=0 | YES (#2) | no |
| 3 | (1,1,0) | b0=1, b1=1, b2=0 | YES (#3) | no (b2 was 0 → (1,1,0) not (1,1,1)) |

At epoch end: bf=(1,1,1) — all bits set (the last packet set bf_2). Algorithm 4 passes it (all 1). CMS=0 because no packet ever had b0=b1=b2=1 at the time of CMS evaluation. Algorithm 5: count = digest_count = **3**. Exact.

**Flow A — 12 packets, Flow B — 6 packets:**

Both get 3 digests (packets 1–3 each set one BF bit and trigger a digest). Packet 4 onward finds all three BF bits already 1, so tbl_cms_0/1/2 fire with `do_cms_inc_*`. By epoch end:
- CMS(A) = 12 - 3 = **9** increments
- CMS(B) = 6 - 3 = **3** increments

The equation solver builds a 6×2 system (3 equations per flow × 2 flows = 6 rows, 2 unknown counts). With no hash collisions, rank=2=n. Solution: x_A=9, x_B=3. Totals: 3+9=**12**, 3+3=**6**. Exact.

### System Parameters

| Parameter | Value |
|-----------|-------|
| BF arrays (k) | 3 |
| BF cells per array (m) | 131,072 (2^17) |
| BF total memory | 48 KB |
| CMS rows (k) | 3 |
| CMS cells per row (m) | 1,024 (2^10) |
| CMS counter width | 16 bits (max 65,535/epoch) |
| CMS total memory | 6 KB |
| Exact-solve threshold | load factor < 0.918 → < 942 flows in C_final per epoch |
| gRPC address | localhost:50052 |
| Switch port mapping | port 0 ↔ veth0/veth1, port 1 ↔ veth2/veth3 |
