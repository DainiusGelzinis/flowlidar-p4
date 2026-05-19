# cpp_lazy_bf131k_cms64x1024 — pure C++ control plane, lazy BF 131k

Pure-C++ FlowLiDAR control plane on real Tofino 1 (p4switch2).

- **Data plane**: lazy BF (3 × **131072** × 1 bit) + sub-sketch CMS
  (3 × 65536 × 16-bit, 64 buckets × 1024 cols).
- **Control plane**: a single C++ binary (`./lazy_bf_cp`) built from the
  shared `../cpp_lazy_common/` sources. Owns the bfrt-grpc client_id 0
  session, receives digests, runs per-epoch bulk read+clear, and reports
  per-flow counts via Algs 4/5 + sub-sketch equation solver (min-fallback
  when `n > kColsPerRow`).

## File map

```
cpp_lazy_bf131k_cms64x1024/
├── lazy_bf.p4         P4 (lazy BF + sub-sketch CMS, 131k cells)
├── build.sh           compiles lazy_bf.p4 with bf-p4c
├── setup_table.py     bfshell one-shot — port enables, LPM, BF/CMS gates
├── print_ids.py       dumps bfrt register table IDs
├── test_packet.py     local 6-flow correctness probe (scapy, sudo)
├── verify_crc.py      CRC parity check (Python crcmod vs C++)
├── Makefile           4-line stub: sets BF_SIZE/P4_NAME/BINARY, includes shared core
├── README.md          this file
└── results.md         measured numbers on real hardware
```

Shared sources live in `../cpp_lazy_common/` (see that directory for the
actual C++ code and the build rules).

## Build

On the switch (with `$SDE` and `$SDE_INSTALL` exported):

```bash
cd ~/dainius/cpp_lazy_bf131k_cms64x1024
./build.sh                  # compiles lazy_bf.p4 with bf-p4c
make                        # builds ./lazy_bf_cp from ../cpp_lazy_common/
```

## Run

Three terminals (T1 + T2 on the switch, T3 sends traffic from hotpot):

### T1 — switchd
```bash
$SDE/run_switchd.sh -p lazy_bf
```
Wait for `bfruntime gRPC server started`.

### T2 — one-shot setup, then C++ control plane
```bash
bfshell
> bfrt_python /home/onie/dainius/cpp_lazy_bf131k_cms64x1024/setup_table.py
> exit

/home/onie/dainius/cpp_lazy_bf131k_cms64x1024/lazy_bf_cp \
    --epoch 15 --pipe 1 \
    --bf-ids  <from print_ids.py> \
    --cms-ids <from print_ids.py>
```

### T3 — traffic from hotpot
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- ~/simple_pcap_replay.click
```

See `results.md` for the measured numbers (~242K visible / 84% coverage
/ 1.40× inflation @ 15 s epoch).
