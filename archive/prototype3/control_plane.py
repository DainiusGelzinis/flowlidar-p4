#!/usr/bin/env python3
"""
FlowLiDAR Prototype 3 — Control Plane

Connects to switchd via gRPC, receives BF flow-digest notifications, and
periodically runs an epoch: reads the CMS register snapshot, computes
per-flow packet count estimates, then clears BF + CMS for the next epoch.

Usage:
    python3 control_plane.py [--epoch SECONDS]

Dependencies:
    pip3 install crcmod          # required for CMS index computation
    pip3 install --upgrade protobuf

The script runs standalone — no bfshell needed.
switchd must already be running with prototype3 loaded.

Epoch behaviour:
  - New-flow digests are collected continuously as they arrive.
  - Every EPOCH_SECONDS the epoch processing fires:
      1. Snapshot and clear the in-memory flow table.
      2. Read cms_0, cms_1, cms_2 register arrays from the switch.
      3. For each known flow compute CMS indices and take the min counter.
      4. Print the per-flow estimate table.
      5. Clear BF + CMS registers on the switch.

CRC polynomials — MUST match prototype3.p4 exactly:
  cms_poly0 (cms_0) : CRC32D     — poly=0xA833982B rev=True  init=0xFFFFFFFF residue=0xFFFFFFFF
  cms_poly1 (cms_1) : CRC32/Q    — poly=0x814141AB rev=False init=0x00000000 residue=0x00000000
  cms_poly2 (cms_2) : CRC32/POSIX— poly=0x04C11DB7 rev=False init=0x00000000 residue=0xFFFFFFFF

  Hash<bit<10>> with use_msb=False → index = crc32_result & 0x3FF  (lower 10 bits).

  Tofino→crcmod mapping (empirically confirmed):
    crcmod initCrc = P4_init XOR P4_residue
    crcmod xorOut  = P4_residue
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
P4_NAME    = 'prototype3'

CMS_SIZE   = 1024          # entries per CMS row (must match Register size in P4)
CMS_ROWS   = ['cms_0', 'cms_1', 'cms_2']
BF_ROWS    = ['bf_0',  'bf_1',  'bf_2']

# ---------------------------------------------------------------------------
# CRC functions — replicate prototype3.p4 CMS polynomial parameters exactly.
#
# crcmod notation: polynomial includes the implicit leading 1 bit.
#   P4 polynomial 0xA833982B  →  crcmod 0x1A833982B
#   P4 polynomial 0x814141AB  →  crcmod 0x1814141AB
#   P4 polynomial 0x04C11DB7  →  crcmod 0x104C11DB7
#
# Hash<bit<10>> with use_msb=False:
#   Tofino returns the lower 10 bits of the 32-bit CRC result.
#   Python side: crc32_value & 0x3FF
# ---------------------------------------------------------------------------
if HAS_CRCMOD:
    # Tofino CRCPolynomial parameter mapping (empirically confirmed against hardware):
    #   P4 CRCPolynomial(poly, reversed, msb, extended, init, residue)
    #   maps to crcmod as:
    #       initCrc = P4_init ^ P4_residue
    #       xorOut  = P4_residue
    #
    # cms_poly0 : CRC32D  (P4: init=0xFFFFFFFF, residue=0xFFFFFFFF)
    #   → initCrc = 0xFFFFFFFF ^ 0xFFFFFFFF = 0x00000000, xorOut = 0xFFFFFFFF
    _crc_fn0 = crcmod.mkCrcFun(0x1A833982B, rev=True,
                                initCrc=0x00000000, xorOut=0xFFFFFFFF)
    # cms_poly1 : CRC32/Q (P4: init=0x00000000, residue=0x00000000)
    #   → initCrc = 0 ^ 0 = 0, xorOut = 0
    _crc_fn1 = crcmod.mkCrcFun(0x1814141AB, rev=False,
                                initCrc=0x00000000, xorOut=0x00000000)
    # cms_poly2 : CRC32/POSIX (P4: init=0x00000000, residue=0xFFFFFFFF)
    #   → initCrc = 0x00000000 ^ 0xFFFFFFFF = 0xFFFFFFFF, xorOut = 0xFFFFFFFF
    _crc_fn2 = crcmod.mkCrcFun(0x104C11DB7, rev=False,
                                initCrc=0xFFFFFFFF, xorOut=0xFFFFFFFF)


def _flow_bytes(src_addr, dst_addr, protocol, src_port, dst_port):
    """
    Pack a 5-tuple to bytes in network (big-endian) order.
    This must match the P4 hash field order:
        {ipv4.src_addr, ipv4.dst_addr, ipv4.protocol, src_port, dst_port}
    """
    src_int = struct.unpack('!I', socket.inet_aton(src_addr))[0]
    dst_int = struct.unpack('!I', socket.inet_aton(dst_addr))[0]
    return struct.pack('!IIBHH', src_int, dst_int, protocol, src_port, dst_port)


def cms_indices(flow_key):
    """
    Compute the three 10-bit CMS indices for a flow key tuple
    (src_addr, dst_addr, protocol, src_port, dst_port).

    Returns (idx0, idx1, idx2) matching what prototype3.p4 writes to.
    """
    if not HAS_CRCMOD:
        return None
    data = _flow_bytes(*flow_key)
    return (
        _crc_fn0(data) & (CMS_SIZE - 1),
        _crc_fn1(data) & (CMS_SIZE - 1),
        _crc_fn2(data) & (CMS_SIZE - 1),
    )


# ---------------------------------------------------------------------------
# Register I/O helpers
# ---------------------------------------------------------------------------

def _read_register_array(bfrt_info, tbl_name, size, target):
    """
    Read all entries of a register table, return (list[int], field_name).

    SDE 9.13.4 quirk: entry_get yields (key_obj, data_obj) pairs, but for
    register tables the $REGISTER_INDEX can appear in data_obj.to_dict()
    rather than key_obj.to_dict().  Additionally, zero-value entries omit
    the value field entirely from to_dict() (sparse representation).

    Strategy:
      - Whichever dict contains '$REGISTER_INDEX' is treated as the index source.
      - The other dict (or the same dict) is searched for the '.f1' value field.
      - Zero-value entries (no value field present) contribute 0 to the array.
      - We never abort early — all 1024 entries are iterated.
    """
    arr = [0] * size
    tbl = bfrt_info.table_get(tbl_name)

    reg_short      = tbl_name.split('.')[-1]          # e.g. 'cms_0'
    expected_field = f'SwitchIngress.{reg_short}.f1'  # e.g. 'SwitchIngress.cms_0.f1'
    discovered     = None  # field name, found on first non-zero entry

    try:
        for key, data in tbl.entry_get(target, None, {'from_hw': True}):
            k_dict = key.to_dict()
            d_dict = data.to_dict()

            # --- find the index -------------------------------------------
            # In SDE 9.13.4, $REGISTER_INDEX may appear in either dict.
            if '$REGISTER_INDEX' in d_dict:
                idx_src = d_dict
                val_src = k_dict   # value field lives in the OTHER dict
            else:
                idx_src = k_dict
                val_src = d_dict

            idx_entry = idx_src.get('$REGISTER_INDEX', 0)
            if isinstance(idx_entry, dict):
                idx = idx_entry.get('value', 0)
            else:
                idx = int(idx_entry)

            # --- find the value -------------------------------------------
            # For zero-value entries the field is absent (sparse).  We look in
            # val_src first; fall back to searching both dicts for any '.f1'.
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
                    val = 0   # zero-value entry — field omitted by SDE

            if isinstance(val, list):
                val = val[0]   # wide registers may return [lo_word, hi_word]

            if 0 <= idx < size:
                arr[idx] = val

    except Exception as e:
        print(f"  [WARN] entry_get failed for {tbl_name}: {e}")

    # Use the discovered name; fall back to the expected pattern for clearing.
    return arr, (discovered or expected_field)


def read_cms_snapshot(bfrt_info, target):
    """
    Read all 3 CMS rows from the switch.
    Returns (snapshot_dict, field_names_dict):
      snapshot_dict    : row_name -> list[int] of length CMS_SIZE
      field_names_dict : row_name -> bfrt field name string (used for clearing)
    """
    snapshot    = {}
    field_names = {}
    for row in CMS_ROWS:
        tbl_name = f'pipe.SwitchIngress.{row}'
        arr, fname = _read_register_array(bfrt_info, tbl_name, CMS_SIZE, target)
        snapshot[row]    = arr
        field_names[row] = fname
    return snapshot, field_names


def clear_all_registers(bfrt_info, target, cms_field_names=None):
    """
    Clear BF and CMS registers to start a fresh epoch.

    Uses entry_mod to write zeros — tbl.clear() does not exist in the
    bfrt_grpc Python client for SDE 9.13.4.
    """
    # Register sizes: BF rows are 131072 entries (bit<1>), CMS rows are 1024 (bit<16>).
    reg_sizes = {r: 131072 for r in BF_ROWS}
    reg_sizes.update({r: CMS_SIZE for r in CMS_ROWS})

    for reg in BF_ROWS + CMS_ROWS:
        tbl_name   = f'pipe.SwitchIngress.{reg}'
        size       = reg_sizes[reg]
        # Use discovered CMS field name if available, else construct from pattern.
        if cms_field_names and reg in cms_field_names:
            field_name = cms_field_names[reg]
        else:
            field_name = f'SwitchIngress.{reg}.f1'

        tbl = bfrt_info.table_get(tbl_name)
        ok  = True
        # Write zeros in batches of 128 to stay within gRPC message limits.
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
# Epoch processing
# ---------------------------------------------------------------------------

def process_epoch(epoch_num, flow_table, bfrt_info, target):
    """
    Read the CMS snapshot, compute per-flow estimates, print a report,
    then clear BF + CMS registers on the switch.
    """
    sep = '=' * 64
    print(f'\n{sep}')
    print(f'  EPOCH {epoch_num} END  —  {len(flow_table)} flows detected by BF')
    print(sep)

    cms_field_names = {}

    if not flow_table:
        print('  (no flows this epoch)')
    else:
        # Read CMS state from switch.
        if HAS_CRCMOD:
            print('  Reading CMS registers...')
            snapshot, cms_field_names = read_cms_snapshot(bfrt_info, target)
            # cms_ok: True if all rows returned non-None arrays.
            # Arrays are always lists (never None), so check for a non-zero sum
            # to detect a completely empty CMS (possible if P4 increment failed).
            cms_ok = True
            total_counts = sum(sum(snapshot[r]) for r in CMS_ROWS)
            if total_counts == 0:
                print('  [WARN] All CMS counters are 0. '
                      'Verify CMS increment is working:')
                print('         In bfshell: '
                      'bfrt.prototype3.pipe.SwitchIngress.cms_0.dump(from_hw=True)')
                cms_ok = False
        else:
            snapshot = {}
            cms_ok = False

        # Header
        print()
        print(f'  {"Flow":<44} {"Digests":>7}  {"CMS est.":>8}')
        print(f'  {"-"*44} {"-"*7}  {"-"*8}')

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
                    estimate = min(counts)
                    est_str = str(estimate)
                else:
                    est_str = 'N/A'
            else:
                est_str = 'N/A'

            print(f'  {flow_str:<44} {digest_count:>7}  {est_str:>8}')

        print()

    # Clear BF + CMS on switch.
    print('  Clearing BF + CMS registers for next epoch...')
    clear_all_registers(bfrt_info, target, cms_field_names)
    print(f'{sep}\n')


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='FlowLiDAR Prototype 3 — Control Plane')
    parser.add_argument('--epoch', type=float, default=10.0,
                        help='Epoch length in seconds (default: 10)')
    args = parser.parse_args()
    epoch_seconds = args.epoch

    print('=' * 64)
    print('  FlowLiDAR Prototype 3 — Control Plane')
    print(f'  Connecting to {GRPC_ADDR} ...')
    print(f'  Epoch length : {epoch_seconds}s')
    print('=' * 64)

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

    flow_table  = {}   # flow_key -> number of digest notifications this epoch
    total       = 0    # total digest notifications across all epochs
    epoch_num   = 1
    epoch_start = time.time()

    while True:
        try:
            # Poll for digest notifications (short timeout so epoch timer fires).
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
            # On Ctrl-C: run final epoch then exit.
            print('\nCtrl-C received — running final epoch report...')
            process_epoch(epoch_num, flow_table, bfrt_info, target)
            print(f'Total digest notifications received: {total}')
            break
        except Exception:
            # Timeout or transient gRPC error — keep polling.
            pass

        # Check epoch timer.
        elapsed = time.time() - epoch_start
        if elapsed >= epoch_seconds:
            process_epoch(epoch_num, flow_table, bfrt_info, target)
            flow_table.clear()
            epoch_num  += 1
            epoch_start = time.time()


if __name__ == '__main__':
    main()
