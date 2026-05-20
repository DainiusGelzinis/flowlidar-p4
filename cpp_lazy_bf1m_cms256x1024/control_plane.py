#!/usr/bin/env python3
"""
FlowLiDAR Python control plane for cpp_lazy_bf1m_cms256x1024.

Mirrors the C++ control plane (cpp_lazy_common/main.cpp) in behavior:
  - Algs 4/5 BF/CMS preprocessing
  - Sub-sketch CMS solver (256 buckets * 1024 cols, 1M BF)
  - Algorithm 6 (least squares) when bucket size n <= kSlowSolverCap=500
  - min(cms_rows) fallback when n > kSlowSolverCap or n > 3*cols
  - Targeted register clearing (only non-zero cells)

For section 6.2 of the evaluation (Python vs C++ comparison): both CPs run
the same data plane, do the same per-flow estimation, write the same CSV
format -- only the implementation language and threading model differ.

Usage:
    python3 control_plane.py --epoch 15 --pipe 1 \\
        [--csv-out estimates.csv] [--epochs N]
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
# SDE Python path -- p4switch2 (SDE 9.11.0, Python 3.8)
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
    print("[FATAL] crcmod not installed. Install: pip3 install crcmod")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Configuration -- matches lazy_bf1m_cms256x1024.p4 and cpp_lazy_common
# ---------------------------------------------------------------------------
GRPC_ADDR  = 'localhost:50052'
CLIENT_ID  = 0
DEVICE_ID  = 0
P4_NAME    = 'lazy_bf1m_cms256x1024'

BF_SIZE        = 1048576              # 2^20 cells per BF row
NUM_BUCKETS    = 256                  # master hash output: 8 bits
COLS_PER_ROW   = 1024                 # 2^10 columns per sub-sketch
CMS_SIZE       = NUM_BUCKETS * COLS_PER_ROW   # 262144 cells per row

# Mirrors C++ kSlowSolverCap. Buckets with n > cap fall back to min(cms).
SLOW_SOLVER_CAP = 500

CMS_ROWS = ['cms_0', 'cms_1', 'cms_2']
BF_ROWS  = ['bf_0',  'bf_1',  'bf_2']

# ---------------------------------------------------------------------------
# CRC functions -- must match lazy_bf1m_cms256x1024.p4 polynomials exactly
# ---------------------------------------------------------------------------
# BF hashes (k=3, all rows use same payload, different polynomials)
_bf_fn0 = crcmod.mkCrcFun(0x104C11DB7, rev=True,
                           initCrc=0x00000000, xorOut=0xFFFFFFFF)
_bf_fn1 = crcmod.mkCrcFun(0x104C11DB7, rev=False,
                           initCrc=0x00000000, xorOut=0xFFFFFFFF)
_bf_fn2 = crcmod.mkCrcFun(0x11EDC6F41, rev=True,
                           initCrc=0x00000000, xorOut=0xFFFFFFFF)

# Master hash -- 256 buckets selected from upper 8 bits of 18-bit output.
_master_fn = crcmod.mkCrcFun(0x1F4ACFB13, rev=True,
                              initCrc=0x00000000, xorOut=0xFFFFFFFF)

# CMS column hashes -- 10-bit output (1024 cols per sub-sketch).
_cms_fn0 = crcmod.mkCrcFun(0x1A833982B, rev=True,
                            initCrc=0x00000000, xorOut=0xFFFFFFFF)
_cms_fn1 = crcmod.mkCrcFun(0x1814141AB, rev=False,
                            initCrc=0x00000000, xorOut=0x00000000)
_cms_fn2 = crcmod.mkCrcFun(0x104C11DB7, rev=False,
                            initCrc=0xFFFFFFFF, xorOut=0xFFFFFFFF)


def _flow_bytes(src_addr, dst_addr, protocol, src_port, dst_port):
    src_int = struct.unpack('!I', socket.inet_aton(src_addr))[0]
    dst_int = struct.unpack('!I', socket.inet_aton(dst_addr))[0]
    return struct.pack('!IIBHH', src_int, dst_int, protocol, src_port, dst_port)


def master_bucket(flow_key):
    """Sub-sketch bucket id (0..255). Mirrors C++:
       h = master_crc & (CMS_SIZE-1)
       bucket = h >> log2(COLS_PER_ROW)"""
    data = _flow_bytes(*flow_key)
    h    = _master_fn(data) & (CMS_SIZE - 1)
    return h >> 10


def cms_indices(flow_key):
    """Full 18-bit CMS index per row: (bucket << 10) | col_hash."""
    data   = _flow_bytes(*flow_key)
    bucket = master_bucket(flow_key)
    high   = bucket << 10
    return (
        high | (_cms_fn0(data) & (COLS_PER_ROW - 1)),
        high | (_cms_fn1(data) & (COLS_PER_ROW - 1)),
        high | (_cms_fn2(data) & (COLS_PER_ROW - 1)),
    )


def bf_indices(flow_key):
    data = _flow_bytes(*flow_key)
    return (
        _bf_fn0(data) & (BF_SIZE - 1),
        _bf_fn1(data) & (BF_SIZE - 1),
        _bf_fn2(data) & (BF_SIZE - 1),
    )


# ---------------------------------------------------------------------------
# Register I/O via bfrt-grpc (same pattern as hardware_version2/control_plane.py)
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
                idx_src, val_src = d_dict, k_dict
            else:
                idx_src, val_src = k_dict, d_dict
            idx_entry = idx_src.get('$REGISTER_INDEX', 0)
            idx = idx_entry.get('value', 0) if isinstance(idx_entry, dict) else int(idx_entry)
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
    return {row: _read_register_array(bfrt_info,
                                        f'pipe.SwitchIngress.{row}',
                                        BF_SIZE, target)
            for row in BF_ROWS}


def read_cms_snapshot(bfrt_info, target):
    return {row: _read_register_array(bfrt_info,
                                        f'pipe.SwitchIngress.{row}',
                                        CMS_SIZE, target)
            for row in CMS_ROWS}


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
    for row in BF_ROWS:
        tbl = bfrt_info.table_get(f'pipe.SwitchIngress.{row}')
        nz  = [i for i, v in enumerate(bf_snapshot[row]) if v != 0]
        _clear_indices(tbl, f'SwitchIngress.{row}.f1', nz, target)
    for row in CMS_ROWS:
        tbl = bfrt_info.table_get(f'pipe.SwitchIngress.{row}')
        nz  = [i for i, v in enumerate(cms_snapshot[row]) if v != 0]
        _clear_indices(tbl, f'SwitchIngress.{row}.f1', nz, target)


# ---------------------------------------------------------------------------
# Per-flow estimation -- mirrors cpp_lazy_common/main.cpp dispatch
# ---------------------------------------------------------------------------

def classify_and_estimate(flow_table, bf_snapshot, cms_snapshot):
    """Returns dict flow_key -> (estimated_packets, path) where path is
       one of: 'alg4', 'alg5', 'exact', 'alg6', 'min'."""
    estimates = {}
    bucketed  = defaultdict(list)   # bucket_id -> list of (flow_key, dc)

    n_alg4 = n_alg5 = 0
    for fk, dc in flow_table.items():
        bf_i0, bf_i1, bf_i2 = bf_indices(fk)
        # Alg 4: 1-pkt mouse
        if dc == 1 and bf_snapshot['bf_1'][bf_i1] == 0:
            estimates[fk] = (1, 'alg4'); n_alg4 += 1; continue
        # Alg 4: 2-pkt mouse
        if dc == 2 and bf_snapshot['bf_2'][bf_i2] == 0:
            estimates[fk] = (2, 'alg4'); n_alg4 += 1; continue

        c0, c1, c2 = cms_indices(fk)
        # Alg 5: 3-pkt flow
        if dc == 3:
            cmin = min(cms_snapshot['cms_0'][c0],
                       cms_snapshot['cms_1'][c1],
                       cms_snapshot['cms_2'][c2])
            if cmin == 0:
                estimates[fk] = (3, 'alg5'); n_alg5 += 1; continue

        # Falls through to per-bucket solver
        bucketed[master_bucket(fk)].append((fk, dc, c0, c1, c2))

    # Per-bucket sub-sketch solve
    n_exact = n_alg6 = n_skip = 0
    used_buckets = 0
    max_bucket_n = 0

    for bucket_id, entries in bucketed.items():
        if not entries:
            continue
        used_buckets += 1
        n = len(entries)
        max_bucket_n = max(max_bucket_n, n)

        if n > 3 * COLS_PER_ROW or n > SLOW_SOLVER_CAP:
            # min(cms_rows) fallback
            n_skip += 1
            for fk, dc, c0, c1, c2 in entries:
                v = min(cms_snapshot['cms_0'][c0],
                        cms_snapshot['cms_1'][c1],
                        cms_snapshot['cms_2'][c2])
                estimates[fk] = (dc + int(v), 'min')
            continue

        # Build system A*x = b
        counter_to_eq = {}
        eq_idx = 0
        for fk, dc, c0, c1, c2 in entries:
            for r, cell in enumerate((c0, c1, c2)):
                if (r, cell) not in counter_to_eq:
                    counter_to_eq[(r, cell)] = eq_idx
                    eq_idx += 1
        m = len(counter_to_eq)
        A = np.zeros((m, n), dtype=float)
        b = np.zeros(m,      dtype=float)
        for (r, cell), eq_i in counter_to_eq.items():
            b[eq_i] = cms_snapshot[CMS_ROWS[r]][cell]
        for j, (fk, dc, c0, c1, c2) in enumerate(entries):
            for r, cell in enumerate((c0, c1, c2)):
                A[counter_to_eq[(r, cell)]][j] = 1.0

        x, _, rank, _ = np.linalg.lstsq(A, b, rcond=None)
        # Mirror C++ Exact-only-if-m==n
        if rank == n and m == n:
            path = 'exact'; n_exact += 1
        else:
            path = 'alg6';  n_alg6 += 1
        x_int = np.clip(np.round(x), 0, None).astype(int)
        for j, (fk, dc, _, _, _) in enumerate(entries):
            estimates[fk] = (dc + int(x_int[j]), path)

    stats = dict(
        alg4=n_alg4, alg5=n_alg5, solver=sum(1 for _, p in estimates.values()
                                              if p in ('exact','alg6','min')),
        exact_buckets=n_exact, alg6_buckets=n_alg6, skipped_buckets=n_skip,
        used_buckets=used_buckets, max_bucket_n=max_bucket_n,
    )
    return estimates, stats


# ---------------------------------------------------------------------------
# Epoch processing
# ---------------------------------------------------------------------------

def process_epoch(epoch_num, flow_table, bfrt_info, target, csv_writer=None):
    sep = '=' * 72
    print(f'\n{sep}')
    print(f'  EPOCH {epoch_num} END  --  {len(flow_table)} flows detected by BF')
    print(sep)

    if not flow_table:
        print('  (no flows this epoch -- skipping snapshot/clear)')
        print(sep)
        return

    t0 = time.time()
    bf_snapshot  = read_bf_snapshot(bfrt_info, target)
    cms_snapshot = read_cms_snapshot(bfrt_info, target)
    read_s = time.time() - t0

    print(f'  bulk read time         : {read_s:.3f} s')
    for row in BF_ROWS:
        arr = bf_snapshot[row]
        nz  = sum(1 for v in arr if v)
        sm  = sum(arr)
        print(f'    {row} : {nz} non-zero cells, sum={sm}')
    for row in CMS_ROWS:
        arr = cms_snapshot[row]
        nz  = sum(1 for v in arr if v)
        sm  = sum(arr)
        print(f'    {row} : {nz} non-zero cells, sum={sm}')

    estimates, stats = classify_and_estimate(flow_table, bf_snapshot, cms_snapshot)

    n_total = len(flow_table)
    epoch_digests = sum(flow_table.values())
    epoch_packets = sum(v for v, _ in estimates.values())
    max_load = stats['max_bucket_n'] / COLS_PER_ROW

    def pct(x): return 100.0 * x / n_total if n_total else 0.0
    print(f'  Total flows            : {n_total}')
    print(f'  Epoch digests          : {epoch_digests}')
    print(f'  Estimated packets      : {epoch_packets}')
    print(f'  Resolved by Alg4       : {stats["alg4"]}  ({pct(stats["alg4"]):.2f}%)')
    print(f'  Resolved by Alg5       : {stats["alg5"]}  ({pct(stats["alg5"]):.2f}%)')
    print(f'  Solver / min fallback  : {stats["solver"]}  ({pct(stats["solver"]):.2f}%)')
    print(f'  Sub-sketch buckets used: {stats["used_buckets"]} / {NUM_BUCKETS}  '
          f'(exact: {stats["exact_buckets"]}, '
          f'Alg6: {stats["alg6_buckets"]}, '
          f'skipped: {stats["skipped_buckets"]})')
    print(f'  Max sub-sketch load    : {max_load:.4f}  '
          f'(max bucket = {stats["max_bucket_n"]} flows / {COLS_PER_ROW} cols)')

    # CSV output -- same schema as the C++ CP
    if csv_writer is not None:
        for fk, (est, path) in estimates.items():
            csv_writer.write(
                f'{fk[0]},{fk[1]},{fk[2]},{fk[3]},{fk[4]},'
                f'{flow_table[fk]},{est},{path}\n')

    t2 = time.time()
    clear_registers_targeted(bfrt_info, target, bf_snapshot, cms_snapshot)
    print(f'  bulk clear time        : {time.time() - t2:.3f} s')
    print(sep)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description=f'FlowLiDAR Python CP for {P4_NAME}')
    parser.add_argument('--epoch', type=float, default=15.0,
                        help='Epoch length in seconds (default: 15)')
    parser.add_argument('--pipe', type=int, default=1,
                        help='Pipe id (default: 1 for p4switch2)')
    parser.add_argument('--csv-out', type=str, default=None,
                        help='If set, append per-flow estimates as CSV')
    parser.add_argument('--epochs', type=int, default=0,
                        help='Exit after N epochs (default: 0 = forever)')
    args = parser.parse_args()

    print('=' * 72)
    print(f'  cpp_lazy_bf1m_cms256x1024 -- Python control plane')
    print(f'  bfrt-gRPC        : {GRPC_ADDR}')
    print(f'  P4 program       : {P4_NAME}')
    print(f'  Device / Pipe    : {DEVICE_ID} / {args.pipe}')
    print(f'  Epoch length     : {args.epoch} s')
    print(f'  BF cells per row : {BF_SIZE}')
    print(f'  CMS cells per row: {CMS_SIZE} ({NUM_BUCKETS} buckets * {COLS_PER_ROW} cols)')
    if args.csv_out:
        print(f'  CSV output       : {args.csv_out}')
    if args.epochs:
        print(f'  Exit after       : {args.epochs} epoch(s)')
    print('=' * 72)

    interface = gc.ClientInterface(
        grpc_addr=GRPC_ADDR,
        client_id=CLIENT_ID,
        device_id=DEVICE_ID,
        num_tries=10,
        notifications=gc.Notifications(enable_learn=True),
    )
    interface.bind_pipeline_config(P4_NAME)
    bfrt_info = interface.bfrt_info_get(P4_NAME)
    learn_filter = bfrt_info.learn_get('flow_digest')
    learn_filter.info.data_field_annotation_add('src_addr', 'ipv4')
    learn_filter.info.data_field_annotation_add('dst_addr', 'ipv4')
    target = gc.Target(device_id=DEVICE_ID, pipe_id=args.pipe)

    print('Connected. Waiting for packets...\n')

    csv_writer = None
    if args.csv_out:
        csv_writer = open(args.csv_out, 'w')
        csv_writer.write('src_ip,dst_ip,proto,src_port,dst_port,'
                         'digest_count,estimated_packets,solver_path\n')

    flow_table  = {}
    total       = 0
    epoch_num   = 1
    epoch_start = time.time()
    done        = False

    while not done:
        try:
            digest = interface.digest_get(timeout=0.5)
            data_list = learn_filter.make_data_list(digest)
            for data in data_list:
                d = data.to_dict()
                flow_key = (d['src_addr'], d['dst_addr'],
                            d['protocol'], d['src_port'], d['dst_port'])
                flow_table[flow_key] = flow_table.get(flow_key, 0) + 1
                total += 1
                if total % 50000 == 0:
                    print(f"  [{total} digests received, "
                          f"{len(flow_table)} unique flows]")
        except KeyboardInterrupt:
            print('\nCtrl-C received -- running final epoch report...')
            process_epoch(epoch_num, flow_table, bfrt_info, target, csv_writer)
            break
        except Exception:
            pass

        if time.time() - epoch_start >= args.epoch:
            process_epoch(epoch_num, flow_table, bfrt_info, target, csv_writer)
            flow_table.clear()
            epoch_num  += 1
            epoch_start = time.time()
            if args.epochs and epoch_num > args.epochs:
                done = True

    if csv_writer:
        csv_writer.close()
    print(f'Total digests received: {total}')


if __name__ == '__main__':
    main()
