#!/usr/bin/env python3
"""
FlowLiDAR Prototype 5 — BF Hash Debug Script

Scans the BF register arrays for non-zero cells and compares them
against Python-predicted indices for the 6 test flows.

Run AFTER test_packet.py and BEFORE the epoch timer clears the registers.

Usage:
    python3 debug_bf.py
"""

import sys
import os
import struct
import socket

SDE_INSTALL = os.environ.get('SDE_INSTALL',
                             '/home/student/Desktop/open-p4studio/install')
sys.path.append(os.path.join(SDE_INSTALL, 'lib/python3.8/site-packages'))
sys.path.append(os.path.join(SDE_INSTALL, 'lib/python3.8/site-packages/tofino'))

import bfrt_grpc.client as gc
import crcmod

GRPC_ADDR = 'localhost:50052'
P4_NAME   = 'prototype5'
BF_SIZE   = 131072

# ---------------------------------------------------------------------------
# Test flows
# ---------------------------------------------------------------------------
FLOWS = [
    ('10.1.0.1', '10.0.0.1', 6,  1000, 80,  'Flow A'),
    ('10.1.0.2', '10.0.0.1', 6,  2000, 80,  'Flow B'),
    ('10.1.0.3', '10.0.0.1', 6,  3000, 80,  'Flow C'),
    ('10.1.0.4', '10.0.0.1', 6,  4000, 443, 'Flow D'),
    ('10.1.0.5', '10.0.0.1', 17, 5000, 53,  'Flow E'),
    ('10.1.0.6', '10.0.0.1', 17, 6000, 53,  'Flow F'),
]

def flow_bytes(src, dst, proto, sport, dport):
    return struct.pack('!IIBHH',
        struct.unpack('!I', socket.inet_aton(src))[0],
        struct.unpack('!I', socket.inet_aton(dst))[0],
        proto, sport, dport)

# ---------------------------------------------------------------------------
# Candidate BF hash function families to try
# CRCPolynomial(poly, reversed, msb, extended, init, residue)
# crcmod: initCrc = init XOR residue, xorOut = residue, poly = 0x1<poly>
# ---------------------------------------------------------------------------
CANDIDATES = [
    # (label, poly_hex, rev, initCrc, xorOut)
    # poly0 in P4: 0x04C11DB7, reversed=true, init=0xFFFFFFFF, residue=0xFFFFFFFF
    ('CRC32  rev=T init=0x00000000 xor=0xFFFFFFFF', 0x104C11DB7, True,  0x00000000, 0xFFFFFFFF),
    ('CRC32  rev=F init=0x00000000 xor=0xFFFFFFFF', 0x104C11DB7, False, 0x00000000, 0xFFFFFFFF),
    ('CRC32  rev=T init=0xFFFFFFFF xor=0x00000000', 0x104C11DB7, True,  0xFFFFFFFF, 0x00000000),
    ('CRC32  rev=F init=0xFFFFFFFF xor=0x00000000', 0x104C11DB7, False, 0xFFFFFFFF, 0x00000000),
    ('CRC32  rev=T init=0xFFFFFFFF xor=0xFFFFFFFF', 0x104C11DB7, True,  0xFFFFFFFF, 0xFFFFFFFF),
    ('CRC32  rev=F init=0xFFFFFFFF xor=0xFFFFFFFF', 0x104C11DB7, False, 0xFFFFFFFF, 0xFFFFFFFF),
    ('CRC32  rev=T init=0x00000000 xor=0x00000000', 0x104C11DB7, True,  0x00000000, 0x00000000),
    ('CRC32  rev=F init=0x00000000 xor=0x00000000', 0x104C11DB7, False, 0x00000000, 0x00000000),
    # poly1 in P4: 0x04C11DB7, reversed=false
    # poly2 in P4: 0x1EDC6F41 (CRC32C), reversed=true, init=0xFFFFFFFF, residue=0xFFFFFFFF
    ('CRC32C rev=T init=0x00000000 xor=0xFFFFFFFF', 0x11EDC6F41, True,  0x00000000, 0xFFFFFFFF),
    ('CRC32C rev=F init=0x00000000 xor=0xFFFFFFFF', 0x11EDC6F41, False, 0x00000000, 0xFFFFFFFF),
    ('CRC32C rev=T init=0xFFFFFFFF xor=0x00000000', 0x11EDC6F41, True,  0xFFFFFFFF, 0x00000000),
    ('CRC32C rev=F init=0xFFFFFFFF xor=0x00000000', 0x11EDC6F41, False, 0xFFFFFFFF, 0x00000000),
]

# ---------------------------------------------------------------------------
# Connect and scan BF registers
# ---------------------------------------------------------------------------
print('Connecting...')
interface = gc.ClientInterface(
    grpc_addr=GRPC_ADDR, client_id=2, device_id=0, num_tries=3)
# Skip bind_pipeline_config — read-only access, client 0 already owns the P4.
bfrt_info = interface.bfrt_info_get(P4_NAME)
target    = gc.Target(device_id=0)

def scan_bf_row(row_name):
    """Return dict of idx -> value for all non-zero cells."""
    tbl_name = f'pipe.SwitchIngress.{row_name}'
    tbl      = bfrt_info.table_get(tbl_name)
    field    = f'SwitchIngress.{row_name}.f1'
    nonzero  = {}
    try:
        for key, data in tbl.entry_get(target, None, {'from_hw': True}):
            k_dict = key.to_dict()
            d_dict = data.to_dict()
            combined = {**k_dict, **d_dict}

            idx_raw = combined.get('$REGISTER_INDEX', 0)
            if isinstance(idx_raw, dict):
                idx = idx_raw.get('value', 0)
            else:
                idx = int(idx_raw)

            val_raw = combined.get(field, 0)
            if isinstance(val_raw, list):
                val_raw = val_raw[0]
            val = int(val_raw)

            if val != 0:
                nonzero[idx] = val
    except Exception as e:
        print(f'  [WARN] {tbl_name}: {e}')
    return nonzero

print('Scanning BF rows (this may take a few seconds)...')
nz = {}
for row in ['bf_0', 'bf_1', 'bf_2']:
    nz[row] = scan_bf_row(row)
    print(f'  {row}: {len(nz[row])} non-zero cells  indices={sorted(nz[row].keys())}')

print()
print('=' * 72)
print('Part 1 — Raw non-zero BF cells')
print('=' * 72)
for row in ['bf_0', 'bf_1', 'bf_2']:
    print(f'\n{row}:')
    for idx in sorted(nz[row].keys()):
        print(f'  [{idx}] = {nz[row][idx]}')

print()
print('=' * 72)
print('Part 2 — Python predictions vs hardware for each candidate function')
print('=' * 72)

bf0_set = set(nz['bf_0'].keys())
bf1_set = set(nz['bf_1'].keys())
bf2_set = set(nz['bf_2'].keys())

# Try each candidate as poly0 and check if predicted indices are in the non-zero set
print('\nTesting candidate functions for bf_0 (all 6 flows should have their index set):')
for label, poly, rev, initCrc, xorOut in CANDIDATES:
    try:
        fn = crcmod.mkCrcFun(poly, rev=rev, initCrc=initCrc, xorOut=xorOut)
    except Exception:
        continue
    hits = 0
    for src, dst, proto, sport, dport, name in FLOWS:
        data = flow_bytes(src, dst, proto, sport, dport)
        idx  = fn(data) & (BF_SIZE - 1)
        if idx in bf0_set:
            hits += 1
    print(f'  hits={hits}/6  {label}')

print()
print('Testing candidate functions for bf_1:')
for label, poly, rev, initCrc, xorOut in CANDIDATES:
    try:
        fn = crcmod.mkCrcFun(poly, rev=rev, initCrc=initCrc, xorOut=xorOut)
    except Exception:
        continue
    hits = 0
    for src, dst, proto, sport, dport, name in FLOWS:
        data = flow_bytes(src, dst, proto, sport, dport)
        idx  = fn(data) & (BF_SIZE - 1)
        if idx in bf1_set:
            hits += 1
    print(f'  hits={hits}/6  {label}')

print()
print('Testing candidate functions for bf_2 (only flows with >=3 pkts: A,B,C):')
for label, poly, rev, initCrc, xorOut in CANDIDATES:
    try:
        fn = crcmod.mkCrcFun(poly, rev=rev, initCrc=initCrc, xorOut=xorOut)
    except Exception:
        continue
    # Only A, B, C should have bf_2 set (3+ packets)
    abc_flows = FLOWS[:3]
    hits = 0
    for src, dst, proto, sport, dport, name in abc_flows:
        data = flow_bytes(src, dst, proto, sport, dport)
        idx  = fn(data) & (BF_SIZE - 1)
        if idx in bf2_set:
            hits += 1
    print(f'  hits={hits}/3  {label}')

print()
print('=' * 72)
print('Part 3 — Per-flow predicted indices with current Python functions')
print('=' * 72)

fn0 = crcmod.mkCrcFun(0x104C11DB7, rev=True,  initCrc=0x00000000, xorOut=0xFFFFFFFF)
fn1 = crcmod.mkCrcFun(0x104C11DB7, rev=False, initCrc=0x00000000, xorOut=0xFFFFFFFF)
fn2 = crcmod.mkCrcFun(0x11EDC6F41, rev=True,  initCrc=0x00000000, xorOut=0xFFFFFFFF)

for src, dst, proto, sport, dport, name in FLOWS:
    data = flow_bytes(src, dst, proto, sport, dport)
    i0 = fn0(data) & (BF_SIZE - 1)
    i1 = fn1(data) & (BF_SIZE - 1)
    i2 = fn2(data) & (BF_SIZE - 1)
    h0 = 'HIT' if i0 in bf0_set else 'MISS'
    h1 = 'HIT' if i1 in bf1_set else 'MISS'
    h2 = 'HIT' if i2 in bf2_set else 'MISS'
    print(f'{name}: bf_0[{i0}]={h0}  bf_1[{i1}]={h1}  bf_2[{i2}]={h2}')
