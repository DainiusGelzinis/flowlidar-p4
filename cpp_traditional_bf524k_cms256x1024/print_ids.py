#!/usr/bin/env python3
"""
print_ids.py — print bfrt table IDs for the 6 traditional_bf register tables.
Run as a regular Python script (NOT via bfshell). Make sure NO other CP
(Python or C++) is using client_id 0 when you run this — bind is exclusive.

Usage on the switch:
    python3 ~/dainius/cpp_traditional_bf524k_cms256x1024/print_ids.py
"""

import os
import sys

SDE_INSTALL = os.environ.get('SDE_INSTALL', '/home/onie/sde/bf-sde-9.11.0/install')
for v in ('python3.8', 'python3.10'):
    base = os.path.join(SDE_INSTALL, 'lib', v, 'site-packages')
    sys.path.append(base)
    sys.path.append(os.path.join(base, 'tofino'))
    sys.path.append(os.path.join(base, 'tofino', 'bfrt_grpc'))

import bfrt_grpc.client as gc

P4_NAME = 'traditional_bf524k_cms256x1024'

interface = gc.ClientInterface(
    grpc_addr='localhost:50052',
    client_id=0,
    device_id=0,
    num_tries=5,
)
interface.bind_pipeline_config(P4_NAME)
bfrt_info = interface.bfrt_info_get(P4_NAME)

bf_ids, cms_ids = [], []
print('Register table IDs (from bfrt_info.table_get):')
for r in ('bf_0', 'bf_1', 'bf_2'):
    tid = bfrt_info.table_get(f'pipe.SwitchIngress.{r}').info.id_get()
    print(f'  {r}: {tid}')
    bf_ids.append(tid)
for r in ('cms_0', 'cms_1', 'cms_2'):
    tid = bfrt_info.table_get(f'pipe.SwitchIngress.{r}').info.id_get()
    print(f'  {r}: {tid}')
    cms_ids.append(tid)

print()
print('Pass these to traditional_bf524k_cms256x1024_cp:')
print('  --bf-ids  ' + ','.join(str(i) for i in bf_ids))
print('  --cms-ids ' + ','.join(str(i) for i in cms_ids))
