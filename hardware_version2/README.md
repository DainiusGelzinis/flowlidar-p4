# FlowLiDAR — Hardware Version 2 (Real Tofino 1, Prototype 6 with Sub-Sketches)

Same workflow as `hardware_version/`, but runs **prototype6**: BF lazy
updates plus the paper's master-hash sub-sketch CMS (64 sub-sketches × 1024
columns per row). Solver works on 64 small independent systems instead of
one large one.

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

Files live at `~/dainius/hardware_version2/` on the switch.

```bash
# Local VM → switch (whole directory)
scp hardware_version2/{prototype6.p4,build.sh,setup_table.py,control_plane.py,reset_epoch.py,test_packet.py} onie.two.hotpot:~/dainius/hardware_version2/

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
cd ~/dainius/hardware_version2
./build.sh
```

Requires `$SDE` to be set. Compiled binary is installed under `$SDE_INSTALL`.
Uses `bf-p4c` (Barefoot SDE 9.11.0 on the switch).

---

### Step 1 — Start switchd (T1, p4switch2)

```bash
$SDE/run_switchd.sh -p prototype6
```

Wait for `bfruntime gRPC server started` before proceeding.

---

### Step 2 — Load tables (T2, p4switch2)

```bash
bfshell
```

Inside bfshell:

```
bfrt_python ~/dainius/hardware_version2/setup_table.py
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
python3 ~/dainius/hardware_version2/control_plane.py --epoch 30
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
| `prototype6.p4` | P4 program (BF lazy updates + master-hash sub-sketch CMS) |
| `build.sh` | Compiles and installs the P4 program (uses `bf-p4c`) |
| `setup_table.py` | Enables ports, loads forwarding + BF/CMS tables |
| `control_plane.py` | Reads digests, runs postprocessing across 64 sub-systems |
| `test_packet.py` | Sends 6 known flows for correctness testing (needs sudo, scapy) |
| `reset_epoch.py` | Manually clears all registers without running an epoch |

---

## Differences from `hardware_version/` (prototype5)

| Aspect | hardware_version | hardware_version2 |
|--------|------------------|-------------------|
| P4 program | `prototype5` | `prototype6` |
| BF | 3×131072×1bit (lazy) | identical |
| CMS | 3 × 1024 × 16-bit | **3 × 65536 × 16-bit** (64 buckets × 1024 cols) |
| Master hash | none | new (CRC32 poly 0xF4ACFB13) |
| Solver | 1 large system | up to 64 small systems |
| Stages used | 0–9 (2 spare) | 0–11 (no spare) |
| CMS bulk read time on simulator | seconds | minutes (64× more cells) |
| CMS bulk read time on hardware | < 1 s | seconds |
