# FlowLiDAR — Implementation Guide

FlowLiDAR is a per-flow packet counting system implemented entirely in the Intel Tofino 1 data plane, with a Python control plane that reconstructs exact counts at epoch boundaries. This guide covers the complete implementation from first principles through all five prototypes.

**Paper:** Monterubbiano et al., "FlowLiDAR: Per-Flow Network Telemetry with Low Processing and Storage", ACM SIGMETRICS 2023.
**PDF:** `/home/student/Desktop/flowlidar/flowlidar_paper.pdf`

---

## Table of Contents

1. [High-Level Overview](#1-high-level-overview)
2. [Repository Structure](#2-repository-structure)
3. [Data Plane](#3-data-plane)
   - 3.1 [Shared Foundations](#31-shared-foundations)
   - 3.2 [Bloom Filter — Standard and Lazy](#32-bloom-filter--standard-and-lazy)
   - 3.3 [Count-Min Sketch](#33-count-min-sketch)
   - 3.4 [Digest Mechanism](#34-digest-mechanism)
   - 3.5 [IPv4 LPM Forwarding](#35-ipv4-lpm-forwarding)
   - 3.6 [Stage Allocation](#36-stage-allocation)
   - 3.7 [Key Tofino TNA Constraints](#37-key-tofino-tna-constraints)
4. [Control Plane](#4-control-plane)
   - 4.1 [bfrt_grpc Connection](#41-bfrt_grpc-connection)
   - 4.2 [Digest Reception Loop](#42-digest-reception-loop)
   - 4.3 [Register I/O](#43-register-io)
   - 4.4 [Hash Replication in Python](#44-hash-replication-in-python)
   - 4.5 [Epoch Processing](#45-epoch-processing)
   - 4.6 [Postprocessing — Prototype 5 Equation Solver](#46-postprocessing--prototype-5-equation-solver)
5. [Setup Scripts](#5-setup-scripts)
6. [Test Scripts](#6-test-scripts)
7. [Build System](#7-build-system)
8. [Hash Polynomial Reference](#8-hash-polynomial-reference)
9. [Prototype Progression Summary](#9-prototype-progression-summary)

---

## 1. High-Level Overview

### What FlowLiDAR Does

A network switch sees millions of packets per second from thousands of flows. The goal is to count, per-flow, how many packets arrived during a measurement window (epoch) — without sending every packet to a CPU.

FlowLiDAR solves this by keeping all heavy work in the switch's data plane at line rate, and offloading only a tiny amount of state to the control plane at epoch boundaries.

### Two-Plane Architecture

**Data Plane (Tofino ASIC, line-rate)**

- A **Bloom Filter (BF)** identifies new flows. When a packet arrives from a flow not yet seen this epoch, the switch sends a compact 5-tuple digest to the control plane and marks the flow as known.
- A **Count-Min Sketch (CMS)** counts packets. Every packet from every known flow increments a small set of counters in a probabilistic structure. The CMS uses much less memory than a per-flow counter table, at the cost of hash-collision noise.
- With the **Lazy Updates BF** (Algorithm 2, prototypes 4 and 5), the first *k* packets of every flow are counted individually as digests, so flows with few packets never touch the CMS at all.

**Control Plane (Python, runs on the switch CPU)**

- Maintains a `flow_table` dictionary: `flow_key → digest_count`.
- At epoch end, reads the CMS register snapshot from the switch via gRPC.
- Computes per-flow estimates (`digest_count + min(CMS rows)` for prototype 4, or exact solver output for prototype 5).
- Clears BF + CMS registers to start the next epoch.

### Epoch Concept

An epoch is a fixed measurement window (e.g., 10–30 seconds). At epoch start, all BF and CMS registers are zero. Packets arriving during the epoch accumulate counts. At epoch end, the control plane reads the snapshot and resets everything. Each epoch produces one independent report.

---

## 2. Repository Structure

```
flowlidar/
├── common/
│   ├── headers.p4          # All packet header definitions and typedefs
│   └── util.p4             # TofinoIngressParser, EmptyEgress stubs, BypassEgress
│
├── prototype1/             # Build pipeline check + IPv4 LPM forwarding
│   ├── prototype1.p4
│   ├── build.sh
│   ├── setup_table.py      # Adds LPM forwarding entry (bfshell)
│   └── test_packet.py
│
├── prototype2/             # Standard Bloom Filter + digest (Algorithm 1, BF only)
│   ├── prototype2.p4
│   ├── build.sh / setup_table.py / test_packet.py
│   ├── control_plane.py    # Digest receiver (no CMS)
│   └── reset_epoch.py
│
├── prototype3/             # BF + Count-Min Sketch (Algorithm 1, complete)
│   ├── prototype3.p4
│   ├── build.sh / setup_table.py / test_packet.py / reset_epoch.py
│   ├── control_plane.py    # Epoch processor: digest + CMS min estimate
│   └── debug_cms.py        # Debug: raw CMS register dump + Python CRC comparison
│
├── prototype4/             # Lazy Updates BF + conditional CMS (Algorithm 2)
│   ├── prototype4.p4
│   ├── build.sh / setup_table.py / test_packet.py / reset_epoch.py
│   └── control_plane.py    # Epoch: digest_count + min(CMS)
│
├── prototype5/             # Same data plane as P4 + equation solver (§3.4)
│   ├── prototype5.p4       # Identical to prototype4.p4
│   ├── build.sh / setup_table.py / test_packet.py / reset_epoch.py
│   ├── control_plane.py    # Algorithms 4/5 + Ax=b solver + Algorithm 6
│   └── debug_bf.py         # Debug: BF register scan + Python CRC comparison
│
└── README.md               # This file
```

### Prototype Progression

| # | BF Algorithm | CMS | Control Plane |
|---|-------------|-----|---------------|
| 1 | None | None | LPM table setup only |
| 2 | Standard (Alg. 1) | None | Digest receiver, no estimation |
| 3 | Standard (Alg. 1) | Unconditional increment | digest + min(CMS) estimate |
| 4 | Lazy Updates (Alg. 2) | Conditional increment (b0=b1=b2=1) | digest_count + min(CMS) |
| 5 | Lazy Updates (Alg. 2) | Conditional increment | Alg.4 + Alg.5 + Ax=b solver |

---

## 3. Data Plane

All P4 programs target the Tofino Native Architecture (TNA) on a Tofino 1 switch with 12 ingress MAU stages.

### 3.1 Shared Foundations

#### `common/headers.p4`

Defines all packet header types, typedefs, and EtherType/protocol constants shared across prototypes.

**Typedefs:**
```p4
typedef bit<48>  mac_addr_t;
typedef bit<32>  ipv4_addr_t;
typedef bit<128> ipv6_addr_t;
typedef bit<12>  vlan_id_t;
typedef bit<16>  ether_type_t;
typedef bit<8>   ip_protocol_t;
```

**Constants:**
```p4
const ether_type_t ETHERTYPE_IPV4 = 16w0x0800;
const ip_protocol_t IP_PROTOCOLS_TCP = 6;
const ip_protocol_t IP_PROTOCOLS_UDP = 17;
```

**Header structs:** `ethernet_h`, `vlan_tag_h`, `mpls_h`, `ipv4_h`, `ipv6_h`, `tcp_h`, `udp_h`, `icmp_h`, `arp_h`, `ipv6_srh_h`, `vxlan_h`, `gre_h`.

**Top-level struct:**
```p4
struct header_t {
    ethernet_h ethernet;
    vlan_tag_h vlan_tag;
    ipv4_h     ipv4;
    ipv6_h     ipv6;
    tcp_h      tcp;
    udp_h      udp;
}
struct empty_header_t {}
struct empty_metadata_t {}
```

#### `common/util.p4`

Provides reusable parser/control blocks used by every prototype.

**`TofinoIngressParser`** — must be the first parser applied. Extracts `ig_intr_md` (Tofino intrinsic ingress metadata) and advances past the port metadata region:
```p4
parser TofinoIngressParser(
        packet_in pkt,
        out ingress_intrinsic_metadata_t ig_intr_md) {
    state start {
        pkt.extract(ig_intr_md);
        transition select(ig_intr_md.resubmit_flag) {
            1 : parse_resubmit;
            0 : parse_port_metadata;
        }
    }
    state parse_port_metadata {
        pkt.advance(PORT_METADATA_SIZE);
        transition accept;
    }
}
```

**`EmptyEgressParser` / `EmptyEgress` / `EmptyEgressDeparser`** — stub egress blocks. All prototypes bypass egress (`ig_tm_md.bypass_egress = 1w1`), so these are used for the egress side of the `Pipeline()` instantiation.

**`BypassEgress`** — a convenience control that sets `ig_tm_md.bypass_egress = 1w1` via a table.

### 3.2 Bloom Filter — Standard and Lazy

A Bloom Filter is an array of bits that answers "have I seen this flow before?" with possible false positives but no false negatives. k independent hash functions each map the flow's 5-tuple to a bit position. Setting all k bits marks the flow as known; checking all k bits confirms it.

#### Register Declaration

Three independent 1-bit arrays, each with 2^17 = 131,072 entries:
```p4
Register<bit<1>, bit<17>>(131072) bf_0;
Register<bit<1>, bit<17>>(131072) bf_1;
Register<bit<1>, bit<17>>(131072) bf_2;
```
Total BF memory: 3 × 128 Kbits = 48 KB.

k=3 (reduced from paper's k=4) to free two MAU stages for the CMS.

#### Hash Functions

Each BF array uses a different CRC32 polynomial to achieve statistical independence:
```p4
// CRC32 standard
CRCPolynomial<bit<32>>(32w0x04C11DB7,
                       true,           // reversed
                       false,          // use_msb
                       false,          // extended
                       32w0xFFFFFFFF,  // init
                       32w0xFFFFFFFF   // residue/xor
                       ) poly0;
Hash<bit<17>>(HashAlgorithm_t.CUSTOM, poly0) hash0;

// CRC32/BZIP2 (same polynomial, not reversed)
CRCPolynomial<bit<32>>(32w0x04C11DB7,
                       false, false, false,
                       32w0xFFFFFFFF, 32w0xFFFFFFFF) poly1;
Hash<bit<17>>(HashAlgorithm_t.CUSTOM, poly1) hash1;

// CRC32C (Castagnoli)
CRCPolynomial<bit<32>>(32w0x1EDC6F41,
                       true, false, false,
                       32w0xFFFFFFFF, 32w0xFFFFFFFF) poly2;
Hash<bit<17>>(HashAlgorithm_t.CUSTOM, poly2) hash2;
```

#### Why One Hash Per Stage (32-bit Pathway Limit)

Each Tofino MAU stage has a 32-bit "immediate pathway" budget for values produced by hash units. A 17-bit BF index uses 17 bits of this budget. Two 17-bit hashes would require 34 bits — exceeding the 32-bit limit. Therefore each BF hash occupies its own stage (stages 0, 1, 2).

The CMS uses 10-bit indices: 3 × 10 = 30 bits ≤ 32, so all three CMS hashes fit in one stage (stage 6).

#### Hash Tables with `@stage()` Annotations

Each hash result is computed in a keyless table with a `@stage()` annotation to force placement in a specific MAU stage:
```p4
action compute_idx0() {
    ig_md.idx0 = hash0.get({hdr.ipv4.src_addr, hdr.ipv4.dst_addr,
                             hdr.ipv4.protocol,
                             ig_md.src_port, ig_md.dst_port});
}

@stage(0) table tbl_hash0 {
    actions        = { compute_idx0; }
    default_action = compute_idx0;
    size           = 1;
}
@stage(1) table tbl_hash1 { ... }
@stage(2) table tbl_hash2 { ... }
```

#### RegisterAction — Check-and-Set

The core BF primitive: atomically read the old bit and set it to 1. Returns 0 if the bit was unset (flow not yet seen in this array), 1 if it was already set:
```p4
RegisterAction<bit<1>, bit<17>, bit<1>>(bf_0) bf_check_set_0 = {
    void apply(inout bit<1> val, out bit<1> rv) {
        rv  = val;  // return old value: 0=absent, 1=present
        val = 1;    // always mark present
    }
};
```

#### Standard BF (Prototypes 2 and 3)

All three arrays are checked-and-set unconditionally for every IPv4 packet. A digest fires if *any* bit was 0 (flow is new or partially seen):
```p4
// Stages 3, 4, 5 — each execute() call occupies its own MAU stage
bit<1> b0 = bf_check_set_0.execute(ig_md.idx0);
bit<1> b1 = bf_check_set_1.execute(ig_md.idx1);
bit<1> b2 = bf_check_set_2.execute(ig_md.idx2);

// Tofino requires separate comparisons (no AND of runtime values)
if (b0 == 0) { ig_dprsr_md.digest_type = 1; }
if (b1 == 0) { ig_dprsr_md.digest_type = 1; }
if (b2 == 0) { ig_dprsr_md.digest_type = 1; }
```

**Limitation:** Every packet from a new flow sets all 3 bits simultaneously on the first packet, so digest fires once per flow (not per bit). But all k packets' BF operations are wasted on already-known flows.

#### Lazy Updates BF (Prototypes 4 and 5) — Algorithm 2

The key change: only the *first zero bit* is set per packet. BF arrays are checked sequentially:

- bf_0 always executes (stage 3).
- bf_1 only executes if b0 == 1 (stage 4).
- bf_2 only executes if b0 == 1 AND b1 == 1 (stage 5).
- CMS only fires if b0 == b1 == b2 == 1 (all bits already set; flow is fully registered).

**Why table match, not `if` statement:** In TNA, `RegisterAction.execute()` must be called from within a table's action, not conditionally from the `apply` block with an `if`. To conditionally execute a RegisterAction, wrap it in a table and key that table on the metadata condition:

```p4
// Stage 4: bf_1 only if b0 == 1
action run_bf1() {
    ig_md.b1 = bf_check_set_1.execute(ig_md.idx1);
}
action skip_bf1() {
    ig_md.b1 = 0;  // skipped → treat as 0 for digest trigger
}
@stage(4) table tbl_bf1 {
    key            = { ig_md.b0 : exact; }
    actions        = { run_bf1; skip_bf1; }
    default_action = skip_bf1;
    size           = 2;
}

// Stage 5: bf_2 only if b0 == 1 AND b1 == 1
@stage(5) table tbl_bf2 {
    key            = { ig_md.b0 : exact; ig_md.b1 : exact; }
    actions        = { run_bf2; skip_bf2; }
    default_action = skip_bf2;
    size           = 4;
}
```

`setup_table.py` adds the control-plane entries that trigger the execute actions:
```python
tbl_bf1.add_with_run_bf1(b0=1)
tbl_bf2.add_with_run_bf2(b0=1, b1=1)
```

**Effect:** With k=3, a flow's first packet sets only bf_0 and sends a digest. The second packet finds bf_0=1, sets bf_1, sends a digest. The third sets bf_2, sends a digest. The fourth finds all bits already 1 and increments the CMS instead. Flows with ≤ k packets are counted entirely by digest, never touching the CMS.

**Metadata struct in prototypes 4/5:**
```p4
struct metadata_t {
    bit<16> src_port;
    bit<16> dst_port;
    bit<17> idx0;       // BF hash indices
    bit<17> idx1;
    bit<17> idx2;
    bit<1>  b0;         // BF check results, carried between stages
    bit<1>  b1;
    bit<1>  b2;
    bit<10> cms_idx0;   // CMS hash indices
    bit<10> cms_idx1;
    bit<10> cms_idx2;
}
```

### 3.3 Count-Min Sketch

A Count-Min Sketch is a 2D array of counters (k rows × m columns). To record a packet from flow x: hash x with k independent functions, increment one counter per row. To query the count for flow x: take min over all k rows.

#### Register Declaration

Three 16-bit counter arrays with 1024 entries each:
```p4
Register<bit<16>, bit<10>>(1024) cms_0;
Register<bit<16>, bit<10>>(1024) cms_1;
Register<bit<16>, bit<10>>(1024) cms_2;
```
Total CMS memory: 3 × 1K × 2 bytes = 6 KB. Counter saturates at 65,535 packets per epoch.

#### CMS Hash Functions

Polynomials distinct from BF polynomials to maximise independence:
```p4
// CRC32D — reversed
CRCPolynomial<bit<32>>(32w0xA833982B,
                       true, false, false,
                       32w0xFFFFFFFF, 32w0xFFFFFFFF) cms_poly0;
Hash<bit<10>>(HashAlgorithm_t.CUSTOM, cms_poly0) cms_hash0;

// CRC32/Q — not reversed
CRCPolynomial<bit<32>>(32w0x814141AB,
                       false, false, false,
                       32w0x00000000, 32w0x00000000) cms_poly1;
Hash<bit<10>>(HashAlgorithm_t.CUSTOM, cms_poly1) cms_hash1;

// CRC32/POSIX — not reversed, init=0
CRCPolynomial<bit<32>>(32w0x04C11DB7,
                       false, false, false,
                       32w0x00000000, 32w0xFFFFFFFF) cms_poly2;
Hash<bit<10>>(HashAlgorithm_t.CUSTOM, cms_poly2) cms_hash2;
```

#### Combined Hash Stage

All three 10-bit CMS indices are computed in a single action at stage 6 (30 bits ≤ 32-bit limit):
```p4
action compute_cms_indices() {
    ig_md.cms_idx0 = cms_hash0.get({hdr.ipv4.src_addr, hdr.ipv4.dst_addr,
                                     hdr.ipv4.protocol,
                                     ig_md.src_port, ig_md.dst_port});
    ig_md.cms_idx1 = cms_hash1.get({...});
    ig_md.cms_idx2 = cms_hash2.get({...});
}

@stage(6) table tbl_cms_hash {
    actions        = { compute_cms_indices; }
    default_action = compute_cms_indices;
    size           = 1;
}
```

#### Unconditional Increment (Prototype 3)

Every IPv4 packet increments all three CMS rows regardless of BF state:
```p4
RegisterAction<bit<16>, bit<10>, bit<16>>(cms_0) cms_inc_0 = {
    void apply(inout bit<16> val, out bit<16> rv) {
        val = val + 1;  // increment counter
        rv  = val;      // return value (discarded in apply)
    }
};
// apply() block:
cms_inc_0.execute(ig_md.cms_idx0);  // stage 7
cms_inc_1.execute(ig_md.cms_idx1);  // stage 8
cms_inc_2.execute(ig_md.cms_idx2);  // stage 9
```

#### Conditional Increment (Prototypes 4 and 5)

CMS only fires when all three BF bits were already 1 (the flow is fully registered). Wrapped in conditional tables keyed on (b0, b1, b2):
```p4
action do_cms_inc_0() { cms_inc_0.execute(ig_md.cms_idx0); }
action nop_cms_0()    {}

@stage(7) table tbl_cms_0 {
    key            = { ig_md.b0 : exact; ig_md.b1 : exact; ig_md.b2 : exact; }
    actions        = { do_cms_inc_0; nop_cms_0; }
    default_action = nop_cms_0;
    size           = 8;
}
```

`setup_table.py` adds the single active entry:
```python
tbl_cms_0.add_with_do_cms_inc_0(b0=1, b1=1, b2=1)
```

### 3.4 Digest Mechanism

The digest is the channel through which the data plane notifies the control plane of new or partially-seen flows.

#### Digest Struct

The 5-tuple that uniquely identifies a flow:
```p4
struct flow_digest_t {
    bit<32> src_addr;
    bit<32> dst_addr;
    bit<8>  protocol;
    bit<16> src_port;
    bit<16> dst_port;
}
```

#### Triggering the Digest

Setting `ig_dprsr_md.digest_type = 1` in the ingress control block causes the deparser to call `flow_digest.pack(...)`:
```p4
Digest<flow_digest_t>() flow_digest;

apply {
    if (ig_dprsr_md.digest_type == 1) {
        flow_digest.pack({
            hdr.ipv4.src_addr,
            hdr.ipv4.dst_addr,
            hdr.ipv4.protocol,
            ig_md.src_port,
            ig_md.dst_port
        });
    }
    ...
}
```

#### When Digest Fires

- **Prototype 2/3 (Standard BF):** Any BF bit was 0 on this packet → new flow → exactly one digest per flow per epoch (under normal conditions).
- **Prototype 4/5 (Lazy BF):** Any BF bit was 0 → fires once per bit set, so up to k=3 times per flow. `ig_md.b1` and `ig_md.b2` are set to 0 by `skip_bf1`/`skip_bf2` when those arrays are not executed, so the three-condition check still fires correctly.

#### Digest Deduplication on the Model

On real hardware, the Tofino quiescence timer suppresses duplicate digests from the same flow within microseconds. On the software model, a `DIGEST_GAP` delay (≥1.5 s) must be inserted between packets of the same flow in test scripts to avoid the model merging them. Prototype 4/5 test scripts space packets 1.5 s apart for exactly this reason.

### 3.5 IPv4 LPM Forwarding

All prototypes forward IPv4 packets via a longest-prefix-match table populated by `setup_table.py`:
```p4
action hit(PortId_t dst_port) {
    ig_tm_md.ucast_egress_port = dst_port;
    hdr.ipv4.ttl = hdr.ipv4.ttl - 1;
    ig_dprsr_md.drop_ctl = 0x0;
}

action miss() {
    ig_dprsr_md.drop_ctl = 0x1;
}

table ipv4_lpm {
    key            = { hdr.ipv4.dst_addr : lpm; }
    actions        = { hit; miss; }
    size           = 1024;
    default_action = miss();
}
```

After forwarding, the deparser recomputes the IPv4 checksum to reflect the TTL decrement:
```p4
Checksum() ipv4_checksum;
hdr.ipv4.hdr_checksum = ipv4_checksum.update({
    hdr.ipv4.version, hdr.ipv4.ihl, hdr.ipv4.diffserv,
    hdr.ipv4.total_len, hdr.ipv4.identification,
    hdr.ipv4.flags, hdr.ipv4.frag_offset,
    hdr.ipv4.ttl, hdr.ipv4.protocol,
    hdr.ipv4.src_addr, hdr.ipv4.dst_addr
});
```

### 3.6 Stage Allocation

Tofino 1 provides 12 ingress MAU stages. The final allocation (prototypes 3–5):

| Stage | Object | Operation |
|-------|--------|-----------|
| 0 | `tbl_hash0` | BF idx0 (17-bit, CRC32 standard) |
| 1 | `tbl_hash1` | BF idx1 (17-bit, CRC32/BZIP2) |
| 2 | `tbl_hash2` | BF idx2 (17-bit, CRC32C) |
| 3 | `tbl_bf0` / `bf_check_set_0` | BF row 0 check-and-set (always) |
| 4 | `tbl_bf1` / `bf_check_set_1` | BF row 1 (conditional on b0=1 for P4/5) |
| 5 | `tbl_bf2` / `bf_check_set_2` | BF row 2 (conditional on b0=b1=1 for P4/5) |
| 6 | `tbl_cms_hash` | CMS idx0/1/2 combined (3 × 10 = 30 bits) |
| 7 | `tbl_cms_0` / `cms_inc_0` | CMS row 0 increment (conditional in P4/5) |
| 8 | `tbl_cms_1` / `cms_inc_1` | CMS row 1 increment |
| 9 | `tbl_cms_2` / `cms_inc_2` | CMS row 2 increment |
| 10 | — | free |
| 11 | — | free |

The `ipv4_lpm` TCAM table shares stage 0 with `tbl_hash0` (different resource types can coexist in the same stage).

### 3.7 Key Tofino TNA Constraints

**Includes:**
```p4
#include <core.p4>
#include <tna.p4>    // or t2na.p4 / t3na.p4 for Tofino 2/3
```

**Top-level instantiation:**
```p4
Pipeline(
    SwitchIngressParser(),
    SwitchIngress(),
    SwitchIngressDeparser(),
    EmptyEgressParser(),
    EmptyEgress(),
    EmptyEgressDeparser()
) pipe;

Switch(pipe) main;
```

**Egress bypass:** `ig_tm_md.bypass_egress = 1w1` skips the egress pipeline entirely (set unconditionally in all prototypes).

**Drop:** `ig_dprsr_md.drop_ctl = 0x1` drops the packet; `0x0` forwards it.

**Resubmit check:** `TofinoIngressParser` handles the resubmit flag; resubmit is unused (transitions to `reject`).

**RegisterAction must be in a table:** You cannot call `RegisterAction.execute()` conditionally from the `apply` block with a plain `if`. You must wrap it in a table action and key the table on the condition.

**Each `execute()` call uses one MAU stage:** Multiple `execute()` calls for different registers must be in different stages (hence 3 BF stages + 3 CMS stages + 1 CMS hash stage = 7 of 12 stages used).

---

## 4. Control Plane

All control-plane scripts are standalone Python 3 programs connecting to switchd via bfrt gRPC.

### 4.1 bfrt_grpc Connection

```python
import bfrt_grpc.client as gc

interface = gc.ClientInterface(
    grpc_addr='localhost:50052',
    client_id=0,
    device_id=0,
    num_tries=10,
    notifications=gc.Notifications(enable_learn=True)  # enable digest reception
)
interface.bind_pipeline_config('prototype3')      # claim ownership of the P4 program
bfrt_info = interface.bfrt_info_get('prototype3') # get table/learn object handles
target    = gc.Target(device_id=0)
```

- **`client_id`:** Only one client can own a P4 program at a time (client_id=0). The debug scripts use client_id=2 and skip `bind_pipeline_config` for read-only access.
- **`enable_learn=True`:** Required to receive digest notifications. Without it, `digest_get()` never returns.
- **`bind_pipeline_config`:** Claims the pipeline; must be called exactly once.

**SDE Python path** must be set before importing:
```python
SDE_INSTALL = os.environ.get('SDE_INSTALL', '/home/student/Desktop/open-p4studio/install')
sys.path.append(os.path.join(SDE_INSTALL, 'lib/python3.8/site-packages'))
sys.path.append(os.path.join(SDE_INSTALL, 'lib/python3.8/site-packages/tofino'))
```

### 4.2 Digest Reception Loop

```python
learn_filter = bfrt_info.learn_get('flow_digest')
# Annotate address fields for automatic dotted-decimal formatting
learn_filter.info.data_field_annotation_add('src_addr', 'ipv4')
learn_filter.info.data_field_annotation_add('dst_addr', 'ipv4')

flow_table = {}   # flow_key -> digest count this epoch

while True:
    try:
        digest    = interface.digest_get(timeout=0.5)   # blocks up to 0.5s
        data_list = learn_filter.make_data_list(digest)

        for data in data_list:
            d = data.to_dict()
            flow_key = (
                d['src_addr'],    # dotted decimal string e.g. '10.1.0.1'
                d['dst_addr'],
                d['protocol'],
                d['src_port'],
                d['dst_port'],
            )
            flow_table[flow_key] = flow_table.get(flow_key, 0) + 1

    except Exception:
        pass   # timeout — keep polling

    # Check epoch timer, clear + report if elapsed
```

`digest_get(timeout=0.5)` raises an exception (not returns None) on timeout, so the `except Exception: pass` pattern is correct.

### 4.3 Register I/O

#### Full Array Read

Used for CMS (1024 entries per row — fast enough):
```python
def _read_register_array(bfrt_info, tbl_name, size, target):
    arr = [0] * size
    tbl = bfrt_info.table_get(tbl_name)        # e.g. 'pipe.SwitchIngress.cms_0'
    expected_field = 'SwitchIngress.cms_0.f1'  # value field name

    for key, data in tbl.entry_get(target, None, {'from_hw': True}):
        k_dict = key.to_dict()
        d_dict = data.to_dict()
        ...
```

`entry_get(target, None, ...)` iterates all entries. `from_hw=True` reads hardware state, not cached.

#### Key/Data Dict Swap — SDE 9.13.4 Quirk

In the Tofino model's bfrt_grpc implementation, the register's value field (`SwitchIngress.cms_0.f1`) and its index (`$REGISTER_INDEX`) can appear in **either** the key dict or the data dict — opposite to what you might expect. The control plane handles this by checking which dict contains `$REGISTER_INDEX` and looking for the value in the other dict:

```python
if '$REGISTER_INDEX' in d_dict:
    idx_src = d_dict   # index is in data dict
    val_src = k_dict   # value is in key dict
else:
    idx_src = k_dict   # normal: index in key dict
    val_src = d_dict   # value in data dict
```

#### List Values from Wide Registers

When a register is replicated across multiple pipeline copies (e.g., ingress pipelines), the value is returned as a list `[val_pipe0, val_pipe1, ...]`. Always take `val[0]`:
```python
if isinstance(val, list):
    val = val[0]
```

#### Targeted Cell Read (Prototype 5)

Reading all 131,072 cells of each BF row takes several seconds. For BF preprocessing, only 3 specific cells per flow are needed. Use an explicit key:
```python
def _read_register_cell(bfrt_info, tbl_name, idx, target):
    tbl = bfrt_info.table_get(tbl_name)
    key = tbl.make_key([gc.KeyTuple('$REGISTER_INDEX', idx)])
    for k, data in tbl.entry_get(target, [key], {'from_hw': True}):
        combined = {**k.to_dict(), **data.to_dict()}
        val = combined.get('SwitchIngress.bf_0.f1', 0)
        if isinstance(val, list):
            val = val[0]
        return int(val)
    return 0
```

This makes BF preprocessing near-instant (18 reads for 6 flows vs. 393,216 reads for a full scan).

### 4.4 Hash Replication in Python

The control plane must reproduce the exact same hash values as the Tofino hardware to look up the correct CMS cells for each flow.

#### `_flow_bytes()` — Packing the 5-Tuple

The P4 hash input is `{ipv4.src_addr, ipv4.dst_addr, ipv4.protocol, src_port, dst_port}`. The Python equivalent:
```python
def _flow_bytes(src_addr, dst_addr, protocol, src_port, dst_port):
    src_int = struct.unpack('!I', socket.inet_aton(src_addr))[0]
    dst_int = struct.unpack('!I', socket.inet_aton(dst_addr))[0]
    return struct.pack('!IIBHH', src_int, dst_int, protocol, src_port, dst_port)
```

Format: two 32-bit IPs (network order) + 8-bit protocol + two 16-bit ports = 13 bytes.

#### Tofino → crcmod Mapping Formula

The Tofino `CRCPolynomial(poly, reversed, msb, extended, init, residue)` parameters map to crcmod as follows (empirically confirmed against hardware register values):

```
crcmod polynomial = 0x1<P4_poly>   (prepend leading 1 bit)
crcmod rev        = P4_reversed
crcmod initCrc    = P4_init XOR P4_residue
crcmod xorOut     = P4_residue
```

The index uses the **lower N bits** of the 32-bit CRC result (`& (size - 1)`), because `Hash<bit<N>>` with `use_msb=False` (the default) returns the least-significant N bits.

#### CMS CRC Functions

```python
import crcmod

# cms_poly0: CRC32D  (P4: poly=0xA833982B, rev=true, init=0xFFFFFFFF, residue=0xFFFFFFFF)
# initCrc = 0xFFFFFFFF ^ 0xFFFFFFFF = 0x00000000
_crc_fn0 = crcmod.mkCrcFun(0x1A833982B, rev=True,
                            initCrc=0x00000000, xorOut=0xFFFFFFFF)

# cms_poly1: CRC32/Q (P4: poly=0x814141AB, rev=false, init=0, residue=0)
_crc_fn1 = crcmod.mkCrcFun(0x1814141AB, rev=False,
                            initCrc=0x00000000, xorOut=0x00000000)

# cms_poly2: CRC32/POSIX (P4: poly=0x04C11DB7, rev=false, init=0, residue=0xFFFFFFFF)
# initCrc = 0x00000000 ^ 0xFFFFFFFF = 0xFFFFFFFF
_crc_fn2 = crcmod.mkCrcFun(0x104C11DB7, rev=False,
                            initCrc=0xFFFFFFFF, xorOut=0xFFFFFFFF)

def cms_indices(flow_key):
    data = _flow_bytes(*flow_key)
    return (
        _crc_fn0(data) & 0x3FF,   # lower 10 bits
        _crc_fn1(data) & 0x3FF,
        _crc_fn2(data) & 0x3FF,
    )
```

#### BF CRC Functions (Prototype 5 Only)

```python
# poly0: CRC32 standard (P4: poly=0x04C11DB7, rev=true, init=0xFFFFFFFF, residue=0xFFFFFFFF)
# initCrc = 0xFFFFFFFF ^ 0xFFFFFFFF = 0x00000000
_bf_fn0 = crcmod.mkCrcFun(0x104C11DB7, rev=True,
                           initCrc=0x00000000, xorOut=0xFFFFFFFF)

# poly1: CRC32/BZIP2 (P4: poly=0x04C11DB7, rev=false, init=0xFFFFFFFF, residue=0xFFFFFFFF)
_bf_fn1 = crcmod.mkCrcFun(0x104C11DB7, rev=False,
                           initCrc=0x00000000, xorOut=0xFFFFFFFF)

# poly2: CRC32C (P4: poly=0x1EDC6F41, rev=true, init=0xFFFFFFFF, residue=0xFFFFFFFF)
_bf_fn2 = crcmod.mkCrcFun(0x11EDC6F41, rev=True,
                           initCrc=0x00000000, xorOut=0xFFFFFFFF)

def bf_indices(flow_key):
    data = _flow_bytes(*flow_key)
    return (
        _bf_fn0(data) & 0x1FFFF,  # lower 17 bits (2^17 = 131072)
        _bf_fn1(data) & 0x1FFFF,
        _bf_fn2(data) & 0x1FFFF,
    )
```

### 4.5 Epoch Processing

At epoch end (`elapsed >= epoch_seconds`):

1. **Snapshot CMS:** Read all three CMS row arrays from hardware.
2. **For each known flow:** Compute CMS indices, look up the three counter values, take the minimum.
3. **Prototype 3:** `estimate = min(cms_rows)`.
4. **Prototype 4:** `total = digest_count + min(cms_rows)` (because the first k packets generated digests, not CMS increments).
5. **Print report.**
6. **Clear registers:** Write zeros to all BF and CMS cells via bfrt gRPC in batches of 128 (to stay within gRPC message size limits).

```python
def clear_all_registers(bfrt_info, target, cms_field_names=None):
    reg_sizes = {r: 131072 for r in BF_ROWS}   # BF: 128K cells each
    reg_sizes.update({r: 1024 for r in CMS_ROWS})  # CMS: 1K cells each

    for reg in BF_ROWS + CMS_ROWS:
        tbl_name   = f'pipe.SwitchIngress.{reg}'
        field_name = f'SwitchIngress.{reg}.f1'
        tbl        = bfrt_info.table_get(tbl_name)
        BATCH = 128
        for start in range(0, size, BATCH):
            end   = min(start + BATCH, size)
            keys  = [tbl.make_key([gc.KeyTuple('$REGISTER_INDEX', i)])
                     for i in range(start, end)]
            datas = [tbl.make_data([gc.DataTuple(field_name, 0)])
                     for _ in range(start, end)]
            tbl.entry_mod(target, keys, datas)
```

Clearing is slow on the model (BF rows are 131,072 entries × 3 = ~400K writes). It happens after printing the report so it does not affect measurement. On real hardware, use atomic register clear instructions instead.

### 4.6 Postprocessing — Prototype 5 Equation Solver

Prototype 5 replaces the simple `digest_count + min(CMS)` estimate with exact counts, implementing §3.4 of the paper.

#### Algorithm 4 — BF Preprocessing

For each known flow, read its three BF bit values using targeted cell reads:
```python
def algorithm4_bf_preprocess(flow_table, bfrt_info, target):
    resolved = {}
    C        = []
    for flow_key, digest_count in flow_table.items():
        b0, b1, b2 = read_bf_bits_for_flow(bfrt_info, target, flow_key)
        if b0 == 0 or b1 == 0 or b2 == 0:
            # Flow had ≤ k packets — all counted as digests
            resolved[flow_key] = digest_count
        else:
            C.append(flow_key)   # all bits set → flow reached CMS
    return resolved, C
```

With lazy BF, a flow with j packets (j ≤ k) sets exactly j BF bits. Any zero bit at epoch end means the flow never reached the CMS — its count is exactly `digest_count`.

#### Algorithm 5 — CMS Preprocessing

For flows that passed Algorithm 4 (all BF bits set), check the CMS:
```python
def algorithm5_cms_preprocess(C, flow_table, cms_snapshot):
    resolved = {}
    C_final  = []
    for flow_key in C:
        i0, i1, i2 = cms_indices(flow_key)
        cms_est = min(cms_snapshot['cms_0'][i0],
                      cms_snapshot['cms_1'][i1],
                      cms_snapshot['cms_2'][i2])
        if cms_est == 0:
            # Flow had exactly k packets — all digests, none in CMS
            resolved[flow_key] = flow_table[flow_key]
        else:
            C_final.append(flow_key)   # needs equation solver
    return resolved, C_final
```

#### `build_matrix()` — Constructing Ax = b

For flows in `C_final`, build a binary matrix A where each row is one unique CMS counter cell referenced by any flow, and each column is one flow. `A[i][j] = 1` if flow j maps to counter cell i:
```python
def build_matrix(C_final, cms_snapshot):
    counter_to_eq = {}   # (row_idx, cell_idx) -> equation index
    eq_idx = 0
    for flow_key in C_final:
        for r, cell in enumerate(cms_indices(flow_key)):
            key = (r, cell)
            if key not in counter_to_eq:
                counter_to_eq[key] = eq_idx
                eq_idx += 1

    m_eq = len(counter_to_eq)
    n    = len(C_final)
    A = np.zeros((m_eq, n), dtype=float)
    b = np.zeros(m_eq, dtype=float)

    for (r, cell), eq_i in counter_to_eq.items():
        b[eq_i] = cms_snapshot[row_names[r]][cell]

    for j, flow_key in enumerate(C_final):
        for r, cell in enumerate(cms_indices(flow_key)):
            A[counter_to_eq[(r, cell)]][j] = 1.0

    return A, b, m_eq, n
```

With no hash collisions and k=3 rows, each column of A has exactly 3 ones. The system is overdetermined (3n equations, n unknowns) and uniquely determined when `rank(A) == n`.

#### `solve_cms_system()`

```python
x, residuals, rank, sv = np.linalg.lstsq(A, b, rcond=None)

if rank < n:
    x = algorithm6_approximate(A, b, n, rank)  # underdetermined fallback
else:
    res = np.linalg.norm(A @ x - b)
    # large residual warns of hash collisions

x = np.clip(np.round(x), 0, None).astype(int)

for j, flow_key in enumerate(C_final):
    result[flow_key] = flow_table[flow_key] + int(x[j])
    # total = digest_count (first k packets) + solver x_j (remaining packets)
```

#### Algorithm 6 — Approximate Fallback

Triggered when `rank(A) < n` (system is underdetermined — more flows than independent equations, due to heavy hash collisions or high load factor). Greedily fixes free variables by processing equations in ascending order of counter value:
```python
def algorithm6_approximate(A, b, n, rank):
    x_approx = np.zeros(n, dtype=float)
    fixed     = np.zeros(n, dtype=bool)
    order     = np.argsort(b)   # smallest counters first

    for eq_i in order:
        cols = [j for j in range(n) if A[eq_i][j] > 0 and not fixed[j]]
        if not cols:
            continue
        val = b[eq_i] / len(cols)   # distribute counter equally
        for j in cols:
            x_approx[j] = val
            fixed[j]    = True

    return x_approx
```

#### Result Merging and Method Tagging

The final report tags each flow with how its count was resolved:
```python
# flow_key -> (digest_count, cms_part, total, method)
#   method: 'alg4'   = BF bit zero, count = digest_count
#           'alg5'   = CMS == 0, count = digest_count
#           'solver' = exact from Ax=b or Algorithm 6 fallback
```

---

## 5. Setup Scripts

Each prototype's `setup_table.py` is run at the `bfshell>` prompt after switchd starts:

```
bfrt_python /home/student/Desktop/flowlidar/prototypeN/setup_table.py
```

### Prototype 1/2/3 — LPM Entry Only

```python
p4 = bfrt.prototype3.pipe
tbl = p4.SwitchIngress.ipv4_lpm
tbl.clear()
tbl.add_with_hit(dst_addr='10.0.0.1', dst_addr_p_length=32, dst_port=1)
```

Routes `10.0.0.1/32` to port 1 (veth2/veth3). All test packets are destined for `10.0.0.1`.

### Prototypes 4 and 5 — LPM + Conditional BF/CMS Tables

```python
p4 = bfrt.prototype4.pipe

# IPv4 LPM
p4.SwitchIngress.ipv4_lpm.add_with_hit(dst_addr='10.0.0.1', dst_addr_p_length=32, dst_port=1)

# Lazy BF conditional tables
p4.SwitchIngress.tbl_bf1.add_with_run_bf1(b0=1)
p4.SwitchIngress.tbl_bf2.add_with_run_bf2(b0=1, b1=1)

# Conditional CMS increment tables
p4.SwitchIngress.tbl_cms_0.add_with_do_cms_inc_0(b0=1, b1=1, b2=1)
p4.SwitchIngress.tbl_cms_1.add_with_do_cms_inc_1(b0=1, b1=1, b2=1)
p4.SwitchIngress.tbl_cms_2.add_with_do_cms_inc_2(b0=1, b1=1, b2=1)
```

Without these entries, the default actions (`skip_bf1`, `nop_cms_0`, etc.) fire for every packet and the BF/CMS never execute.

### `reset_epoch.py`

Clears all BF and CMS registers manually (useful for debugging without restarting):
```
bfrt_python /home/student/Desktop/flowlidar/prototype3/reset_epoch.py
```

---

## 6. Test Scripts

Each prototype has a `test_packet.py` that sends Scapy packets on `veth1` (which feeds into switch port 0).

### Test Flows

Six flows with deliberate packet count variation to exercise all code paths:

| Flow | Source | Dest | Proto | Packets (P3) | Packets (P4/P5) |
|------|--------|------|-------|-------------|-----------------|
| A | 10.1.0.1:1000 | 10.0.0.1:80 | TCP | 12 | 12 |
| B | 10.1.0.2:2000 | 10.0.0.1:80 | TCP | 6 | 6 |
| C | 10.1.0.3:3000 | 10.0.0.1:80 | TCP | 3 | 3 |
| D | 10.1.0.4:4000 | 10.0.0.1:443 | TCP | 2 | 2 |
| E | 10.1.0.5:5000 | 10.0.0.1:53 | UDP | 2 | 2 |
| F | 10.1.0.6:6000 | 10.0.0.1:53 | UDP | 2 | 2 |

### Expected Outputs

**Prototype 3 (Standard BF + CMS):**

| Flow | Digests | CMS est. |
|------|---------|----------|
| A | 1 | 12 |
| B | 1 | 6 |
| C | 1 | 3 |
| D | 1 | 2 |
| E | 1 | 2 |
| F | 1 | 2 |

**Prototype 5 (Lazy BF + equation solver):**

| Flow | Digests | CMS/Solve | Total | Method |
|------|---------|-----------|-------|--------|
| A | 3 | 9 | 12 | solver |
| B | 3 | 3 | 6 | solver |
| C | 3 | 0 | 3 | alg5 |
| D | 2 | 0 | 2 | alg4 |
| E | 2 | 0 | 2 | alg4 |
| F | 2 | 0 | 2 | alg4 |

**How each flow is resolved (Prototype 5):**
- **D, E, F (2 packets):** Lazy BF sets bf_0 on packet 1, bf_1 on packet 2. At epoch end, bf_2=0 → Algorithm 4: count = digest_count = 2. Exact.
- **C (3 packets = k):** All 3 BF bits set. Algorithm 4 passes it (all bits 1). CMS=0 because packet 3 set bf_2 and triggered a digest, never incrementing the CMS → Algorithm 5: count = 3. Exact.
- **A, B (> k packets):** All 3 BF bits set, CMS > 0. Equation solver: 6×2 overdetermined system, rank=2, residual=0 → exact counts.

### `DIGEST_GAP` Rationale

Prototype 4/5 test scripts insert a `DIGEST_GAP = 1.5` second delay between consecutive packets from the same flow. On the Tofino model (not real hardware), the quiescence timer that deduplicates digests for the same flow has a long debounce window. Without the gap, multiple packets from the same flow send only one digest, making it impossible to accumulate the expected digest counts. On real hardware this gap is not needed — the timer fires in microseconds.

---

## 7. Build System

Each prototype has a `build.sh` that wraps the cmake + make invocation:

```bash
SDE=/home/student/Desktop/open-p4studio
SDE_INSTALL=$SDE/install

rm -rf /tmp/build_prototype3   # delete stale cache between reconfigurations

cmake $SDE/p4studio/ \
    -DCMAKE_INSTALL_PREFIX=$SDE_INSTALL \
    -DCMAKE_MODULE_PATH=$SDE/cmake \
    -DP4_NAME=prototype3 \
    -DP4_PATH=/abs/path/to/prototype3.p4 \
    -DP4C=$SDE_INSTALL/bin/p4c \   # critical: explicit path prevents wrong compiler
    -B /tmp/build_prototype3

make -C /tmp/build_prototype3 prototype3
make -C /tmp/build_prototype3 install
```

**Critical flag:** `-DP4C=$SDE_INSTALL/bin/p4c` must be passed explicitly. Without it, cmake may find a system p4c that does not support TNA, producing cryptic compilation errors.

**Delete build directory between reconfigurations.** CMake caches the configuration in the build directory. If you change cmake options or the P4 file path, delete `/tmp/build_<name>` first or cmake will silently ignore the new options.

**Run the build:**
```bash
cd /home/student/Desktop/flowlidar/prototype3
./build.sh
```

**Start the model and switchd after a successful build:**
```bash
# Terminal 1
sudo -E $SDE/run_tofino_model.sh -p prototype3

# Terminal 2 (wait for model to print "Blocking on message from CPU")
sudo -E $SDE/run_switchd.sh -p prototype3
```

Wait for `bfruntime gRPC server started on 0.0.0.0:50052` before connecting the control plane.

---

## 8. Hash Polynomial Reference

### BF Polynomials (Prototypes 2–5)

| Array | P4 `CRCPolynomial` | crcmod call |
|-------|--------------------|-------------|
| bf_0 | `poly=0x04C11DB7, rev=true, init=0xFFFFFFFF, residue=0xFFFFFFFF` | `mkCrcFun(0x104C11DB7, rev=True, initCrc=0x00000000, xorOut=0xFFFFFFFF)` |
| bf_1 | `poly=0x04C11DB7, rev=false, init=0xFFFFFFFF, residue=0xFFFFFFFF` | `mkCrcFun(0x104C11DB7, rev=False, initCrc=0x00000000, xorOut=0xFFFFFFFF)` |
| bf_2 | `poly=0x1EDC6F41, rev=true, init=0xFFFFFFFF, residue=0xFFFFFFFF` | `mkCrcFun(0x11EDC6F41, rev=True, initCrc=0x00000000, xorOut=0xFFFFFFFF)` |

Index width: 17 bits → `& 0x1FFFF` (range 0–131071).

### CMS Polynomials (Prototypes 3–5)

| Row | P4 `CRCPolynomial` | crcmod call |
|-----|--------------------|-------------|
| cms_0 | `poly=0xA833982B, rev=true, init=0xFFFFFFFF, residue=0xFFFFFFFF` | `mkCrcFun(0x1A833982B, rev=True, initCrc=0x00000000, xorOut=0xFFFFFFFF)` |
| cms_1 | `poly=0x814141AB, rev=false, init=0x00000000, residue=0x00000000` | `mkCrcFun(0x1814141AB, rev=False, initCrc=0x00000000, xorOut=0x00000000)` |
| cms_2 | `poly=0x04C11DB7, rev=false, init=0x00000000, residue=0xFFFFFFFF` | `mkCrcFun(0x104C11DB7, rev=False, initCrc=0xFFFFFFFF, xorOut=0xFFFFFFFF)` |

Index width: 10 bits → `& 0x3FF` (range 0–1023).

### Mapping Formula (Empirically Confirmed)

```
crcmod polynomial  = 0x1 followed by P4_poly hex digits
crcmod rev         = P4_reversed
crcmod initCrc     = P4_init XOR P4_residue
crcmod xorOut      = P4_residue
```

This was determined by running `debug_cms.py` / `debug_bf.py` to compare Python-predicted indices against the hardware register values for known test flows, and iterating over candidate configurations until all predictions matched.

---

## 9. Prototype Progression Summary

| Prototype | Data Plane | Control Plane | Key Added |
|-----------|-----------|---------------|-----------|
| **P1** | IPv4 LPM forwarding only | `setup_table.py` for route | TNA build pipeline verified |
| **P2** | Standard BF (k=3, m=128K) | Digest receiver | New-flow detection + digest |
| **P3** | BF + CMS (k=3, m=1K, 16-bit) | Epoch: digest + min(CMS) | Per-flow counting, epoch processor |
| **P4** | Lazy BF + conditional CMS | Epoch: digest_count + min(CMS) | Algorithm 2, conditional table dispatch |
| **P5** | Same as P4 | Alg.4 + Alg.5 + Ax=b solver + Alg.6 | Exact counts via postprocessing |

**Memory footprint per epoch:**

| Structure | Entries | Width | Total |
|-----------|---------|-------|-------|
| BF (×3 rows) | 131,072 | 1 bit | 48 KB |
| CMS (×3 rows) | 1,024 | 16 bits | 6 KB |
| **Total** | — | — | **54 KB** |

**Theoretical scaling (from paper):** 4×128K BF + 64×1K CMS supports ~60K–900K active flows per epoch with exact equation solving (load factor stays below 0.918 threshold).
