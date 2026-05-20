/* =============================================================================
 * lazy_bf262k_cms2048.p4 — FlowLiDAR Lazy BF (262 K cells) + wider CMS
 *
 * Variant of cpp_lazy_bf262k_cms64x1024/lazy_bf262k.p4 with the
 * Count-Min Sketch widened from 1024 cols/sub-sketch to 2048
 * cols/sub-sketch. Keeps 64 sub-sketches and 16-bit counters.
 *
 *   BF  : 3 × 262144 × 1 bit   (unchanged from lazy_bf262k.p4)
 *   CMS : 3 × 131072 × 16 bit  (64 sub-sketches × 2048 cols)
 *
 * Index widths:
 *   - cms register index: bit<17>  (was bit<16>)
 *   - col_hash output   : bit<11>  (was bit<10>)
 *   - sketchlet_offset  : bit<17>, bucket_id << 11, masked to bits [16:11]
 *
 * Goal: drop per-bucket flow count under kColsPerRow=2048 so the exact
 * Gauss-Jordan path and Algorithm 6 finally fire on real CAIDA traffic.
 * (At 64 × 1024 every bucket was >1024 and the solver always fell back
 *  to min(cms_rows).)
 *
 * Stage allocation (12 ingress MAU stages on Tofino 1):
 *
 *   Stage 0  : tbl_hash0       — BF idx0 (18-bit)
 *   Stage 1  : tbl_hash1       — BF idx1 (18-bit)
 *   Stage 2  : tbl_hash2       — BF idx2 (18-bit)
 *   Stage 3  : tbl_bf0         — always: check-and-set bf_0
 *   Stage 4  : tbl_bf1         — conditional on b0==1
 *   Stage 5  : tbl_bf2         — conditional on b0==1 AND b1==1
 *   Stage 6  : tbl_master_hash — master hash (6-bit, sub-sketch id)
 *   Stage 7  : tbl_col_hash_*  — column hashes (3 × 11-bit)
 *   Stage 8  : tbl_cms_idx_*   — CMS indices (3 × 17-bit add)
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

#include "../common/headers.p4"
#include "../common/util.p4"

struct flow_digest_t {
    bit<32> src_addr;
    bit<32> dst_addr;
    bit<8>  protocol;
    bit<16> src_port;
    bit<16> dst_port;
}

struct metadata_t {
    bit<16> src_port;
    bit<16> dst_port;

    // BF hash indices — 18-bit each (262144 cells per row).
    bit<18> idx0;
    bit<18> idx1;
    bit<18> idx2;

    bit<1> b0;
    bit<1> b1;
    bit<1> b2;

    // Sub-sketch offset — bucket_id << 11, in bits [16:11] of a bit<17>.
    bit<17> sketchlet_offset;

    // Column hashes — bit<11> matches Hash<bit<11>> output (2048 cols).
    bit<11> col_hash_0;
    bit<11> col_hash_1;
    bit<11> col_hash_2;

    // CMS indices — 17-bit each (131072 cells per row).
    bit<17> cms_idx0;
    bit<17> cms_idx1;
    bit<17> cms_idx2;
}

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

control SwitchIngress(
        inout header_t hdr,
        inout metadata_t ig_md,
        in    ingress_intrinsic_metadata_t ig_intr_md,
        in    ingress_intrinsic_metadata_from_parser_t ig_prsr_md,
        inout ingress_intrinsic_metadata_for_deparser_t ig_dprsr_md,
        inout ingress_intrinsic_metadata_for_tm_t ig_tm_md) {

    // =========================================================================
    // BLOOM FILTER — Lazy Updates, 3 × 262144 cells (unchanged from lazy_bf262k)
    // =========================================================================

    Register<bit<1>, bit<18>>(262144) bf_0;
    Register<bit<1>, bit<18>>(262144) bf_1;
    Register<bit<1>, bit<18>>(262144) bf_2;

    RegisterAction<bit<1>, bit<18>, bit<1>>(bf_0) bf_check_set_0 = {
        void apply(inout bit<1> val, out bit<1> rv) {
            rv  = val;
            val = 1;
        }
    };
    RegisterAction<bit<1>, bit<18>, bit<1>>(bf_1) bf_check_set_1 = {
        void apply(inout bit<1> val, out bit<1> rv) {
            rv  = val;
            val = 1;
        }
    };
    RegisterAction<bit<1>, bit<18>, bit<1>>(bf_2) bf_check_set_2 = {
        void apply(inout bit<1> val, out bit<1> rv) {
            rv  = val;
            val = 1;
        }
    };

    CRCPolynomial<bit<32>>(32w0x04C11DB7,
                           true, false, false,
                           32w0xFFFFFFFF, 32w0xFFFFFFFF) poly0;
    Hash<bit<18>>(HashAlgorithm_t.CUSTOM, poly0) hash0;

    CRCPolynomial<bit<32>>(32w0x04C11DB7,
                           false, false, false,
                           32w0xFFFFFFFF, 32w0xFFFFFFFF) poly1;
    Hash<bit<18>>(HashAlgorithm_t.CUSTOM, poly1) hash1;

    CRCPolynomial<bit<32>>(32w0x1EDC6F41,
                           true, false, false,
                           32w0xFFFFFFFF, 32w0xFFFFFFFF) poly2;
    Hash<bit<18>>(HashAlgorithm_t.CUSTOM, poly2) hash2;

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
    // LAZY BF TABLES
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
    action skip_bf1() {
        ig_md.b1 = 0;
    }
    @stage(4) table tbl_bf1 {
        key            = { ig_md.b0 : exact; }
        actions        = { run_bf1; skip_bf1; }
        default_action = skip_bf1;
        size           = 2;
    }

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
        size           = 4;
    }

    // =========================================================================
    // MASTER HASH — selects which of 64 sub-sketches this flow belongs to.
    // Hash<bit<17>>; pick upper 6 bits via & 17w0x1F800 (bits [16:11]).
    // =========================================================================

    CRCPolynomial<bit<32>>(32w0xF4ACFB13,
                           true, false, false,
                           32w0xFFFFFFFF, 32w0xFFFFFFFF) master_poly;
    Hash<bit<17>>(HashAlgorithm_t.CUSTOM, master_poly) master_hash_fn;

    action compute_master_offset() {
        ig_md.sketchlet_offset = master_hash_fn.get(
            {hdr.ipv4.src_addr, hdr.ipv4.dst_addr,
             hdr.ipv4.protocol,
             ig_md.src_port, ig_md.dst_port}) & 17w0x1F800;
    }

    @stage(6) table tbl_master_hash {
        actions        = { compute_master_offset; }
        default_action = compute_master_offset;
        size           = 1;
    }

    // =========================================================================
    // COUNT-MIN SKETCH — 64 sub-sketches × 2048 cols × 16-bit per row.
    // Final index = master_hash :: col_hash  (6 high bits :: 11 low bits)
    // =========================================================================

    Register<bit<16>, bit<17>>(131072) cms_0;
    Register<bit<16>, bit<17>>(131072) cms_1;
    Register<bit<16>, bit<17>>(131072) cms_2;

    RegisterAction<bit<16>, bit<17>, bit<16>>(cms_0) cms_inc_0 = {
        void apply(inout bit<16> val, out bit<16> rv) {
            val = val + 1;
            rv  = val;
        }
    };
    RegisterAction<bit<16>, bit<17>, bit<16>>(cms_1) cms_inc_1 = {
        void apply(inout bit<16> val, out bit<16> rv) {
            val = val + 1;
            rv  = val;
        }
    };
    RegisterAction<bit<16>, bit<17>, bit<16>>(cms_2) cms_inc_2 = {
        void apply(inout bit<16> val, out bit<16> rv) {
            val = val + 1;
            rv  = val;
        }
    };

    // CMS column hashes — bit<11> output (2048 cols per sub-sketch).
    CRCPolynomial<bit<32>>(32w0xA833982B,
                           true, false, false,
                           32w0xFFFFFFFF, 32w0xFFFFFFFF) cms_poly0;
    Hash<bit<11>>(HashAlgorithm_t.CUSTOM, cms_poly0) cms_hash0;

    CRCPolynomial<bit<32>>(32w0x814141AB,
                           false, false, false,
                           32w0x00000000, 32w0x00000000) cms_poly1;
    Hash<bit<11>>(HashAlgorithm_t.CUSTOM, cms_poly1) cms_hash1;

    CRCPolynomial<bit<32>>(32w0x04C11DB7,
                           false, false, false,
                           32w0x00000000, 32w0xFFFFFFFF) cms_poly2;
    Hash<bit<11>>(HashAlgorithm_t.CUSTOM, cms_poly2) cms_hash2;

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

    // Stage 8: combine sketchlet_offset with each col hash (17-bit add).
    action compute_cms_idx_0() {
        ig_md.cms_idx0 = ig_md.sketchlet_offset + (bit<17>)ig_md.col_hash_0;
    }
    action compute_cms_idx_1() {
        ig_md.cms_idx1 = ig_md.sketchlet_offset + (bit<17>)ig_md.col_hash_1;
    }
    action compute_cms_idx_2() {
        ig_md.cms_idx2 = ig_md.sketchlet_offset + (bit<17>)ig_md.col_hash_2;
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

Pipeline(
    SwitchIngressParser(),
    SwitchIngress(),
    SwitchIngressDeparser(),
    EmptyEgressParser(),
    EmptyEgress(),
    EmptyEgressDeparser()
) pipe;

Switch(pipe) main;
