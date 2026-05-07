// Single flow test — 1 packet per second
// Sends one UDP flow (fixed src/dst IP and ports) at 1 pps.
// Use this to verify BF bits are set correctly and CMS is reached after 3 packets.
//
// Run on hotpot:
//   /opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- ~/single_flow.click

define($txport 0)
define($bout 32)
define($txverbose 99)

define($SRCMAC b8:3f:d2:b0:d7:78)
define($DSTMAC b8:3f:d2:b0:d7:79)

define($SRCIP  10.1.0.1)
define($DSTIP  10.0.0.1)
define($SPORT  1234)
define($DPORT  5678)

define($LEN    64)

tdIN :: ToDPDKDevice($txport, BLOCKING true, BURST $bout, VERBOSE $txverbose, IQUEUE $bout, NDESC 0, TCO 0)

gen :: FastUDPFlows(1000000000, -1, $LEN,
    $SRCMAC, $SRCIP,
    $DSTMAC, $DSTIP,
    1, 1000000000)

gen -> RatedUnqueue(1, ACTIVE true) -> cnt :: AverageCounter(IGNORE 0) -> tdIN

StaticThreadSched(gen 0/1)

ig :: Script(TYPE ACTIVE,
    label loop,
    wait 1s,
    print "SENT PKTS: $(cnt.count)",
    print "#######################",
    goto loop
)

StaticThreadSched(ig 15)
