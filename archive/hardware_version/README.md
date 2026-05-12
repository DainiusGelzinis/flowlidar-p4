# FlowLiDAR — Hardware Version (Real Tofino 1)

Runs on **p4switch2** (Intel Tofino 1) via the university lab. Traffic is injected from **hotpot** using FastClick/DPDK.

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

- hotpot `enp172s0f0np0` → switch port 2/0 (packets enter here)
- hotpot `enp172s0f1np1` → switch port 1/0 (packets exit here)
- DPDK PCI address: `0000:ac:00.0` (hotpot's `enp172s0f0np0`)

---

## SSH Access

```bash
# From local VM: connect to hotpot
ssh dgelzini@hotpot.win.tue.nl

# From local VM: connect to switch (SSH alias, routes through hotpot)
ssh onie.two.hotpot

# From hotpot: connect to switch
ssh onie@192.168.12.58
```

---

## File Transfer

Files live at `~/dainius/hardware_version/` on the switch.

**Local VM to switch** (using SSH alias):
```bash
scp hardware_version/control_plane.py onie.two.hotpot:~/dainius/hardware_version/control_plane.py
scp simple_pcap_replay.click dgelzini@hotpot.win.tue.nl:~/
```

**Local VM to hotpot:**
```bash
scp simple_pcap_replay.click dgelzini@hotpot.win.tue.nl:~/
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

### Step 0 — Build (only needed after P4 changes)

On **p4switch2**:

```bash
cd ~/dainius/hardware_version
./build.sh
```

Requires `$SDE` to be set. The compiled binary is installed to `$SDE_INSTALL`.

---

### Step 1 — Start switchd (T1, p4switch2)

```bash
$SDE/run_switchd.sh -p prototype5
```

Wait until you see `bfruntime gRPC server started` before proceeding.

---

### Step 2 — Load tables (T2, p4switch2)

```bash
bfshell
```

Inside bfshell:

```
bfrt_python ~/dainius/hardware_version/setup_table.py
```

This enables ports 1/0 and 2/0, adds the IPv4 LPM forwarding entry, and populates the BF/CMS conditional tables.

---

### Step 3 — Start control plane (T2, p4switch2)

```bash
python3 ~/dainius/hardware_version/control_plane.py --epoch 60
```

`--epoch` sets the measurement window in seconds (default: 10). The control plane prints a summary at the end of each epoch showing total flows, how many were resolved by each algorithm, and matrix solver info.

---

### Step 4 — Send traffic (T3, hotpot)

```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- ~/simple_pcap_replay.click
```

This replays the equinix-nyc CAIDA trace (`equinix-nyc.dirA.20190117-130000.UTC.anon.pcap`) at the rate set in `simple_pcap_replay.click` (currently 1 Mbps). The trace loops indefinitely.

To change the rate, edit `simple_pcap_replay.click`:
```
define($RATE 1Mbps)   # change this line
```

---

## Verify Traffic is Flowing

On **p4switch2**, inside bfshell:

```
bfshell> pm rate-show
```

You should see non-zero RX rates on port 2/0 (D_P=140) and TX on port 1/0 (D_P=132).

---

## Restarting Between Runs

- **switchd crashed / restarted**: re-run Steps 1 → 2 → 3 (in order)
- **Only control plane restarted**: re-run Step 2 (setup_table) then Step 3
- **Only click restarted**: just re-run Step 4
- **P4 code changed**: re-run Step 0, then Steps 1 → 2 → 3

---

## Files

| File | Purpose |
|------|---------|
| `prototype5.p4` | P4 program (BF lazy updates + CMS) |
| `build.sh` | Compiles and installs the P4 program |
| `setup_table.py` | Loads forwarding and BF/CMS tables into the switch |
| `control_plane.py` | Reads digests, runs postprocessing (Algorithms 4/5/6) |
| `test_packet.py` | Sends 6 known flows for correctness testing (needs sudo) |
| `debug_bf.py` | Scans BF registers and validates hash predictions |
| `reset_epoch.py` | Manually clears all registers without running an epoch |
