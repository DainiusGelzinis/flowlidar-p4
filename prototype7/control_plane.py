#!/usr/bin/env python3
"""
FlowLiDAR Prototype 6 — Control Plane (Sub-sketch / Sketchlet partitioning)

Adds master-hash sub-sketch partitioning to the equation solver:
  - Each flow is mapped to one of 64 buckets by a master hash.
  - The CMS is logically 64 sub-sketches × 1024 cells per row.
  - Solver runs 64 small independent systems instead of one large one.

Otherwise identical to prototype5: BF preprocessing (Alg 4), CMS preprocessing
(Alg 5), exact equation solving, Algorithm 6 fallback.

Usage:
    python3 control_plane.py [--epoch SECONDS]
"""

import sys
import os
import time
import struct
import socket
import argparse
from collections import defaultdict

import numpy as np

# ---------------------------------------------------------------------------
# SDE Python path
# ---------------------------------------------------------------------------
SDE_INSTALL = os.environ.get('SDE_INSTALL',
                             '/home/student/Desktop/open-p4studio/install')
sys.path.append(os.path.join(SDE_INSTALL, 'lib/python3.8/site-packages'))
sys.path.append(os.path.join(SDE_INSTALL, 'lib/python3.8/site-packages/tofino'))

import bfrt_grpc.client as gc

try:
    import crcmod
    HAS_CRCMOD = True
except ImportError:
    HAS_CRCMOD = False
    print("[WARN] crcmod not installed — postprocessing will not run.")
    print("       Install with: pip3 install crcmod\n")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
GRPC_ADDR  = 'localhost:50052'
CLIENT_ID  = 0
DEVICE_ID  = 0
P4_NAME    = 'prototype7'

# Sub-sketch parameters
NUM_BUCKETS    = 64                  # Master hash output: 6 bits
COLS_PER_ROW   = 1024                # Columns per sub-sketch (10 bits)
CMS_SIZE       = NUM_BUCKETS * COLS_PER_ROW   # 65536 total cells per row
CMS_ROWS       = ['cms_0', 'cms_1', 'cms_2']
BF_ROWS        = ['bf_0',  'bf_1',  'bf_2']
BF_SIZE        = 1048576  # 2^20  (8x prototype6, 4x earlier prototype7)

# ---------------------------------------------------------------------------
# CRC functions
# Master hash: NEW polynomial (0xF4ACFB13), distinct from BF and column hashes.
# Column hashes: same as prototype5.
# BF hashes: same as prototype5.
# Mapping: crcmod initCrc = P4_init XOR P4_residue, xorOut = P4_residue
# ---------------------------------------------------------------------------
if HAS_CRCMOD:
    # Master hash (32-bit polynomial, take low 6 bits of output)
    _master_fn_full = crcmod.mkCrcFun(0x1F4ACFB13, rev=True,
                                       initCrc=0x00000000, xorOut=0xFFFFFFFF)

    # CMS column hashes (32-bit polynomial, take low 10 bits of output)
    _cms_fn0 = crcmod.mkCrcFun(0x1A833982B, rev=True,
                                initCrc=0x00000000, xorOut=0xFFFFFFFF)
    _cms_fn1 = crcmod.mkCrcFun(0x1814141AB, rev=False,
                                initCrc=0x00000000, xorOut=0x00000000)
    _cms_fn2 = crcmod.mkCrcFun(0x104C11DB7, rev=False,
                                initCrc=0xFFFFFFFF, xorOut=0xFFFFFFFF)

    # BF hash functions
    _bf_fn0 = crcmod.mkCrcFun(0x104C11DB7, rev=True,
                               initCrc=0x00000000, xorOut=0xFFFFFFFF)
    # poly1: CRC-32D (0xA833982B), distinct generator from poly0/poly2
    _bf_fn1 = crcmod.mkCrcFun(0x1A833982B, rev=True,
                               initCrc=0x00000000, xorOut=0xFFFFFFFF)
    _bf_fn2 = crcmod.mkCrcFun(0x11EDC6F41, rev=True,
                               initCrc=0x00000000, xorOut=0xFFFFFFFF)


def _flow_bytes(src_addr, dst_addr, protocol, src_port, dst_port):
    src_int = struct.unpack('!I', socket.inet_aton(src_addr))[0]
    dst_int = struct.unpack('!I', socket.inet_aton(dst_addr))[0]
    return struct.pack('!IIBHH', src_int, dst_int, protocol, src_port, dst_port)


def master_idx(flow_key):
    """Sub-sketch bucket id (0..63) for a given flow."""
    if not HAS_CRCMOD:
        return 0
    data = _flow_bytes(*flow_key)
    return _master_fn_full(data) & (NUM_BUCKETS - 1)


def cms_indices(flow_key):
    """Full 16-bit CMS indices: master_hash[5:0] :: col_hash[9:0]."""
    if not HAS_CRCMOD:
        return None
    data = _flow_bytes(*flow_key)
    bucket = master_idx(flow_key)
    high   = bucket << 10  # shift to bits [15:10]
    return (
        high | (_cms_fn0(data) & (COLS_PER_ROW - 1)),
        high | (_cms_fn1(data) & (COLS_PER_ROW - 1)),
        high | (_cms_fn2(data) & (COLS_PER_ROW - 1)),
    )


def bf_indices(flow_key):
    if not HAS_CRCMOD:
        return None
    data = _flow_bytes(*flow_key)
    return (
        _bf_fn0(data) & (BF_SIZE - 1),
        _bf_fn1(data) & (BF_SIZE - 1),
        _bf_fn2(data) & (BF_SIZE - 1),
    )


# ---------------------------------------------------------------------------
# Register I/O helpers (same approach as hardware_version)
# ---------------------------------------------------------------------------

def _read_register_array(bfrt_info, tbl_name, size, target):
    arr = [0] * size
    tbl = bfrt_info.table_get(tbl_name)
    reg_short      = tbl_name.split('.')[-1]
    expected_field = f'SwitchIngress.{reg_short}.f1'

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
            elif expected_field in idx_src:
                val = idx_src[expected_field]
            else:
                combined = {**k_dict, **d_dict}
                f1 = next((f for f in combined if f.endswith('.f1')), None)
                val = combined[f1] if f1 else 0

            if isinstance(val, list):
                val = val[0]

            if 0 <= idx < size:
                arr[idx] = val

    except Exception as e:
        print(f"  [WARN] entry_get failed for {tbl_name}: {e}")

    return arr


def read_bf_snapshot(bfrt_info, target):
    snapshot = {}
    for row in BF_ROWS:
        tbl_name = f'pipe.SwitchIngress.{row}'
        snapshot[row] = _read_register_array(bfrt_info, tbl_name, BF_SIZE, target)
    return snapshot


def read_bf_bits_for_flow(bf_snapshot, flow_key):
    idxs = bf_indices(flow_key)
    if idxs is None:
        return None
    i0, i1, i2 = idxs
    return (bf_snapshot['bf_0'][i0], bf_snapshot['bf_1'][i1], bf_snapshot['bf_2'][i2])


def read_cms_snapshot(bfrt_info, target):
    snapshot    = {}
    field_names = {}
    for row in CMS_ROWS:
        tbl_name = f'pipe.SwitchIngress.{row}'
        snapshot[row] = _read_register_array(bfrt_info, tbl_name, CMS_SIZE, target)
        field_names[row] = f'SwitchIngress.{row}.f1'
    return snapshot, field_names


def clear_all_registers(bfrt_info, target, cms_field_names=None):
    reg_sizes = {r: BF_SIZE  for r in BF_ROWS}
    reg_sizes.update({r: CMS_SIZE for r in CMS_ROWS})

    for reg in BF_ROWS + CMS_ROWS:
        tbl_name   = f'pipe.SwitchIngress.{reg}'
        size       = reg_sizes[reg]
        field_name = (cms_field_names or {}).get(reg, f'SwitchIngress.{reg}.f1')

        tbl  = bfrt_info.table_get(tbl_name)
        BATCH = 128
        ok    = True
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
            print(f"  [INFO] Partial clear for {reg}.")


def _clear_indices(tbl, field_name, indices, target, batch=4096):
    for start in range(0, len(indices), batch):
        chunk = indices[start:start + batch]
        keys  = [tbl.make_key([gc.KeyTuple('$REGISTER_INDEX', i)]) for i in chunk]
        datas = [tbl.make_data([gc.DataTuple(field_name, 0)]) for _ in chunk]
        try:
            tbl.entry_mod(target, keys, datas)
        except Exception as e:
            print(f"  [WARN] clear failed: {e}")


def clear_registers_targeted(bfrt_info, target, bf_snapshot, cms_snapshot):
    """Clear only cells that were non-zero this epoch."""
    for row in BF_ROWS:
        tbl = bfrt_info.table_get(f'pipe.SwitchIngress.{row}')
        nz  = [i for i, v in enumerate(bf_snapshot[row]) if v != 0]
        _clear_indices(tbl, f'SwitchIngress.{row}.f1', nz, target)
    for row in CMS_ROWS:
        tbl = bfrt_info.table_get(f'pipe.SwitchIngress.{row}')
        nz  = [i for i, v in enumerate(cms_snapshot[row]) if v != 0]
        _clear_indices(tbl, f'SwitchIngress.{row}.f1', nz, target)


# ---------------------------------------------------------------------------
# Postprocessing — Algorithms 4, 5, sub-sketch solver, Algorithm 6
# ---------------------------------------------------------------------------

def algorithm4_bf_preprocess(flow_table, bf_snapshot):
    resolved = {}
    C        = []
    for flow_key, digest_count in flow_table.items():
        bits = read_bf_bits_for_flow(bf_snapshot, flow_key)
        if bits is None:
            C.append(flow_key)
            continue
        b0, b1, b2 = bits
        if b0 == 0 or b1 == 0 or b2 == 0:
            resolved[flow_key] = digest_count
        else:
            C.append(flow_key)
    return resolved, C


def algorithm5_cms_preprocess(C, flow_table, cms_snapshot):
    resolved = {}
    C_final  = []
    for flow_key in C:
        digest_count = flow_table[flow_key]
        idxs = cms_indices(flow_key)
        if idxs is None:
            C_final.append(flow_key)
            continue
        i0, i1, i2 = idxs
        counts = [
            cms_snapshot['cms_0'][i0],
            cms_snapshot['cms_1'][i1],
            cms_snapshot['cms_2'][i2],
        ]
        cms_est = min(counts)
        if cms_est == 0:
            resolved[flow_key] = digest_count
        else:
            C_final.append(flow_key)
    return resolved, C_final


def build_matrix(C_bucket, cms_snapshot):
    """Build Ax=b for one sub-sketch bucket. Same logic as prototype5."""
    row_names = ['cms_0', 'cms_1', 'cms_2']

    counter_to_eq = {}
    eq_idx = 0
    for flow_key in C_bucket:
        idxs = cms_indices(flow_key)
        if idxs is None:
            continue
        for r, cell in enumerate(idxs):
            key = (r, cell)
            if key not in counter_to_eq:
                counter_to_eq[key] = eq_idx
                eq_idx += 1

    m_eq = len(counter_to_eq)
    n    = len(C_bucket)

    A = np.zeros((m_eq, n), dtype=float)
    b = np.zeros(m_eq,      dtype=float)

    for (r, cell), eq_i in counter_to_eq.items():
        b[eq_i] = cms_snapshot[row_names[r]][cell]

    for j, flow_key in enumerate(C_bucket):
        idxs = cms_indices(flow_key)
        if idxs is None:
            continue
        for r, cell in enumerate(idxs):
            eq_i = counter_to_eq[(r, cell)]
            A[eq_i][j] = 1.0

    return A, b, m_eq, n


def algorithm6_approximate(A, b, n, rank):
    free_remaining = n - rank
    x_approx   = np.zeros(n, dtype=float)
    fixed      = np.zeros(n, dtype=bool)
    order = np.argsort(b)

    for eq_i in order:
        if free_remaining <= 0:
            break
        cols = [j for j in range(n) if A[eq_i][j] > 0 and not fixed[j]]
        if not cols:
            continue
        val = b[eq_i] / len(cols)
        for j in cols:
            x_approx[j] = val
            fixed[j]    = True
        free_remaining -= len(cols)

    unfixed = [j for j in range(n) if not fixed[j]]
    if unfixed:
        b_reduced = b.copy()
        for j in range(n):
            if fixed[j]:
                b_reduced -= A[:, j] * x_approx[j]
        A_reduced = A[:, unfixed]
        x_sub, _, _, _ = np.linalg.lstsq(A_reduced, b_reduced, rcond=None)
        for k, j in enumerate(unfixed):
            x_approx[j] = x_sub[k]

    return x_approx


def solve_cms_system(C_final, flow_table, cms_snapshot):
    """
    Partition C_final by master hash bucket, then solve each sub-system.
    This is the core sub-sketch optimisation: 64 small systems instead of one big one.
    """
    if not C_final:
        return {}

    buckets = defaultdict(list)
    for flow in C_final:
        buckets[master_idx(flow)].append(flow)

    result            = {}
    n_buckets_used    = len(buckets)
    n_underdetermined = 0
    bad_residual      = 0
    max_load          = 0.0

    for bucket_id, bucket_flows in buckets.items():
        A, b, m_eq, n = build_matrix(bucket_flows, cms_snapshot)
        if n == 0:
            continue

        load = n / COLS_PER_ROW
        if load > max_load:
            max_load = load

        x, residuals, rank, sv = np.linalg.lstsq(A, b, rcond=None)

        if rank < n:
            x = algorithm6_approximate(A, b, n, rank)
            n_underdetermined += 1
        else:
            res = np.linalg.norm(A @ x - b)
            if res > 0.5:
                bad_residual += 1

        x = np.clip(np.round(x), 0, None).astype(int)
        for j, flow_key in enumerate(bucket_flows):
            result[flow_key] = flow_table[flow_key] + int(x[j])

    print(f'  Sub-systems solved   : {n_buckets_used} / {NUM_BUCKETS}  '
          f'(max load: {max_load:.3f}, underdetermined: {n_underdetermined}, '
          f'high residual: {bad_residual})')

    return result


# ---------------------------------------------------------------------------
# Epoch processing
# ---------------------------------------------------------------------------

def process_epoch(epoch_num, flow_table, bfrt_info, target, total=0):
    sep = '=' * 72
    print(f'\n{sep}')
    print(f'  EPOCH {epoch_num} END  —  {len(flow_table)} flows detected by BF')
    print(sep)

    cms_field_names = {}

    if not flow_table:
        print('  (no flows this epoch)')
        print('  Clearing BF + CMS registers for next epoch...')
        clear_all_registers(bfrt_info, target)
        print(f'{sep}\n')
        return

    print('  Reading BF + CMS registers...')
    bf_snapshot                   = read_bf_snapshot(bfrt_info, target)
    cms_snapshot, cms_field_names = read_cms_snapshot(bfrt_info, target)

    if not HAS_CRCMOD:
        print()
        print(f'  {"Flow":<44} {"Digests":>7}  {"CMS est.":>8}  {"Total":>5}')
        print(f'  {"-"*44} {"-"*7}  {"-"*8}  {"-"*5}')
        for flow_key, digest_count in sorted(flow_table.items()):
            src, dst, proto, sport, dport = flow_key
            proto_name = {6: 'TCP', 17: 'UDP'}.get(proto, str(proto))
            flow_str = f'{src}:{sport} -> {dst}:{dport} {proto_name}'
            print(f'  {flow_str:<44} {digest_count:>7}  {"N/A":>8}  {"N/A":>5}')
        print()
    else:
        print()

        resolved, C        = algorithm4_bf_preprocess(flow_table, bf_snapshot)
        resolved5, C_final = algorithm5_cms_preprocess(C, flow_table, cms_snapshot)
        resolved.update(resolved5)
        solver_results = solve_cms_system(C_final, flow_table, cms_snapshot)
        print()

        n_alg4   = len(resolved) - len(resolved5)
        n_alg5   = len(resolved5)
        n_solver = len(solver_results)
        n_total  = len(flow_table)

        epoch_digests   = sum(flow_table.values())
        epoch_packets   = sum(resolved.values()) + sum(solver_results.values())

        print(f'  Total flows          : {n_total}')
        print(f'  Epoch digests        : {epoch_digests}  (cumulative: {total})')
        print(f'  Estimated packets    : {epoch_packets}  '
              f'(digests: {epoch_digests} + CMS: {epoch_packets - epoch_digests})')
        print(f'  Digest only (Alg4)   : {n_alg4}  ({100*n_alg4/n_total:.1f}%)')
        print(f'  Digest only (Alg5)   : {n_alg5}  ({100*n_alg5/n_total:.1f}%)')
        print(f'  Equation solver      : {n_solver}  ({100*n_solver/n_total:.1f}%)')

    print()
    print('  Clearing BF + CMS registers for next epoch...')
    clear_registers_targeted(bfrt_info, target, bf_snapshot, cms_snapshot)
    print(f'{sep}\n')


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='FlowLiDAR Prototype 6 — Control Plane (Sub-sketch solver)')
    parser.add_argument('--epoch', type=float, default=10.0,
                        help='Epoch length in seconds (default: 10)')
    parser.add_argument('--pipe', type=int, default=None,
                        help='Pipe id for register access (real hw: 1, simulator: leave unset)')
    args = parser.parse_args()
    epoch_seconds = args.epoch
    pipe_id       = args.pipe

    print('=' * 72)
    print('  FlowLiDAR Prototype 6 — Control Plane (Sub-sketch solver)')
    print(f'  Connecting to {GRPC_ADDR} ...')
    print(f'  Epoch length : {epoch_seconds}s')
    print(f'  Sub-sketches : {NUM_BUCKETS} × {COLS_PER_ROW} cells/row')
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

    if pipe_id is None:
        target = gc.Target(device_id=DEVICE_ID)
    else:
        target = gc.Target(device_id=DEVICE_ID, pipe_id=pipe_id)
        print(f'Using pipe_id={pipe_id}')

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
                if total % 5000 == 0:
                    print(f"  [{total} digests received, {len(flow_table)} unique flows]")

        except KeyboardInterrupt:
            print('\nCtrl-C received — running final epoch report...')
            process_epoch(epoch_num, flow_table, bfrt_info, target, total)
            print(f'Total digest notifications received: {total}')
            break
        except Exception:
            pass

        elapsed = time.time() - epoch_start
        if elapsed >= epoch_seconds:
            process_epoch(epoch_num, flow_table, bfrt_info, target, total)
            flow_table.clear()
            epoch_num  += 1
            epoch_start = time.time()


if __name__ == '__main__':
    main()
