/* =============================================================================
 * prototype3.p4 — FlowLiDAR Prototype 3
 *
 * Goal: Add a Count-Min Sketch (CMS) for per-flow packet counting in the data
 * plane. Together with the Bloom Filter from Prototype 2, this completes the
 * full data-plane side of Algorithm 1 from the FlowLiDAR paper.
 *
 * What this prototype adds over prototype2:
 *   - 3 CMS register arrays (3 x 1K x 16-bit counters = 6 KB)
 *   - 3 independent CRC hash functions for CMS indexing (distinct from BF)
 *   - Combined CMS hash stage: 3 × 10-bit = 30 bits ≤ 32-bit pathway limit
 *   - Unconditional atomic increment RegisterActions, one per row
 *
 * Algorithm 1 (Standard BF — now complete) from the paper:
 *   For each packet with FlowID x:
 *     1. Query element x in the BF (check all k bits)
 *     2. If Negative:
 *          - Add x to the BF (set all k bits)
 *          - Send FlowID to control plane via digest
 *     3. Send x to packet counting block (CMS) ← NEW IN THIS PROTOTYPE
 *
 * Stage allocation (12 ingress MAU stages on Tofino 1):
 *
 *   Stage 0  : tbl_hash0       — BF idx0  (17-bit, CRC32 standard)
 *   Stage 1  : tbl_hash1       — BF idx1  (17-bit, CRC32/BZIP2)
 *   Stage 2  : tbl_hash2       — BF idx2  (17-bit, CRC32C/Castagnoli)
 *   Stage 3  : bf_check_set_0  — BF row 0 RegisterAction (check-and-set)
 *   Stage 4  : bf_check_set_1  — BF row 1 RegisterAction
 *   Stage 5  : bf_check_set_2  — BF row 2 RegisterAction
 *   Stage 6  : tbl_cms_hash    — CMS idx0/idx1/idx2 combined action
 *                                3 × 10 bits = 30 bits ≤ 32-bit limit ✓
 *   Stage 7  : cms_inc_0       — CMS row 0 RegisterAction (increment)
 *   Stage 8  : cms_inc_1       — CMS row 1 RegisterAction
 *   Stage 9  : cms_inc_2       — CMS row 2 RegisterAction
 *   Stage 10 : free
 *   Stage 11 : free
 *
 * CMS parameters:
 *   k = 3 rows  (matches BF k for implementation symmetry)
 *   m = 1024 entries per row  (10-bit addressing, 2^10 = 1K)
 *   counter width = 16 bits  (saturates at 65535 packets per epoch)
 *
 * CMS hash polynomials (distinct from BF polynomials to maximise independence):
 *   cms_poly0 : CRC32D      (0xA833982B, reversed)
 *   cms_poly1 : CRC32/Q     (0x814141AB, not reversed)
 *   cms_poly2 : CRC32/POSIX (0x04C11DB7, not reversed, init=0, xor=0xFFFFFFFF)
 *
 * COMPILER NOTE — Combined CMS hash:
 *   If the compiler rejects tbl_cms_hash with "immediate pathway bits exceeded",
 *   split compute_cms_indices() into two tables:
 *     @stage(6) table tbl_cms_hash01 { action: compute cms_idx0 + cms_idx1 (20 bits) }
 *     @stage(7) table tbl_cms_hash2  { action: compute cms_idx2 (10 bits) }
 *   Then shift cms_inc_0/1/2 to stages 8, 9, 10 accordingly.
 *
 * At epoch end the control plane (control_plane.py):
 *   1. Collects all FlowIDs received via digest during the epoch
 *   2. Reads cms_0, cms_1, cms_2 register arrays via bfrt gRPC
 *   3. For each known flow, recomputes CMS hash indices and takes min(row0, row1, row2)
 *   4. Reports per-flow packet count estimates
 *   5. Clears BF (bf_0..2) and CMS (cms_0..2) registers for the next epoch
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
// (unchanged from prototype2)
// ---------------------------------------------------------------------------
struct flow_digest_t {
    bit<32> src_addr;
    bit<32> dst_addr;
    bit<8>  protocol;
    bit<16> src_port;
    bit<16> dst_port;
}

// ---------------------------------------------------------------------------
// Metadata
// ---------------------------------------------------------------------------
struct metadata_t {
    // Transport ports copied from TCP/UDP header (0 for other protocols).
    bit<16> src_port;
    bit<16> dst_port;

    // BF hash indices — 17-bit each, one per stage (32-bit pathway limit).
    bit<17> idx0;
    bit<17> idx1;
    bit<17> idx2;

    // CMS hash indices — 10-bit each (1K entries per row, 2^10 = 1024).
    // All three fit in one stage: 3 × 10 = 30 bits ≤ 32-bit immediate limit.
    bit<10> cms_idx0;
    bit<10> cms_idx1;
    bit<10> cms_idx2;
}

// ---------------------------------------------------------------------------
// Ingress Parser (unchanged from prototype2)
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
// Ingress Deparser (unchanged from prototype2)
// ---------------------------------------------------------------------------
control SwitchIngressDeparser(
        packet_out pkt,
        inout header_t hdr,
        in metadata_t ig_md,
        in ingress_intrinsic_metadata_for_deparser_t ig_dprsr_md) {

    Digest<flow_digest_t>() flow_digest;
    Checksum() ipv4_checksum;

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

    // =========================================================================
    // BLOOM FILTER (unchanged from prototype2)
    // k=3 independent arrays of 128K bits each (2^17 = 131072 entries × 1 bit)
    // Total BF memory: 3 × 128 Kbits = 48 KB
    // =========================================================================

    Register<bit<1>, bit<17>>(131072) bf_0;
    Register<bit<1>, bit<17>>(131072) bf_1;
    Register<bit<1>, bit<17>>(131072) bf_2;

    // Atomic check-and-set: returns old value (0=absent, 1=present), sets to 1.
    RegisterAction<bit<1>, bit<17>, bit<1>>(bf_0) bf_check_set_0 = {
        void apply(inout bit<1> val, out bit<1> rv) {
            rv  = val;
            val = 1;
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

    // BF hash functions — 3 different CRC32 polynomials, 17-bit output.
    CRCPolynomial<bit<32>>(32w0x04C11DB7,
                           true, false, false,
                           32w0xFFFFFFFF, 32w0xFFFFFFFF) poly0;  // CRC32 standard
    Hash<bit<17>>(HashAlgorithm_t.CUSTOM, poly0) hash0;

    CRCPolynomial<bit<32>>(32w0x04C11DB7,
                           false, false, false,
                           32w0xFFFFFFFF, 32w0xFFFFFFFF) poly1;  // CRC32/BZIP2
    Hash<bit<17>>(HashAlgorithm_t.CUSTOM, poly1) hash1;

    CRCPolynomial<bit<32>>(32w0x1EDC6F41,
                           true, false, false,
                           32w0xFFFFFFFF, 32w0xFFFFFFFF) poly2;  // CRC32C/Castagnoli
    Hash<bit<17>>(HashAlgorithm_t.CUSTOM, poly2) hash2;

    // BF hash tables — one per stage to stay within 32-bit immediate pathway.
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

    @stage(0) table tbl_hash0 {
        actions        = { compute_idx0; }
        default_action = compute_idx0;
        size           = 1;
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

    // =========================================================================
    // COUNT-MIN SKETCH (NEW)
    //
    // k=3 rows × 1024 entries × 16-bit counters = 6 KB total.
    // Each packet increments one counter per row based on the flow's CMS index.
    // Per-flow estimate at epoch end: min(cms_0[h0], cms_1[h1], cms_2[h2]).
    //
    // Hash polynomials chosen to be distinct from BF polynomials (poly0-2):
    //   cms_poly0 : CRC32D         — 0xA833982B, reversed
    //   cms_poly1 : CRC32/Q        — 0x814141AB, not reversed
    //   cms_poly2 : CRC32/POSIX    — 0x04C11DB7, not reversed, init=0
    //
    // The control plane replicates these using crcmod to look up CMS values.
    // See control_plane.py for the exact Python-side CRC parameters.
    // =========================================================================

    Register<bit<16>, bit<10>>(1024) cms_0;
    Register<bit<16>, bit<10>>(1024) cms_1;
    Register<bit<16>, bit<10>>(1024) cms_2;

    // Increment counter and return new value.
    // Return value is intentionally discarded in apply() — only side effect matters.
    RegisterAction<bit<16>, bit<10>, bit<16>>(cms_0) cms_inc_0 = {
        void apply(inout bit<16> val, out bit<16> rv) {
            val = val + 1;
            rv  = val;
        }
    };
    RegisterAction<bit<16>, bit<10>, bit<16>>(cms_1) cms_inc_1 = {
        void apply(inout bit<16> val, out bit<16> rv) {
            val = val + 1;
            rv  = val;
        }
    };
    RegisterAction<bit<16>, bit<10>, bit<16>>(cms_2) cms_inc_2 = {
        void apply(inout bit<16> val, out bit<16> rv) {
            val = val + 1;
            rv  = val;
        }
    };

    // CMS hash functions — 3 distinct CRC polynomials, 10-bit output (1K entries).
    CRCPolynomial<bit<32>>(32w0xA833982B,
                           true, false, false,
                           32w0xFFFFFFFF, 32w0xFFFFFFFF) cms_poly0;  // CRC32D
    Hash<bit<10>>(HashAlgorithm_t.CUSTOM, cms_poly0) cms_hash0;

    CRCPolynomial<bit<32>>(32w0x814141AB,
                           false, false, false,
                           32w0x00000000, 32w0x00000000) cms_poly1;  // CRC32/Q
    Hash<bit<10>>(HashAlgorithm_t.CUSTOM, cms_poly1) cms_hash1;

    CRCPolynomial<bit<32>>(32w0x04C11DB7,
                           false, false, false,
                           32w0x00000000, 32w0xFFFFFFFF) cms_poly2;  // CRC32/POSIX
    Hash<bit<10>>(HashAlgorithm_t.CUSTOM, cms_poly2) cms_hash2;

    // Combined CMS hash action — all 3 indices computed in one stage.
    // 3 × 10 = 30 bits fits within the 32-bit immediate pathway limit.
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

    @stage(6)
    table tbl_cms_hash {
        actions        = { compute_cms_indices; }
        default_action = compute_cms_indices;
        size           = 1;
    }

    // =========================================================================
    // IPv4 LPM forwarding table (unchanged from prototype1/2)
    // =========================================================================

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

    // =========================================================================
    // Apply
    // =========================================================================
    apply {
        // Step 1: Copy transport ports to metadata (0 for non-TCP/UDP).
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
            // Step 2: Forward via IPv4 LPM.
            ipv4_lpm.apply();

            // Step 3: Compute BF hash indices (stages 0, 1, 2).
            tbl_hash0.apply();
            tbl_hash1.apply();
            tbl_hash2.apply();

            // Step 4: Atomically check-and-set BF arrays (stages 3, 4, 5).
            bit<1> b0 = bf_check_set_0.execute(ig_md.idx0);
            bit<1> b1 = bf_check_set_1.execute(ig_md.idx1);
            bit<1> b2 = bf_check_set_2.execute(ig_md.idx2);

            // Step 5: If ANY BF bit was 0 → new flow → trigger digest.
            // Three separate conditions required (Tofino: each must compare
            // one runtime value to a constant; ANDing them is "too complex").
            if (b0 == 0) { ig_dprsr_md.digest_type = 1; }
            if (b1 == 0) { ig_dprsr_md.digest_type = 1; }
            if (b2 == 0) { ig_dprsr_md.digest_type = 1; }

            // Step 6: Compute all 3 CMS hash indices in one stage (stage 6).
            tbl_cms_hash.apply();

            // Step 7: Increment CMS counters (stages 7, 8, 9).
            // Unconditional — every IPv4 packet is counted (Algorithm 1, line 9:
            // "Send x to packet counting block"). RegisterActions cannot be
            // called conditionally in TNA.
            cms_inc_0.execute(ig_md.cms_idx0);
            cms_inc_1.execute(ig_md.cms_idx1);
            cms_inc_2.execute(ig_md.cms_idx2);

        } else {
            miss();
        }

        // Bypass egress pipeline.
        ig_tm_md.bypass_egress = 1w1;
    }
}

// ---------------------------------------------------------------------------
// Top-level pipeline (unchanged)
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
