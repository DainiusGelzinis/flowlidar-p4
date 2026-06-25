
//define the trace
define($trace /opt/p4eval/data/equinix_2019/equinix-nyc.dirA.20190117-130000.UTC.anon.pcap)

define($txport 0)

define($bout 32)
define($txverbose 99)
define($rxverbose 99)

define($RATE 1Gbps)

define($max_packets_in_queue 500000)
define($replay_count -1)

define($INsrcmac b8:3f:d2:b0:d7:78)

define($INdstmac b8:3f:d2:b0:d7:79)

define($ignore 0)

define($quick false)

// read the trace
fdIN :: FromDump($trace, STOP false, BURST 1, TIMING false, TIMING_FNT "100", ACTIVE true)

// set port for transmission
tdIN :: ToDPDKDevice($txport, BLOCKING true, BURST $bout, VERBOSE $txverbose, IQUEUE $bout, NDESC 0, TCO 0)

elementclass Generator { $magic |
    input
    -> MarkMACHeader
    -> EnsureDPDKBuffer
    -> EtherEncap(0x0800, 1:1:1:1:1:1, 2:2:2:2:2:2) 
    -> doethRewrite :: { input[0] -> active::Switch(OUTPUT 0)[0] -> rwIN :: EtherRewrite($INsrcmac, $INdstmac) -> [0]output; active[1] -> [0]output }
    -> Pad
    -> cnt :: AverageCounter(IGNORE 0)
    -> output;
}

fdIN -> unqueue0 :: BandwidthRatedUnqueue($RATE, LINK_RATE true, ACTIVE true) -> gen0 :: Generator(\<5700>) -> tdIN;

StaticThreadSched(fdIN 0/1, unqueue0 0/1)

pkt_cnt :: HandlerAggregate(ELEMENT gen0/cnt);

// script for displaying the running process
ig :: Script(TYPE ACTIVE,
    set s $(now),
    set lastcount 0,
    set lastbytes 0,
    set lastbytessent 0,
    set lastsent 0,
    set lastdrop 0,
    set last $s,
    set indexB 0,
    set indexC 0,
    set indexD 0,
    label loop,
    wait 0.5s,
    set n $(now),
    set t $(sub $n $s),
    set elapsed $(sub $n $last),
    set last $n,
    set count $(pkt_cnt.add count),
    print "SENT PKTS: $count",
    print "SEND RATE: $(gen0/cnt.bit_rate)",
    print "#######################",
    goto loop
)

StaticThreadSched(ig 15);

