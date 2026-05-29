
// FlowLiDAR synthetic traffic generator
// Uses FastUDPFlows — no pcap file needed, full control over flow count and size.
//
// Key parameters:
//   FLOWS    — number of unique flows (unique src/dst port pairs)
//   FLOWSIZE — packets per flow before ports rotate
//              < 3 : flows stay Alg4 (digest only)
//              = 3 : flows get all BF bits set -> Alg5
//              >= 4: flows hit CMS -> equation solver
//   RATE     — packets per second
//   LIMIT    — total packets to send (-1 not supported; use a large number)
//
// Run on hotpot:
//   /opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- ~/synthetic_traffic.click

define($txport 0)
define($bout 32)
define($txverbose 99)

// Hotpot enp172s0f0np0 MAC (source)
define($SRCMAC b8:3f:d2:b0:d7:78)
// Hotpot enp172s0f1np1 MAC (next hop / switch ingress)
define($DSTMAC b8:3f:d2:b0:d7:79)

define($SRCIP  10.1.0.1)
define($DSTIP  10.0.0.1)

// --- Adjust these for different test scenarios ---
define($FLOWS    10000)   // number of unique flows
define($FLOWSIZE 10)      // packets per flow (>=4 to exercise CMS + solver)
define($RATE     1Mbps)   // link rate — change to test different loads (e.g. 10Mbps, 1Gbps)
define($LIMIT    1000000000) // total packets (large enough to run indefinitely)
define($LEN      64)      // packet length in bytes

tdIN :: ToDPDKDevice($txport, BLOCKING true, BURST $bout, VERBOSE $txverbose, IQUEUE $bout, NDESC 0, TCO 0)

gen :: FastUDPFlows(1000000000, $LIMIT, $LEN,
    $SRCMAC, $SRCIP,
    $DSTMAC, $DSTIP,
    $FLOWS, $FLOWSIZE)

gen -> BandwidthRatedUnqueue($RATE, LINK_RATE true, ACTIVE true) -> cnt :: AverageCounter(IGNORE 0) -> tdIN

StaticThreadSched(gen 0/1)

ig :: Script(TYPE ACTIVE,
    label loop,
    wait 1s,
    print "SENT PKTS: $(cnt.count)",
    print "SEND RATE: $(cnt.bit_rate)",
    print "#######################",
    goto loop
)

StaticThreadSched(ig 15)
