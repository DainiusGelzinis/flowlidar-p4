# hardware_version_cpp_lazy_BF — pure C++ control plane

Pure-C++ FlowLiDAR control plane on real Tofino 1 (p4switch2).

- **Data plane**: lazy BF (3 × 131072 × 1 bit) + sub-sketch CMS (64 × 1024).
  Identical to `hardware_version2/prototype6.p4`, just renamed `lazy_bf.p4`.
- **Control plane**: a single C++ binary (`cp_cpp/lazy_bf_cp`) that owns the
  bfrt-grpc client_id 0 session, receives digests, runs per-epoch bulk
  read/clear, and reports flow counts.
- No Python control plane. No bfshell at run time (only for one-shot table
  setup).

## File map

```
hardware_version_cpp_lazy_BF/
├── lazy_bf.p4            P4 (lazy BF + sub-sketch CMS, prototype5/6 size)
├── build.sh              compiles lazy_bf.p4 with bf-p4c
├── setup_table.py        bfshell one-shot — port enables, LPM, BF/CMS gates
├── test_packet.py        local 6-flow correctness probe (scapy, sudo)
├── README.md             this file
└── cp_cpp/
    ├── Makefile          builds lazy_bf_cp using bfrt-grpc + auto-generated stubs
    ├── main.cpp          entrypoint + per-epoch loop
    ├── bfrt_client.{hpp,cpp}  gRPC wrapper: subscribe, BIND, register I/O, digests
    ├── crc.hpp           CRC-32 family hashes matching lazy_bf.p4
    └── flow.hpp          5-tuple flow key + accumulator
```

## Build

On the switch (with `$SDE` and `$SDE_INSTALL` exported):

```bash
cd hardware_version_cpp_lazy_BF
./build.sh                  # compiles lazy_bf.p4 with bf-p4c
cd cp_cpp && make           # builds lazy_bf_cp
```

The Makefile uses `pkg-config` to pull in the absl/grpc/protobuf transitive
dependencies — it works on both open-p4studio (SDE 9.13.4) and bf-sde-9.11.0.

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
> bfrt_python ~/dainius/hardware_version_cpp_lazy_BF/setup_table.py
> exit

~/dainius/hardware_version_cpp_lazy_BF/cp_cpp/lazy_bf_cp \
    --epoch 30 --pipe 1
```

### T3 — traffic from hotpot
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- ~/simple_pcap_replay.click
```

## What the report looks like

```
EPOCH 1 END  -  N flows detected by BF
  bulk read time         : ... s
  Total flows            : ...
  Epoch digests          : ...
  Estimated packets      : ...   (digests + CMS)
  Max sub-sketch load    : ...   (max bucket = .. / 1024 cols)
  Clearing BF + CMS registers...
  bulk clear time        : ... s
```

## MVP caveats / next steps

- Per-flow estimate is `digest_count + min(cms_rows)` — no Algorithm 4/5/6
  classification yet. For visible flows with <=3 packets `min(cms)` is 0;
  for elephants it tracks the post-3rd-packet count. Same accuracy as the
  Python CP at the top-level summary, but doesn't print per-flow estimates.
- No equation solver yet — when sub-sketches are overloaded the `min` will
  slightly over-count. Adding the linear-system solver (e.g. with Eigen) is
  a follow-up.
- Default `--pipe 1` matches p4switch2. For the simulator pass `--pipe 0`.
- The first epoch on real hardware may take a few seconds for the bulk read
  while the connection warms up; subsequent epochs should be much faster.
