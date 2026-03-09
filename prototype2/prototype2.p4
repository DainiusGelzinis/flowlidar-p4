/* =============================================================================
 * prototype2.p4 — FlowLiDAR Prototype 2
 *
 * Goal: Implement the Standard Bloom Filter (Algorithm 1 from the paper) in
 * the data plane. Detect new flows and notify the control plane via a digest.
 *
 * What this prototype adds over prototype1:
 *   - 4 independent BF register arrays (4 x 128K bits = 64 KB total)
 *   - 4 CRC hash functions with different polynomials
 *   - Atomic check-and-set RegisterActions
 *   - Digest to notify the control plane on new flow detection
 *
 * Algorithm 1 (Standard BF) from the paper:
 *   For each packet with FlowID x:
 *     1. Query element x in the BF (check all k bits)
 *     2. If Negative (any bit == 0):
 *          - Add x to the BF (set all k bits to 1)
 *          - Send FlowID to the control plane via digest
 *     3. Send x to the packet counting block (CMS — added in prototype3)
 *
 * BF parameters (from paper, Section 5):
 *   k = 4 arrays, m = 128K bits per array
 *
 * Future prototypes:
 *   - Prototype 3: Count-Min Sketch (packet counting)
 *   - Prototype 4: Control-plane epoch + equation solver
 *   - Prototype 5: Lazy Bloom Filter (Algorithm 2)
 * ============================================================================= */

#include <core.p4>
#if __TARGET_TOFINO__ == 3
#include <t3na.p4>
#elif __TARGET_TOFINO__ == 2
#include <t2na.p4>
#else
#include <tna.p4>
#endif

#include "../common/headers.p4"
#include "../common/util.p4"

// ---------------------------------------------------------------------------
// Digest struct — 5-tuple sent to control plane for each new flow
// ---------------------------------------------------------------------------
struct flow_digest_t {
    bit<32> src_addr;
    bit<32> dst_addr;
    bit<8>  protocol;
    bit<16> src_port;
    bit<16> dst_port;
}

// ---------------------------------------------------------------------------
// Metadata — carries per-packet state between parser, control, deparser
// ---------------------------------------------------------------------------
struct metadata_t {
    // Ports copied from TCP or UDP header so the BF and digest can use them
    // regardless of transport protocol.
    bit<16> src_port;
    bit<16> dst_port;
    // BF hash indices — computed in separate stages to stay within the
    // 32-bit immediate-pathway limit per stage (17 bits each).
    bit<17> idx0;
    bit<17> idx1;
    bit<17> idx2;
    bit<17> idx3;
}

// ---------------------------------------------------------------------------
// Ingress Parser
// ---------------------------------------------------------------------------
parser SwitchIngressParser(
        packet_in pkt,
        out header_t hdr,
        out metadata_t ig_md,
        out ingress_intrinsic_metadata_t ig_intr_md) {

    TofinoIngressParser() tofino_parser;

    state start {
        tofino_parser.apply(pkt, ig_intr_md);
        transition parse_ethernet;
    }

    state parse_ethernet {
        pkt.extract(hdr.ethernet);
        transition select(hdr.ethernet.ether_type) {
            ETHERTYPE_IPV4 : parse_ipv4;
            default        : accept;
        }
    }

    state parse_ipv4 {
        pkt.extract(hdr.ipv4);
        transition select(hdr.ipv4.protocol) {
            IP_PROTOCOLS_TCP : parse_tcp;
            IP_PROTOCOLS_UDP : parse_udp;
            default          : accept;
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

// ---------------------------------------------------------------------------
// Ingress Deparser
// Sends the flow digest to the control plane if digest_type == 1.
// Recomputes the IPv4 checksum after TTL decrement.
// ---------------------------------------------------------------------------
control SwitchIngressDeparser(
        packet_out pkt,
        inout header_t hdr,
        in metadata_t ig_md,
        in ingress_intrinsic_metadata_for_deparser_t ig_dprsr_md) {

    Digest<flow_digest_t>() flow_digest;
    Checksum() ipv4_checksum;

    apply {
        // Send 5-tuple to control plane if this is a new flow.
        if (ig_dprsr_md.digest_type == 1) {
            flow_digest.pack({
                hdr.ipv4.src_addr,
                hdr.ipv4.dst_addr,
                hdr.ipv4.protocol,
                ig_md.src_port,
                ig_md.dst_port
            });
        }

        // Recompute IPv4 checksum after TTL decrement.
        hdr.ipv4.hdr_checksum = ipv4_checksum.update({
            hdr.ipv4.version,
            hdr.ipv4.ihl,
            hdr.ipv4.diffserv,
            hdr.ipv4.total_len,
            hdr.ipv4.identification,
            hdr.ipv4.flags,
            hdr.ipv4.frag_offset,
            hdr.ipv4.ttl,
            hdr.ipv4.protocol,
            hdr.ipv4.src_addr,
            hdr.ipv4.dst_addr
        });

        pkt.emit(hdr);
    }
}

// ---------------------------------------------------------------------------
// Ingress Control
// ---------------------------------------------------------------------------
control SwitchIngress(
        inout header_t hdr,
        inout metadata_t ig_md,
        in    ingress_intrinsic_metadata_t ig_intr_md,
        in    ingress_intrinsic_metadata_from_parser_t ig_prsr_md,
        inout ingress_intrinsic_metadata_for_deparser_t ig_dprsr_md,
        inout ingress_intrinsic_metadata_for_tm_t ig_tm_md) {

    // -------------------------------------------------------------------------
    // Bloom Filter — 4 independent arrays of 128K bits (k=4, m=128K)
    //
    // Each array is indexed by a different CRC hash of the 5-tuple.
    // RegisterAction atomically reads the old value and sets the bit to 1.
    // Returned value: 0 = bit was unset (flow not seen on this array)
    //                 1 = bit was already set (flow seen on this array)
    // -------------------------------------------------------------------------

    Register<bit<1>, bit<17>>(131072) bf_0;
    Register<bit<1>, bit<17>>(131072) bf_1;
    Register<bit<1>, bit<17>>(131072) bf_2;
    Register<bit<1>, bit<17>>(131072) bf_3;

    RegisterAction<bit<1>, bit<17>, bit<1>>(bf_0) bf_check_set_0 = {
        void apply(inout bit<1> val, out bit<1> rv) {
            rv  = val;  // return old value (0 = absent, 1 = present)
            val = 1;    // always mark as present
        }
    };

    RegisterAction<bit<1>, bit<17>, bit<1>>(bf_1) bf_check_set_1 = {
        void apply(inout bit<1> val, out bit<1> rv) {
            rv  = val;
            val = 1;
        }
    };

    RegisterAction<bit<1>, bit<17>, bit<1>>(bf_2) bf_check_set_2 = {
        void apply(inout bit<1> val, out bit<1> rv) {
            rv  = val;
            val = 1;
        }
    };

    RegisterAction<bit<1>, bit<17>, bit<1>>(bf_3) bf_check_set_3 = {
        void apply(inout bit<1> val, out bit<1> rv) {
            rv  = val;
            val = 1;
        }
    };

    // -------------------------------------------------------------------------
    // Hash functions — 4 different CRC32 polynomials for independence
    // Each produces a 17-bit index into its BF array (2^17 = 131072 entries).
    // -------------------------------------------------------------------------

    // CRC32 (standard)
    CRCPolynomial<bit<32>>(32w0x04C11DB7,
                           true,           // reversed
                           false,          // use msb
                           false,          // extended
                           32w0xFFFFFFFF,  // init
                           32w0xFFFFFFFF   // xor
                           ) poly0;
    Hash<bit<17>>(HashAlgorithm_t.CUSTOM, poly0) hash0;

    // CRC32/BZIP2 (same polynomial, not reversed)
    CRCPolynomial<bit<32>>(32w0x04C11DB7,
                           false,
                           false,
                           false,
                           32w0xFFFFFFFF,
                           32w0xFFFFFFFF
                           ) poly1;
    Hash<bit<17>>(HashAlgorithm_t.CUSTOM, poly1) hash1;

    // CRC32C (Castagnoli)
    CRCPolynomial<bit<32>>(32w0x1EDC6F41,
                           true,
                           false,
                           false,
                           32w0xFFFFFFFF,
                           32w0xFFFFFFFF
                           ) poly2;
    Hash<bit<17>>(HashAlgorithm_t.CUSTOM, poly2) hash2;

    // CRC32D
    CRCPolynomial<bit<32>>(32w0xA833982B,
                           true,
                           false,
                           false,
                           32w0xFFFFFFFF,
                           32w0xFFFFFFFF
                           ) poly3;
    Hash<bit<17>>(HashAlgorithm_t.CUSTOM, poly3) hash3;

    // -------------------------------------------------------------------------
    // Hash computation tables — one per stage to stay within the 32-bit
    // immediate-pathway limit.  Each action writes one 17-bit index into
    // metadata; the @stage annotation guarantees a separate MAU stage.
    // -------------------------------------------------------------------------

    action compute_idx0() {
        ig_md.idx0 = hash0.get({hdr.ipv4.src_addr, hdr.ipv4.dst_addr,
                                 hdr.ipv4.protocol,
                                 ig_md.src_port, ig_md.dst_port});
    }
    action compute_idx1() {
        ig_md.idx1 = hash1.get({hdr.ipv4.src_addr, hdr.ipv4.dst_addr,
                                 hdr.ipv4.protocol,
                                 ig_md.src_port, ig_md.dst_port});
    }
    action compute_idx2() {
        ig_md.idx2 = hash2.get({hdr.ipv4.src_addr, hdr.ipv4.dst_addr,
                                 hdr.ipv4.protocol,
                                 ig_md.src_port, ig_md.dst_port});
    }
    action compute_idx3() {
        ig_md.idx3 = hash3.get({hdr.ipv4.src_addr, hdr.ipv4.dst_addr,
                                 hdr.ipv4.protocol,
                                 ig_md.src_port, ig_md.dst_port});
    }

    @stage(1)
    table tbl_hash0 {
        actions     = { compute_idx0; }
        default_action = compute_idx0;
        size        = 1;
    }
    @stage(2)
    table tbl_hash1 {
        actions     = { compute_idx1; }
        default_action = compute_idx1;
        size        = 1;
    }
    @stage(3)
    table tbl_hash2 {
        actions     = { compute_idx2; }
        default_action = compute_idx2;
        size        = 1;
    }
    @stage(4)
    table tbl_hash3 {
        actions     = { compute_idx3; }
        default_action = compute_idx3;
        size        = 1;
    }

    // -------------------------------------------------------------------------
    // IPv4 LPM forwarding table (same as prototype 1)
    // -------------------------------------------------------------------------

    action hit(PortId_t dst_port) {
        ig_tm_md.ucast_egress_port = dst_port;
        hdr.ipv4.ttl = hdr.ipv4.ttl - 1;
        ig_dprsr_md.drop_ctl = 0x0;
    }

    action miss() {
        ig_dprsr_md.drop_ctl = 0x1;
    }

    table ipv4_lpm {
        key = {
            hdr.ipv4.dst_addr : lpm;
        }
        actions = { hit; miss; }
        size           = 1024;
        default_action = miss();
    }

    // -------------------------------------------------------------------------
    // Apply
    // -------------------------------------------------------------------------
    apply {
        // Step 1: Copy transport ports to metadata for use in BF hash and digest.
        // Default to 0 for non-TCP/UDP protocols.
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
            // Step 2: Forward packet.
            ipv4_lpm.apply();

            // Step 3: Compute 4 hash indices, each in its own stage.
            tbl_hash0.apply();
            tbl_hash1.apply();
            tbl_hash2.apply();
            tbl_hash3.apply();

            // Step 4: Atomically check and set each BF array.
            // Execute all 4 unconditionally — RegisterActions cannot be
            // called conditionally in TNA.
            bit<1> b0 = bf_check_set_0.execute(ig_md.idx0);
            bit<1> b1 = bf_check_set_1.execute(ig_md.idx1);
            bit<1> b2 = bf_check_set_2.execute(ig_md.idx2);
            bit<1> b3 = bf_check_set_3.execute(ig_md.idx3);

            // Step 5: If ALL 4 bits were already set → known flow (no action).
            //         If ANY bit was 0 → new flow → trigger digest.
            // Tofino requires each condition to compare one runtime value to a
            // constant, so we use 4 separate checks instead of ANDing them.
            if (b0 == 0) { ig_dprsr_md.digest_type = 1; }
            if (b1 == 0) { ig_dprsr_md.digest_type = 1; }
            if (b2 == 0) { ig_dprsr_md.digest_type = 1; }
            if (b3 == 0) { ig_dprsr_md.digest_type = 1; }
        } else {
            miss();
        }

        // Bypass egress pipeline.
        ig_tm_md.bypass_egress = 1w1;
    }
}

// ---------------------------------------------------------------------------
// Top-level pipeline
// ---------------------------------------------------------------------------
Pipeline(
    SwitchIngressParser(),
    SwitchIngress(),
    SwitchIngressDeparser(),
    EmptyEgressParser(),
    EmptyEgress(),
    EmptyEgressDeparser()
) pipe;

Switch(pipe) main;
