#!/usr/bin/env python3
"""
FlowLiDAR Prototype 2 — Control Plane

Connects to switchd via gRPC and receives flow digest notifications.
Each notification means a new flow was detected by the Bloom Filter.

Usage:
    python3 control_plane.py

Runs standalone — no bfshell needed.
switchd must already be running with prototype2 loaded.
"""

import sys
import os

# Add SDE Python libraries to path
SDE_INSTALL = os.environ.get('SDE_INSTALL', '/home/student/Desktop/open-p4studio/install')
sys.path.append(os.path.join(SDE_INSTALL, 'lib/python3.8/site-packages'))
sys.path.append(os.path.join(SDE_INSTALL, 'lib/python3.8/site-packages/tofino'))

import bfrt_grpc.client as gc

GRPC_ADDR  = 'localhost:50052'
CLIENT_ID  = 0
DEVICE_ID  = 0
P4_NAME    = 'prototype2'

def main():
    print("=" * 60)
    print("  FlowLiDAR Prototype 2 — Control Plane")
    print(f"  Connecting to {GRPC_ADDR} ...")
    print("=" * 60)

    # Connect to switchd gRPC server and enable learn (digest) notifications.
    interface = gc.ClientInterface(
        grpc_addr=GRPC_ADDR,
        client_id=CLIENT_ID,
        device_id=DEVICE_ID,
        num_tries=10,
        notifications=gc.Notifications(enable_learn=True)
    )
    interface.bind_pipeline_config(P4_NAME)

    bfrt_info = interface.bfrt_info_get(P4_NAME)

    # Get the learn filter for our flow digest.
    # Name matches the Digest<flow_digest_t>() instance in the deparser.
    learn_filter = bfrt_info.learn_get('flow_digest')

    # Annotate IP address fields for human-readable output.
    learn_filter.info.data_field_annotation_add('src_addr', 'ipv4')
    learn_filter.info.data_field_annotation_add('dst_addr', 'ipv4')

    print("Connected. Waiting for new flow notifications...\n")

    # Per-epoch flow table: maps 5-tuple -> count of digest messages received.
    # This count is the exact packet count for flows that never set all k BF bits
    # (used in prototype 4 postprocessing).
    flow_table = {}
    total = 0

    while True:
        try:
            # Block until a digest arrives (timeout = 1 second).
            digest = interface.digest_get(timeout=1)
            data_list = learn_filter.make_data_list(digest)

            for data in data_list:
                d = data.to_dict()

                src   = d['src_addr']
                dst   = d['dst_addr']
                proto = d['protocol']
                sport = d['src_port']
                dport = d['dst_port']

                # Build a canonical flow key tuple.
                flow_key = (src, dst, proto, sport, dport)

                # Count how many times this flow was reported (should be 1
                # for standard BF; > 1 indicates a false positive reset or
                # lazy BF behaviour in prototype 5).
                flow_table[flow_key] = flow_table.get(flow_key, 0) + 1
                total += 1

                proto_name = {6: 'TCP', 17: 'UDP'}.get(proto, str(proto))
                print(f"[{total:4d}] NEW FLOW  {src}:{sport} -> {dst}:{dport}  {proto_name}"
                      f"  (seen {flow_table[flow_key]}x)")

        except KeyboardInterrupt:
            print(f"\nStopped. Total new flows detected this epoch: {len(flow_table)}")
            print(f"Total digest messages received: {total}")
            break
        except Exception:
            # Timeout or transient error — keep polling.
            pass

if __name__ == '__main__':
    main()
