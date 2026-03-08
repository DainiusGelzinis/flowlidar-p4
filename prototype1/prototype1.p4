/* =============================================================================
 * prototype1.p4 — FlowLiDAR Prototype 1
 *
 * Goal: Confirm the build pipeline, Tofino model, and switchd work correctly.
 *
 * What this prototype does:
 *   - Parses Ethernet, IPv4, TCP, and UDP headers
 *   - Forwards IPv4 packets using a longest-prefix-match (LPM) table
 *   - Decrements TTL and recomputes the IPv4 checksum on forwarded packets
 *   - Drops non-IPv4 packets and unmatched IPv4 packets
 *   - Bypasses the egress pipeline (not needed at this stage)
 *
 * Future prototypes will build on this foundation:
 *   - Prototype 2: Bloom Filter (new-flow detection)
 *   - Prototype 3: Count-Min Sketch (packet counting)
 *   - Prototype 4: Control-plane equation solver
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

// User-defined ingress metadata.
// Empty for now; future prototypes add Bloom Filter / CMS state here.
struct metadata_t {}

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
            default        : accept;   // Non-IPv4 — will be dropped in control.
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
// Recomputes the IPv4 checksum after TTL decrement.
// ---------------------------------------------------------------------------
control SwitchIngressDeparser(
        packet_out pkt,
        inout header_t hdr,
        in metadata_t ig_md,
        in ingress_intrinsic_metadata_for_deparser_t ig_intr_dprsr_md) {

    Checksum() ipv4_checksum;

    apply {
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

    // Forward packet out the given port and decrement TTL.
    action hit(PortId_t dst_port) {
        ig_tm_md.ucast_egress_port = dst_port;
        hdr.ipv4.ttl = hdr.ipv4.ttl - 1;
        ig_dprsr_md.drop_ctl = 0x0;
    }

    // Drop the packet.
    action miss() {
        ig_dprsr_md.drop_ctl = 0x1;
    }

    // IPv4 LPM forwarding table.
    // The control plane populates this with (prefix, port) entries.
    // Default: drop (no matching route).
    table ipv4_lpm {
        key = {
            hdr.ipv4.dst_addr : lpm;
        }
        actions = {
            hit;
            miss;
        }
        size           = 1024;
        default_action = miss();
    }

    apply {
        if (hdr.ipv4.isValid()) {
            ipv4_lpm.apply();
        } else {
            miss();
        }

        // Egress pipeline is not needed for this prototype.
        ig_tm_md.bypass_egress = 1w1;
    }
}

// ---------------------------------------------------------------------------
// Top-level pipeline instantiation
// Egress is bypassed so we use the empty blocks from util.p4.
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
