// chunked_replay.click — pcap replay that sends exactly $LIMIT packets
// then stops. Variant of simple_pcap_replay.click for the evaluation
// harness (one chunk = one epoch = one click invocation).
//
// Configurable from the command line:
//   $TRACE  : pcap file to replay
//   $LIMIT  : packet count to send before stopping (default: 5,000,000)
//   $RATE   : sending rate, e.g. 2Gbps (default: 2Gbps)
//   $TXPORT : DPDK port id (default: 0)
//
// Usage on hotpot:
//   /opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
//       chunked_replay.click TRACE=/.../chunk.pcap LIMIT=5000000 RATE=2Gbps

define($trace  /opt/p4eval/data/equinix_2019/equinix-nyc.dirA.20190117-130000.UTC.anon.pcap)
define($txport 0)
define($bout   32)
define($txverbose 99)
define($RATE   2Gbps)
define($LIMIT  5000000)
define($max_packets_in_queue 500000)

define($INsrcmac b8:3f:d2:b0:d7:78)
define($INdstmac b8:3f:d2:b0:d7:79)

// Read the pcap, stop at EOF (single pass), do not loop.
fdIN :: FromDump($trace, STOP false, BURST 1, TIMING false, ACTIVE true)

tdIN :: ToDPDKDevice($txport, BLOCKING true, BURST $bout, VERBOSE $txverbose,
                    IQUEUE $bout, NDESC 0, TCO 0)

elementclass Generator { $magic |
    input
    -> MarkMACHeader
    -> EnsureDPDKBuffer
    -> EtherEncap(0x0800, 1:1:1:1:1:1, 2:2:2:2:2:2)
    -> doethRewrite :: { input[0] -> active::Switch(OUTPUT 0)[0]
                          -> rwIN :: EtherRewrite($INsrcmac, $INdstmac)
                          -> [0]output;
                          active[1] -> [0]output }
    -> Pad
    -> cnt :: AverageCounter(IGNORE 0)
    -> output;
}

// Limit chain: send at most $LIMIT pkts, then stop the click router.
fdIN -> unqueue0 :: BandwidthRatedUnqueue($RATE, LINK_RATE true, ACTIVE true)
     -> limiter :: Counter(COUNT_CALL "$LIMIT stop")
     -> gen0    :: Generator(\<5700>)
     -> tdIN;

StaticThreadSched(fdIN 0/1, unqueue0 0/1)

pkt_cnt :: HandlerAggregate(ELEMENT gen0/cnt);

// Progress / final-line printer
ig :: Script(TYPE ACTIVE,
    set s $(now),
    set last $s,
    label loop,
    wait 1s,
    set n $(now),
    set count $(pkt_cnt.add count),
    print "SENT PKTS: $count",
    print "SEND RATE: $(gen0/cnt.bit_rate)",
    print "#######################",
    goto loop
)
StaticThreadSched(ig 15);
