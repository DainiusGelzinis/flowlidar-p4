# traffic_gen

Click configurations and pcap utilities used to generate / inspect
test traffic. Most of these live on hotpot in production; this
directory is the canonical copy under version control.

- `simple_pcap_replay.click` — main DPDK replay used by E8 and the
  lazy-vs-traditional sweep. Variables (`trace`, `RATE`,
  `replay_count`) are overridden on the command line.
- `single_flow.click` — single-flow generator (debugging).
- `synthetic_traffic.click` — synthetic traffic generator.
- `pcap_distribution.sh` / `pcap_distribution_strict.sh` — tshark
  helpers that emit per-flow size distribution for a pcap. Used
  for the trace characteristics table.
