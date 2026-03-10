# Prototype 5 — FlowLiDAR: Lazy Bloom Filter + Equation Solver

## Overview

This prototype implements the complete FlowLiDAR system from the paper:
> Monterubbiano et al., "FlowLiDAR: Per-Flow Network Telemetry with Low Processing and Storage", ACM SIGMETRICS 2023.

The goal is to count, exactly, how many packets each network flow sent during a measurement window (epoch), using only the resources available inside an Intel Tofino 1 programmable switch.

The system splits work across two components:

**Data plane** (`prototype5.p4`) runs inside the switch ASIC at line rate. It uses two probabilistic data structures — a Bloom Filter (BF) and a Count-Min Sketch (CMS) — to detect flows and accumulate packet counts. It never touches the CPU while packets are flowing. The BF implements the *Lazy Updates* variant (Algorithm 2 from the paper), which causes the first *k* packets of every flow to be individually reported to the control plane as *digests*, deferring CMS counting to packets that arrive after a flow is fully registered.

**Control plane** (`control_plane.py`) runs on the switch CPU as a Python process. It receives digests in real time and, at epoch boundaries, reads a snapshot of the CMS registers and runs a postprocessing pipeline to recover exact per-flow counts:
- Algorithm 4: resolve flows whose exact count is already known from the digests alone (by checking which BF bits are still zero).
- Algorithm 5: resolve flows where the CMS estimate is zero (flow had exactly *k* packets).
- Equation solver: build and solve a sparse binary linear system Ax = b for the remaining flows.
- Algorithm 6: approximate fallback for underdetermined systems (heavy load / collisions).

The result is exact per-flow packet counts for all flows in the epoch.

---

## File Structure

```
prototype5/
├── prototype5.p4       # P4-16 data plane program (Tofino 1 / TNA)
├── build.sh            # Build script: cmake + make + install
├── setup_table.py      # Adds LPM route + conditional BF/CMS table entries (bfshell)
├── reset_epoch.py      # Clears all BF + CMS register arrays (bfshell)
├── control_plane.py    # Control plane: digest receiver + epoch postprocessing
├── test_packet.py      # Test script: sends 6 flows with known packet counts via Scapy
└── debug_bf.py         # Debug: scans BF registers, compares with Python CRC predictions

Shared:
../common/headers.p4    # Packet header definitions (all prototypes share this)
../common/util.p4       # Reusable TNA parser/control stubs (all prototypes share this)
```

---

## Table of Contents

1. [System Architecture](#1-system-architecture)
2. [Shared Foundations](#2-shared-foundations)
3. [Data Plane Walkthrough](#3-data-plane-walkthrough)
   - 3.1 [Packet Headers and Metadata](#31-packet-headers-and-metadata)
   - 3.2 [Ingress Parser](#32-ingress-parser)
   - 3.3 [Lazy Bloom Filter](#33-lazy-bloom-filter)
   - 3.4 [Count-Min Sketch](#34-count-min-sketch)
   - 3.5 [Digest Mechanism](#35-digest-mechanism)
   - 3.6 [IPv4 LPM Forwarding](#36-ipv4-lpm-forwarding)
   - 3.7 [Apply Block — Packet Processing Order](#37-apply-block--packet-processing-order)
   - 3.8 [Stage Allocation](#38-stage-allocation)
   - 3.9 [Pipeline Instantiation](#39-pipeline-instantiation)
4. [Control Plane Walkthrough](#4-control-plane-walkthrough)
   - 4.1 [Connecting to switchd via gRPC](#41-connecting-to-switchd-via-grpc)
   - 4.2 [Digest Reception Loop](#42-digest-reception-loop)
   - 4.3 [CMS Register Snapshot](#43-cms-register-snapshot)
   - 4.4 [Hash Replication in Python](#44-hash-replication-in-python)
   - 4.5 [Algorithm 4 — BF Preprocessing](#45-algorithm-4--bf-preprocessing)
   - 4.6 [Algorithm 5 — CMS Preprocessing](#46-algorithm-5--cms-preprocessing)
   - 4.7 [Equation Solver — Building Ax = b](#47-equation-solver--building-ax--b)
   - 4.8 [Solving and Result Assembly](#48-solving-and-result-assembly)
   - 4.9 [Algorithm 6 — Approximate Fallback](#49-algorithm-6--approximate-fallback)
   - 4.10 [Register Clearing](#410-register-clearing)
   - 4.11 [Main Loop](#411-main-loop)
5. [Setup Scripts](#5-setup-scripts)
6. [Test Script](#6-test-script)
7. [Debug Script](#7-debug-script)
8. [Build System](#8-build-system)
9. [Hash Polynomial Reference](#9-hash-polynomial-reference)
10. [How to Run](#10-how-to-run)
11. [Understanding the Test Results](#11-understanding-the-test-results)

---

## 1. System Architecture

```
                    ┌─────────────────────────────────────────────┐
                    │              Tofino 1 ASIC                  │
  Packets ──────▶   │                                             │
  (veth1 → port 0)  │  ┌──────────┐   ┌────────────────────────┐ │
                    │  │  Parser  │──▶│    SwitchIngress        │ │
                    │  └──────────┘   │                        │ │
                    │                 │  Stage 0–2: BF hashes  │ │
                    │                 │  Stage 3–5: Lazy BF    │ │
                    │                 │  Stage 6:   CMS hash   │ │
                    │                 │  Stage 7–9: Cond. CMS  │ │
                    │                 └──────────┬─────────────┘ │
                    │                            │  digest        │
                    └────────────────────────────┼───────────────┘
                                                 │ gRPC (port 50052)
                    ┌────────────────────────────▼───────────────┐
                    │            control_plane.py                 │
                    │                                             │
                    │  flow_table: {flow_key → digest_count}     │
                    │                                             │
                    │  Every epoch_seconds:                       │
                    │    1. Read CMS snapshot                     │
                    │    2. Read BF cells (targeted)              │
                    │    3. Algorithm 4 → exact (BF zero bit)    │
                    │    4. Algorithm 5 → exact (CMS = 0)        │
                    │    5. Solve Ax = b  → exact (equation)     │
                    │    6. Algorithm 6   → approx (fallback)    │
                    │    7. Clear BF + CMS registers             │
                    └─────────────────────────────────────────────┘
```

### The Epoch Concept

An **epoch** is a measurement window with a fixed duration (default 10 s, configurable via `--epoch`). At the start of every epoch, the BF and CMS registers are all zero. As packets flow through the switch, the BF detects new/partially-seen flows (sending digests to the control plane), and the CMS accumulates packet counts. At epoch end the control plane reads a snapshot, runs postprocessing, prints a report, then clears everything for the next epoch.

### Why the Lazy BF?

The standard BF marks all k bits on the *first* packet of a flow. That single packet triggers a digest. Subsequent packets from the same flow hit all-1 bits and go directly to the CMS — correct.

The Lazy Updates BF (Algorithm 2) instead sets only **one** bit per packet, the first zero bit it encounters. A flow with k=3 packets sets bit 0 on packet 1 (digest fires), bit 1 on packet 2 (digest fires), bit 2 on packet 3 (digest fires). A fourth packet finds all bits 1 and goes to the CMS. This means:

- Flows with ≤ k packets are **entirely counted by digests** — the control plane has their exact count without reading the CMS at all.
- The CMS only accumulates counts for flows with > k packets, keeping its counters precise.
- The control plane's count for any flow is: `digest_count + CMS_count`.

---

## 2. Shared Foundations

### `common/headers.p4`

Defines every packet header struct and typedef used by the parser and control blocks.

**Type aliases** give semantic names to raw bit widths:
```p4
typedef bit<48>  mac_addr_t;   // 6-byte Ethernet address
typedef bit<32>  ipv4_addr_t;  // 4-byte IPv4 address
typedef bit<16>  ether_type_t; // EtherType field
typedef bit<8>   ip_protocol_t;
```

**Constants** let the parser branch on protocol values without magic numbers:
```p4
const ether_type_t ETHERTYPE_IPV4 = 16w0x0800;
const ip_protocol_t IP_PROTOCOLS_TCP = 6;
const ip_protocol_t IP_PROTOCOLS_UDP = 17;
```

**Header structs** mirror the on-wire binary layout of each protocol. The compiler maps each field directly to the bits extracted from the packet wire:
```p4
header ipv4_h {
    bit<4>  version;
    bit<4>  ihl;
    bit<8>  diffserv;
    bit<16> total_len;
    bit<16> identification;
    bit<3>  flags;
    bit<13> frag_offset;
    bit<8>  ttl;
    bit<8>  protocol;
    bit<16> hdr_checksum;
    ipv4_addr_t src_addr;
    ipv4_addr_t dst_addr;
}

header tcp_h {
    bit<16> src_port;
    bit<16> dst_port;
    bit<32> seq_no;
    bit<32> ack_no;
    bit<4>  data_offset;
    bit<4>  res;
    bit<8>  flags;
    bit<16> window;
    bit<16> checksum;
    bit<16> urgent_ptr;
}

header udp_h {
    bit<16> src_port;
    bit<16> dst_port;
    bit<16> hdr_length;
    bit<16> checksum;
}
```

**The top-level header bundle** holds one instance of each header. The parser populates whichever headers are valid for each packet; fields in invalid headers are not accessible:
```p4
struct header_t {
    ethernet_h ethernet;
    vlan_tag_h vlan_tag;
    ipv4_h     ipv4;
    ipv6_h     ipv6;
    tcp_h      tcp;
    udp_h      udp;
}
```

**Empty stubs** satisfy the TNA type signatures for the egress pipeline (which this prototype does not use):
```p4
struct empty_header_t {}
struct empty_metadata_t {}
```

### `common/util.p4`

Provides reusable parser and control blocks required by every TNA program.

**`TofinoIngressParser`** is always the first parser applied in any TNA ingress parser. It extracts the Tofino-internal intrinsic metadata header (`ig_intr_md`) that precedes every packet on the internal bus, then skips past the port metadata region. Without this, none of the intrinsic metadata fields (ingress port, timestamp, etc.) are accessible:

```p4
parser TofinoIngressParser(
        packet_in pkt,
        out ingress_intrinsic_metadata_t ig_intr_md) {
    state start {
        pkt.extract(ig_intr_md);           // read Tofino's internal header
        transition select(ig_intr_md.resubmit_flag) {
            1 : parse_resubmit;            // packet was resubmitted (unused here)
            0 : parse_port_metadata;
        }
    }
    state parse_port_metadata {
        pkt.advance(PORT_METADATA_SIZE);   // skip port metadata — not used
        transition accept;
    }
}
```

**`EmptyEgressParser` / `EmptyEgress` / `EmptyEgressDeparser`** are no-op stubs. This prototype bypasses the egress pipeline (`ig_tm_md.bypass_egress = 1w1`), so the egress blocks are never executed. They are required by the `Pipeline()` type signature:
```p4
parser EmptyEgressParser(packet_in pkt,
        out empty_header_t hdr, out empty_metadata_t eg_md,
        out egress_intrinsic_metadata_t eg_intr_md) {
    state start { transition accept; }
}
control EmptyEgress(...) { apply {} }
control EmptyEgressDeparser(...) { apply {} }
```

---

## 3. Data Plane Walkthrough

### 3.1 Packet Headers and Metadata

**`flow_digest_t`** is the struct packed into a digest message and sent to the control plane. It contains exactly the fields needed to identify a flow — the 5-tuple:
```p4
struct flow_digest_t {
    bit<32> src_addr;   // IPv4 source address
    bit<32> dst_addr;   // IPv4 destination address
    bit<8>  protocol;   // IP protocol number (6=TCP, 17=UDP, ...)
    bit<16> src_port;   // transport source port (0 for non-TCP/UDP)
    bit<16> dst_port;   // transport destination port
}
```

**`metadata_t`** carries per-packet state that must persist between stages but is not part of the packet headers. TNA passes this struct through every stage of the ingress pipeline:
```p4
struct metadata_t {
    // Transport ports extracted from TCP or UDP header.
    // Stored here so the hash and digest can use them regardless of protocol.
    bit<16> src_port;
    bit<16> dst_port;

    // BF hash indices — one per BF array, computed in stages 0/1/2.
    // Each is 17 bits because the BF register has 2^17 = 131,072 entries.
    // They are stored in metadata because they are computed in one stage
    // and consumed in a later stage (the RegisterAction execute call).
    bit<17> idx0;
    bit<17> idx1;
    bit<17> idx2;

    // BF check-and-set results — 1 bit each.
    // Stored in metadata because tbl_bf1 (stage 4) needs b0 (produced in
    // stage 3), and tbl_bf2 (stage 5) needs both b0 and b1.
    bit<1> b0;
    bit<1> b1;
    bit<1> b2;

    // CMS hash indices — one per CMS row, computed together in stage 6.
    // 10 bits because CMS has 2^10 = 1,024 entries per row.
    bit<10> cms_idx0;
    bit<10> cms_idx1;
    bit<10> cms_idx2;
}
```

### 3.2 Ingress Parser

The parser extracts protocol headers from the raw packet bytes. It runs before any control logic, and P4 compilation guarantees it fits within the parser's clock budget.

```p4
parser SwitchIngressParser(
        packet_in pkt,
        out header_t hdr,
        out metadata_t ig_md,
        out ingress_intrinsic_metadata_t ig_intr_md) {

    TofinoIngressParser() tofino_parser;  // instantiate the shared stub

    state start {
        tofino_parser.apply(pkt, ig_intr_md);  // mandatory first step
        transition parse_ethernet;
    }

    state parse_ethernet {
        pkt.extract(hdr.ethernet);
        transition select(hdr.ethernet.ether_type) {
            ETHERTYPE_IPV4 : parse_ipv4;
            default        : accept;  // non-IPv4: control will call miss()
        }
    }

    state parse_ipv4 {
        pkt.extract(hdr.ipv4);
        transition select(hdr.ipv4.protocol) {
            IP_PROTOCOLS_TCP : parse_tcp;
            IP_PROTOCOLS_UDP : parse_udp;
            default          : accept;  // ICMP etc: ports default to 0
        }
    }

    state parse_tcp {
        pkt.extract(hdr.tcp);
        transition accept;
    }

    state parse_udp {
        pkt.extract(hdr.udp);
        transition accept;
    }
}
```

After parsing, `hdr.ipv4.isValid()` is true only for IPv4 packets. `hdr.tcp.isValid()` and `hdr.udp.isValid()` indicate whether the transport layer was parsed. The control block uses these validity bits to guard all IPv4-specific logic.

### 3.3 Lazy Bloom Filter

A Bloom Filter is a memory-efficient probabilistic set. It represents a set of flows as k bit arrays. To **insert** a flow: hash it k times, set the bit at each hash index to 1. To **query**: hash it k times, check all k bits — if any bit is 0, the flow is definitely not in the set; if all are 1, the flow is probably in the set (rare false positives, no false negatives).

The Lazy Updates variant changes *insert*: instead of setting all k bits at once on the first packet, set only the first zero bit encountered. This spreads the k "insert" events across k separate packets, with a digest sent each time. A flow is fully inserted after k packets have passed through.

#### Register Declaration

Three independent 1-bit arrays, each with 131,072 entries (2^17):

```p4
Register<bit<1>, bit<17>>(131072) bf_0;
Register<bit<1>, bit<17>>(131072) bf_1;
Register<bit<1>, bit<17>>(131072) bf_2;
```

`Register<V, K>(n)` declares a register with value type `V` (here `bit<1>`, one bit per cell), index type `K` (`bit<17>`, a 17-bit address), and `n` entries. Total memory: 3 × 131,072 bits = 48 KB.

k=3 was chosen instead of the paper's k=4 to free two MAU stages for the CMS (see §3.8).

#### RegisterAction — Atomic Check-and-Set

A `RegisterAction` is the only way to read and modify a register in the same pipeline pass — it runs as an atomic read-modify-write directly in the MAU stage where the register lives:

```p4
RegisterAction<bit<1>, bit<17>, bit<1>>(bf_0) bf_check_set_0 = {
    void apply(inout bit<1> val, out bit<1> rv) {
        rv  = val;  // capture old value before modification
        val = 1;    // unconditionally set the bit to 1
    }
    // Return value rv: 0 means the bit was 0 before this packet
    //                  1 means the bit was already 1 (flow already registered here)
};
```

`val` is the register cell addressed by `execute(idx)`. The `inout` qualifier allows both reading and writing it. `rv` is the return value of `execute()`, available in the calling action.

All three BF arrays use identical logic:
```p4
RegisterAction<bit<1>, bit<17>, bit<1>>(bf_1) bf_check_set_1 = {
    void apply(inout bit<1> val, out bit<1> rv) { rv = val; val = 1; }
};
RegisterAction<bit<1>, bit<17>, bit<1>>(bf_2) bf_check_set_2 = {
    void apply(inout bit<1> val, out bit<1> rv) { rv = val; val = 1; }
};
```

#### Hash Functions — Three Independent CRC32 Polynomials

Each BF array needs a statistically independent hash function so that different flows have uncorrelated bit patterns, minimising false positive rates. Three CRC32 variants with different polynomials and configurations provide this independence:

```p4
// poly0 — CRC32 standard (IEEE 802.3)
CRCPolynomial<bit<32>>(
    32w0x04C11DB7,  // standard CRC32 generator polynomial
    true,           // reversed: process bits LSB-first (reflected input/output)
    false,          // use_msb: false = return lower N bits of result
    false,          // extended: not used
    32w0xFFFFFFFF,  // init: initial CRC register value
    32w0xFFFFFFFF   // residue: XORed into the final output
) poly0;
Hash<bit<17>>(HashAlgorithm_t.CUSTOM, poly0) hash0;
// → produces a 17-bit index from the 5-tuple

// poly1 — CRC32/BZIP2 (same polynomial, not reversed)
CRCPolynomial<bit<32>>(32w0x04C11DB7,
    false, false, false,        // NOT reversed — bit-processing order differs
    32w0xFFFFFFFF, 32w0xFFFFFFFF) poly1;
Hash<bit<17>>(HashAlgorithm_t.CUSTOM, poly1) hash1;

// poly2 — CRC32C (Castagnoli) — different generator polynomial
CRCPolynomial<bit<32>>(32w0x1EDC6F41,
    true, false, false,         // reversed again
    32w0xFFFFFFFF, 32w0xFFFFFFFF) poly2;
Hash<bit<17>>(HashAlgorithm_t.CUSTOM, poly2) hash2;
```

`Hash<bit<17>>` means the hash output is truncated (or modularly reduced) to 17 bits, giving a value in range [0, 131071].

#### Why One Hash Per Stage — the 32-bit Pathway Limit

Each MAU stage has a 32-bit "immediate pathway" — a hardware data path that carries hash outputs from the hash engine to the ALU. One 17-bit hash index consumes 17 bits of this budget. Two 17-bit hashes would need 34 bits, which exceeds the 32-bit limit.

Therefore, each BF hash gets its own dedicated stage:

```p4
action compute_idx0() {
    ig_md.idx0 = hash0.get({
        hdr.ipv4.src_addr, hdr.ipv4.dst_addr,
        hdr.ipv4.protocol,
        ig_md.src_port, ig_md.dst_port
    });
}
// The @stage(N) annotation forces the compiler to place this table
// in exactly stage N of the ingress pipeline. Without it, the compiler
// might co-locate two hash tables in the same stage, breaking the layout.
@stage(0) table tbl_hash0 {
    actions        = { compute_idx0; }
    default_action = compute_idx0;  // no key — always fires
    size           = 1;             // only one "row", acts as an unconditional action
}

@stage(1) table tbl_hash1 {
    actions        = { compute_idx1; }
    default_action = compute_idx1;
    size           = 1;
}

@stage(2) table tbl_hash2 {
    actions        = { compute_idx2; }
    default_action = compute_idx2;
    size           = 1;
}
```

The hash input is the same 5-tuple for all three: `{src_addr, dst_addr, protocol, src_port, dst_port}`. Different polynomials produce different indices for the same input, which is what independence means.

#### Conditional BF Tables — Lazy Execution

In TNA, `RegisterAction.execute()` must be called from inside a table action — it cannot be placed inside a bare `if` block in `apply`. The Lazy BF's conditional logic is therefore implemented as a set of tables keyed on the metadata bits `b0` and `b1`:

**Stage 3 — bf_0: always executes**

bf_0 runs unconditionally for every IPv4 packet. Its result (`b0 = old value`) tells subsequent stages whether this flow was already registered in the first BF array:

```p4
action run_bf0() {
    // execute() returns the old value of bf_0[idx0], then sets it to 1.
    // Storing the result in ig_md.b0 makes it available to later stages.
    ig_md.b0 = bf_check_set_0.execute(ig_md.idx0);
}
@stage(3) table tbl_bf0 {
    actions        = { run_bf0; }
    default_action = run_bf0;   // no key — always fires
    size           = 1;
}
```

**Stage 4 — bf_1: only if b0 == 1**

If `b0 == 0`, the first BF bit was zero before this packet. The Lazy BF rule says: we found the first zero, we set it, we stop. There is no point checking further arrays. So bf_1 should be skipped. The table key is `ig_md.b0`:

```p4
action run_bf1() {
    ig_md.b1 = bf_check_set_1.execute(ig_md.idx1);
}
action skip_bf1() {
    // b0 was 0 — this packet already "used" its one allowed bit-set on bf_0.
    // Set b1 = 0 so the digest condition fires correctly (see §3.5).
    ig_md.b1 = 0;
}
@stage(4) table tbl_bf1 {
    key            = { ig_md.b0 : exact; }
    actions        = { run_bf1; skip_bf1; }
    default_action = skip_bf1;  // fires when b0 != 1, i.e. when b0 == 0
    size           = 2;
}
// setup_table.py adds: tbl_bf1.add_with_run_bf1(b0=1)
// So:  b0=1 → run_bf1 (execute the register action)
//      b0=0 → skip_bf1 (default, do nothing to the register)
```

**Stage 5 — bf_2: only if b0 == 1 AND b1 == 1**

Similarly, bf_2 is only reached if both earlier arrays already had the bit set (meaning this packet has passed two fully-registered arrays and is now probing the third):

```p4
action run_bf2() {
    ig_md.b2 = bf_check_set_2.execute(ig_md.idx2);
}
action skip_bf2() {
    ig_md.b2 = 0;
}
@stage(5) table tbl_bf2 {
    key            = { ig_md.b0 : exact; ig_md.b1 : exact; }
    actions        = { run_bf2; skip_bf2; }
    default_action = skip_bf2;
    size           = 4;  // 2-bit key → 4 possible combinations
}
// setup_table.py adds: tbl_bf2.add_with_run_bf2(b0=1, b1=1)
// So: (1,1) → run_bf2
//     (1,0), (0,1), (0,0) → skip_bf2 (default)
```

**Why `size = 4` and `size = 2`?** The `size` annotation tells the compiler how many entries to reserve for the table's match storage. `tbl_bf1` has a 1-bit key with 2 possible values → size=2. `tbl_bf2` has a 2-bit key with 4 possible combinations → size=4. Only one entry is actually installed (the active case); the rest hit the default action.

### 3.4 Count-Min Sketch

A Count-Min Sketch (CMS) is a k × m array of counters that supports approximate per-flow counting. To **increment** flow x: hash x with k independent functions to get k indices, increment counter `row[i][hash_i(x)]` for each row i. To **query** flow x: take `min over i of row[i][hash_i(x)]`. The minimum guards against hash collisions inflating the count.

In this prototype, the CMS only increments when a packet's flow is *fully registered* in the BF (b0 = b1 = b2 = 1), meaning it is a packet after the first k=3.

#### Register Declaration

Three 16-bit counter arrays, 1,024 entries each:

```p4
Register<bit<16>, bit<10>>(1024) cms_0;
Register<bit<16>, bit<10>>(1024) cms_1;
Register<bit<16>, bit<10>>(1024) cms_2;
```

`bit<16>` counters saturate at 65,535. `bit<10>` index addresses 2^10 = 1,024 cells. Total memory: 3 × 1,024 × 2 bytes = 6 KB.

#### CMS RegisterActions — Atomic Increment

```p4
RegisterAction<bit<16>, bit<10>, bit<16>>(cms_0) cms_inc_0 = {
    void apply(inout bit<16> val, out bit<16> rv) {
        val = val + 1;  // increment the counter in-place
        rv  = val;      // return the new value (discarded in apply; side effect is all that matters)
    }
};
// Identical for cms_1, cms_2.
```

Note: unlike the BF RegisterActions, `val` is modified here. The operation is still atomic — no other packet can read or write this cell between the read and write.

#### CMS Hash Functions — Three More Distinct Polynomials

The CMS hashes use different polynomials from the BF hashes to maximise independence between the two structures:

```p4
// cms_poly0 — CRC32D (different generator: 0xA833982B)
CRCPolynomial<bit<32>>(32w0xA833982B,
    true,           // reversed
    false, false,
    32w0xFFFFFFFF,  // init
    32w0xFFFFFFFF   // residue
) cms_poly0;
Hash<bit<10>>(HashAlgorithm_t.CUSTOM, cms_poly0) cms_hash0;

// cms_poly1 — CRC32/Q
CRCPolynomial<bit<32>>(32w0x814141AB,
    false,          // NOT reversed
    false, false,
    32w0x00000000,  // init = 0
    32w0x00000000   // residue = 0
) cms_poly1;
Hash<bit<10>>(HashAlgorithm_t.CUSTOM, cms_poly1) cms_hash1;

// cms_poly2 — CRC32/POSIX
CRCPolynomial<bit<32>>(32w0x04C11DB7,
    false,          // NOT reversed
    false, false,
    32w0x00000000,  // init = 0
    32w0xFFFFFFFF   // residue (XOR out)
) cms_poly2;
Hash<bit<10>>(HashAlgorithm_t.CUSTOM, cms_poly2) cms_hash2;
```

#### Combined CMS Hash Stage

Three 10-bit indices sum to 30 bits, which fits within the 32-bit immediate pathway limit. All three hash computations can therefore share a single MAU stage:

```p4
action compute_cms_indices() {
    ig_md.cms_idx0 = cms_hash0.get({hdr.ipv4.src_addr, hdr.ipv4.dst_addr,
                                     hdr.ipv4.protocol,
                                     ig_md.src_port, ig_md.dst_port});
    ig_md.cms_idx1 = cms_hash1.get({hdr.ipv4.src_addr, hdr.ipv4.dst_addr,
                                     hdr.ipv4.protocol,
                                     ig_md.src_port, ig_md.dst_port});
    ig_md.cms_idx2 = cms_hash2.get({hdr.ipv4.src_addr, hdr.ipv4.dst_addr,
                                     hdr.ipv4.protocol,
                                     ig_md.src_port, ig_md.dst_port});
}
@stage(6) table tbl_cms_hash {
    actions        = { compute_cms_indices; }
    default_action = compute_cms_indices;
    size           = 1;
}
```

Compare with the BF hash tables: those need one stage each (17+17=34 > 32), but the CMS indices are only 10 bits each (10+10+10=30 ≤ 32).

#### Conditional CMS Increment Tables

The CMS only fires when b0 = b1 = b2 = 1 (all BF bits were already set, meaning the CMS now "owns" counting this packet). The same table-keying pattern as the BF tables is used:

```p4
action do_cms_inc_0() { cms_inc_0.execute(ig_md.cms_idx0); }
action nop_cms_0()    {}   // no-op: this packet does not go to CMS row 0

@stage(7) table tbl_cms_0 {
    key            = { ig_md.b0 : exact; ig_md.b1 : exact; ig_md.b2 : exact; }
    actions        = { do_cms_inc_0; nop_cms_0; }
    default_action = nop_cms_0;   // any key combination other than (1,1,1)
    size           = 8;           // 3-bit key → 8 combinations
}
// setup_table.py adds: tbl_cms_0.add_with_do_cms_inc_0(b0=1, b1=1, b2=1)
// Result: only packets where all 3 BF bits were already 1 increment the CMS.

// Identical pattern for tbl_cms_1 (@stage 8) and tbl_cms_2 (@stage 9)
```

`b0`, `b1`, `b2` at this point reflect the *old* values returned by the BF `execute()` calls (or 0 if the skip actions ran). If all three are 1, every BF array already had this flow's bit set before this packet arrived, which means the flow was registered at least k=3 packets ago — this packet is a "known flow" packet.

### 3.5 Digest Mechanism

The digest is a lightweight DMA channel from the data plane to the control plane. It can carry a small fixed-size struct at line rate without involving the CPU in the packet path.

**Setting the digest type in the control block:**
```p4
// After executing tbl_bf0/1/2:
if (ig_md.b0 == 0) { ig_dprsr_md.digest_type = 1; }
if (ig_md.b1 == 0) { ig_dprsr_md.digest_type = 1; }
if (ig_md.b2 == 0) { ig_dprsr_md.digest_type = 1; }
```

Setting `ig_dprsr_md.digest_type = 1` signals the deparser to call `flow_digest.pack(...)`. The three separate comparisons are needed because Tofino's condition hardware requires each comparison to be between one runtime value and one constant — you cannot write `if (b0 == 0 && b1 == 0)`.

Why three checks instead of one? Because in the Lazy BF, a packet that skips bf_1 and bf_2 (because b0 = 0) will have `b1 = 0` and `b2 = 0` set by the skip actions — not because those arrays have a zero at this flow's index, but simply because the arrays were not executed. The control plane counts all three `b*==0` conditions as "this packet is a new/partial flow" because in all cases, the flow is not yet fully registered.

**Packing and sending the digest in the deparser:**
```p4
control SwitchIngressDeparser(...) {
    Digest<flow_digest_t>() flow_digest;
    Checksum() ipv4_checksum;

    apply {
        // Only pack a digest if the control block set digest_type = 1.
        if (ig_dprsr_md.digest_type == 1) {
            flow_digest.pack({
                hdr.ipv4.src_addr,
                hdr.ipv4.dst_addr,
                hdr.ipv4.protocol,
                ig_md.src_port,     // from metadata, not directly from tcp/udp header
                ig_md.dst_port
            });
        }
        // Recompute the IPv4 checksum after TTL was decremented by the LPM hit action.
        hdr.ipv4.hdr_checksum = ipv4_checksum.update({
            hdr.ipv4.version, hdr.ipv4.ihl, hdr.ipv4.diffserv,
            hdr.ipv4.total_len, hdr.ipv4.identification,
            hdr.ipv4.flags, hdr.ipv4.frag_offset,
            hdr.ipv4.ttl, hdr.ipv4.protocol,
            hdr.ipv4.src_addr, hdr.ipv4.dst_addr
        });
        pkt.emit(hdr);  // serialise valid headers back onto the wire
    }
}
```

`ig_md.src_port` is used instead of `hdr.tcp.src_port` directly because the port value was copied to metadata at the top of `apply` — this single field serves both TCP and UDP packets without needing separate digest actions.

### 3.6 IPv4 LPM Forwarding

The switch forwards packets based on a longest-prefix-match lookup of the IPv4 destination address. `setup_table.py` installs the route entry.

```p4
action hit(PortId_t dst_port) {
    ig_tm_md.ucast_egress_port = dst_port;  // send packet out this physical port
    hdr.ipv4.ttl = hdr.ipv4.ttl - 1;       // decrement TTL as required by IPv4 forwarding
    ig_dprsr_md.drop_ctl = 0x0;             // 0 = forward, 1 = drop
}

action miss() {
    ig_dprsr_md.drop_ctl = 0x1;  // no route → drop the packet
}

table ipv4_lpm {
    key = {
        hdr.ipv4.dst_addr : lpm;   // longest prefix match on destination IP
    }
    actions = { hit; miss; }
    size           = 1024;    // up to 1K LPM entries
    default_action = miss();  // drop if no route matches
}
```

The IPv4 checksum must be recomputed after the TTL decrement. This is done in the deparser (see §3.5) using the `Checksum()` extern, which the compiler maps to a hardware checksum unit.

### 3.7 Apply Block — Packet Processing Order

The `apply` block is the main control flow for each packet. It runs every stage in order:

```p4
apply {
    // Step 1: Copy transport ports to metadata.
    // The BF hash and digest both need the ports regardless of protocol.
    // Non-TCP/UDP packets get port 0, which still produces a valid hash.
    ig_md.src_port = 0;
    ig_md.dst_port = 0;
    if (hdr.tcp.isValid()) {
        ig_md.src_port = hdr.tcp.src_port;
        ig_md.dst_port = hdr.tcp.dst_port;
    } else if (hdr.udp.isValid()) {
        ig_md.src_port = hdr.udp.src_port;
        ig_md.dst_port = hdr.udp.dst_port;
    }

    if (hdr.ipv4.isValid()) {

        // Step 2: Forward the packet (LPM lookup runs in stage 0, same stage
        // as tbl_hash0 — different resource types coexist in the same stage).
        ipv4_lpm.apply();

        // Step 3: Compute all three BF hash indices, one per stage (0, 1, 2).
        // Each writes one metadata field (idx0/1/2) for use in the next steps.
        tbl_hash0.apply();
        tbl_hash1.apply();
        tbl_hash2.apply();

        // Step 4: Lazy BF check-and-set, stages 3, 4, 5.
        // tbl_bf0 always executes; tbl_bf1 and tbl_bf2 are conditional on
        // the results of earlier stages, enforced via table key matching.
        tbl_bf0.apply();  // always: stores old bf_0[idx0] in b0
        tbl_bf1.apply();  // if b0==1: stores old bf_1[idx1] in b1; else b1=0
        tbl_bf2.apply();  // if b0==1 AND b1==1: stores old bf_2[idx2] in b2; else b2=0

        // Step 5: Trigger digest if any BF bit was 0.
        // Three separate conditions are required (Tofino condition hardware
        // compares one runtime value to one constant per expression).
        if (ig_md.b0 == 0) { ig_dprsr_md.digest_type = 1; }
        if (ig_md.b1 == 0) { ig_dprsr_md.digest_type = 1; }
        if (ig_md.b2 == 0) { ig_dprsr_md.digest_type = 1; }

        // Step 6: Compute all three CMS hash indices in one stage (stage 6).
        // 3 × 10 bits = 30 bits ≤ 32-bit immediate pathway limit → fits in one stage.
        tbl_cms_hash.apply();

        // Step 7: Conditionally increment CMS rows, stages 7, 8, 9.
        // Each fires only when b0=b1=b2=1 (all BF bits were pre-set).
        // If any b* is 0, nop_cms_* fires and the counter is not touched.
        tbl_cms_0.apply();
        tbl_cms_1.apply();
        tbl_cms_2.apply();

    } else {
        miss();  // non-IPv4: drop
    }

    // Bypass the egress pipeline entirely — this prototype does not use egress.
    ig_tm_md.bypass_egress = 1w1;
}
```

### 3.8 Stage Allocation

Tofino 1 provides 12 ingress MAU stages (0–11). The full allocation:

| Stage | Table / Object | Resource Type | Notes |
|-------|----------------|---------------|-------|
| 0 | `ipv4_lpm` | TCAM (LPM) | Shares stage 0 with tbl_hash0 — different units |
| 0 | `tbl_hash0` | Hash + SRAM | BF idx0 (17-bit) |
| 1 | `tbl_hash1` | Hash + SRAM | BF idx1 (17-bit) |
| 2 | `tbl_hash2` | Hash + SRAM | BF idx2 (17-bit) |
| 3 | `tbl_bf0` + `bf_0` register | SRAM + stateful ALU | Always: check-and-set bf_0 |
| 4 | `tbl_bf1` + `bf_1` register | SRAM + stateful ALU | Conditional on b0=1 |
| 5 | `tbl_bf2` + `bf_2` register | SRAM + stateful ALU | Conditional on b0=b1=1 |
| 6 | `tbl_cms_hash` | Hash + SRAM | CMS idx0/1/2 combined (30 bits) |
| 7 | `tbl_cms_0` + `cms_0` register | SRAM + stateful ALU | Conditional on b0=b1=b2=1 |
| 8 | `tbl_cms_1` + `cms_1` register | SRAM + stateful ALU | Conditional on b0=b1=b2=1 |
| 9 | `tbl_cms_2` + `cms_2` register | SRAM + stateful ALU | Conditional on b0=b1=b2=1 |
| 10 | — | — | Free |
| 11 | — | — | Free |

Each `RegisterAction.execute()` call consumes one stateful ALU unit in the stage where its register lives. That is why each BF and CMS register occupies a separate stage: you cannot run two independent stateful ALU operations for different registers in the same stage.

### 3.9 Pipeline Instantiation

TNA requires a top-level `Pipeline` and `Switch` instantiation that wires all six blocks (ingress parser, ingress control, ingress deparser, egress parser, egress control, egress deparser) together:

```p4
Pipeline(
    SwitchIngressParser(),
    SwitchIngress(),
    SwitchIngressDeparser(),
    EmptyEgressParser(),   // egress bypassed — use the no-op stubs from util.p4
    EmptyEgress(),
    EmptyEgressDeparser()
) pipe;

Switch(pipe) main;  // the top-level module switchd loads
```

`Switch(pipe) main` is the mandatory name the toolchain looks for when loading the compiled binary.

---

## 4. Control Plane Walkthrough

`control_plane.py` is a standalone Python 3 script. It runs as a separate process on the switch CPU and communicates with the data plane through the Barefoot Runtime (bfrt) gRPC API.

### 4.1 Connecting to switchd via gRPC

```python
import bfrt_grpc.client as gc

interface = gc.ClientInterface(
    grpc_addr='localhost:50052',  # switchd listens on this port
    client_id=0,                  # client identifier; only one client owns the P4 at a time
    device_id=0,                  # device index (single-device setup)
    num_tries=10,                 # retry connection up to 10 times before failing
    notifications=gc.Notifications(enable_learn=True)
    # enable_learn=True is required to receive digest notifications.
    # Without it, interface.digest_get() never returns anything.
)

# Claim ownership of the P4 program's runtime tables.
# This must be called before any table or register access.
# Only one client can own a program at a time.
interface.bind_pipeline_config('prototype5')

# Get handles to all tables and learn objects defined in prototype5.p4.
bfrt_info = interface.bfrt_info_get('prototype5')

# Register the IPv4 annotation on address fields so digest_get() returns
# dotted-decimal strings ('10.1.0.1') instead of raw integers.
learn_filter = bfrt_info.learn_get('flow_digest')
learn_filter.info.data_field_annotation_add('src_addr', 'ipv4')
learn_filter.info.data_field_annotation_add('dst_addr', 'ipv4')

# Target object identifies which device to operate on.
target = gc.Target(device_id=0)
```

The SDE Python packages are not on the system path by default. Before importing `bfrt_grpc`, the script prepends the SDE install paths:
```python
SDE_INSTALL = os.environ.get('SDE_INSTALL',
                             '/home/student/Desktop/open-p4studio/install')
sys.path.append(os.path.join(SDE_INSTALL, 'lib/python3.8/site-packages'))
sys.path.append(os.path.join(SDE_INSTALL, 'lib/python3.8/site-packages/tofino'))
```

### 4.2 Digest Reception Loop

The main loop polls for digest notifications from the data plane and builds a `flow_table` dictionary mapping each flow's 5-tuple to how many digests were received for it this epoch:

```python
flow_table  = {}  # { (src_addr, dst_addr, protocol, src_port, dst_port) : digest_count }
epoch_start = time.time()
epoch_num   = 1

while True:
    try:
        # digest_get blocks for up to 0.5s waiting for a notification batch.
        # If no digests arrive within 0.5s it raises an exception (not returns None).
        digest    = interface.digest_get(timeout=0.5)

        # make_data_list unpacks the raw gRPC message into a list of
        # data objects, one per digest packed in the notification.
        # The P4 deparser may batch multiple digests into a single notification.
        data_list = learn_filter.make_data_list(digest)

        for data in data_list:
            d = data.to_dict()
            # to_dict() returns a plain Python dict with field names as keys.
            # Because of the 'ipv4' annotation added above, src_addr and dst_addr
            # are already formatted as dotted-decimal strings.
            flow_key = (
                d['src_addr'],   # e.g. '10.1.0.1'
                d['dst_addr'],
                d['protocol'],   # integer: 6 for TCP, 17 for UDP
                d['src_port'],
                d['dst_port'],
            )
            # Count how many digests we received for this flow this epoch.
            # With Lazy BF and k=3, we expect up to 3 digests per flow.
            flow_table[flow_key] = flow_table.get(flow_key, 0) + 1

    except KeyboardInterrupt:
        # Ctrl-C: run a final epoch report before exiting.
        process_epoch(epoch_num, flow_table, bfrt_info, target)
        break
    except Exception:
        # Catches the timeout exception from digest_get.
        # Also catches transient gRPC errors during model startup.
        pass

    # Check if the epoch timer has elapsed.
    if time.time() - epoch_start >= epoch_seconds:
        process_epoch(epoch_num, flow_table, bfrt_info, target)
        flow_table.clear()       # reset for next epoch
        epoch_num   += 1
        epoch_start  = time.time()
```

**`digest_count` semantics with Lazy BF:** With k=3 and the lazy scheme, a flow receiving N packets sends min(N, k) digests — one per BF bit set. After k digests, all BF bits are 1 and no more digests fire; subsequent packets go to the CMS. So `flow_table[flow_key]` is:
- N if N < k (flow had fewer than k packets)
- k if N ≥ k (exactly k digests, regardless of total packet count)

### 4.3 CMS Register Snapshot

At epoch end, the full CMS state is read before any processing begins. This ensures a consistent snapshot — if registers were read per-flow later, the control plane would be racing against ongoing packet processing.

```python
def _read_register_array(bfrt_info, tbl_name, size, target):
    """
    Read all entries of a register table into a Python list.
    tbl_name: fully qualified bfrt table name, e.g. 'pipe.SwitchIngress.cms_0'
    size:     number of register cells (must match the P4 Register declaration)
    Returns:  list of ints, indexed 0..size-1
    """
    arr = [0] * size
    tbl = bfrt_info.table_get(tbl_name)
    expected_field = f'SwitchIngress.{tbl_name.split(".")[-1]}.f1'
    # e.g. 'SwitchIngress.cms_0.f1' — the bfrt field name for the register value

    for key, data in tbl.entry_get(target, None, {'from_hw': True}):
        # Passing None as the key list means "iterate all entries".
        # from_hw=True reads from hardware registers, not any software cache.
        k_dict = key.to_dict()
        d_dict = data.to_dict()

        # SDE 9.13.4 quirk: the $REGISTER_INDEX (cell index) and the value field
        # (.f1) can appear in EITHER the key dict or the data dict.
        # The normal expectation is: key dict = index, data dict = value.
        # But in the model (and sometimes on hardware) it is swapped.
        # We detect which dict holds the index and look for the value in the other.
        if '$REGISTER_INDEX' in d_dict:
            idx_src = d_dict
            val_src = k_dict
        else:
            idx_src = k_dict
            val_src = d_dict

        idx_raw = idx_src.get('$REGISTER_INDEX', 0)
        # The index may be a plain int, or a dict like {'value': 42, 'mask': None}.
        if isinstance(idx_raw, dict):
            idx = idx_raw.get('value', 0)
        else:
            idx = int(idx_raw)

        # Look for the value field. Zero-value entries may omit the field
        # entirely (sparse representation), in which case the cell stays 0.
        if expected_field in val_src:
            val = val_src[expected_field]
        elif expected_field in idx_src:
            val = idx_src[expected_field]
        else:
            combined = {**k_dict, **d_dict}
            f1 = next((f for f in combined if f.endswith('.f1')), None)
            val = combined[f1] if f1 else 0

        # Wide registers (or pipeline replication) may return a list of values,
        # one per pipeline copy. Index [0] gives the value for the first pipe.
        if isinstance(val, list):
            val = val[0]

        if 0 <= idx < size:
            arr[idx] = val

    return arr
```

The CMS snapshot is called for all three rows:
```python
def read_cms_snapshot(bfrt_info, target):
    snapshot    = {}
    field_names = {}
    for row in ['cms_0', 'cms_1', 'cms_2']:
        tbl_name      = f'pipe.SwitchIngress.{row}'
        arr           = _read_register_array(bfrt_info, tbl_name, 1024, target)
        snapshot[row] = arr
        field_names[row] = f'SwitchIngress.{row}.f1'
    return snapshot, field_names
```

### 4.4 Hash Replication in Python

The control plane must compute the same hash values as the P4 program to look up the correct CMS and BF cells for each flow. This is done using the `crcmod` library.

#### Packing the 5-Tuple

The P4 hash input is `{ipv4.src_addr, ipv4.dst_addr, ipv4.protocol, src_port, dst_port}` — these fields are concatenated in order. The Python equivalent packs them in network (big-endian) byte order, which is what the Tofino's internal data bus uses:

```python
import struct, socket

def _flow_bytes(src_addr, dst_addr, protocol, src_port, dst_port):
    # socket.inet_aton converts '10.1.0.1' to 4-byte network representation.
    # struct.unpack('!I', ...) interprets those 4 bytes as a big-endian uint32.
    src_int = struct.unpack('!I', socket.inet_aton(src_addr))[0]
    dst_int = struct.unpack('!I', socket.inet_aton(dst_addr))[0]
    # Format: 2× uint32 (IP addresses), 1× uint8 (protocol), 2× uint16 (ports)
    # Total: 4 + 4 + 1 + 2 + 2 = 13 bytes — matches the P4 field concatenation order.
    return struct.pack('!IIBHH', src_int, dst_int, protocol, src_port, dst_port)
```

#### Tofino → crcmod Parameter Mapping

The Tofino's `CRCPolynomial` uses four parameters that affect the CRC computation: `poly`, `reversed`, `init`, and `residue`. The crcmod library uses different parameter names with different semantics. The mapping (determined empirically by comparing Python predictions against hardware register values):

```
crcmod polynomial  = 0x1 followed by P4_poly  (prepend the implicit leading bit)
crcmod rev         = P4_reversed
crcmod initCrc     = P4_init XOR P4_residue
crcmod xorOut      = P4_residue
```

`Hash<bit<10>>` with `use_msb=False` (the default) returns the **lower 10 bits** of the 32-bit CRC, so the Python side applies `& (size - 1)`.

#### CMS Hash Functions

```python
import crcmod

# cms_poly0: CRC32D
# P4:  poly=0xA833982B, rev=true, init=0xFFFFFFFF, residue=0xFFFFFFFF
# crcmod: poly = 0x1_A833982B, initCrc = 0xFFFFFFFF ^ 0xFFFFFFFF = 0x00000000
_cms_fn0 = crcmod.mkCrcFun(0x1A833982B, rev=True,
                            initCrc=0x00000000, xorOut=0xFFFFFFFF)

# cms_poly1: CRC32/Q
# P4:  poly=0x814141AB, rev=false, init=0x00000000, residue=0x00000000
# crcmod: initCrc = 0 ^ 0 = 0
_cms_fn1 = crcmod.mkCrcFun(0x1814141AB, rev=False,
                            initCrc=0x00000000, xorOut=0x00000000)

# cms_poly2: CRC32/POSIX
# P4:  poly=0x04C11DB7, rev=false, init=0x00000000, residue=0xFFFFFFFF
# crcmod: initCrc = 0x00000000 ^ 0xFFFFFFFF = 0xFFFFFFFF
_cms_fn2 = crcmod.mkCrcFun(0x104C11DB7, rev=False,
                            initCrc=0xFFFFFFFF, xorOut=0xFFFFFFFF)

def cms_indices(flow_key):
    data = _flow_bytes(*flow_key)
    return (
        _cms_fn0(data) & 0x3FF,   # lower 10 bits → range [0, 1023]
        _cms_fn1(data) & 0x3FF,
        _cms_fn2(data) & 0x3FF,
    )
```

#### BF Hash Functions

Algorithm 4 needs to look up the BF cell values for each flow, which requires replicating the BF hash functions:

```python
# bf_fn0: CRC32 standard
# P4:  poly=0x04C11DB7, rev=true, init=0xFFFFFFFF, residue=0xFFFFFFFF
# crcmod: initCrc = 0xFFFFFFFF ^ 0xFFFFFFFF = 0x00000000
_bf_fn0 = crcmod.mkCrcFun(0x104C11DB7, rev=True,
                           initCrc=0x00000000, xorOut=0xFFFFFFFF)

# bf_fn1: CRC32/BZIP2 (same poly, not reversed)
# P4:  poly=0x04C11DB7, rev=false, init=0xFFFFFFFF, residue=0xFFFFFFFF
_bf_fn1 = crcmod.mkCrcFun(0x104C11DB7, rev=False,
                           initCrc=0x00000000, xorOut=0xFFFFFFFF)

# bf_fn2: CRC32C (Castagnoli, different poly)
# P4:  poly=0x1EDC6F41, rev=true, init=0xFFFFFFFF, residue=0xFFFFFFFF
_bf_fn2 = crcmod.mkCrcFun(0x11EDC6F41, rev=True,
                           initCrc=0x00000000, xorOut=0xFFFFFFFF)

def bf_indices(flow_key):
    data = _flow_bytes(*flow_key)
    return (
        _bf_fn0(data) & 0x1FFFF,   # lower 17 bits → range [0, 131071]
        _bf_fn1(data) & 0x1FFFF,
        _bf_fn2(data) & 0x1FFFF,
    )
```

#### Targeted BF Cell Read

Reading all 131,072 cells of each BF row via gRPC takes several seconds — the same order of magnitude as the register clearing operation. For Algorithm 4, only 3 specific cells per flow are needed (one per BF array, at the hash-computed index). A targeted read fetches just those cells:

```python
def _read_register_cell(bfrt_info, tbl_name, idx, target):
    """
    Read a single register cell by index. Much faster than a full array read
    when only a few cells are needed (18 reads for 6 flows vs 393,216 for a scan).
    """
    tbl = bfrt_info.table_get(tbl_name)
    expected_field = f'SwitchIngress.{tbl_name.split(".")[-1]}.f1'
    # Construct an explicit key for the single entry we want.
    key = tbl.make_key([gc.KeyTuple('$REGISTER_INDEX', idx)])
    try:
        for k, data in tbl.entry_get(target, [key], {'from_hw': True}):
            # Merge both dicts to handle the key/data swap quirk.
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

def read_bf_bits_for_flow(bfrt_info, target, flow_key):
    """Return (b0, b1, b2) — the actual BF register values at this flow's positions."""
    i0, i1, i2 = bf_indices(flow_key)
    b0 = _read_register_cell(bfrt_info, 'pipe.SwitchIngress.bf_0', i0, target)
    b1 = _read_register_cell(bfrt_info, 'pipe.SwitchIngress.bf_1', i1, target)
    b2 = _read_register_cell(bfrt_info, 'pipe.SwitchIngress.bf_2', i2, target)
    return (b0, b1, b2)
```

### 4.5 Algorithm 4 — BF Preprocessing

This is the first postprocessing step. For every flow the control plane knows about, it reads the three BF bit values at that flow's hash positions and checks whether all three are 1.

```python
def algorithm4_bf_preprocess(flow_table, bfrt_info, target):
    """
    Returns:
        resolved: dict flow_key -> exact total packet count
                  (flows whose count is fully determined by digest_count)
        C:        list of flow_keys that need CMS inspection
    """
    resolved = {}
    C        = []

    for flow_key, digest_count in flow_table.items():
        b0, b1, b2 = read_bf_bits_for_flow(bfrt_info, target, flow_key)

        if b0 == 0 or b1 == 0 or b2 == 0:
            # At least one BF bit is still 0 at epoch end.
            # With the Lazy BF, a flow with j < k packets sets exactly j bits.
            # Any zero bit means the flow had fewer than k packets total.
            # Every one of those packets triggered a digest → exact count = digest_count.
            resolved[flow_key] = digest_count
        else:
            # All three BF bits are 1. This flow had ≥ k=3 packets.
            # The first k were counted as digests; packets k+1 onward went to the CMS.
            # We need to read the CMS to know the full count.
            C.append(flow_key)

    return resolved, C
```

**Why this works:** With the Lazy BF, packet 1 sets bf_0 (bf_1 and bf_2 stay 0). Packet 2 sets bf_1 (bf_2 stays 0). Packet 3 sets bf_2. If a flow had exactly 2 packets, bf_2 is still 0 at epoch end. Algorithm 4 sees bf_2 = 0, concludes N < k, and returns `digest_count = 2`. No CMS read is needed. This is correct because packets 1 and 2 each triggered a digest, so the control plane received 2 digests for this flow.

### 4.6 Algorithm 5 — CMS Preprocessing

For flows that passed Algorithm 4 (all three BF bits are 1, flow had ≥ k packets), check whether the flow has any entries in the CMS. If the CMS estimate is zero, the flow had exactly k packets — the k-th packet set the last BF bit and triggered a digest; no packet from this flow ever reached the CMS.

```python
def algorithm5_cms_preprocess(C, flow_table, cms_snapshot):
    """
    C:            list of flow_keys from Algorithm 4 (all BF bits = 1)
    flow_table:   full digest count dict from the epoch
    cms_snapshot: dict row_name -> list[int] (the CMS register arrays)

    Returns:
        resolved: dict flow_key -> exact total count (added to Alg4 results)
        C_final:  list of flow_keys that still need the equation solver
    """
    resolved = {}
    C_final  = []

    for flow_key in C:
        digest_count = flow_table[flow_key]
        i0, i1, i2  = cms_indices(flow_key)

        # Look up the CMS counter for this flow in each row.
        counts = [
            cms_snapshot['cms_0'][i0],
            cms_snapshot['cms_1'][i1],
            cms_snapshot['cms_2'][i2],
        ]
        cms_est = min(counts)

        if cms_est == 0:
            # All three CMS counters for this flow are 0.
            # This means no packet from this flow ever incremented the CMS.
            # With the Lazy BF, a flow reaches the CMS only on its (k+1)-th packet.
            # CMS = 0 → the flow had exactly k packets, all counted as digests.
            resolved[flow_key] = digest_count
        else:
            # This flow has genuine CMS entries. We need the equation solver
            # to disentangle it from other flows that may share the same cells.
            C_final.append(flow_key)

    return resolved, C_final
```

**Why CMS = 0 means exactly k packets:** The k-th packet sets the last BF bit (bf_2) and triggers a digest. At that point, b2's *old* value was 0, so the skip path was taken for the CMS — the CMS was not incremented. Only the (k+1)-th packet finds all three bits already 1, triggering the CMS increment. If CMS = 0 for all three rows, no such (k+1)-th packet ever arrived. Total packets = k = digest_count.

### 4.7 Equation Solver — Building Ax = b

For flows in `C_final` (all BF bits = 1, CMS > 0), we need to recover the exact CMS contribution for each flow. Hash collisions mean multiple flows may share a CMS counter cell, making it impossible to read one flow's count in isolation. The equation solver reconstructs individual counts from the shared counters.

**Variables:** `x = [x_1, ..., x_n]^T` where `x_j` is the number of CMS increments for flow j (i.e., packets arriving after the first k=3).

**Equations:** For each unique (row, cell) pair referenced by any flow in `C_final`, the counter value equals the sum of `x_j` for all flows that hash to that cell:
```
counter[row_r][cell_c] = sum of x_j for all j where hash_r(flow_j) == cell_c
```

**Matrix A:** `A[i][j] = 1` if flow j contributes to equation i. Each flow contributes to exactly k=3 equations (one per CMS row), giving each column exactly 3 ones when there are no hash collisions.

```python
def build_matrix(C_final, cms_snapshot):
    row_names = ['cms_0', 'cms_1', 'cms_2']

    # Map each unique (row_index, cell_index) pair to an equation number.
    # Two flows sharing the same cell in the same row get the same equation index —
    # that is exactly the collision we need the solver to resolve.
    counter_to_eq = {}
    eq_idx = 0
    for flow_key in C_final:
        idxs = cms_indices(flow_key)     # (i0, i1, i2)
        for r, cell in enumerate(idxs):  # r = row number 0/1/2
            key = (r, cell)
            if key not in counter_to_eq:
                counter_to_eq[key] = eq_idx
                eq_idx += 1
    # With n flows and k rows, we have at most k*n equations, but collisions reduce
    # the count (two flows sharing a cell → one equation, not two).

    m_eq = len(counter_to_eq)  # number of unique counter cells = number of equations
    n    = len(C_final)        # number of unknown flow counts

    # Allocate the matrix and vector.
    A = np.zeros((m_eq, n), dtype=float)
    b = np.zeros(m_eq,      dtype=float)

    # Fill b: the measured counter value for each equation's cell.
    for (r, cell), eq_i in counter_to_eq.items():
        b[eq_i] = cms_snapshot[row_names[r]][cell]

    # Fill A: for each flow, mark which equations it contributes to.
    for j, flow_key in enumerate(C_final):
        idxs = cms_indices(flow_key)
        for r, cell in enumerate(idxs):
            eq_i = counter_to_eq[(r, cell)]
            A[eq_i][j] = 1.0   # flow j increments the counter at equation eq_i

    return A, b, m_eq, n
```

**Example — 2 flows, no collisions, k=3 rows:**
```
          flow_A  flow_B
row0,c0A: [ 1       0  ]   b[0] = cms_0[hash0(A)] = 9
row0,c0B: [ 0       1  ]   b[1] = cms_0[hash0(B)] = 3
row1,c1A: [ 1       0  ]   b[2] = cms_1[hash1(A)] = 9
row1,c1B: [ 0       1  ]   b[3] = cms_1[hash1(B)] = 3
row2,c2A: [ 1       0  ]   b[4] = cms_2[hash2(A)] = 9
row2,c2B: [ 0       1  ]   b[5] = cms_2[hash2(B)] = 3

System: 6 equations, 2 unknowns → heavily overdetermined.
Solution: x_A = 9, x_B = 3. Exact.
```

**Example — 2 flows sharing row 0, cell c:**
```
row0,c:   [ 1       1  ]   b[0] = 12  ← A and B both hash to the same cell
row1,c1A: [ 1       0  ]   b[1] = 9
row1,c1B: [ 0       1  ]   b[2] = 3
row2,c2A: [ 1       0  ]   b[3] = 9
row2,c2B: [ 0       1  ]   b[4] = 3

System: 5 equations, 2 unknowns. From rows 1 and 2: x_A=9, x_B=3. Row 0 is consistent (9+3=12). Rank=2. Exact.
```

### 4.8 Solving and Result Assembly

```python
def solve_cms_system(C_final, flow_table, cms_snapshot):
    if not C_final:
        return {}

    A, b, m_eq, n = build_matrix(C_final, cms_snapshot)

    # numpy.linalg.lstsq solves the linear least-squares problem:
    # find x that minimises ||Ax - b||. For full-rank systems this is exact.
    # For overdetermined systems (m_eq > n, typical here) it finds the exact
    # solution if one exists, or the best approximation if not.
    x, residuals, rank, sv = np.linalg.lstsq(A, b, rcond=None)

    load_factor = n / 1024   # n flows / CMS row size
    # The system is guaranteed to be uniquely solvable when load_factor < 0.918
    # (k=3, from the paper's Table 2). Above this threshold, hash collisions
    # can make the system underdetermined.

    if rank < n:
        # Underdetermined: more unknown flows than independent equations.
        # Fall back to Algorithm 6.
        x = algorithm6_approximate(A, b, n, rank)
    else:
        res = np.linalg.norm(A @ x - b)
        if res > 0.5:
            print(f'  [WARN] Residual={res:.2f} — possible hash collisions.')
        # Small residual (< 0.5) means the solution is exact.

    # Round to nearest non-negative integer (counts must be whole numbers ≥ 0).
    x = np.clip(np.round(x), 0, None).astype(int)

    result = {}
    for j, flow_key in enumerate(C_final):
        # Total count = digests (first k packets) + CMS count (packets k+1 onward).
        result[flow_key] = flow_table[flow_key] + int(x[j])

    return result
```

### 4.9 Algorithm 6 — Approximate Fallback

Triggered when `rank(A) < n`: there are more unknown flow counts than independent equations. This happens at high load (many flows colliding into the same CMS cells) when the exact system is unsolvable.

The algorithm greedily fixes variables by processing equations in ascending order of their counter value — the smallest counters have the fewest flows sharing them, making them the most informative:

```python
def algorithm6_approximate(A, b, n, rank):
    x_approx = np.zeros(n, dtype=float)
    fixed     = np.zeros(n, dtype=bool)

    # Sort equation indices by b_i ascending: start with the smallest counters.
    # Rationale: a counter with value 2 shared by 1 flow tells us that flow
    # has count 2. A counter with value 100 shared by 10 flows tells us much less.
    order = np.argsort(b)

    free_remaining = n - rank

    for eq_i in order:
        if free_remaining <= 0:
            break   # all free variables have been fixed
        # Which flows contribute to this equation and are not yet fixed?
        cols = [j for j in range(n) if A[eq_i][j] > 0 and not fixed[j]]
        if not cols:
            continue  # all flows in this equation already fixed
        # Distribute the counter value equally among the unfixed flows.
        # This is the best estimate when we have no additional information.
        val = b[eq_i] / len(cols)
        for j in cols:
            x_approx[j] = val
            fixed[j]    = True
        free_remaining -= len(cols)

    # If any variables remain unfixed, solve the now-reduced system.
    unfixed = [j for j in range(n) if not fixed[j]]
    if unfixed:
        b_reduced = b.copy()
        for j in range(n):
            if fixed[j]:
                b_reduced -= A[:, j] * x_approx[j]  # subtract known contributions
        A_reduced = A[:, unfixed]
        x_sub, _, _, _ = np.linalg.lstsq(A_reduced, b_reduced, rcond=None)
        for k, j in enumerate(unfixed):
            x_approx[j] = x_sub[k]

    return x_approx
```

### 4.10 Register Clearing

After the epoch report is printed, all BF and CMS registers are zeroed so the next epoch starts clean. The bfrt Python client in SDE 9.13.4 does not expose a bulk-clear method for registers via gRPC, so clearing is done by writing zeros to every cell in batches:

```python
def clear_all_registers(bfrt_info, target, cms_field_names=None):
    reg_sizes = {r: 131072 for r in ['bf_0', 'bf_1', 'bf_2']}   # 2^17 cells
    reg_sizes.update({r: 1024 for r in ['cms_0', 'cms_1', 'cms_2']})  # 2^10 cells

    for reg in ['bf_0', 'bf_1', 'bf_2', 'cms_0', 'cms_1', 'cms_2']:
        tbl_name   = f'pipe.SwitchIngress.{reg}'
        size       = reg_sizes[reg]
        field_name = (cms_field_names or {}).get(reg, f'SwitchIngress.{reg}.f1')
        tbl        = bfrt_info.table_get(tbl_name)

        # Write in batches of 128 entries. A single gRPC call with all 131,072
        # entries for a BF row would exceed the gRPC message size limit.
        BATCH = 128
        for start in range(0, size, BATCH):
            end   = min(start + BATCH, size)
            keys  = [tbl.make_key([gc.KeyTuple('$REGISTER_INDEX', i)])
                     for i in range(start, end)]
            datas = [tbl.make_data([gc.DataTuple(field_name, 0)])
                     for _ in range(start, end)]
            tbl.entry_mod(target, keys, datas)
```

**Performance note:** Clearing the three BF rows (131,072 cells each) via gRPC takes several seconds on the model because every cell requires a separate gRPC message. This does not affect measurement accuracy — clearing happens after the report is printed. On real hardware, atomic register clear instructions complete in microseconds. The bfshell `reset_epoch.py` script uses the faster bfshell-internal `clear()` API.

### 4.11 Main Loop

The full `process_epoch` function assembles all steps and produces the report:

```python
def process_epoch(epoch_num, flow_table, bfrt_info, target):
    print(f'EPOCH {epoch_num} END — {len(flow_table)} flows detected by BF')

    # Step 1: Read the CMS snapshot before doing anything else.
    # This ensures we see a consistent state (not a mixture of cells read at
    # different times while packets are still arriving).
    cms_snapshot, cms_field_names = read_cms_snapshot(bfrt_info, target)

    # Step 2: Algorithm 4 — use BF register reads to resolve flows with < k packets.
    resolved, C = algorithm4_bf_preprocess(flow_table, bfrt_info, target)

    # Step 3: Algorithm 5 — resolve flows with exactly k packets (CMS = 0).
    resolved5, C_final = algorithm5_cms_preprocess(C, flow_table, cms_snapshot)
    resolved.update(resolved5)

    # Step 4: Equation solver for remaining flows (> k packets, CMS > 0).
    solver_results = solve_cms_system(C_final, flow_table, cms_snapshot)

    # Step 5: Merge all results and tag each flow with its resolution method.
    all_results = {}
    for flow_key in flow_table:
        if flow_key in solver_results:
            all_results[flow_key] = (flow_table[flow_key],
                                     solver_results[flow_key] - flow_table[flow_key],
                                     solver_results[flow_key], 'solver')
        elif flow_key in resolved5:
            all_results[flow_key] = (flow_table[flow_key], 0,
                                     resolved5[flow_key], 'alg5')
        else:
            all_results[flow_key] = (flow_table[flow_key], 0,
                                     resolved.get(flow_key, flow_table[flow_key]), 'alg4')
    # Tuple layout: (digest_count, cms_part, total, method)

    # Step 6: Print report.
    print(f'  {"Flow":<44} {"Digests":>7}  {"CMS/Solve":>9}  {"Total":>5}  {"Method":>6}')
    for flow_key in sorted(all_results):
        digest_count, cms_part, total, method = all_results[flow_key]
        ...

    # Step 7: Clear registers for the next epoch.
    clear_all_registers(bfrt_info, target, cms_field_names)
```

---

## 5. Setup Scripts

### `setup_table.py`

Run at the `bfshell>` prompt after switchd starts. Installs all table entries that the P4 program needs but cannot populate itself (tables are populated by the control plane, not by the P4 program):

```python
p4 = bfrt.prototype5.pipe

# ── IPv4 LPM forwarding entry ──────────────────────────────────────────────
# Route all packets destined for 10.0.0.1 out of port 1.
# Port 1 → veth2/veth3 in the Tofino model veth mapping.
tbl = p4.SwitchIngress.ipv4_lpm
tbl.clear()
tbl.add_with_hit(dst_addr='10.0.0.1', dst_addr_p_length=32, dst_port=1)

# ── Lazy BF conditional tables ─────────────────────────────────────────────
# tbl_bf1 has key=b0. Add the one entry that triggers execution:
#   b0=1 → run_bf1 (execute the RegisterAction for bf_1)
# Any packet with b0=0 hits the default action skip_bf1.
tbl_bf1 = p4.SwitchIngress.tbl_bf1
tbl_bf1.clear()
tbl_bf1.add_with_run_bf1(b0=1)

# tbl_bf2 has key=(b0, b1). Add the one entry that triggers execution:
#   b0=1, b1=1 → run_bf2
# All other combinations (0,0), (0,1), (1,0) hit skip_bf2.
tbl_bf2 = p4.SwitchIngress.tbl_bf2
tbl_bf2.clear()
tbl_bf2.add_with_run_bf2(b0=1, b1=1)

# ── Conditional CMS increment tables ──────────────────────────────────────
# Each CMS table has key=(b0, b1, b2). Only (1,1,1) triggers the increment.
# The other 7 combinations all hit the nop default action.
for tbl_name, action in [('tbl_cms_0', 'do_cms_inc_0'),
                          ('tbl_cms_1', 'do_cms_inc_1'),
                          ('tbl_cms_2', 'do_cms_inc_2')]:
    tbl = getattr(p4.SwitchIngress, tbl_name)
    tbl.clear()
    getattr(tbl, f'add_with_{action}')(b0=1, b1=1, b2=1)
```

**Without these entries:** The default actions (`skip_bf1`, `skip_bf2`, `nop_cms_0/1/2`) fire for every packet. bf_1 and bf_2 are never executed, so flows are never fully registered, and the CMS is never incremented. The system would only generate digest #1 per flow and never count beyond that.

### `reset_epoch.py`

Clears all BF and CMS registers without stopping the switch or restarting the control plane. Useful when debugging (avoids waiting for the epoch timer or restarting the whole setup):

```python
p4 = bfrt.prototype5.pipe

# bfshell's internal .clear() is an atomic hardware operation — much faster
# than the gRPC zero-write loop used by control_plane.py.
p4.SwitchIngress.bf_0.clear()
p4.SwitchIngress.bf_1.clear()
p4.SwitchIngress.bf_2.clear()
p4.SwitchIngress.cms_0.clear()
p4.SwitchIngress.cms_1.clear()
p4.SwitchIngress.cms_2.clear()
```

Run at the `bfshell>` prompt:
```
bfrt_python /home/student/Desktop/flowlidar/prototype5/reset_epoch.py
```

---

## 6. Test Script

`test_packet.py` sends six flows with known packet counts using Scapy, providing ground truth to verify the postprocessing pipeline.

### Test Flows and Packet Counts

```python
PKT_A = Ether()/IP(src='10.1.0.1', dst='10.0.0.1', ttl=64)/TCP(sport=1000, dport=80)
PKT_B = Ether()/IP(src='10.1.0.2', dst='10.0.0.1', ttl=64)/TCP(sport=2000, dport=80)
PKT_C = Ether()/IP(src='10.1.0.3', dst='10.0.0.1', ttl=64)/TCP(sport=3000, dport=80)
PKT_D = Ether()/IP(src='10.1.0.4', dst='10.0.0.1', ttl=64)/TCP(sport=4000, dport=443)
PKT_E = Ether()/IP(src='10.1.0.5', dst='10.0.0.1', ttl=64)/UDP(sport=5000, dport=53)
PKT_F = Ether()/IP(src='10.1.0.6', dst='10.0.0.1', ttl=64)/UDP(sport=6000, dport=53)
```

All packets go to `veth1` (the sending side of the veth pair connected to switch port 0).

The test is structured in phases to control exactly which packets each flow receives and when:

```
Phase 1: Send 1 packet per flow (6 flows)
         Each flow's bf_0 gets set. digest #1 fires for each flow.

DIGEST_GAP (1.5 s wait)     ← allows the model dedup timer to expire

Phase 2: Send packet 2 for flows A and B only
         bf_0 is already 1 for A and B. tbl_bf1 fires run_bf1, setting bf_1.
         digest #2 fires for A and B.

DIGEST_GAP

Phase 3: Send packet 3 for flows A and B
         bf_0=1, bf_1=1 for A and B. tbl_bf2 fires run_bf2, setting bf_2.
         digest #3 fires for A and B. Now A and B are fully registered.

DIGEST_GAP

Phase 4: Send 8 more packets for A, 2 more for B (no gaps needed — CMS only)
         A and B have b0=b1=b2=1 on every packet → go to CMS, no digest.
         CMS(A) accumulates 8 increments; CMS(B) accumulates 2.

Phase 5: Send packet 2 for Flow C
         C had 1 packet so far (bf_0=1, bf_1=0, bf_2=0).
         This packet sets bf_1. digest #2 fires for C.

DIGEST_GAP

Phase 6: Re-send all 6 flows once each
         A, B: CMS+1 each (fully registered). CMS(A)→9, CMS(B)→3.
         C:    bf_0=1, bf_1=1, bf_2=0 → sets bf_2, digest #3. C fully registered,
               but this is the 3rd packet so no CMS increment (b2 was 0).
         D, E, F: bf_0=1, bf_1=0 → sets bf_1, digest #2.
```

Final state at epoch end:

| Flow | Total packets | digest_count | BF state | CMS cells |
|------|--------------|--------------|----------|-----------|
| A | 12 | 3 | (1,1,1) | 9 |
| B | 6  | 3 | (1,1,1) | 3 |
| C | 3  | 3 | (1,1,1) | 0 |
| D | 2  | 2 | (1,1,0) | 0 |
| E | 2  | 2 | (1,1,0) | 0 |
| F | 2  | 2 | (1,1,0) | 0 |

### `DIGEST_GAP = 1.5` Seconds

On real Tofino hardware, a quiescence timer fires within microseconds after the last digest from a given flow key, merging duplicate digests. On the software model, this debounce window is much longer (on the order of seconds). Without the gap between packets of the same flow, consecutive packets from the same flow generate only one digest message — the model merges them. With a 1.5 s gap, each packet produces a separate digest.

This gap is only needed on the model. On real hardware, the test would send all packets at normal line rate with no gaps.

---

## 7. Debug Script

`debug_bf.py` is a diagnostic tool for verifying that the Python BF hash functions produce the same indices as the Tofino hardware.

It works in three parts:

**Part 1 — Raw non-zero BF cells:** Scans all three BF register arrays and prints which cells are non-zero. Run this *after* `test_packet.py` and *before* the epoch timer fires (which would clear the registers). This gives the ground-truth hardware state:
```
bf_0: 6 non-zero cells  indices=[12345, 23456, ...]
bf_1: 6 non-zero cells  indices=[...]
bf_2: 3 non-zero cells  indices=[...]  ← only flows A, B, C reach bf_2
```

**Part 2 — Candidate function sweep:** Tests multiple candidate hash configurations against the hardware's non-zero indices, printing how many of the 6 test flows each candidate correctly predicts. A perfect match (6/6 or 3/3) identifies the correct crcmod parameters:
```python
CANDIDATES = [
    ('CRC32  rev=T init=0x00000000 xor=0xFFFFFFFF', 0x104C11DB7, True,  0x00000000, 0xFFFFFFFF),
    ...
]
for label, poly, rev, initCrc, xorOut in CANDIDATES:
    fn   = crcmod.mkCrcFun(poly, rev=rev, initCrc=initCrc, xorOut=xorOut)
    hits = sum(1 for flow in FLOWS
               if (fn(_flow_bytes(*flow)) & (BF_SIZE-1)) in bf0_set)
    print(f'  hits={hits}/6  {label}')
```

**Part 3 — Per-flow prediction with confirmed functions:** Uses the final confirmed hash functions to predict each flow's three BF indices and checks each prediction against the hardware:
```
Flow A: bf_0[119916]=HIT  bf_1[88234]=HIT  bf_2[44123]=HIT
Flow D: bf_0[77654]=HIT   bf_1[33210]=HIT  bf_2[99012]=MISS  ← only 2 packets
```

The script connects with `client_id=2` (read-only) and skips `bind_pipeline_config` to avoid interfering with the running control plane.

---

## 8. Build System

### `build.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail

PROGRAM_NAME="prototype5"
P4_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/prototype5.p4"
BUILD_DIR="/tmp/build_${PROGRAM_NAME}"

SDE_INSTALL="${SDE}/install"
P4C_BIN="${SDE_INSTALL}/bin/p4c"

# Step 1: CMake configuration
# Delete the build directory first to avoid stale CMake cache.
# If you change any -D option without deleting the cache, cmake silently
# uses the old value from the cache file.
rm -rf "$BUILD_DIR"
cmake "$SDE/p4studio/" \
    -DCMAKE_INSTALL_PREFIX="$SDE_INSTALL" \
    -DCMAKE_MODULE_PATH="$SDE/cmake" \
    -DP4_NAME="$PROGRAM_NAME" \
    -DP4_PATH="$P4_FILE" \
    -DP4C="$P4C_BIN" \        # critical: must be explicit
    -B "$BUILD_DIR"

# Step 2: Compile the P4 program
make -C "$BUILD_DIR" "$PROGRAM_NAME"

# Step 3: Install the compiled artifacts (context.json, tofino.bin) to SDE_INSTALL
make -C "$BUILD_DIR" install
```

**Why `-DP4C` is critical:** Without it, cmake searches `$PATH` for a binary named `p4c`. On this system a system-installed p4c (without TNA support) may be found first, producing errors like `architecture 'tna' is not supported`. The explicit path guarantees the SDE's Tofino-capable compiler is used.

**What the build produces:**

After `make install`, the compiled artifacts are placed under `$SDE_INSTALL/share/tofinopd/prototype5/`:
- `context.json` — maps P4 table/register names to hardware addresses; used by bfrt
- `tofino.bin` — the compiled pipeline binary loaded into the ASIC

**Running the build:**
```bash
export SDE=/home/student/Desktop/open-p4studio
cd /home/student/Desktop/flowlidar/prototype5
./build.sh
```

Success output ends with:
```
[100%] Built target prototype5-tofino
Install the project...
```

---

## 9. Hash Polynomial Reference

### BF Hash Functions

Used by the data plane (stages 0–2) and the Python control plane (`bf_indices()`).

| Array | P4 `CRCPolynomial` parameters | crcmod equivalent |
|-------|-------------------------------|-------------------|
| `bf_0` | `poly=0x04C11DB7, rev=true, init=0xFFFFFFFF, residue=0xFFFFFFFF` | `mkCrcFun(0x104C11DB7, rev=True, initCrc=0x00000000, xorOut=0xFFFFFFFF)` |
| `bf_1` | `poly=0x04C11DB7, rev=false, init=0xFFFFFFFF, residue=0xFFFFFFFF` | `mkCrcFun(0x104C11DB7, rev=False, initCrc=0x00000000, xorOut=0xFFFFFFFF)` |
| `bf_2` | `poly=0x1EDC6F41, rev=true, init=0xFFFFFFFF, residue=0xFFFFFFFF` | `mkCrcFun(0x11EDC6F41, rev=True, initCrc=0x00000000, xorOut=0xFFFFFFFF)` |

Index range: `result & 0x1FFFF` → [0, 131071]

### CMS Hash Functions

Used by the data plane (stage 6) and the Python control plane (`cms_indices()`).

| Row | P4 `CRCPolynomial` parameters | crcmod equivalent |
|-----|-------------------------------|-------------------|
| `cms_0` | `poly=0xA833982B, rev=true, init=0xFFFFFFFF, residue=0xFFFFFFFF` | `mkCrcFun(0x1A833982B, rev=True, initCrc=0x00000000, xorOut=0xFFFFFFFF)` |
| `cms_1` | `poly=0x814141AB, rev=false, init=0x00000000, residue=0x00000000` | `mkCrcFun(0x1814141AB, rev=False, initCrc=0x00000000, xorOut=0x00000000)` |
| `cms_2` | `poly=0x04C11DB7, rev=false, init=0x00000000, residue=0xFFFFFFFF` | `mkCrcFun(0x104C11DB7, rev=False, initCrc=0xFFFFFFFF, xorOut=0xFFFFFFFF)` |

Index range: `result & 0x3FF` → [0, 1023]

### Mapping Formula (Empirically Confirmed)

```
crcmod polynomial  =  0x1  +  P4_poly           (prepend the implicit leading CRC bit)
crcmod rev         =  P4_reversed
crcmod initCrc     =  P4_init  XOR  P4_residue
crcmod xorOut      =  P4_residue
```

The `initCrc` XOR follows from the way Tofino applies the residue at the start vs. the end of the computation.

---

## 10. How to Run

### Prerequisites

```bash
# veth interfaces (once per boot)
sudo $SDE_INSTALL/bin/veth_setup.sh

# Python dependencies
pip3 install --upgrade protobuf crcmod numpy scapy
```

### Step 0 — Kill Any Stale Processes

```bash
sudo pkill -f tofino-model; sudo pkill -f bf_switchd; sleep 2
```

### Step 1 — Build (only needed after P4 changes)

```bash
cd /home/student/Desktop/flowlidar/prototype5
./build.sh
```

### Step 2 — Terminal A: Start the Tofino Model

```bash
sudo -E $SDE/run_tofino_model.sh -p prototype5
```

Wait for:
```
Blocking on message from CPU
```

### Step 3 — Terminal B: Start switchd

```bash
sudo -E $SDE/run_switchd.sh -p prototype5
```

Wait for:
```
bfruntime gRPC server started on 0.0.0.0:50052
```

### Step 4 — Terminal B: Configure Tables (at the bfshell prompt)

```
bfrt_python /home/student/Desktop/flowlidar/prototype5/setup_table.py
```

Expected output:
```
IPv4 LPM entry added: 10.0.0.1/32 -> port 1
tbl_bf1: entry (b0=1) -> run_bf1
tbl_bf2: entry (b0=1, b1=1) -> run_bf2
tbl_cms_0: entry (1,1,1) -> do_cms_inc_0
tbl_cms_1: entry (1,1,1) -> do_cms_inc_1
tbl_cms_2: entry (1,1,1) -> do_cms_inc_2

Setup complete. Run control_plane.py to receive flow digests and CMS reports.
```

### Step 5 — Terminal C: Start the Control Plane

```bash
python3 /home/student/Desktop/flowlidar/prototype5/control_plane.py --epoch 30
```

Expected output:
```
========================================================================
  FlowLiDAR Prototype 5 — Control Plane (Equation Solver)
  Connecting to localhost:50052 ...
  Epoch length : 30.0s
========================================================================
Connected. Waiting for packets...
```

### Step 6 — Terminal D: Send Test Packets

```bash
sudo python3 /home/student/Desktop/flowlidar/prototype5/test_packet.py
```

As packets arrive, Terminal C prints digest notifications in real time:
```
[   1] NEW FLOW  10.1.0.1:1000 -> 10.0.0.1:80  TCP  (digest #1)
[   2] NEW FLOW  10.1.0.2:2000 -> 10.0.0.1:80  TCP  (digest #1)
...
[  15] NEW FLOW  10.1.0.6:6000 -> 10.0.0.1:53  UDP  (digest #2)
```

### Step 7 — Read the Epoch Report (after 30 s or press Ctrl-C)

```
========================================================================
  EPOCH 1 END  —  6 flows detected by BF
========================================================================
  Reading CMS registers...
  Reading BF registers (targeted)...

  --- Algorithm 4: BF preprocessing ---
  10.1.0.4:4000->10.0.0.1:443 TCP  bf=(1,1,0)  -> exact=2 (digest only)
  10.1.0.5:5000->10.0.0.1:53  UDP  bf=(1,1,0)  -> exact=2 (digest only)
  10.1.0.6:6000->10.0.0.1:53  UDP  bf=(1,1,0)  -> exact=2 (digest only)
  Flows resolved by Alg4: 3  Flows remaining for CMS: 3

  --- Algorithm 5: CMS preprocessing ---
  10.1.0.3:3000->10.0.0.1:80  TCP  CMS=0  -> exact=3 (digest only)
  Flows resolved by Alg5: 1  Flows remaining for solver: 2

  --- Equation solver (Ax=b, 6x2 system) ---
  rank=2  n=2  load=0.002
  System uniquely determined. Residual=0.0000

  Flow                                         Digests  CMS/Solve  Total  Method
  -------------------------------------------- -------  ---------  -----  ------
  10.1.0.1:1000 -> 10.0.0.1:80 TCP                   3          9     12  solver
  10.1.0.2:2000 -> 10.0.0.1:80 TCP                   3          3      6  solver
  10.1.0.3:3000 -> 10.0.0.1:80 TCP                   3          0      3    alg5
  10.1.0.4:4000 -> 10.0.0.1:443 TCP                  2          0      2    alg4
  10.1.0.5:5000 -> 10.0.0.1:53 UDP                   2          0      2    alg4
  10.1.0.6:6000 -> 10.0.0.1:53 UDP                   2          0      2    alg4

  Flows reported: 6/6

  Clearing BF + CMS registers for next epoch...
========================================================================
```

### Manual Epoch Reset

To clear BF + CMS without waiting for the timer (useful when debugging):
```
bfrt_python /home/student/Desktop/flowlidar/prototype5/reset_epoch.py
```

### BF Register Debug (run before the epoch timer clears registers)

```bash
python3 /home/student/Desktop/flowlidar/prototype5/debug_bf.py
```

---

## 11. Understanding the Test Results

### Per-Flow Trace Through the Pipeline

**Flow D, E, F — 2 packets each:**

| Packet # | BF state before | Action | BF state after | Digest? | CMS? |
|----------|----------------|--------|----------------|---------|------|
| 1 | (0, 0, 0) | run_bf0 sets bf_0; skip_bf1 (b0=0); skip_bf2 (b0=0) | (1, 0, 0) | b0=0 → YES (#1) | no |
| 2 | (1, 0, 0) | run_bf0 finds bf_0=1; run_bf1 sets bf_1 (b0=1); skip_bf2 (b1=0) | (1, 1, 0) | b1=0 → YES (#2) | no |

At epoch end: bf_2=0 → Algorithm 4: count = digest_count = **2**. Exact.

**Flow C — 3 packets (= k):**

| Packet # | BF state before | b0/b1/b2 returned | Digest? | CMS? |
|----------|----------------|-------------------|---------|------|
| 1 | (0,0,0) | b0=0 | YES (#1) | no |
| 2 | (1,0,0) | b0=1, b1=0 | YES (#2) | no |
| 3 | (1,1,0) | b0=1, b1=1, b2=0 | YES (#3) | no (b2 was 0 → (1,1,0) not (1,1,1)) |

At epoch end: bf=(1,1,1) — all bits set (the last packet set bf_2). Algorithm 4 passes it (all 1). CMS=0 because no packet ever had b0=b1=b2=1 at the time of CMS evaluation. Algorithm 5: count = digest_count = **3**. Exact.

**Flow A — 12 packets, Flow B — 6 packets:**

Both get 3 digests (packets 1–3 each set one BF bit and trigger a digest). Packet 4 onward finds all three BF bits already 1, so tbl_cms_0/1/2 fire with `do_cms_inc_*`. By epoch end:
- CMS(A) = 12 - 3 = **9** increments
- CMS(B) = 6 - 3 = **3** increments

The equation solver builds a 6×2 system (3 equations per flow × 2 flows = 6 rows, 2 unknown counts). With no hash collisions, rank=2=n. Solution: x_A=9, x_B=3. Totals: 3+9=**12**, 3+3=**6**. Exact.

### System Parameters

| Parameter | Value |
|-----------|-------|
| BF arrays (k) | 3 |
| BF cells per array (m) | 131,072 (2^17) |
| BF total memory | 48 KB |
| CMS rows (k) | 3 |
| CMS cells per row (m) | 1,024 (2^10) |
| CMS counter width | 16 bits (max 65,535/epoch) |
| CMS total memory | 6 KB |
| Exact-solve threshold | load factor < 0.918 → < 942 flows in C_final per epoch |
| gRPC address | localhost:50052 |
| Switch port mapping | port 0 ↔ veth0/veth1, port 1 ↔ veth2/veth3 |
