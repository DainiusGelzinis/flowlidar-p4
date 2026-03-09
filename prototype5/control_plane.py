#!/usr/bin/env python3
"""
FlowLiDAR Prototype 5 — Control Plane (Equation Solver / Postprocessing)

Implements the full §3.4 postprocessing pipeline from the paper:
  - Algorithm 4: BF preprocessing (targeted register reads)
  - Algorithm 5: CMS preprocessing
  - Equation solver: Ax=b via numpy (exact counts)
  - Algorithm 6: approximate fallback when system is underdetermined

Usage:
    python3 control_plane.py [--epoch SECONDS]
"""

import sys
import os
import time
import struct
import socket
import argparse

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
P4_NAME    = 'prototype5'

CMS_SIZE   = 1024
CMS_ROWS   = ['cms_0', 'cms_1', 'cms_2']
BF_ROWS    = ['bf_0',  'bf_1',  'bf_2']
BF_SIZE    = 131072   # 2^17

# ---------------------------------------------------------------------------
# CRC functions
# CMS: same polynomials as prototype3/4 (empirically confirmed)
# BF:  same polynomials as prototype2/3/4
# Mapping: crcmod initCrc = P4_init XOR P4_residue, xorOut = P4_residue
# ---------------------------------------------------------------------------
if HAS_CRCMOD:
    # CMS hash functions
    _cms_fn0 = crcmod.mkCrcFun(0x1A833982B, rev=True,
                                initCrc=0x00000000, xorOut=0xFFFFFFFF)
    _cms_fn1 = crcmod.mkCrcFun(0x1814141AB, rev=False,
                                initCrc=0x00000000, xorOut=0x00000000)
    _cms_fn2 = crcmod.mkCrcFun(0x104C11DB7, rev=False,
                                initCrc=0xFFFFFFFF, xorOut=0xFFFFFFFF)

    # BF hash functions
    _bf_fn0 = crcmod.mkCrcFun(0x104C11DB7, rev=True,
                               initCrc=0x00000000, xorOut=0xFFFFFFFF)
    _bf_fn1 = crcmod.mkCrcFun(0x104C11DB7, rev=False,
                               initCrc=0x00000000, xorOut=0xFFFFFFFF)
    _bf_fn2 = crcmod.mkCrcFun(0x11EDC6F41, rev=True,
                               initCrc=0x00000000, xorOut=0xFFFFFFFF)


def _flow_bytes(src_addr, dst_addr, protocol, src_port, dst_port):
    src_int = struct.unpack('!I', socket.inet_aton(src_addr))[0]
    dst_int = struct.unpack('!I', socket.inet_aton(dst_addr))[0]
    return struct.pack('!IIBHH', src_int, dst_int, protocol, src_port, dst_port)


def cms_indices(flow_key):
    if not HAS_CRCMOD:
        return None
    data = _flow_bytes(*flow_key)
    return (
        _cms_fn0(data) & (CMS_SIZE - 1),
        _cms_fn1(data) & (CMS_SIZE - 1),
        _cms_fn2(data) & (CMS_SIZE - 1),
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
# Register I/O helpers
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


def _read_register_cell(bfrt_info, tbl_name, idx, target):
    """Read a single register cell by index (targeted, fast)."""
    tbl = bfrt_info.table_get(tbl_name)
    reg_short      = tbl_name.split('.')[-1]
    expected_field = f'SwitchIngress.{reg_short}.f1'
    key = tbl.make_key([gc.KeyTuple('$REGISTER_INDEX', idx)])
    try:
        for k, data in tbl.entry_get(target, [key], {'from_hw': True}):
            combined = {**k.to_dict(), **data.to_dict()}
            if expected_field in combined:
                val = combined[expected_field]
            else:
                val = next((combined[f] for f in combined if f.endswith('.f1')), 0)
            if isinstance(val, list):
                val = val[0]
            return int(val)
    except Exception as e:
        print(f"  [WARN] cell read failed {tbl_name}[{idx}]: {e}")
    return 0


def read_cms_snapshot(bfrt_info, target):
    snapshot    = {}
    field_names = {}
    for row in CMS_ROWS:
        tbl_name = f'pipe.SwitchIngress.{row}'
        arr = _read_register_array(bfrt_info, tbl_name, CMS_SIZE, target)
        snapshot[row] = arr
        field_names[row] = f'SwitchIngress.{row}.f1'
    return snapshot, field_names


def read_bf_bits_for_flow(bfrt_info, target, flow_key):
    """Return (b0, b1, b2) — the BF bit values for this flow's hash positions."""
    idxs = bf_indices(flow_key)
    if idxs is None:
        return None
    i0, i1, i2 = idxs
    b0 = _read_register_cell(bfrt_info, 'pipe.SwitchIngress.bf_0', i0, target)
    b1 = _read_register_cell(bfrt_info, 'pipe.SwitchIngress.bf_1', i1, target)
    b2 = _read_register_cell(bfrt_info, 'pipe.SwitchIngress.bf_2', i2, target)
    return (b0, b1, b2)


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


# ---------------------------------------------------------------------------
# Postprocessing — Algorithms 4, 5, solver, Algorithm 6
# ---------------------------------------------------------------------------

def algorithm4_bf_preprocess(flow_table, bfrt_info, target):
    """
    Algorithm 4 (BF preprocessing with lazy updates).
    Returns:
        resolved: dict flow_key -> exact total count
        C:        list of flow_keys that need CMS processing
    """
    resolved = {}
    C        = []

    print('  --- Algorithm 4: BF preprocessing ---')
    for flow_key, digest_count in flow_table.items():
        bits = read_bf_bits_for_flow(bfrt_info, target, flow_key)
        if bits is None:
            # crcmod unavailable — treat as needing CMS
            C.append(flow_key)
            continue
        b0, b1, b2 = bits
        if b0 == 0 or b1 == 0 or b2 == 0:
            # At least one BF bit is 0: flow had ≤ k packets, all counted
            # as digests. Exact count = digest_count.
            src, dst, proto, sport, dport = flow_key
            proto_name = {6: 'TCP', 17: 'UDP'}.get(proto, str(proto))
            print(f'  {src}:{sport}->{dst}:{dport} {proto_name}'
                  f'  bf=({b0},{b1},{b2})  -> exact={digest_count} (digest only)')
            resolved[flow_key] = digest_count
        else:
            C.append(flow_key)

    print(f'  Flows resolved by Alg4: {len(resolved)}  '
          f'Flows remaining for CMS: {len(C)}')
    return resolved, C


def algorithm5_cms_preprocess(C, flow_table, cms_snapshot):
    """
    Algorithm 5 (CMS preprocessing).
    Returns:
        resolved: dict flow_key -> exact total count (added to caller's resolved)
        C_final:  list of flow_keys that need equation solving
    """
    resolved = {}
    C_final  = []

    print('  --- Algorithm 5: CMS preprocessing ---')
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
            src, dst, proto, sport, dport = flow_key
            proto_name = {6: 'TCP', 17: 'UDP'}.get(proto, str(proto))
            print(f'  {src}:{sport}->{dst}:{dport} {proto_name}'
                  f'  CMS=0  -> exact={digest_count} (digest only)')
            resolved[flow_key] = digest_count
        else:
            C_final.append(flow_key)

    print(f'  Flows resolved by Alg5: {len(resolved)}  '
          f'Flows remaining for solver: {len(C_final)}')
    return resolved, C_final


def build_matrix(C_final, cms_snapshot):
    """
    Build the binary matrix A and counter vector b for the equation system Ax=b.

    Each unique (row, cell) pair referenced by any flow in C_final becomes one
    equation. A[eq_i][j] = 1 if flow j hashes to the cell of equation eq_i.
    b[eq_i] = the CMS counter value for that cell.
    """
    row_names = ['cms_0', 'cms_1', 'cms_2']

    # Collect all unique counter positions
    counter_to_eq = {}
    eq_idx = 0
    for flow_key in C_final:
        idxs = cms_indices(flow_key)
        if idxs is None:
            continue
        for r, cell in enumerate(idxs):
            key = (r, cell)
            if key not in counter_to_eq:
                counter_to_eq[key] = eq_idx
                eq_idx += 1

    m_eq = len(counter_to_eq)
    n    = len(C_final)

    A = np.zeros((m_eq, n), dtype=float)
    b = np.zeros(m_eq,      dtype=float)

    for (r, cell), eq_i in counter_to_eq.items():
        b[eq_i] = cms_snapshot[row_names[r]][cell]

    for j, flow_key in enumerate(C_final):
        idxs = cms_indices(flow_key)
        if idxs is None:
            continue
        for r, cell in enumerate(idxs):
            eq_i = counter_to_eq[(r, cell)]
            A[eq_i][j] = 1.0

    return A, b, m_eq, n


def algorithm6_approximate(A, b, n, rank):
    """
    Algorithm 6 — approximate resolution for underdetermined systems.

    Fixes free variables by sorting equations by b_i ascending and assigning
    b_i / n_i to each variable in the equation, reducing the number of free
    variables until the system is fully determined.
    """
    print('  --- Algorithm 6: approximate fallback ---')
    free_remaining = n - rank

    # Work on a copy; track which columns are fixed
    x_approx   = np.zeros(n, dtype=float)
    fixed      = np.zeros(n, dtype=bool)

    # Sort equation indices by b value ascending
    order = np.argsort(b)

    for eq_i in order:
        if free_remaining <= 0:
            break
        # Which columns (flows) appear in this equation and are not yet fixed?
        cols = [j for j in range(n) if A[eq_i][j] > 0 and not fixed[j]]
        if not cols:
            continue
        val = b[eq_i] / len(cols)
        for j in cols:
            x_approx[j] = val
            fixed[j]    = True
        free_remaining -= len(cols)

    # Solve the reduced system for any remaining unfixed variables
    unfixed = [j for j in range(n) if not fixed[j]]
    if unfixed:
        # Build reduced system: subtract fixed contributions from b
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
    Build and solve Ax=b for flows in C_final.
    Returns dict flow_key -> total count (digest_count + solver x_j).
    Falls back to Algorithm 6 if underdetermined.
    """
    if not C_final:
        return {}

    A, b, m_eq, n = build_matrix(C_final, cms_snapshot)
    print(f'  --- Equation solver (Ax=b, {m_eq}x{n} system) ---')

    # Solve via least squares
    x, residuals, rank, sv = np.linalg.lstsq(A, b, rcond=None)

    load_factor = n / CMS_SIZE
    print(f'  rank={rank}  n={n}  load={load_factor:.3f}')

    if rank < n:
        print(f'  System underdetermined (rank {rank} < n {n}) '
              f'-> Algorithm 6 approximate fallback')
        x = algorithm6_approximate(A, b, n, rank)
    else:
        # Check residual — large residual means hash collisions distorted b
        res = np.linalg.norm(A @ x - b)
        if res > 0.5:
            print(f'  [WARN] Residual={res:.2f} — possible hash collisions. '
                  f'Result may be approximate.')
        else:
            print(f'  System uniquely determined. Residual={res:.4f}')

    # Round and clip (counts must be non-negative integers)
    x = np.clip(np.round(x), 0, None).astype(int)

    result = {}
    for j, flow_key in enumerate(C_final):
        result[flow_key] = flow_table[flow_key] + int(x[j])

    return result


# ---------------------------------------------------------------------------
# Epoch processing
# ---------------------------------------------------------------------------

def process_epoch(epoch_num, flow_table, bfrt_info, target):
    sep = '=' * 72
    print(f'\n{sep}')
    print(f'  EPOCH {epoch_num} END  —  {len(flow_table)} flows detected by BF')
    print(sep)

    cms_field_names = {}

    if not flow_table:
        print('  (no flows this epoch)')
        clear_all_registers(bfrt_info, target)
        print(f'{sep}\n')
        return

    print('  Reading CMS registers...')
    cms_snapshot, cms_field_names = read_cms_snapshot(bfrt_info, target)

    if not HAS_CRCMOD:
        # Fallback: plain CMS min estimate (same as prototype4)
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
        print('  Reading BF registers (targeted)...')
        print()

        # --- Algorithm 4: BF preprocessing ---
        resolved, C = algorithm4_bf_preprocess(flow_table, bfrt_info, target)
        print()

        # --- Algorithm 5: CMS preprocessing ---
        resolved5, C_final = algorithm5_cms_preprocess(C, flow_table, cms_snapshot)
        resolved.update(resolved5)
        print()

        # --- Equation solver ---
        solver_results = solve_cms_system(C_final, flow_table, cms_snapshot)
        print()

        # Merge all results
        all_results = {}
        for flow_key in flow_table:
            if flow_key in solver_results:
                all_results[flow_key] = (
                    flow_table[flow_key],
                    solver_results[flow_key] - flow_table[flow_key],
                    solver_results[flow_key],
                    'solver'
                )
            elif flow_key in resolved5:
                all_results[flow_key] = (
                    flow_table[flow_key], 0,
                    resolved5[flow_key], 'alg5'
                )
            else:
                all_results[flow_key] = (
                    flow_table[flow_key], 0,
                    resolved.get(flow_key, flow_table[flow_key]), 'alg4'
                )

        # Print report
        print(f'  {"Flow":<44} {"Digests":>7}  {"CMS/Solve":>9}  {"Total":>5}  {"Method":>6}')
        print(f'  {"-"*44} {"-"*7}  {"-"*9}  {"-"*5}  {"-"*6}')

        exact_count = 0
        for flow_key in sorted(all_results):
            src, dst, proto, sport, dport = flow_key
            proto_name = {6: 'TCP', 17: 'UDP'}.get(proto, str(proto))
            flow_str = f'{src}:{sport} -> {dst}:{dport} {proto_name}'
            digest_count, cms_part, total, method = all_results[flow_key]
            print(f'  {flow_str:<44} {digest_count:>7}  {cms_part:>9}  {total:>5}  {method:>6}')
            exact_count += 1

        print()
        print(f'  Flows reported: {exact_count}/{len(flow_table)}')

    print()
    print('  Clearing BF + CMS registers for next epoch...')
    clear_all_registers(bfrt_info, target, cms_field_names)
    print(f'{sep}\n')


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description='FlowLiDAR Prototype 5 — Control Plane (Equation Solver)')
    parser.add_argument('--epoch', type=float, default=10.0,
                        help='Epoch length in seconds (default: 10)')
    args = parser.parse_args()
    epoch_seconds = args.epoch

    print('=' * 72)
    print('  FlowLiDAR Prototype 5 — Control Plane (Equation Solver)')
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
