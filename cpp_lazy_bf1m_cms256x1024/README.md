# cpp_lazy_bf1m_cms256x1024 — lazy BF 1M + 256-sub-sketch CMS

Pure-C++ FlowLiDAR control plane on real Tofino 1 (p4switch2). Pushes
both axes — BF 4× bigger, CMS redistributed into 4× more sub-sketches:

- **Data plane**: lazy BF (3 × **1,048,576** × 1 bit, bit<20>) +
  sub-sketch CMS (3 × **262,144** × 16-bit, **256 buckets × 1024 cols**).
  Total CMS cells per row identical to the 64×2048 variant — only
  redistributed.
- **Control plane**: `./lazy_bf1m_cms256x1024_cp`, shared
  `../cpp_lazy_common/` sources, compiled with `BF_SIZE=1048576`,
  `CMS_BUCKETS=256`, `CMS_COLS=1024` macros.

## Why this variant exists

At N≈290 K flows on CAIDA, the 64×2048 variant had max bucket = 3,903
flows — still over the kColsPerRow=2048 exact-solver threshold, so the
exact Gauss-Jordan solver never fired. With **256 buckets** the
average bucket drops to N/256 ≈ 1,130 flows. The kColsPerRow threshold
is 1,024 — many buckets should fall under, and the exact CMS solver
should fire for the first time on real CAIDA traffic.

## Expected vs the 64×2048 variant

| | 64 × 2048 (cur best) | **256 × 1024** |
|---|---:|---:|
| Total CMS cells per row | 131 K | 262 K |
| BF cells per row | 262 K | **1 M** |
| Avg bucket at N=290 K | 4,650 | **1,130** |
| Max bucket at N=290 K | ~3,900 | **~1,500** (est.) |
| Exact solver fires | 0/64 | **expected for most of 256** |
| Per-flow inflation | 1.03× | **~1.00×** (target) |

## Build SRAM footprint (open-p4studio compile)

| Stage | SRAM blocks | What |
|---|---:|---|
| 0 | 1 | ipv4_lpm |
| 1-2 | 0 | BF hashes |
| 3-5 | 9-10 | BF rows (was 3 in 262k variant) |
| 6-8 | 0 | master/col hashes, cms_idx |
| 9-11 | **34** | CMS rows (was 18 in 64×2048) |

Total: **132 / 960 blocks = 13.8%**. Still well within Tofino 1 budget.

## File map

```
cpp_lazy_bf1m_cms256x1024/
├── lazy_bf1m_cms256x1024.p4   P4 (lazy BF 1M + CMS 256×1024)
├── build.sh                    compiles with bf-p4c
├── setup_table.py              bfshell one-shot
├── print_ids.py                dumps bfrt register table IDs
├── test_packet.py              local 6-flow correctness probe
├── verify_crc.py               CRC parity check
├── Makefile                    5-line stub: BF=1M, CMS_BUCKETS=256, ...
└── README.md                   this file
```

## Build & run (on the switch)

```bash
cd ~/dainius/cpp_lazy_bf1m_cms256x1024
./build.sh                                  # compiles the P4
make                                        # builds ./lazy_bf1m_cms256x1024_cp

# T1
$SDE/run_switchd.sh -p lazy_bf1m_cms256x1024

# T2
bfshell
> bfrt_python /home/onie/dainius/cpp_lazy_bf1m_cms256x1024/setup_table.py
> exit
python3 /home/onie/dainius/cpp_lazy_bf1m_cms256x1024/print_ids.py

/home/onie/dainius/cpp_lazy_bf1m_cms256x1024/lazy_bf1m_cms256x1024_cp \
    --epoch 15 --pipe 1 \
    --bf-ids  <from print_ids.py> \
    --cms-ids <from print_ids.py>

# T3 (hotpot)
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- ~/simple_pcap_replay.click
```
