import time
from scapy.all import Ether, IP, TCP, sendp, AsyncSniffer # type: ignore

# Start sniffing on BOTH veth2 and veth3 to see where packet arrives
sniffer2 = AsyncSniffer(iface="veth2", filter="ip", count=1, timeout=3)
sniffer3 = AsyncSniffer(iface="veth3", filter="ip", count=1, timeout=3)
sniffer2.start()
sniffer3.start()

# Small delay to ensure sniffers are ready
time.sleep(0.5)

# Send packet into port 0 (veth1)
sendp(Ether()/IP(dst="10.0.0.1", ttl=64)/TCP(dport=80), iface="veth1", verbose=True)

sniffer2.join()
sniffer3.join()

print(f"Packets on veth2: {len(sniffer2.results)}")
print(f"Packets on veth3: {len(sniffer3.results)}")

pkts = sniffer2.results + sniffer3.results
if pkts:
    print("SUCCESS — packet forwarded correctly")
    for p in pkts:
        print(f"  TTL out: {p[IP].ttl}  (should be 63)")
        p.show()
else:
    print("FAILURE — no packet received on veth2 or veth3")
