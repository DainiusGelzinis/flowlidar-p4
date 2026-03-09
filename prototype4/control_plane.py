#!/usr/bin/env python3
"""
FlowLiDAR Prototype 4 — Control Plane (Lazy BF)

Same as prototype3 control plane, with one key change:
  estimate = digest_count + min(cms_rows)

With lazy BF, the first k=3 packets of each flow generate digests (counted
by digest_count). Only packets 4+ are counted by the CMS. The total is
the sum of both.

Usage:
    python3 control_plane.py [--epoch SECONDS]
"""

import sys
import os
import time
import struct
import socket
import argparse

# ---------------------------------------------------------------------------
# SDE Python path
# ---------------------------------------------------------------------------
SDE_INSTALL = os.environ.get('SDE_INSTALL',
                             '/home/student/Desktop/open-p4studio/install')
sys.path.append(os.path.join(SDE_INSTALL, 'lib/python3.8/site-packages'))
sys.path.append(os.path.join(SDE_INSTALL, 'lib/python3.8/site-packages/tofino'))

import bfrt_grpc.client as gc

# ---------------------------------------------------------------------------
# Optional: crcmod for CMS index replication
# ---------------------------------------------------------------------------
try:
    import crcmod
    HAS_CRCMOD = True
except ImportError:
    HAS_CRCMOD = False
    print("[WARN] crcmod not installed — CMS estimates will not be computed.")
    print("       Install with: pip3 install crcmod\n")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
GRPC_ADDR  = 'localhost:50052'
CLIENT_ID  = 0
DEVICE_ID  = 0
P4_NAME    = 'prototype4'

CMS_SIZE   = 1024
CMS_ROWS   = ['cms_0', 'cms_1', 'cms_2']
BF_ROWS    = ['bf_0',  'bf_1',  'bf_2']

# ---------------------------------------------------------------------------
# CRC functions — same polynomials as prototype3/4.p4
# Tofino→crcmod: initCrc = P4_init ^ P4_residue, xorOut = P4_residue
# ---------------------------------------------------------------------------
if HAS_CRCMOD:
    _crc_fn0 = crcmod.mkCrcFun(0x1A833982B, rev=True,
                                initCrc=0x00000000, xorOut=0xFFFFFFFF)
    _crc_fn1 = crcmod.mkCrcFun(0x1814141AB, rev=False,
                                initCrc=0x00000000, xorOut=0x00000000)
    _crc_fn2 = crcmod.mkCrcFun(0x104C11DB7, rev=False,
                                initCrc=0xFFFFFFFF, xorOut=0xFFFFFFFF)


def _flow_bytes(src_addr, dst_addr, protocol, src_port, dst_port):
    src_int = struct.unpack('!I', socket.inet_aton(src_addr))[0]
    dst_int = struct.unpack('!I', socket.inet_aton(dst_addr))[0]
    return struct.pack('!IIBHH', src_int, dst_int, protocol, src_port, dst_port)


def cms_indices(flow_key):
    if not HAS_CRCMOD:
        return None
    data = _flow_bytes(*flow_key)
    return (
        _crc_fn0(data) & (CMS_SIZE - 1),
        _crc_fn1(data) & (CMS_SIZE - 1),
        _crc_fn2(data) & (CMS_SIZE - 1),
    )


# ---------------------------------------------------------------------------
# Register I/O helpers (same as prototype3)
# ---------------------------------------------------------------------------

def _read_register_array(bfrt_info, tbl_name, size, target):
    arr = [0] * size
    tbl = bfrt_info.table_get(tbl_name)

    reg_short      = tbl_name.split('.')[-1]
    expected_field = f'SwitchIngress.{reg_short}.f1'
    discovered     = None

    try:
        for key, data in tbl.entry_get(target, None, {'from_hw': True}):
            k_dict = key.to_dict()
            d_dict = data.to_dict()

            if '$REGISTER_INDEX' in d_dict:
                idx_src = d_dict
                val_src = k_dict
            else:
                idx_src = k_dict
                val_src = d_dict

            idx_entry = idx_src.get('$REGISTER_INDEX', 0)
            if isinstance(idx_entry, dict):
                idx = idx_entry.get('value', 0)
            else:
                idx = int(idx_entry)

            if expected_field in val_src:
                val = val_src[expected_field]
                discovered = expected_field
            elif expected_field in idx_src:
                val = idx_src[expected_field]
                discovered = expected_field
            else:
                combined = {**k_dict, **d_dict}
                f1 = next((f for f in combined if f.endswith('.f1')), None)
                if f1:
                    val = combined[f1]
                    discovered = f1
                else:
                    val = 0

            if isinstance(val, list):
                val = val[0]

            if 0 <= idx < size:
                arr[idx] = val

    except Exception as e:
        print(f"  [WARN] entry_get failed for {tbl_name}: {e}")

    return arr, (discovered or expected_field)


def read_cms_snapshot(bfrt_info, target):
    snapshot    = {}
    field_names = {}
    for row in CMS_ROWS:
        tbl_name = f'pipe.SwitchIngress.{row}'
        arr, fname = _read_register_array(bfrt_info, tbl_name, CMS_SIZE, target)
        snapshot[row]    = arr
        field_names[row] = fname
    return snapshot, field_names


def clear_all_registers(bfrt_info, target, cms_field_names=None):
    reg_sizes = {r: 131072 for r in BF_ROWS}
    reg_sizes.update({r: CMS_SIZE for r in CMS_ROWS})

    for reg in BF_ROWS + CMS_ROWS:
        tbl_name   = f'pipe.SwitchIngress.{reg}'
        size       = reg_sizes[reg]
        if cms_field_names and reg in cms_field_names:
            field_name = cms_field_names[reg]
        else:
            field_name = f'SwitchIngress.{reg}.f1'

        tbl = bfrt_info.table_get(tbl_name)
        ok  = True
        BATCH = 128
        for start in range(0, size, BATCH):
            end   = min(start + BATCH, size)
            keys  = [tbl.make_key([gc.KeyTuple('$REGISTER_INDEX', i)])
                     for i in range(start, end)]
            datas = [tbl.make_data([gc.DataTuple(field_name, 0)])
                     for _ in range(start, end)]
            try:
                tbl.entry_mod(target, keys, datas)
            except Exception as e:
                print(f"  [WARN] Could not clear {reg}[{start}:{end}]: {e}")
                ok = False
                break
        if not ok:
            print(f"  [INFO] Partial clear for {reg}. "
                  f"Run reset_epoch.py in bfshell for a full reset.")


# ---------------------------------------------------------------------------
# Epoch processing — key change: estimate = digest_count + min(cms)
# ---------------------------------------------------------------------------

def process_epoch(epoch_num, flow_table, bfrt_info, target):
    sep = '=' * 72
    print(f'\n{sep}')
    print(f'  EPOCH {epoch_num} END  —  {len(flow_table)} flows detected by BF')
    print(sep)

    cms_field_names = {}

    if not flow_table:
        print('  (no flows this epoch)')
    else:
        if HAS_CRCMOD:
            print('  Reading CMS registers...')
            snapshot, cms_field_names = read_cms_snapshot(bfrt_info, target)
            cms_ok = True
        else:
            snapshot = {}
            cms_ok = False

        # Header
        print()
        print(f'  {"Flow":<44} {"Digests":>7}  {"CMS est.":>8}  {"Total":>5}')
        print(f'  {"-"*44} {"-"*7}  {"-"*8}  {"-"*5}')

        for flow_key, digest_count in sorted(flow_table.items()):
            src, dst, proto, sport, dport = flow_key
            proto_name = {6: 'TCP', 17: 'UDP'}.get(proto, str(proto))
            flow_str = f'{src}:{sport} -> {dst}:{dport} {proto_name}'

            if cms_ok:
                indices = cms_indices(flow_key)
                if indices is not None:
                    i0, i1, i2 = indices
                    counts = [
                        snapshot['cms_0'][i0],
                        snapshot['cms_1'][i1],
                        snapshot['cms_2'][i2],
                    ]
                    cms_est = min(counts)
                    total   = digest_count + cms_est
                    est_str   = str(cms_est)
                    total_str = str(total)
                else:
                    est_str   = 'N/A'
                    total_str = 'N/A'
            else:
                est_str   = 'N/A'
                total_str = 'N/A'

            print(f'  {flow_str:<44} {digest_count:>7}  {est_str:>8}  {total_str:>5}')

        print()

    print('  Clearing BF + CMS registers for next epoch...')
    clear_all_registers(bfrt_info, target, cms_field_names)
    print(f'{sep}\n')


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='FlowLiDAR Prototype 4 — Control Plane (Lazy BF)')
    parser.add_argument('--epoch', type=float, default=10.0,
                        help='Epoch length in seconds (default: 10)')
    args = parser.parse_args()
    epoch_seconds = args.epoch

    print('=' * 72)
    print('  FlowLiDAR Prototype 4 — Control Plane (Lazy BF)')
    print(f'  Connecting to {GRPC_ADDR} ...')
    print(f'  Epoch length : {epoch_seconds}s')
    print('=' * 72)

    interface = gc.ClientInterface(
        grpc_addr=GRPC_ADDR,
        client_id=CLIENT_ID,
        device_id=DEVICE_ID,
        num_tries=10,
        notifications=gc.Notifications(enable_learn=True)
    )
    interface.bind_pipeline_config(P4_NAME)

    bfrt_info = interface.bfrt_info_get(P4_NAME)

    learn_filter = bfrt_info.learn_get('flow_digest')
    learn_filter.info.data_field_annotation_add('src_addr', 'ipv4')
    learn_filter.info.data_field_annotation_add('dst_addr', 'ipv4')

    target = gc.Target(device_id=DEVICE_ID)

    print('Connected. Waiting for packets...\n')

    flow_table  = {}
    total       = 0
    epoch_num   = 1
    epoch_start = time.time()

    while True:
        try:
            digest = interface.digest_get(timeout=0.5)
            data_list = learn_filter.make_data_list(digest)

            for data in data_list:
                d = data.to_dict()
                flow_key = (
                    d['src_addr'],
                    d['dst_addr'],
                    d['protocol'],
                    d['src_port'],
                    d['dst_port'],
                )
                flow_table[flow_key] = flow_table.get(flow_key, 0) + 1
                total += 1
                proto_name = {6: 'TCP', 17: 'UDP'}.get(d['protocol'],
                                                         str(d['protocol']))
                print(f"[{total:4d}] NEW FLOW  "
                      f"{d['src_addr']}:{d['src_port']} -> "
                      f"{d['dst_addr']}:{d['dst_port']}  {proto_name}"
                      f"  (digest #{flow_table[flow_key]})")

        except KeyboardInterrupt:
            print('\nCtrl-C received — running final epoch report...')
            process_epoch(epoch_num, flow_table, bfrt_info, target)
            print(f'Total digest notifications received: {total}')
            break
        except Exception:
            pass

        elapsed = time.time() - epoch_start
        if elapsed >= epoch_seconds:
            process_epoch(epoch_num, flow_table, bfrt_info, target)
            flow_table.clear()
            epoch_num  += 1
            epoch_start = time.time()


if __name__ == '__main__':
    main()
