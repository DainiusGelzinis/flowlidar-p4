#!/usr/bin/env python3
"""
FlowLiDAR Prototype 3 — CMS Debug Script

Run this AFTER sending test packets (before the epoch clears the registers).
It answers two questions:

  1. What does a register entry actually look like in the bfrt gRPC API?
     (prints raw key.to_dict() and data.to_dict() for the first few entries)

  2. Where did Tofino actually put the CMS counts for each flow?
     (scans all 1024 cells of cms_0 and lists non-zero entries)

  3. What indices does the Python CRC computation predict for each flow?
     (compares predicted vs. actual non-zero cells)

Usage:
    # Send packets first (test_packet.py), then before epoch fires:
    python3 debug_cms.py
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

try:
    import crcmod
    HAS_CRCMOD = True
    _crc_fn0 = crcmod.mkCrcFun(0x1A833982B, rev=True,
                                initCrc=0xFFFFFFFF, xorOut=0xFFFFFFFF)
    _crc_fn1 = crcmod.mkCrcFun(0x1814141AB, rev=False,
                                initCrc=0x00000000, xorOut=0x00000000)
    _crc_fn2 = crcmod.mkCrcFun(0x104C11DB7, rev=False,
                                initCrc=0x00000000, xorOut=0xFFFFFFFF)
except ImportError:
    HAS_CRCMOD = False

GRPC_ADDR = 'localhost:50052'
DEVICE_ID = 0
P4_NAME   = 'prototype3'
CMS_SIZE  = 1024

TEST_FLOWS = [
    ('10.1.0.1', '10.0.0.1', 6,  1000, 80,  'Flow A (12 pkts)'),
    ('10.1.0.2', '10.0.0.1', 6,  2000, 80,  'Flow B (6 pkts)'),
    ('10.1.0.3', '10.0.0.1', 6,  3000, 80,  'Flow C (3 pkts)'),
    ('10.1.0.4', '10.0.0.1', 6,  4000, 443, 'Flow D (2 pkts)'),
    ('10.1.0.5', '10.0.0.1', 17, 5000, 53,  'Flow E (2 pkts)'),
    ('10.1.0.6', '10.0.0.1', 17, 6000, 53,  'Flow F (2 pkts)'),
]


def flow_bytes(src, dst, proto, sport, dport):
    src_int = struct.unpack('!I', socket.inet_aton(src))[0]
    dst_int = struct.unpack('!I', socket.inet_aton(dst))[0]
    return struct.pack('!IIBHH', src_int, dst_int, proto, sport, dport)


def python_indices(src, dst, proto, sport, dport):
    if not HAS_CRCMOD:
        return None
    data = flow_bytes(src, dst, proto, sport, dport)
    return (
        _crc_fn0(data) & (CMS_SIZE - 1),
        _crc_fn1(data) & (CMS_SIZE - 1),
        _crc_fn2(data) & (CMS_SIZE - 1),
    )


def main():
    interface = gc.ClientInterface(
        grpc_addr=GRPC_ADDR, client_id=1, device_id=DEVICE_ID, num_tries=10)
    interface.bind_pipeline_config(P4_NAME)
    bfrt_info = interface.bfrt_info_get(P4_NAME)
    target = gc.Target(device_id=DEVICE_ID)

    tbl = bfrt_info.table_get('pipe.SwitchIngress.cms_0')

    # ------------------------------------------------------------------
    # Part 1: raw dict structure — read indices 0, 1, 2 explicitly
    # ------------------------------------------------------------------
    print('=' * 64)
    print('PART 1 — Raw bfrt dict structure for cms_0 (indices 0, 1, 2)')
    print('=' * 64)
    for idx in range(3):
        key = tbl.make_key([gc.KeyTuple('$REGISTER_INDEX', idx)])
        for k, d in tbl.entry_get(target, [key], {'from_hw': True}):
            print(f'  index {idx}:')
            print(f'    key.to_dict()  = {k.to_dict()}')
            print(f'    data.to_dict() = {d.to_dict()}')
    print()

    # ------------------------------------------------------------------
    # Part 2: scan all 1024 cells of each CMS row for non-zero values
    # ------------------------------------------------------------------
    print('=' * 64)
    print('PART 2 — Non-zero cells in CMS rows (scanning all 1024 entries)')
    print('=' * 64)
    for row_name in ['cms_0', 'cms_1', 'cms_2']:
        tbl_r = bfrt_info.table_get(f'pipe.SwitchIngress.{row_name}')
        nonzero = []
        for idx in range(CMS_SIZE):
            key = tbl_r.make_key([gc.KeyTuple('$REGISTER_INDEX', idx)])
            for k, d in tbl_r.entry_get(target, [key], {'from_hw': True}):
                k_dict = k.to_dict()
                d_dict = d.to_dict()
                # Try to extract value from all possible locations
                val = 0
                for src_dict in [d_dict, k_dict]:
                    for fname, fval in src_dict.items():
                        if fname == '$REGISTER_INDEX':
                            continue
                        if isinstance(fval, list):
                            fval = fval[0]
                        if isinstance(fval, int) and fval != 0:
                            val = fval
                # Also check if $REGISTER_INDEX value in either dict is the count
                # (some SDE versions embed the register value under this key)
                # We print both raw dicts for the first non-zero found
                if val != 0:
                    nonzero.append((idx, val, k_dict, d_dict))
        if nonzero:
            print(f'  {row_name}: {len(nonzero)} non-zero cells')
            for idx, val, k_dict, d_dict in nonzero[:10]:
                print(f'    [{idx:4d}] = {val}   key={k_dict}  data={d_dict}')
            if len(nonzero) > 10:
                print(f'    ... and {len(nonzero)-10} more')
        else:
            print(f'  {row_name}: ALL ZEROS — CMS may not be incrementing')
            print(f'    (First cell raw: read index 0 above)')
    print()

    # ------------------------------------------------------------------
    # Part 3: Python-predicted indices for each test flow
    # ------------------------------------------------------------------
    print('=' * 64)
    print('PART 3 — Python-predicted CMS indices for test flows')
    print('=' * 64)
    if not HAS_CRCMOD:
        print('  crcmod not installed — cannot predict indices')
    else:
        for src, dst, proto, sport, dport, label in TEST_FLOWS:
            idxs = python_indices(src, dst, proto, sport, dport)
            print(f'  {label}')
            print(f'    cms_0 index: {idxs[0]}')
            print(f'    cms_1 index: {idxs[1]}')
            print(f'    cms_2 index: {idxs[2]}')
    print()
    print('Compare Part 2 non-zero cell indices with Part 3 predicted indices.')
    print('If they differ, the Python CRC parameters do not match Tofino.')


if __name__ == '__main__':
    main()
