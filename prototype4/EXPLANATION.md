# Prototype 4 — Complete Technical Explanation

This document explains every line of `prototype4.p4` in precise detail.
It is written for someone who will be asked about it in a thesis defence or meeting.

---

## Table of Contents

1. [What Problem Does This Solve?](#1-what-problem-does-this-solve)
2. [P4 and TNA — The Basics](#2-p4-and-tna--the-basics)
3. [Data Structures Declared](#3-data-structures-declared)
4. [Parser — Reading the Packet](#4-parser--reading-the-packet)
5. [Ingress Control — The Pipeline](#5-ingress-control--the-pipeline)
   - [Step 0: Port Extraction](#step-0-port-extraction)
   - [Step 1: IPv4 LPM Forwarding](#step-1-ipv4-lpm-forwarding)
   - [Step 2: BF Hash Indices (Stages 0–2)](#step-2-bf-hash-indices-stages-02)
   - [Step 3: Lazy BF Check-and-Set (Stages 3–5)](#step-3-lazy-bf-check-and-set-stages-35)
   - [Step 4: Digest Decision](#step-4-digest-decision)
   - [Step 5: CMS Hash + Conditional Increment (Stages 6–9)](#step-5-cms-hash--conditional-increment-stages-69)
6. [Deparser — Sending the Digest](#6-deparser--sending-the-digest)
7. [Control Plane — Collecting Results](#7-control-plane--collecting-results)
8. [Per-Packet Walkthrough](#8-per-packet-walkthrough)
9. [Why These Design Choices?](#9-why-these-design-choices)
10. [Key Numbers to Remember](#10-key-numbers-to-remember)

---

## 1. What Problem Does This Solve?

FlowLiDAR measures **how many packets each network flow sent** during a time window (epoch).

A **flow** = unique 5-tuple: (src IP, dst IP, protocol, src port, dst port).

The challenge: a 100 Gbps link can have millions of flows per second. You cannot keep a hash table of every flow in slow memory — you need to do this **at line rate in hardware**.

The solution in Prototype 4 is **Algorithm 2 (Lazy Updates BF)** from the paper:

- A **Bloom Filter (BF)** tracks which flows have been seen, using 3 bits of persistent memory per flow (spread across 3 arrays).
- A **Count-Min Sketch (CMS)** counts packets for flows that have been seen more than k=3 times.
- The control plane combines both to estimate the total packet count per flow.

**Key insight of Algorithm 2 vs Algorithm 1:**
- Algorithm 1 (Prototype 2): sets all 3 BF bits on the first packet, sends 1 digest per flow.
- Algorithm 2 (Prototype 4): sets 1 BF bit per packet, sends up to 3 digests per flow (one per packet until all bits are set). This lets the control plane count the first k packets exactly (via digest count), and the CMS counts the rest.

---

## 2. P4 and TNA — The Basics

**P4** is a domain-specific language for programming the data plane of network switches. It describes how packets are parsed, matched, and acted upon.

**TNA (Tofino Native Architecture)** is Intel's specific architecture for the Tofino ASIC. Key facts:
- 12 ingress MAU (Match-Action Unit) stages
- Each stage can do one match-action table lookup
- A `RegisterAction.execute()` occupies **one full stage exclusively** (stateful ALU constraint)
- Packet processing is **pipelined**: all stages run in parallel on different packets; a single packet flows through all stages sequentially
- No loops, no recursion, no dynamic memory allocation — everything is fixed at compile time

**The pipeline structure:**
```
Packet → [Parser] → [Stage 0] → [Stage 1] → ... → [Stage 11] → [Deparser] → Out
```

---

## 3. Data Structures Declared

### 3.1 `flow_digest_t` struct

```p4
struct flow_digest_t {
    bit<32> src_addr;
    bit<32> dst_addr;
    bit<8>  protocol;
    bit<16> src_port;
    bit<16> dst_port;
}
```

This defines the **shape of the message** sent from the data plane to the control plane when a new flow (or new BF bit) is detected.

- `bit<32>` = 32-bit unsigned integer (IPv4 address)
- `bit<8>` = 8-bit (IP protocol number: 6=TCP, 17=UDP)
- `bit<16>` = 16-bit (port numbers)
- Total: 104 bits = 13 bytes per digest message

### 3.2 `metadata_t` struct

```p4
struct metadata_t {
    bit<16> src_port;
    bit<16> dst_port;
    bit<17> idx0; bit<17> idx1; bit<17> idx2;
    bit<1>  b0;   bit<1>  b1;   bit<1>  b2;
    bit<10> cms_idx0; bit<10> cms_idx1; bit<10> cms_idx2;
}
```

Metadata is **per-packet scratch space** that persists across all pipeline stages for a single packet. It is not stored between packets — it lives only while the packet moves through the pipeline.

- `src_port`, `dst_port` — copied from TCP/UDP header so later stages can access them without re-parsing
- `idx0`–`idx2` — 17-bit BF hash indices computed in stages 0–2, used in stages 3–5
- `b0`–`b2` — results of the BF check-and-set, used in stages 4–9 for conditional logic
- `cms_idx0`–`cms_idx2` — 10-bit CMS indices computed in stage 6, used in stages 7–9

**Why 17 bits for BF indices?** Because the BF has 2^17 = 131,072 cells. You need exactly 17 bits to address any cell.

**Why 10 bits for CMS indices?** Because each CMS row has 2^10 = 1,024 cells.

### 3.3 Register Arrays

```p4
Register<bit<1>, bit<17>>(131072) bf_0;
Register<bit<1>, bit<17>>(131072) bf_1;
Register<bit<1>, bit<17>>(131072) bf_2;
```

`Register<ValueType, IndexType>(size)` declares a persistent memory array on the ASIC.

- `bit<1>` value = one bit per cell (0 = not seen, 1 = seen)
- `bit<17>` index = 17-bit address (can address 0 to 131071)
- `131072` = number of cells = 2^17
- Three separate arrays because each needs a different hash function

This memory **persists between packets** and **across clock cycles** — this is the "state" of the Bloom Filter. It is reset at epoch boundaries by `reset_epoch.py`.

```p4
Register<bit<16>, bit<10>>(1024) cms_0;
Register<bit<16>, bit<10>>(1024) cms_1;
Register<bit<16>, bit<10>>(1024) cms_2;
```

- `bit<16>` value = 16-bit counter (counts up to 65,535 packets per CMS cell)
- 1,024 cells per row, 3 rows = Count-Min Sketch

---

## 4. Parser — Reading the Packet

The parser is a **state machine** that reads bytes off the wire and fills header structs.

```p4
state start {
    tofino_parser.apply(pkt, ig_intr_md);  // read Tofino-specific metadata (port, timestamp)
    transition parse_ethernet;              // unconditionally go to next state
}
```

`tofino_parser.apply()` is a built-in that reads the intrinsic metadata prepended by the Tofino hardware before the actual packet bytes.

```p4
state parse_ethernet {
    pkt.extract(hdr.ethernet);                      // read 14 bytes into hdr.ethernet
    transition select(hdr.ethernet.ether_type) {    // branch based on EtherType field
        ETHERTYPE_IPV4 : parse_ipv4;                // 0x0800 → it's IPv4
        default        : accept;                    // anything else → stop parsing
    }
}
```

`pkt.extract(hdr.X)` — reads exactly `sizeof(hdr.X)` bytes from the packet and fills the struct. After this, `hdr.ethernet.isValid()` returns true.

`transition select(field) { value : state; }` — like a switch-case. Reads the field and jumps to the matching state.

```p4
state parse_ipv4 {
    pkt.extract(hdr.ipv4);
    transition select(hdr.ipv4.protocol) {
        IP_PROTOCOLS_TCP : parse_tcp;    // protocol == 6
        IP_PROTOCOLS_UDP : parse_udp;    // protocol == 17
        default          : accept;       // ICMP etc → stop, no ports available
    }
}

state parse_tcp { pkt.extract(hdr.tcp); transition accept; }
state parse_udp { pkt.extract(hdr.udp); transition accept; }
```

After the parser finishes, all successfully extracted headers have `isValid() == true`. Headers that were not extracted (e.g., `hdr.tcp` for a UDP packet) have `isValid() == false`.

---

## 5. Ingress Control — The Pipeline

The `apply {}` block defines the **order of operations** for each packet. This is where the algorithm runs.

### Step 0: Port Extraction

```p4
ig_md.src_port = 0;
ig_md.dst_port = 0;
if (hdr.tcp.isValid()) {
    ig_md.src_port = hdr.tcp.src_port;
    ig_md.dst_port = hdr.tcp.dst_port;
} else if (hdr.udp.isValid()) {
    ig_md.src_port = hdr.udp.src_port;
    ig_md.dst_port = hdr.udp.dst_port;
}
```

Ports live in different structs depending on protocol. We copy them into metadata so all later stages can use a single field regardless of TCP vs UDP. For protocols with no ports (ICMP, etc.), ports stay 0 — they still contribute to the 5-tuple hash, just as zero.

---

### Step 1: IPv4 LPM Forwarding

```p4
table ipv4_lpm {
    key            = { hdr.ipv4.dst_addr : lpm; }  // match destination IP
    actions        = { hit; miss; }
    size           = 1024;                          // up to 1024 routing entries
    default_action = miss();                        // no match → drop
}
```

`lpm` = **Longest Prefix Match** — the same algorithm real routers use. Match `10.0.0.0/24` before `10.0.0.0/8`. The control plane installs routes via `setup_table.py`.

```p4
action hit(PortId_t dst_port) {
    ig_tm_md.ucast_egress_port = dst_port;  // tell traffic manager: send out this port
    hdr.ipv4.ttl = hdr.ipv4.ttl - 1;       // decrement TTL (standard router behaviour)
    ig_dprsr_md.drop_ctl = 0x0;            // 0 = do not drop
}

action miss() {
    ig_dprsr_md.drop_ctl = 0x1;            // 1 = drop packet
}
```

`ig_tm_md` = ingress traffic manager metadata. Setting `ucast_egress_port` tells the hardware which physical port to send the packet out.
`ig_dprsr_md.drop_ctl` = deparser drop control. Setting bit 0 to 1 causes the packet to be dropped before it leaves.

**Important:** forwarding happens independently of the BF/CMS logic. Every IPv4 packet is forwarded (if a route exists) regardless of whether it's a new or known flow.

---

### Step 2: BF Hash Indices (Stages 0–2)

#### Why separate stages?

Tofino has a **32-bit immediate pathway limit per stage**: the hash computation output path is 32 bits wide. Since we need 3 × 17 = 51 bits of hash output, we must spread across 3 stages.

#### Hash function declaration

```p4
CRCPolynomial<bit<32>>(
    32w0x04C11DB7,   // polynomial: the bit pattern defining the CRC variant
    true,            // reversed: process bits LSB-first (reflected)
    false,           // MSB in data: not used here
    false,           // extended: not used here
    32w0xFFFFFFFF,   // initial value: CRC register starts at all-ones
    32w0xFFFFFFFF    // final XOR: XOR the result with this before output
) poly0;

Hash<bit<17>>(HashAlgorithm_t.CUSTOM, poly0) hash0;
```

`CRCPolynomial` — configures a CRC engine on the Tofino hardware. Each instance uses a different polynomial so the three hash functions produce **independent outputs** for the same input. If two hash functions were correlated, two BF bits might always land on the same cell, defeating the purpose of having 3 arrays.

`Hash<bit<17>>` — declares the hash unit. The type parameter `bit<17>` means the output is truncated/folded to 17 bits, giving a value in range [0, 131071].

#### Why different polynomials?

| Hash | Polynomial | Reversed |
|------|-----------|---------|
| hash0 (BF) | `0x04C11DB7` (CRC32) | yes |
| hash1 (BF) | `0x04C11DB7` (CRC32) | **no** |
| hash2 (BF) | `0x1EDC6F41` (CRC32C) | yes |

Same polynomial with different bit-reversal produces statistically independent outputs. Different polynomial (`CRC32C`) adds further independence. The goal is that for any given 5-tuple, the three indices are unlikely to collide.

#### Computing the index

```p4
action compute_idx0() {
    ig_md.idx0 = hash0.get({
        hdr.ipv4.src_addr,   // 32 bits
        hdr.ipv4.dst_addr,   // 32 bits
        hdr.ipv4.protocol,   // 8 bits
        ig_md.src_port,      // 16 bits
        ig_md.dst_port       // 16 bits
    });                      // total: 104 bits fed into CRC engine → 17-bit output
}
```

`hash0.get({...})` — concatenates the listed fields in order and feeds them through the CRC engine. The result is a 17-bit index into the BF array.

#### The table wrapper

```p4
@stage(0) table tbl_hash0 {
    actions        = { compute_idx0; }
    default_action = compute_idx0;
    size           = 1;
}
```

`@stage(0)` — compiler directive forcing this table into stage 0. Without this, the compiler might place it in any stage and the register actions later might end up in the wrong order.

`default_action = compute_idx0` — this table has **no key**. It always runs the same action on every packet. The table is just a wrapper to place the hash computation in a specific stage.

`size = 1` — one entry (the default). No match logic needed.

---

### Step 3: Lazy BF Check-and-Set (Stages 3–5)

This is the core of Algorithm 2. The algorithm says: for each packet, find the first BF bit that is 0, set it, and stop.

In hardware you cannot loop, so this is implemented as **three sequential conditional table lookups**.

#### RegisterAction — the atomic read-modify-write

```p4
RegisterAction<bit<1>, bit<17>, bit<1>>(bf_0) bf_check_set_0 = {
//             ↑value type  ↑index type  ↑return type   ↑which register
    void apply(inout bit<1> val, out bit<1> rv) {
        rv  = val;   // FIRST: copy old value to return variable
        val = 1;     // THEN:  overwrite with 1
    }
};
```

`RegisterAction<V, I, R>(reg)` — a stateful operation on register `reg`. Parameters:
- `V` = type of the stored value (`bit<1>`)
- `I` = type of the index (`bit<17>`)
- `R` = type of the return value (`bit<1>`)

`inout bit<1> val` — the actual cell content. `inout` means you can both read and write it. This is the BF cell at the index you provide.

`out bit<1> rv` — the return value sent back to the pipeline. `out` means write-only inside the action.

**Atomicity guarantee:** the hardware executes `rv = val; val = 1;` as a single indivisible operation. No two packets can interleave within this — packet B cannot read `val` between packet A's read and write. This prevents race conditions where two packets both think they are first.

`bf_check_set_0.execute(ig_md.idx0)` — runs the RegisterAction at cell `idx0`. Returns `rv` which is the **old value** of that cell.

#### Stage 3 — bf_0 always runs

```p4
action run_bf0() {
    ig_md.b0 = bf_check_set_0.execute(ig_md.idx0);
}

@stage(3) table tbl_bf0 {
    actions        = { run_bf0; }
    default_action = run_bf0;   // no key → always fires
    size           = 1;
}
```

After stage 3:
- `ig_md.b0 = 0` → cell was empty → this flow has not set bf_0 before → new/partial flow
- `ig_md.b0 = 1` → cell was already set → this flow has been seen at least once before

The cell is now set to 1 regardless. Even if `b0=0` (new), we set it so the next packet will see `b0=1`.

#### Stage 4 — bf_1 only if b0 == 1

```p4
action run_bf1()  { ig_md.b1 = bf_check_set_1.execute(ig_md.idx1); }
action skip_bf1() { ig_md.b1 = 0; }

@stage(4) table tbl_bf1 {
    key            = { ig_md.b0 : exact; }   // match on the result of stage 3
    actions        = { run_bf1; skip_bf1; }
    default_action = skip_bf1;               // if no match → skip
    size           = 2;
}
```

`setup_table.py` installs **one entry** into this table: `b0 = 1 → run_bf1`.

The table lookup result:

| `b0` from stage 3 | Table match? | Action | `b1` result |
|---|---|---|---|
| 0 | No (default) | `skip_bf1()` | `b1 = 0` |
| 1 | Yes | `run_bf1()` | `b1 = actual register read` |

**Why skip when b0==0?**
If `b0==0`, we found a zero in bf_0. Algorithm 2 says: set the first zero and **stop**. We already set bf_0 (the `val=1` in the RegisterAction ran regardless). There is no need to check bf_1 or bf_2. We skip them.

**Why set `b1=0` in skip_bf1?**
Because the digest logic in the next step checks `if (b1==0) → send digest`. By setting `b1=0` in the skip case, we ensure the digest is triggered correctly — a skipped stage means we didn't fully see the flow, so it is still a "new" event worth reporting.

#### Stage 5 — bf_2 only if b0==1 AND b1==1

```p4
action run_bf2()  { ig_md.b2 = bf_check_set_2.execute(ig_md.idx2); }
action skip_bf2() { ig_md.b2 = 0; }

@stage(5) table tbl_bf2 {
    key            = { ig_md.b0 : exact; ig_md.b1 : exact; }
    actions        = { run_bf2; skip_bf2; }
    default_action = skip_bf2;
    size           = 4;   // 2^2 possible combinations of b0,b1
}
```

`setup_table.py` installs **one entry**: `b0=1, b1=1 → run_bf2`.

| `b0` | `b1` | Action | Meaning |
|---|---|---|---|
| 0 | 0 | skip (default) | Stopped at bf_0 |
| 0 | 1 | skip (default) | Impossible (b1 would be 0 if b0 was 0) |
| 1 | 0 | skip (default) | Stopped at bf_1 |
| 1 | 1 | `run_bf2()` | Both previous bits set → check bf_2 |

After all three stages, the state of the flow (across all packets) is:

| Flow packet # | b0 | b1 | b2 | What happened |
|---|---|---|---|---|
| 1st packet | 0 | 0 | 0 | bf_0 was empty; set it; skipped bf_1, bf_2 |
| 2nd packet | 1 | 0 | 0 | bf_0 was full; bf_1 was empty; set it; skipped bf_2 |
| 3rd packet | 1 | 1 | 0 | bf_0,bf_1 full; bf_2 was empty; set it |
| 4th+ packet | 1 | 1 | 1 | All bits already set; no BF action needed |

---

### Step 4: Digest Decision

```p4
if (ig_md.b0 == 0) { ig_dprsr_md.digest_type = 1; }
if (ig_md.b1 == 0) { ig_dprsr_md.digest_type = 1; }
if (ig_md.b2 == 0) { ig_dprsr_md.digest_type = 1; }
```

`ig_dprsr_md.digest_type = 1` — a signal to the deparser: "pack a digest for this packet". Setting it to 1 triggers the `flow_digest.pack()` call in the deparser.

**Why check all three?**
Because of how the skip actions work:
- If `b0=0` → bf_1 and bf_2 were skipped → `b1=0, b2=0`
- If `b1=0` → bf_2 was skipped → `b2=0`
- If `b2=0` → bf_2 found a zero → new event

So `b0==0 OR b1==0 OR b2==0` is equivalent to "at least one BF bit was zero (or skipped)", which means the flow is new or not fully registered yet. All three checks would independently trigger the digest; the result is the same as checking `(b0 AND b1 AND b2) == 0`.

The control plane receives one digest per "BF registration event" — up to 3 per flow (one per packet until all bits are set). It counts these digests. For a flow with N≤3 packets, the digest count IS the packet count.

---

### Step 5: CMS Hash + Conditional Increment (Stages 6–9)

#### Stage 6 — CMS hash indices (always computed)

```p4
CRCPolynomial<bit<32>>(32w0xA833982B, true, false, false,
                        32w0xFFFFFFFF, 32w0xFFFFFFFF) cms_poly0;
Hash<bit<10>>(HashAlgorithm_t.CUSTOM, cms_poly0) cms_hash0;
// ... cms_poly1, cms_poly2 similarly

action compute_cms_indices() {
    ig_md.cms_idx0 = cms_hash0.get({src, dst, proto, sport, dport});
    ig_md.cms_idx1 = cms_hash1.get({...});
    ig_md.cms_idx2 = cms_hash2.get({...});
}

@stage(6) table tbl_cms_hash {
    actions        = { compute_cms_indices; }
    default_action = compute_cms_indices;
    size           = 1;
}
```

Three **different** CRC polynomials from the BF ones — ensures CMS hashes are independent from each other AND from the BF hashes. A 10-bit output → index in [0, 1023].

The CMS hashes are always computed (no key, always fires), even for packets that won't use them. This is fine — computing a hash doesn't modify any state.

#### Stages 7–9 — Conditional CMS increment

```p4
action do_cms_inc_0() { cms_inc_0.execute(ig_md.cms_idx0); }
action nop_cms_0()    {}   // do nothing

@stage(7) table tbl_cms_0 {
    key            = { ig_md.b0 : exact; ig_md.b1 : exact; ig_md.b2 : exact; }
    actions        = { do_cms_inc_0; nop_cms_0; }
    default_action = nop_cms_0;
    size           = 8;   // 2^3 possible combinations
}
```

`setup_table.py` installs **one entry** per table: `b0=1, b1=1, b2=1 → do_cms_inc_i`.

All other combinations (7 out of 8) hit the default → `nop` → no increment.

The `cms_inc_0` RegisterAction:
```p4
RegisterAction<bit<16>, bit<10>, bit<16>>(cms_0) cms_inc_0 = {
    void apply(inout bit<16> val, out bit<16> rv) {
        val = val + 1;   // increment the counter
        rv  = val;       // return new value (not used)
    }
};
```

This increments the 16-bit counter at cell `cms_idx0`. The CMS has 3 rows; incrementing all 3 at different indices with different hashes is the standard CMS update operation.

**Why CMS only when b0==b1==b2==1?**
Because that means all 3 BF bits were already set — this is at least the 4th packet of this flow. The first 3 are counted exactly via digests. The CMS counts only the excess (packets 4, 5, 6, ...).

At epoch end, the control plane reads all CMS cells and computes:
```
estimate = digest_count + min(cms_row_0[f], cms_row_1[f], cms_row_2[f])
```
The `min` is the Count-Min Sketch estimator (it underestimates collisions). The `digest_count` adds back the first ≤3 packets that were counted exactly.

---

## 6. Deparser — Sending the Digest

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
    pkt.emit(hdr);   // serialize all valid headers back into a packet
}
```

`Digest<T>()` — a hardware mechanism that sends a small fixed-size message from the data plane to the control plane CPU. It uses the **CPU path** (a special internal port), not the regular packet forwarding path.

`flow_digest.pack({...})` — fills the digest struct with field values and queues it for sending.

`pkt.emit(hdr)` — writes all `isValid()` headers back into the outgoing packet byte stream. Headers that were never extracted (or were invalidated) are not emitted.

The digest arrives at the control plane via gRPC as a notification, processed by `learn_get('flow_digest')` in `control_plane.py`.

---

## 7. Control Plane — Collecting Results

`control_plane.py` runs on the switch CPU and:

1. Connects to `bf_switchd` via gRPC on port 50052
2. Registers to receive `flow_digest` notifications
3. For each digest received, increments `digest_count[5-tuple]`
4. At each epoch boundary (timer-based):
   - Reads all 3 CMS register arrays via bfrt
   - For each flow in the digest table, looks up its 3 CMS cells
   - Computes: `estimate = digest_count + min(cms_0[idx], cms_1[idx], cms_2[idx])`
   - Prints the epoch report

**Example with 12 packets on flow A (all going to same 5-tuple):**
- Packets 1, 2, 3: each sets one BF bit → 3 digests → `digest_count = 3`
- Packets 4–12: all bits set → 9 CMS increments → `min(cms_rows) ≈ 9`
- Estimate: `3 + 9 = 12` ✓

---

## 8. Per-Packet Walkthrough

### Flow X, Packet 1 (completely new flow)

| Stage | Action | Result |
|---|---|---|
| 0–2 | Compute idx0, idx1, idx2 | e.g., idx0=42, idx1=1337, idx2=5000 |
| 3 | `bf_check_set_0.execute(42)` | bf_0[42] was 0 → b0=0, set to 1 |
| 4 | `tbl_bf1`: key=b0=0 → no match → `skip_bf1` | b1=0 |
| 5 | `tbl_bf2`: key=(b0=0,b1=0) → no match → `skip_bf2` | b2=0 |
| — | `b0==0` → `digest_type=1` | Digest queued |
| 6 | Compute CMS indices | cms_idx0, cms_idx1, cms_idx2 |
| 7–9 | key=(b0=0,b1=0,b2=0) → no match → `nop` | CMS unchanged |
| — | Forward packet | Sent to egress port |
| Deparser | `digest_type==1` → `flow_digest.pack(5-tuple)` | Digest sent to CPU |

### Flow X, Packet 2

| Stage | Action | Result |
|---|---|---|
| 0–2 | Same indices (same 5-tuple → same hash) | idx0=42, idx1=1337, idx2=5000 |
| 3 | `bf_check_set_0.execute(42)` | bf_0[42] was 1 → b0=1, still 1 |
| 4 | `tbl_bf1`: key=b0=1 → match → `run_bf1` | bf_1[1337] was 0 → b1=0, set to 1 |
| 5 | `tbl_bf2`: key=(b0=1,b1=0) → no match → `skip_bf2` | b2=0 |
| — | `b1==0` → `digest_type=1` | Digest queued |
| 7–9 | key=(1,0,0) → no match → `nop` | CMS unchanged |
| Deparser | Digest sent | digest_count[X] = 2 |

### Flow X, Packet 4 (and all subsequent)

| Stage | Action | Result |
|---|---|---|
| 3 | bf_0[42] was 1 → b0=1 | |
| 4 | bf_1[1337] was 1 → b1=1 | |
| 5 | bf_2[5000] was 1 → b2=1 | |
| — | b0=b1=b2=1 → no digest | |
| 7–9 | key=(1,1,1) → match → `do_cms_inc_i` | CMS incremented |

---

## 9. Why These Design Choices?

### Why use tables for conditional RegisterAction execution?

In P4/TNA you **cannot** write:
```p4
if (ig_md.b0 == 1) {
    ig_md.b1 = bf_check_set_1.execute(ig_md.idx1);  // ILLEGAL
}
```

A RegisterAction must be called from inside a table action. The only way to make it conditional is to put it in a table with a key — if the key matches, the action (with the RegisterAction) fires; otherwise the default action fires.

### Why 3 BF arrays and not 4?

The paper specifies k=4, but Tofino 1 has only 12 stages. With k=4:
- 4 hash stages + 4 BF stages + 1 CMS hash stage + 3 CMS stages = 12 stages exactly
- Zero slack — impossible to compile in practice

With k=3:
- 3 + 3 + 1 + 3 = 10 stages used, 2 free
- Compiles reliably, leaves room for future additions

### Why is the CMS hash always computed even when not used?

Because there is no cost to computing it (no register write, no side effects), and separating it into its own stage is required anyway (32-bit pathway limit). Making it conditional would waste a stage on a control table.

### Why `size=8` for CMS conditional tables?

`8 = 2^3` = all possible combinations of the 3 binary keys (b0, b1, b2). The table needs to be large enough to hold all possible inputs, even though only one entry is installed.

---

## 10. Key Numbers to Remember

| Parameter | Value | Why |
|---|---|---|
| BF arrays (k) | 3 | Stage budget |
| BF cells per array (m) | 131,072 = 2^17 | Paper §5 |
| BF index width | 17 bits | log2(131072) |
| CMS rows | 3 | One per stage |
| CMS cells per row | 1,024 = 2^10 | |
| CMS index width | 10 bits | log2(1024) |
| CMS counter width | 16 bits | Max 65,535 packets |
| Stages used | 10 (0–9) | 2 free |
| Digests per flow | ≤ 3 | One per BF bit set |
| CMS starts at packet | 4 | After all 3 bits set |
| Total estimate formula | digest_count + min(CMS rows) | |

### Expected output for test scenario (6 flows, A=12, B=6, C=3, D=2, E=2, F=2 packets):

| Flow | Packets | Digests | CMS increments | Estimate |
|---|---|---|---|---|
| A | 12 | 3 | 9 | 3+9=12 ✓ |
| B | 6 | 3 | 3 | 3+3=6 ✓ |
| C | 3 | 3 | 0 | 3+0=3 ✓ |
| D | 2 | 2 | 0 | 2+0=2 ✓ |
| E | 2 | 2 | 0 | 2+0=2 ✓ |
| F | 2 | 2 | 0 | 2+0=2 ✓ |
