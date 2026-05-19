# cpp_traditional_bf131k_cms64x1024 — pure C++ control plane, traditional BF

Pure-C++ FlowLiDAR control plane on real Tofino 1 (p4switch2). Baseline
variant of `cpp_lazy_bf131k_cms64x1024` with a **traditional** Bloom
Filter instead of the lazy chain — every packet flips all 3 BF rows,
exactly one digest per visible flow.

- **Data plane**: traditional BF (3 × **131072** × 1 bit, bit<17>, all rows
  always check-and-set) + sub-sketch CMS (3 × 65536 × 16-bit, 64 buckets ×
  1024 cols). Same BF / CMS sizes as the 131k lazy variant.
- **Control plane**: a single C++ binary (`cp_cpp/traditional_bf_cp`) that
  owns the bfrt-grpc client_id 0 session, receives digests, runs per-epoch
  bulk read+clear, and reports flow counts.
- **Algorithms 4 / 5 are disabled here**: every packet flips all 3 BF rows,
  so a 1-pkt mouse and an N-pkt elephant produce identical BF state. Every
  visible flow goes straight to the sub-sketch equation solver (with
  `min(cms_rows)` fallback when `n > kColsPerRow`).

This is the apples-to-apples comparison baseline for the lazy-BF
variant — same BF/CMS dimensions, same C++ CP, only the BF semantics differ.

## File map

```
cpp_traditional_bf131k_cms64x1024/
├── traditional_bf.p4    P4 (traditional BF + sub-sketch CMS)
├── build.sh             compiles traditional_bf.p4 with bf-p4c
├── setup_table.py       bfshell one-shot — port enables, LPM, CMS gates
├── print_ids.py         dumps bfrt register table IDs (run as plain Python)
├── test_packet.py       local 6-flow correctness probe (scapy, sudo)
├── verify_crc.py        CRC parity check
├── README.md            this file
└── cp_cpp/
    ├── Makefile         builds traditional_bf_cp using bfrt-grpc + auto-generated stubs
    ├── main.cpp         entrypoint + per-epoch loop (no Algs 4/5)
    ├── bfrt_client.{hpp,cpp}  gRPC wrapper: subscribe, BIND, register I/O, digests
    ├── crc.hpp          CRC-32 family hashes matching traditional_bf.p4
    ├── flow.hpp         5-tuple flow key
    └── solver.{hpp,cpp} sub-sketch equation solver (Exact / Alg6 / min fallback)
```

## Build

On the switch (with `$SDE` and `$SDE_INSTALL` exported):

```bash
cd ~/dainius/cpp_traditional_bf131k_cms64x1024
./build.sh                   # compiles traditional_bf.p4 with bf-p4c
cd cp_cpp && make            # builds traditional_bf_cp
```

## Run

Three terminals (T1 + T2 on the switch, T3 sends traffic from hotpot):

### T1 — switchd
```bash
sudo -E $SDE/run_switchd.sh -p traditional_bf
```
Wait for `bfruntime gRPC server started`.

### T2a — one-shot setup
```bash
bfshell
> bfrt_python ~/dainius/cpp_traditional_bf131k_cms64x1024/setup_table.py
> exit
```

### T2b — print table IDs (run with NO other CP attached)
```bash
python3 ~/dainius/cpp_traditional_bf131k_cms64x1024/print_ids.py
```

### T2c — C++ control plane
```bash
~/dainius/cpp_traditional_bf131k_cms64x1024/cp_cpp/traditional_bf_cp \
    --epoch 15 --pipe 1 \
    --bf-ids  <from print_ids.py> \
    --cms-ids <from print_ids.py>
```

### T3 — traffic from hotpot
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- ~/simple_pcap_replay.click
```

## What the report looks like

```
EPOCH 1 END  -  N flows detected by BF
  bulk read time         : ... s
    bf_0 : ... non-zero cells, sum=...
    ...
  Total flows            : ...
  Epoch digests          : ...
  Estimated packets      : ...
  Equation solver / min fallback  : ... (100%)   <-- no Algs 4/5 here
  Sub-sketch buckets used: 64 / 64  (exact: ..., Alg6 approx: ..., n>cols skip: ...)
  Max sub-sketch load    : ...
  bulk clear time        : ... s
```

## Expected vs lazy variant

Both variants share the BF/CMS sizes and the C++ CP. The only data-plane
difference is the BF update rule. So at the same line rate / epoch length:

- **Same coverage** (BF saturation is the same — every visible flow sets
  all 3 bits in both variants).
- **More digests in lazy**: lazy fires 1, 2, or 3 digests per flow
  (`epoch_digests > total_flows`). Traditional fires exactly 1
  (`epoch_digests == total_flows`).
- **More CMS counts in traditional**: lazy's CMS only counts the 4th
  packet onwards; traditional's CMS counts the 2nd packet onwards.
- **No Alg 4 / 5 cheap-classification path** for traditional — solver is
  load-bearing for every flow.
