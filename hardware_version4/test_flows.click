// test_flows.click — Replay a small deterministic pcap into the DPDK
// interface at a low rate, useful for FlowLiDAR correctness testing.
//
// The pcap contains 6 known flows (12+6+3+2+2+2 = 27 packets). At 100 pps
// the whole replay finishes in ~0.3 s, so use a long control-plane epoch
// (e.g. --epoch 30) so all 27 packets land in epoch 1.
//
// Generate the pcap first:
//     python3 make_test_pcap.py /tmp/test_packets.pcap
//
// Then run on hotpot:
//     /opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
//         ~/test_flows.click PCAP=/tmp/test_packets.pcap RATE=100
//
// Vars:
//     PCAP  — path to the pcap to replay (default /tmp/test_packets.pcap)
//     RATE  — packets per second (default 100)
//     LIMIT — total packet cap; set to 27 to send each flow exactly once,
//             or a multiple of 27 to repeat the whole pattern. 0 = unlimited.

define($PCAP   /tmp/test_packets.pcap)
define($RATE   100)
define($LIMIT  27)

// Read pcap, ignore original timing (we set our own rate).
src :: FromDump($PCAP, STOP true, TIMING false, BURST 1, END_AFTER 0);

// Rate-limit the output (packets/sec).
shape :: RatedUnqueue($RATE);

// Send out the DPDK port (matches "-a 0000:ac:00.0" on the click cmdline).
out :: ToDPDKDevice(0, BURST 1);

// Optional: print a small summary so you can confirm the file was found.
src
    -> Print("OUT")
    -> Counter
    -> shape
    -> out;

// STOP true on FromDump tells the router to stop the driver at EOF, so
// click exits on its own once the pcap is fully read.
DriverManager(pause,
              print "[test_flows] EOF reached, exiting");
