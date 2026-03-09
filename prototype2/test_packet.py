#!/usr/bin/env python3
"""
FlowLiDAR Prototype 2 — Test Script

Tests the Bloom Filter by sending packets and verifying the control plane
receives each new flow exactly once.

Run control_plane.py in a separate terminal first, then run this script.

Usage:
    sudo python3 test_packet.py
"""

import time
from scapy.all import Ether, IP, TCP, UDP, sendp

SEND_IFACE = "veth1"   # into port 0
DELAY      = 0.1       # seconds between sends

def send(desc, pkt, count=1):
    print(f"  Sending {count}x [{desc}]")
    for _ in range(count):
        sendp(pkt, iface=SEND_IFACE, verbose=False)
        time.sleep(DELAY)

print("=" * 60)
print("  FlowLiDAR Prototype 2 — BF Test")
print("  Make sure control_plane.py is running in another terminal.")
print("=" * 60)
print()

# ── Test 1: Single new flow ───────────────────────────────────────────────────
print("[Test 1] Send 1 packet of a new flow → expect 1 digest notification")
send("Flow A: 10.1.0.1:1000 -> 10.0.0.1:80 TCP",
     Ether()/IP(src="10.1.0.1", dst="10.0.0.1", ttl=64)/TCP(sport=1000, dport=80))
time.sleep(0.5)

# ── Test 2: Repeat same flow → BF should suppress ────────────────────────────
print()
print("[Test 2] Send 5 more packets of same flow → expect 0 new notifications")
send("Flow A repeated", Ether()/IP(src="10.1.0.1", dst="10.0.0.1", ttl=64)/TCP(sport=1000, dport=80), count=5)
time.sleep(0.5)

# ── Test 3: Multiple distinct flows ──────────────────────────────────────────
print()
print("[Test 3] Send 5 distinct flows → expect 5 digest notifications")
flows = [
    ("Flow B: 10.1.0.2:2000->10.0.0.1:80 TCP",  Ether()/IP(src="10.1.0.2", dst="10.0.0.1", ttl=64)/TCP(sport=2000, dport=80)),
    ("Flow C: 10.1.0.3:3000->10.0.0.1:80 TCP",  Ether()/IP(src="10.1.0.3", dst="10.0.0.1", ttl=64)/TCP(sport=3000, dport=80)),
    ("Flow D: 10.1.0.4:4000->10.0.0.1:443 TCP", Ether()/IP(src="10.1.0.4", dst="10.0.0.1", ttl=64)/TCP(sport=4000, dport=443)),
    ("Flow E: 10.1.0.5:5000->10.0.0.1:53 UDP",  Ether()/IP(src="10.1.0.5", dst="10.0.0.1", ttl=64)/UDP(sport=5000, dport=53)),
    ("Flow F: 10.1.0.6:6000->10.0.0.1:53 UDP",  Ether()/IP(src="10.1.0.6", dst="10.0.0.1", ttl=64)/UDP(sport=6000, dport=53)),
]
for desc, pkt in flows:
    send(desc, pkt)
time.sleep(0.5)

# ── Test 4: Re-send all flows → all suppressed ────────────────────────────────
print()
print("[Test 4] Re-send all flows → expect 0 new notifications")
for desc, pkt in flows:
    send(f"{desc} (repeat)", pkt)
time.sleep(0.5)

print()
print("Done. Check control_plane.py output.")
print("Expected: 6 notifications total (Test 1: 1, Test 2: 0, Test 3: 5, Test 4: 0)")
