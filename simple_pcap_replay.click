
//define the trace
define($trace <path to PCAP file>)


// define the transmission port
define($txport 0)


define($bout 32)
define($txverbose 99)
define($rxverbose 99)

//set sending rate to 10Gbps
define($RATE 10Gbps) //1Gpbs

define($max_packets_in_queue 500000)
define($replay_count -1)


//d :: DPDKInfo(NB_SOCKET_MBUF  2048575) //Should be a bit more than 4 times the limit

/* Can be whatever */
define($INsrcmac b8:3f:d2:9f:2e:9b)
/* Hotpot: b8:3f:d2:b0:d7:79, Grill: b8:3f:d2:9f:2e:9b Onie: 70:b3:d5:cc:ff:3c */
define($INdstmac b8:3f:d2:b0:d7:79)

define($ignore 0)

define($quick false)


// read the trace
fdIN :: FromDump($trace, STOP true, BURST 1, TIMING false, TIMING_FNT "100", ACTIVE true)


// set port for transmission
tdIN :: ToDPDKDevice($txport, BLOCKING true, BURST $bout, VERBOSE $txverbose, IQUEUE $bout, NDESC 0, TCO 0)


//elementclass Numberise { $magic |
//    input -> Strip(14) -> check :: MarkIPHeader -> nPacket :: NumberPacket(42) -> StoreData(40, $magic) -> ResetIPChecksum -> Unstrip(14) -> output
//}


// this is function-like entity that adds ethernet frame to each packet of CAIDA trace 
elementclass Generator { $magic |
    input
    -> MarkMACHeader
    -> EnsureDPDKBuffer
    -> EtherEncap(0x0800, 1:1:1:1:1:1, 2:2:2:2:2:2) 
    -> doethRewrite :: { input[0] -> active::Switch(OUTPUT 0)[0] -> rwIN :: EtherRewrite($INsrcmac, $INdstmac) -> [0]output; active[1] -> [0]output }
    -> Pad
    // -> Numberise($magic)
    -> cnt :: AverageCounter(IGNORE 0)
    -> output;
}


// send the traffic by redirecting the trace from pcap file to the port
fdIN -> unqueue0 :: BandwidthRatedUnqueue($RATE, LINK_RATE true, ACTIVE true) -> gen0 :: Generator(\<5700>) -> tdIN;


// pin fdIN and unqueue0 to specific core and thread
StaticThreadSched(fdIN 0/1, unqueue0 0/1)


pkt_cnt :: HandlerAggregate(ELEMENT gen0/cnt);

// this code can be used as receiver
//fd0 :: FromDPDKDevice(1, PROMISC true, VERBOSE $rxverbose)
//-> oc0 :: AverageCounter() -> Discard;
//StaticThreadSched(fd0 0/3)

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
    print "RCVD PKTS: $(oc0.count)",
    print "RX bit rate: $(oc0.bit_rate)",
    print "#######################",
    goto loop
)

StaticThreadSched(ig 15);



