#!/usr/bin/env python3
"""
FlowLiDAR Prototype 6 — Test Script

Same traffic pattern as prototype5 (6 known flows). Sub-sketch partitioning
should not change the per-flow result — only the way the solver works.

Expected epoch report (all exact via postprocessing):
  Flow A: digest=3 + solver=9  = 12
  Flow B: digest=3 + solver=3  =  6
  Flow C: digest=3 + alg5=0    =  3
  Flow D: digest=2 + alg4      =  2
  Flow E: digest=2 + alg4      =  2
  Flow F: digest=2 + alg4      =  2

Usage:
    sudo python3 test_packet.py
"""

import time
from scapy.all import Ether, IP, TCP, UDP, sendp

SEND_IFACE = 'veth1'
DELAY      = 0.05
DIGEST_GAP = 1.5

def send(desc, pkt, count=1, quiet=False):
    if not quiet:
        print(f'  Sending {count}x [{desc}]')
    for _ in range(count):
        sendp(pkt, iface=SEND_IFACE, verbose=False)
        time.sleep(DELAY)

PKT_A = Ether()/IP(src='10.1.0.1', dst='10.0.0.1', ttl=64)/TCP(sport=1000, dport=80)
PKT_B = Ether()/IP(src='10.1.0.2', dst='10.0.0.1', ttl=64)/TCP(sport=2000, dport=80)
PKT_C = Ether()/IP(src='10.1.0.3', dst='10.0.0.1', ttl=64)/TCP(sport=3000, dport=80)
PKT_D = Ether()/IP(src='10.1.0.4', dst='10.0.0.1', ttl=64)/TCP(sport=4000, dport=443)
PKT_E = Ether()/IP(src='10.1.0.5', dst='10.0.0.1', ttl=64)/UDP(sport=5000, dport=53)
PKT_F = Ether()/IP(src='10.1.0.6', dst='10.0.0.1', ttl=64)/UDP(sport=6000, dport=53)

print('=' * 64)
print('  FlowLiDAR Prototype 6 — Sub-sketch Solver Test')
print('  Make sure control_plane.py is running in another terminal.')
print('=' * 64)
print()

print('[Test 1] Send 1 packet per flow (6 flows) -> digest #1 each')
send('Flow A: 10.1.0.1:1000 -> 10.0.0.1:80  TCP', PKT_A)
send('Flow B: 10.1.0.2:2000 -> 10.0.0.1:80  TCP', PKT_B)
send('Flow C: 10.1.0.3:3000 -> 10.0.0.1:80  TCP', PKT_C)
send('Flow D: 10.1.0.4:4000 -> 10.0.0.1:443 TCP', PKT_D)
send('Flow E: 10.1.0.5:5000 -> 10.0.0.1:53  UDP', PKT_E)
send('Flow F: 10.1.0.6:6000 -> 10.0.0.1:53  UDP', PKT_F)
time.sleep(DIGEST_GAP)

print()
print('[Test 2] Send pkt 2 for A and B -> digest #2')
send('Flow A pkt 2', PKT_A)
send('Flow B pkt 2', PKT_B)
time.sleep(DIGEST_GAP)

print()
print('[Test 3] Send pkt 3 for A and B -> digest #3 (all BF bits now set)')
send('Flow A pkt 3', PKT_A)
send('Flow B pkt 3', PKT_B)
time.sleep(DIGEST_GAP)

print()
print('[Test 4] Send 8 more for A, 2 more for B -> CMS only')
send('Flow A x8 (CMS)', PKT_A, count=8, quiet=True)
print('  Sent 8x [Flow A] -> CMS = 8')
send('Flow B x2 (CMS)', PKT_B, count=2, quiet=True)
print('  Sent 2x [Flow B] -> CMS = 2')
time.sleep(0.5)

print()
print('[Test 5] Send pkt 2 for Flow C -> digest #2')
send('Flow C pkt 2', PKT_C)
time.sleep(DIGEST_GAP)

print()
print('[Test 6] Re-send all 6 flows once each')
print('         A,B: CMS+1. C: digest #3. D,E,F: digest #2.')
for label, pkt in [('Flow A', PKT_A), ('Flow B', PKT_B), ('Flow C', PKT_C),
                    ('Flow D', PKT_D), ('Flow E', PKT_E), ('Flow F', PKT_F)]:
    send(f'{label} re-send', pkt, quiet=True)
print('  Sent 1x [each of 6 flows]')
time.sleep(0.5)

print()
print('=' * 64)
print('  Done sending.')
print()
print('  Expected totals (all exact via postprocessing):')
print('    Flow A: digest=3 + solver=9  = 12')
print('    Flow B: digest=3 + solver=3  =  6')
print('    Flow C: digest=3 + alg5=0    =  3')
print('    Flow D: digest=2 + alg4      =  2')
print('    Flow E: digest=2 + alg4      =  2')
print('    Flow F: digest=2 + alg4      =  2')
print()
print('  Wait for the epoch timer, or press Ctrl-C in control_plane.py.')
print('=' * 64)
