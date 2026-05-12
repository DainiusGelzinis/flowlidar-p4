/* =============================================================================
 * prototype9.p4 — FlowLiDAR Prototype 9 (Traditional BF baseline)
 *
 * Drops the lazy-update BF logic in favour of a TRADITIONAL Bloom Filter:
 *   - All 3 BF rows are checked-and-set unconditionally on every packet.
 *   - A digest is sent if ANY of the 3 bits was 0 before this packet.
 *   - Each visible flow therefore generates exactly ONE digest.
 *
 * Bloom Filter sized to match prototype5 / prototype6:
 *   3 × 131072 × 1 bit (17-bit indexing)
 *
 * The point of this prototype is to get a clean baseline:
 *   - No conditional table chain, no lazy semantics.
 *   - Algorithms 4 / 5 (digest-count classification) collapse — every visible
 *     flow becomes a "solver candidate" because we cannot distinguish 1-pkt
 *     from N-pkt flows from BF state alone.
 *   - CMS sub-sketches unchanged from prototype6/7 (64 × 1024 × 16 bit).
 *
 * Stage allocation (12 ingress MAU stages on Tofino 1):
 *
 *   Stage 0  : tbl_hash0       — BF idx0 (17-bit, CRC-32)
 *   Stage 1  : tbl_hash1       — BF idx1 (17-bit, CRC-32D)
 *   Stage 2  : tbl_hash2       — BF idx2 (17-bit, CRC-32C)
 *   Stage 3  : tbl_bf0         — always: check-and-set bf_0
 *   Stage 4  : tbl_bf1         — always: check-and-set bf_1
 *   Stage 5  : tbl_bf2         — always: check-and-set bf_2
 *   Stage 6  : tbl_master_hash — master hash (6-bit, sub-sketch id)
 *   Stage 7  : tbl_col_hash_*  — column hashes (3 × 10-bit)
 *   Stage 8  : tbl_cms_idx_*   — CMS indices (3 × 16-bit add)
 *   Stage 9  : tbl_cms_0       — conditional CMS row 0 increment
 *   Stage 10 : tbl_cms_1       — conditional CMS row 1 increment
 *   Stage 11 : tbl_cms_2       — conditional CMS row 2 increment
 * ============================================================================= */

#include <core.p4>
#if __TARGET_TOFINO__ == 3
#include <t3na.p4>
#elif __TARGET_TOFINO__ == 2
#include <t2na.p4>
#else
#include <tna.p4>
#endif

#include "../../common/headers.p4"
#include "../../common/util.p4"

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
// Metadata
// ---------------------------------------------------------------------------
struct metadata_t {
    // Transport ports copied from TCP/UDP header.
    bit<16> src_port;
    bit<16> dst_port;

    // BF hash indices — 17-bit each (131072 cells per row, prototype5 size).
    bit<17> idx0;
    bit<17> idx1;
    bit<17> idx2;

    // BF check-and-set results. With traditional BF all 3 are always populated.
    bit<1> b0;
    bit<1> b1;
    bit<1> b2;

    // Sub-sketch offset — already shifted: bucket_id << 10, in [15:10].
    bit<16> sketchlet_offset;

    // Column hashes — bit<10> matches Hash<bit<10>> output.
    bit<10> col_hash_0;
    bit<10> col_hash_1;
    bit<10> col_hash_2;

    // CMS indices — 16-bit each, computed per-table to stay within pathway limits.
    bit<16> cms_idx0;
    bit<16> cms_idx1;
    bit<16> cms_idx2;
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
    // BLOOM FILTER — Traditional check-and-set (no lazy updates)
    // =========================================================================

    Register<bit<1>, bit<17>>(131072) bf_0;
    Register<bit<1>, bit<17>>(131072) bf_1;
    Register<bit<1>, bit<17>>(131072) bf_2;

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

    CRCPolynomial<bit<32>>(32w0x04C11DB7,
                           true, false, false,
                           32w0xFFFFFFFF, 32w0xFFFFFFFF) poly0;
    Hash<bit<17>>(HashAlgorithm_t.CUSTOM, poly0) hash0;

    // Three distinct CRC-32 generator polynomials (poly0/1/2 do NOT share
    // the same generator — only differing bit reversal would leave them
    // correlated).
    CRCPolynomial<bit<32>>(32w0xA833982B,
                           true, false, false,
                           32w0xFFFFFFFF, 32w0xFFFFFFFF) poly1;
    Hash<bit<17>>(HashAlgorithm_t.CUSTOM, poly1) hash1;

    CRCPolynomial<bit<32>>(32w0x1EDC6F41,
                           true, false, false,
                           32w0xFFFFFFFF, 32w0xFFFFFFFF) poly2;
    Hash<bit<17>>(HashAlgorithm_t.CUSTOM, poly2) hash2;

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
    // TRADITIONAL BF TABLES — every packet runs check-and-set on all 3 rows
    // =========================================================================

    action run_bf0() {
        ig_md.b0 = bf_check_set_0.execute(ig_md.idx0);
    }
    @stage(3) table tbl_bf0 {
        actions        = { run_bf0; }
        default_action = run_bf0;
        size           = 1;
    }

    action run_bf1() {
        ig_md.b1 = bf_check_set_1.execute(ig_md.idx1);
    }
    @stage(4) table tbl_bf1 {
        actions        = { run_bf1; }
        default_action = run_bf1;
        size           = 1;
    }

    action run_bf2() {
        ig_md.b2 = bf_check_set_2.execute(ig_md.idx2);
    }
    @stage(5) table tbl_bf2 {
        actions        = { run_bf2; }
        default_action = run_bf2;
        size           = 1;
    }

    // =========================================================================
    // MASTER HASH — selects which of 64 sub-sketches this flow belongs to
    // Distinct polynomial from BF and CMS column hashes.
    // =========================================================================

    CRCPolynomial<bit<32>>(32w0xF4ACFB13,
                           true, false, false,
                           32w0xFFFFFFFF, 32w0xFFFFFFFF) master_poly;
    // Use Hash<bit<16>> and mask to bits [15:10] so the bucket_id lives in
    // the upper 6 bits — no cast/multiply needed (avoids PHV/compiler issues).
    Hash<bit<16>>(HashAlgorithm_t.CUSTOM, master_poly) master_hash_fn;

    action compute_master_offset() {
        ig_md.sketchlet_offset = master_hash_fn.get(
            {hdr.ipv4.src_addr, hdr.ipv4.dst_addr,
             hdr.ipv4.protocol,
             ig_md.src_port, ig_md.dst_port}) & 16w0xFC00;
    }

    @stage(6) table tbl_master_hash {
        actions        = { compute_master_offset; }
        default_action = compute_master_offset;
        size           = 1;
    }

    // =========================================================================
    // COUNT-MIN SKETCH — sub-sketch partitioned (64 × 1024 cells per row)
    // Final index = master_hash :: col_hash  (6 high bits :: 10 low bits)
    // =========================================================================

    Register<bit<16>, bit<16>>(65536) cms_0;
    Register<bit<16>, bit<16>>(65536) cms_1;
    Register<bit<16>, bit<16>>(65536) cms_2;

    RegisterAction<bit<16>, bit<16>, bit<16>>(cms_0) cms_inc_0 = {
        void apply(inout bit<16> val, out bit<16> rv) {
            val = val + 1;
            rv  = val;
        }
    };
    RegisterAction<bit<16>, bit<16>, bit<16>>(cms_1) cms_inc_1 = {
        void apply(inout bit<16> val, out bit<16> rv) {
            val = val + 1;
            rv  = val;
        }
    };
    RegisterAction<bit<16>, bit<16>, bit<16>>(cms_2) cms_inc_2 = {
        void apply(inout bit<16> val, out bit<16> rv) {
            val = val + 1;
            rv  = val;
        }
    };

    // CMS column hashes — bit<10> output (30 bits total fits 32-bit pathway).
    CRCPolynomial<bit<32>>(32w0xA833982B,
                           true, false, false,
                           32w0xFFFFFFFF, 32w0xFFFFFFFF) cms_poly0;
    Hash<bit<10>>(HashAlgorithm_t.CUSTOM, cms_poly0) cms_hash0;

    CRCPolynomial<bit<32>>(32w0x814141AB,
                           false, false, false,
                           32w0x00000000, 32w0x00000000) cms_poly1;
    Hash<bit<10>>(HashAlgorithm_t.CUSTOM, cms_poly1) cms_hash1;

    CRCPolynomial<bit<32>>(32w0x04C11DB7,
                           false, false, false,
                           32w0x00000000, 32w0xFFFFFFFF) cms_poly2;
    Hash<bit<10>>(HashAlgorithm_t.CUSTOM, cms_poly2) cms_hash2;

    // Stage 7: 3 column hashes — one per table to keep each table's
    // immediate-pathway use under the 32-bit limit.
    action compute_col_hash_0() {
        ig_md.col_hash_0 = cms_hash0.get(
            {hdr.ipv4.src_addr, hdr.ipv4.dst_addr,
             hdr.ipv4.protocol,
             ig_md.src_port, ig_md.dst_port});
    }
    action compute_col_hash_1() {
        ig_md.col_hash_1 = cms_hash1.get(
            {hdr.ipv4.src_addr, hdr.ipv4.dst_addr,
             hdr.ipv4.protocol,
             ig_md.src_port, ig_md.dst_port});
    }
    action compute_col_hash_2() {
        ig_md.col_hash_2 = cms_hash2.get(
            {hdr.ipv4.src_addr, hdr.ipv4.dst_addr,
             hdr.ipv4.protocol,
             ig_md.src_port, ig_md.dst_port});
    }

    @stage(7) table tbl_col_hash_0 {
        actions        = { compute_col_hash_0; }
        default_action = compute_col_hash_0;
        size           = 1;
    }
    @stage(7) table tbl_col_hash_1 {
        actions        = { compute_col_hash_1; }
        default_action = compute_col_hash_1;
        size           = 1;
    }
    @stage(7) table tbl_col_hash_2 {
        actions        = { compute_col_hash_2; }
        default_action = compute_col_hash_2;
        size           = 1;
    }

    // Stage 8: combine sketchlet_offset with each col hash — split into
    // 3 separate tables so each only does ONE 16-bit add (avoids 48-bit limit).
    action compute_cms_idx_0() {
        ig_md.cms_idx0 = ig_md.sketchlet_offset + (bit<16>)ig_md.col_hash_0;
    }
    action compute_cms_idx_1() {
        ig_md.cms_idx1 = ig_md.sketchlet_offset + (bit<16>)ig_md.col_hash_1;
    }
    action compute_cms_idx_2() {
        ig_md.cms_idx2 = ig_md.sketchlet_offset + (bit<16>)ig_md.col_hash_2;
    }

    @stage(8) table tbl_cms_idx_0 {
        actions        = { compute_cms_idx_0; }
        default_action = compute_cms_idx_0;
        size           = 1;
    }
    @stage(8) table tbl_cms_idx_1 {
        actions        = { compute_cms_idx_1; }
        default_action = compute_cms_idx_1;
        size           = 1;
    }
    @stage(8) table tbl_cms_idx_2 {
        actions        = { compute_cms_idx_2; }
        default_action = compute_cms_idx_2;
        size           = 1;
    }

    action do_cms_inc_0() { cms_inc_0.execute(ig_md.cms_idx0); }
    action nop_cms_0()    {}
    @stage(9) table tbl_cms_0 {
        key            = { ig_md.b0 : exact; ig_md.b1 : exact; ig_md.b2 : exact; }
        actions        = { do_cms_inc_0; nop_cms_0; }
        default_action = nop_cms_0;
        size           = 8;
    }

    action do_cms_inc_1() { cms_inc_1.execute(ig_md.cms_idx1); }
    action nop_cms_1()    {}
    @stage(10) table tbl_cms_1 {
        key            = { ig_md.b0 : exact; ig_md.b1 : exact; ig_md.b2 : exact; }
        actions        = { do_cms_inc_1; nop_cms_1; }
        default_action = nop_cms_1;
        size           = 8;
    }

    action do_cms_inc_2() { cms_inc_2.execute(ig_md.cms_idx2); }
    action nop_cms_2()    {}
    @stage(11) table tbl_cms_2 {
        key            = { ig_md.b0 : exact; ig_md.b1 : exact; ig_md.b2 : exact; }
        actions        = { do_cms_inc_2; nop_cms_2; }
        default_action = nop_cms_2;
        size           = 8;
    }

    // =========================================================================
    // IPv4 LPM forwarding table
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
            ipv4_lpm.apply();

            tbl_hash0.apply();
            tbl_hash1.apply();
            tbl_hash2.apply();

            tbl_bf0.apply();
            tbl_bf1.apply();
            tbl_bf2.apply();

            if (ig_md.b0 == 0) { ig_dprsr_md.digest_type = 1; }
            if (ig_md.b1 == 0) { ig_dprsr_md.digest_type = 1; }
            if (ig_md.b2 == 0) { ig_dprsr_md.digest_type = 1; }

            tbl_master_hash.apply();
            tbl_col_hash_0.apply();
            tbl_col_hash_1.apply();
            tbl_col_hash_2.apply();
            tbl_cms_idx_0.apply();
            tbl_cms_idx_1.apply();
            tbl_cms_idx_2.apply();

            tbl_cms_0.apply();
            tbl_cms_1.apply();
            tbl_cms_2.apply();

        } else {
            miss();
        }

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
