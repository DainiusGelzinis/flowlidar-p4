# FlowLiDAR — Prototype 1

## What This Prototype Does

Prototype 1 is a **minimal IPv4 forwarder** whose only purpose is to confirm
that the full toolchain works end-to-end:

- Barefoot SDE cmake/make build pipeline compiles the P4 program without errors
- The Tofino software model (`run_tofino_model.sh`) loads and runs it
- `switchd` connects and the control plane can insert table entries

No Bloom Filter, no Count-Min Sketch, no control-plane logic. Just parsing and
forwarding. Future prototypes build on this foundation.

### What the data plane does

| Packet type | Action |
|-------------|--------|
| IPv4 (matched in `ipv4_lpm`) | Forward out the configured egress port |
| IPv4 (no matching route) | Drop (default action) |
| Non-IPv4 | Drop |

### Headers parsed

- Ethernet
- IPv4
- TCP (when `protocol == 6`)
- UDP (when `protocol == 17`)

---

## Directory Layout

```
prototype1/
├── prototype1.p4   # P4-16 TNA source
├── build.sh        # Build script (cmake + make)
└── README.md       # This file
```

---

## Prerequisites

1. **Barefoot SDE 9.13.4** installed under `/home/student/Desktop/open-p4studio`
   (`$SDE` and `$SDE_INSTALL` are set in `.netrc` — no manual export needed)
2. Python 3 with **Scapy** installed (for the verification test):
   ```bash
   pip3 install scapy
   ```

---

## How to Build

```bash
cd /home/student/p4_projects/flowlidar/prototype1
./build.sh
```

The script runs `cmake` and `make` and prints a clear success or failure
message. Build artifacts go to `/tmp/build_prototype1/` and the compiled
program is installed into `$SDE/install`.

---

## How to Run

Open **three separate terminals**.

### Terminal 1 — Tofino software model

```bash
$SDE/run_tofino_model.sh -p prototype1
```

Wait until output settles and the model is listening.

### Terminal 2 — switchd (driver + control plane bridge)

```bash
$SDE/run_switchd.sh -p prototype1
```

Wait until the `bf-sde>` prompt appears.

### Terminal 3 — Control plane (bfshell + bfrt_python)

```bash
$SDE_INSTALL/bin/bfshell
```

At the `bfshell>` prompt, enter the bfrt Python environment:

```
bfshell> bfrt_python
```

Insert a forwarding rule so that packets to `10.0.0.1/32` exit on port 1:

```python
# Get a handle to the table
p4 = bfrt.prototype1.pipe
tbl = p4.Ingress.ipv4_lpm

# Add a host route: 10.0.0.1/32 -> port 1
tbl.add_with_ipv4_forward(
    ipv4_dst_addr='10.0.0.1',
    prefix_len=32,
    egress_port=1
)

# Verify the entry was installed
tbl.dump(table=True)
```

---

## Verification with Scapy

With the model and switchd running and the table entry installed, send a test
packet from a third terminal:

```python
#!/usr/bin/env python3
"""
Simple Scapy test for Prototype 1.
Run as root or with sudo.
"""
from scapy.all import Ether, IP, TCP, sendp, sniff

# Adjust iface to the veth connected to the Tofino model's port 0 (typically veth0)
SEND_IFACE = "veth0"
RECV_IFACE = "veth2"   # veth connected to port 1 (the expected egress)

pkt = Ether(dst="ff:ff:ff:ff:ff:ff") / IP(dst="10.0.0.1") / TCP(dport=80)

print("Sending packet...")
sendp(pkt, iface=SEND_IFACE, verbose=True)

print("Listening for forwarded packet on", RECV_IFACE, "...")
received = sniff(iface=RECV_IFACE, filter="ip dst 10.0.0.1", count=1, timeout=3)

if received:
    print("SUCCESS: packet received on egress interface")
    received[0].show()
else:
    print("FAILURE: no packet received within timeout")
```

Save as `test_prototype1.py` and run with:

```bash
sudo python3 test_prototype1.py
```

**What to expect:**
- The packet enters on `veth0` (model port 0)
- The `ipv4_lpm` table matches `10.0.0.1/32` and forwards to port 1
- The packet exits on `veth2` (model port 1)
- Scapy captures it and prints `SUCCESS`

> **Note on veth numbering:** The Tofino model maps switch ports to veth
> interfaces. Port N typically maps to `veth(2*N)` / `veth(2*N+1)`. Adjust
> `SEND_IFACE` and `RECV_IFACE` to match your setup.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| `cmake` fails with "P4_PATH not found" | Wrong path to `.p4` file | Run `build.sh` from its own directory, or check `$P4_FILE` inside the script |
| `run_tofino_model.sh` exits immediately | Program not installed | Make sure `make install` step completed |
| `bfshell` can't find the table | switchd not fully started | Wait for `bf-sde>` prompt before connecting |
| Scapy test times out | Wrong veth interface | Check model output for port-to-veth mapping |
| Packet dropped unexpectedly | No matching LPM entry | Verify entry with `tbl.dump(table=True)` |

---

## Next Steps (Future Prototypes)

| Prototype | Feature |
|-----------|---------|
| 2 | Bloom Filter — detect new flows in the data plane |
| 3 | Count-Min Sketch — count packets per flow |
| 4 | Control-plane equation solver — compute exact per-flow counts |
