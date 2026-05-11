# FlowLiDAR — Hardware Version 4 (Real Tofino 1, Prototype 8: traditional BF baseline)

Same workflow as `hardware_version3/`, but runs **prototype8**: traditional
Bloom Filter (no lazy updates) sized like prototype5/6 (3 × 131072 × 1 bit,
17-bit indexing). Each visible flow generates exactly one digest, so
Algorithms 4 / 5 (digest-count classification) are bypassed in the control
plane and every visible flow goes straight to the sub-sketch equation
solver. CMS sub-sketch partitioning (64 × 1024 cells per row) is unchanged.

Runs on **p4switch2** (Intel Tofino 1) via the university lab. Traffic is
injected from **hotpot** using FastClick/DPDK.

---

## Network Topology

```
Local VM ──SSH──► hotpot (dgelzini@hotpot.win.tue.nl)
                       │
                       │ 40G cable
                       ▼
               p4switch2 port 2/0 (D_P=140)  ← ingress
               p4switch2 port 1/0 (D_P=132)  ← egress
                       │
                       │ (looped back to hotpot enp172s0f1np1)
```

Both ports are on **Pipe 1** (D_P >> 7 == 1). Control plane uses
`gc.Target(device_id=0, pipe_id=1)` — register reads from the wrong pipe
return all zeros.

DPDK PCI: `0000:ac:00.0` (hotpot's `enp172s0f0np0`).

---

## SSH Access

```bash
# From local VM: connect to switch
ssh onie.two.hotpot

# From local VM: connect to hotpot
ssh dgelzini@hotpot.win.tue.nl
```

---

## File Transfer

Files live at `~/dainius/hardware_version4/` on the switch.

```bash
# Local VM → switch (whole directory)
scp hardware_version4/{prototype8.p4,build.sh,setup_table.py,control_plane.py,reset_epoch.py,test_packet.py} onie.two.hotpot:~/dainius/hardware_version4/

# Local VM → hotpot (FastClick file)
scp single_flow.click dgelzini@hotpot.win.tue.nl:~/
```

---

## Running the System

Open **3 terminals**:

| Terminal | Machine | Purpose |
|----------|---------|---------|
| T1 | p4switch2 | switchd daemon |
| T2 | p4switch2 | table setup + control plane |
| T3 | hotpot | FastClick traffic sender |

---

### Step 0 — Build (only after P4 changes)

On **p4switch2**:

```bash
cd ~/dainius/hardware_version4
./build.sh
```

Requires `$SDE` to be set. Compiled binary is installed under `$SDE_INSTALL`.
Uses `bf-p4c` (Barefoot SDE 9.11.0 on the switch).

---

### Step 1 — Start switchd (T1, p4switch2)

```bash
$SDE/run_switchd.sh -p prototype8
```

Wait for `bfruntime gRPC server started` before proceeding.

---

### Step 2 — Load tables (T2, p4switch2)

```bash
bfshell
```

Inside bfshell:

```
bfrt_python ~/dainius/hardware_version4/setup_table.py
```

This enables ports 1/0 (D_P=132) and 2/0 (D_P=140), populates the IPv4
LPM table, and adds entries to the conditional BF/CMS tables. Verify with:

```
ucli
pm show
```

You should see both ports with `RDY=YES`, `OPR=UP`.

---

### Step 3 — Start control plane (T2, p4switch2)

Exit bfshell, then:

```bash
python3 ~/dainius/hardware_version4/control_plane.py --epoch 30
```

`--epoch` sets the measurement window in seconds (default: 10). Each epoch
the control plane reads BF + CMS, runs Algorithms 4/5, partitions the
remaining flows by master hash bucket, and solves up to 64 small linear
systems independently.

---

### Step 4 — Send traffic (T3, hotpot)

For a single-flow test:

```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- ~/single_flow.click
```

For pcap replay:

```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- ~/simple_pcap_replay.click
```

---

## Expected Output (single_flow at 1 pps for 30 s)

```
========================================================================
  EPOCH 1 END  —  1 flows detected by BF
========================================================================
  Reading BF + CMS registers...

  Sub-systems solved   : 1 / 64  (max load: 0.001, underdetermined: 0, high residual: 0)

  Total flows          : 1
  Total digests        : 3
  Digest only (Alg4)   : 0  (0.0%)
  Digest only (Alg5)   : 0  (0.0%)
  Equation solver      : 1  (100.0%)
```

Total = digests + solver count ≈ packets sent.

---

## Restarting Between Runs

- **switchd crashed / restarted** → re-run Steps 1 → 2 → 3 (in order)
- **Only control plane restarted** → re-run Step 2 then Step 3
- **Only click restarted** → just re-run Step 4
- **P4 code changed** → re-run Step 0, then Steps 1 → 2 → 3

---

## Files

| File | Purpose |
|------|---------|
| `prototype8.p4` | P4 program (traditional BF + master-hash sub-sketch CMS) |
| `build.sh` | Compiles and installs the P4 program (uses `bf-p4c`) |
| `setup_table.py` | Enables ports, loads forwarding + BF/CMS tables |
| `control_plane.py` | Reads digests, runs postprocessing across 64 sub-systems |
| `test_packet.py` | Sends 6 known flows for correctness testing (needs sudo, scapy) |
| `reset_epoch.py` | Manually clears all registers without running an epoch |

---

## Differences from `hardware_version3/` (prototype7, lazy BF)

| Aspect | hardware_version3 (lazy BF) | hardware_version4 (traditional BF) |
|--------|-----------------------------|-------------------------------------|
| P4 program | `prototype7` | `prototype8` |
| BF semantics | Lazy: chained, set-one-bit-per-pkt | Traditional: all 3 always set |
| BF size | 3 × 1048576 × 1 bit (4× growth) | **3 × 131072 × 1 bit** (back to prototype5/6 size) |
| BF index width | bit<20> | bit<17> |
| BF tables | tbl_bf1/tbl_bf2 keyed on b0/b1 | tbl_bf1/tbl_bf2 keyless (always run) |
| Digests per visible flow | up to 3 | exactly 1 |
| CMS | 3 × 65536 × 16-bit (64 × 1024) | identical |
| Algorithms 4 / 5 in CP | both fire | both bypassed (every flow → solver) |
| Stages used | 0–11 | 0–11 |
