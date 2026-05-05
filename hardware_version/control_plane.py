#!/usr/bin/env python3
"""
FlowLiDAR hardware_version — Control Plane (Equation Solver / Postprocessing)
Run this on p4switch2 (the real Tofino switch).

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
# SDE Python path — adjusted for p4switch2 (SDE 9.11.0, Python 3.10)
# ---------------------------------------------------------------------------
SDE_INSTALL = os.environ.get('SDE_INSTALL',
                             '/home/onie/sde/bf-sde-9.11.0/install')
sys.path.append(os.path.join(SDE_INSTALL, 'lib/python3.8/site-packages'))
sys.path.append(os.path.join(SDE_INSTALL, 'lib/python3.8/site-packages/tofino'))
sys.path.append(os.path.join(SDE_INSTALL, 'lib/python3.8/site-packages/tofino/bfrt_grpc'))

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


def _read_register_cells(bfrt_info, tbl_name, indices, target):
    """Read specific register cells in one gRPC call. Returns {idx: value}."""
    if not indices:
        return {}
    tbl = bfrt_info.table_get(tbl_name)
    reg_short      = tbl_name.split('.')[-1]
    expected_field = f'SwitchIngress.{reg_short}.f1'
    keys   = [tbl.make_key([gc.KeyTuple('$REGISTER_INDEX', i)]) for i in indices]
    result = {}
    try:
        for k, data in tbl.entry_get(target, keys, {'from_hw': True}):
            k_dict = k.to_dict()
            d_dict = data.to_dict()
            if '$REGISTER_INDEX' in d_dict:
                idx_src, val_src = d_dict, k_dict
            else:
                idx_src, val_src = k_dict, d_dict
            idx_raw = idx_src.get('$REGISTER_INDEX', 0)
            idx = idx_raw.get('value', 0) if isinstance(idx_raw, dict) else int(idx_raw)
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
            result[idx] = int(val)
    except Exception as e:
        print(f"  [WARN] targeted read failed for {tbl_name}: {e}")
    return result


def read_bf_snapshot(bfrt_info, target, flow_table):
    """Read only the BF cells needed by flows in flow_table (one gRPC call per row)."""
    indices_needed = [set() for _ in BF_ROWS]
    for flow_key in flow_table:
        idxs = bf_indices(flow_key)
        if idxs:
            for r, idx in enumerate(idxs):
                indices_needed[r].add(idx)
    snapshot = {}
    for r, row in enumerate(BF_ROWS):
        tbl_name = f'pipe.SwitchIngress.{row}'
        snapshot[row] = _read_register_cells(
            bfrt_info, tbl_name, list(indices_needed[r]), target)
    return snapshot


def read_bf_bits_for_flow(bf_snapshot, flow_key):
    """Return (b0, b1, b2) from an in-memory BF snapshot (dict per row)."""
    idxs = bf_indices(flow_key)
    if idxs is None:
        return None
    i0, i1, i2 = idxs
    return (bf_snapshot['bf_0'].get(i0, 0),
            bf_snapshot['bf_1'].get(i1, 0),
            bf_snapshot['bf_2'].get(i2, 0))


def _clear_indices(tbl, field_name, indices, target, batch=4096):
    """Write 0 to a specific set of register indices."""
    for start in range(0, len(indices), batch):
        chunk = indices[start:start + batch]
        keys  = [tbl.make_key([gc.KeyTuple('$REGISTER_INDEX', i)]) for i in chunk]
        datas = [tbl.make_data([gc.DataTuple(field_name, 0)]) for _ in chunk]
        try:
            tbl.entry_mod(target, keys, datas)
        except Exception as e:
            print(f"  [WARN] clear failed: {e}")


def clear_registers_targeted(bfrt_info, target, bf_snapshot, cms_snapshot):
    """Clear only the register cells that were actually set this epoch."""
    for row in BF_ROWS:
        tbl = bfrt_info.table_get(f'pipe.SwitchIngress.{row}')
        nz  = [i for i, v in bf_snapshot[row].items() if v != 0]
        _clear_indices(tbl, f'SwitchIngress.{row}.f1', nz, target)
    for row in CMS_ROWS:
        tbl = bfrt_info.table_get(f'pipe.SwitchIngress.{row}')
        nz  = [i for i, v in enumerate(cms_snapshot[row]) if v != 0]
        _clear_indices(tbl, f'SwitchIngress.{row}.f1', nz, target)


# ---------------------------------------------------------------------------
# Postprocessing — Algorithms 4, 5, solver, Algorithm 6
# ---------------------------------------------------------------------------

def algorithm4_bf_preprocess(flow_table, bf_snapshot):
    """
    Algorithm 4 (BF preprocessing with lazy updates).
    Returns:
        resolved: dict flow_key -> exact total count
        C:        list of flow_keys that need CMS processing
    """
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
    """
    Algorithm 5 (CMS preprocessing).
    Returns:
        resolved: dict flow_key -> exact total count (added to caller's resolved)
        C_final:  list of flow_keys that need equation solving
    """
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


def build_matrix(C_final, cms_snapshot):
    """
    Build the binary matrix A and counter vector b for the equation system Ax=b.
    """
    row_names = ['cms_0', 'cms_1', 'cms_2']

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
    """
    print('  --- Algorithm 6: approximate fallback ---')
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
    Build and solve Ax=b for flows in C_final.
    Returns dict flow_key -> total count (digest_count + solver x_j).
    Falls back to Algorithm 6 if underdetermined.
    """
    if not C_final:
        return {}

    A, b, m_eq, n = build_matrix(C_final, cms_snapshot)
    x, residuals, rank, sv = np.linalg.lstsq(A, b, rcond=None)

    load_factor = n / CMS_SIZE
    exact = rank >= n
    if not exact:
        x = algorithm6_approximate(A, b, n, rank)
        solver_note = f'underdetermined -> Alg6 approx'
    else:
        res = np.linalg.norm(A @ x - b)
        solver_note = f'exact, residual={res:.4f}' if res <= 0.5 else f'[WARN] residual={res:.2f}'

    print(f'  Matrix {m_eq}x{n} | rank={rank} | load={load_factor:.3f} | {solver_note}')

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
        print(f'{sep}\n')
        return

    print('  Reading BF + CMS registers...')
    bf_snapshot              = read_bf_snapshot(bfrt_info, target, flow_table)
    cms_snapshot, _          = read_cms_snapshot(bfrt_info, target)

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
        print('  Running postprocessing...')

        resolved, C = algorithm4_bf_preprocess(flow_table, bf_snapshot)
        resolved5, C_final = algorithm5_cms_preprocess(C, flow_table, cms_snapshot)
        resolved.update(resolved5)
        solver_results = solve_cms_system(C_final, flow_table, cms_snapshot)

        n_alg4   = len(resolved) - len(resolved5)
        n_alg5   = len(resolved5)
        n_solver = len(solver_results)
        n_total  = len(flow_table)

        print()
        print(f'  Total flows          : {n_total}')
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
        description='FlowLiDAR hardware_version — Control Plane (Equation Solver)')
    parser.add_argument('--epoch', type=float, default=10.0,
                        help='Epoch length in seconds (default: 10)')
    args = parser.parse_args()
    epoch_seconds = args.epoch

    print('=' * 72)
    print('  FlowLiDAR hardware_version — Control Plane (Equation Solver)')
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
                if total % 1000 == 0:
                    print(f"  [{total} digests received, {len(flow_table)} unique flows]")

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
