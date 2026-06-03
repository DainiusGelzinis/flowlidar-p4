# Runbook — lazy vs traditional BF (10 variants) × 2 validation traces

Validates the original chunk-0/130000 sweep against the 5M chunks of
130100 and 130200. The 130000 baseline lives in
`results/lazy_vs_traditional_bf/`; this run produces matching estimates
for the two new traces under per-trace subdirectories.

10 variants × 2 traces = **20 runs**. P4 + CP binaries are already on
the switch from the original sweep, no rebuild needed.

Order: variant-major (V1 trace 130100, V1 trace 130200, V2 trace 130100, ...).
That keeps the same P4 program loaded for two consecutive runs and avoids
half the program switches.

## One-time shell setup

**Switch terminals A and B:**
```bash
ssh onie.two.hotpot
export BF_IDS=2338372543,2333775667,2347111112
export CMS_IDS=2346354927,2339499036,2335880110
```

**Hotpot:**
```bash
ssh dgelzini@hotpot.win.tue.nl
RATE=2Gbps
```

## Pcap + truth paths

| Trace | Pcap (hotpot) | Truth (hotpot) |
|---|---|---|
| 130100 | `/home2/dgelzini/chunks/130100_chunk5M/chunk_00000_legacy.pcap` | `/home2/dgelzini/chunks/130100_chunk5M/chunk0_truth.csv` |
| 130200 | `/home2/dgelzini/chunks/130200_chunk5M/chunk_00000_legacy.pcap` | `/home2/dgelzini/chunks/130200_chunk5M/chunk0_truth.csv` |

Each chunk is exactly 5,000,000 packets. Flow counts: 477,897 (130100)
and 456,332 (130200).

## Run pattern (applies to every block)

1. **Terminal A:** start switchd line.
2. **Terminal B:** wait for switchd ready, paste bfshell + CP block.
3. **Hotpot:** when CP prints "Listening for digests", paste replay.
4. **After CP exits:** Ctrl+\ in Terminal A.

`--epoch 20` is fine for all 10 variants at 5M (replay takes ~3 s; epoch
just needs to cover that plus bulk read).

Sanity check after each run:
```bash
grep -E "Resolved by Alg|Sub-sketch buckets|cms_[012] :" /tmp/$LOG
```

---

# Block 1 — lazy_bf131k_cms256x1024, trace 130100

**Terminal A:**
```bash
$SDE/run_switchd.sh -p lazy_bf131k_cms256x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_lazy_bf131k_cms256x1024/setup_table.py
EOF

mkdir -p ~/results_lazy_vs_traditional_bf/130100/lazy_bf131k_cms256x1024
~/dainius/cpp_lazy_bf131k_cms256x1024/lazy_bf131k_cms256x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_lazy_vs_traditional_bf/130100/lazy_bf131k_cms256x1024/est_chunk_00000.csv 2>&1 \
  | tee /tmp/lazy_bf131k_130100.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130100_chunk5M/chunk_00000_legacy.pcap \
  RATE=$RATE replay_count=1
```

# Block 2 — lazy_bf131k_cms256x1024, trace 130200

**Terminal A:**
```bash
$SDE/run_switchd.sh -p lazy_bf131k_cms256x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_lazy_bf131k_cms256x1024/setup_table.py
EOF

mkdir -p ~/results_lazy_vs_traditional_bf/130200/lazy_bf131k_cms256x1024
~/dainius/cpp_lazy_bf131k_cms256x1024/lazy_bf131k_cms256x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_lazy_vs_traditional_bf/130200/lazy_bf131k_cms256x1024/est_chunk_00000.csv 2>&1 \
  | tee /tmp/lazy_bf131k_130200.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130200_chunk5M/chunk_00000_legacy.pcap \
  RATE=$RATE replay_count=1
```

---

# Block 3 — lazy_bf262k_cms256x1024, trace 130100

**Terminal A:**
```bash
$SDE/run_switchd.sh -p lazy_bf262k_cms256x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_lazy_bf262k_cms256x1024/setup_table.py
EOF

mkdir -p ~/results_lazy_vs_traditional_bf/130100/lazy_bf262k_cms256x1024
~/dainius/cpp_lazy_bf262k_cms256x1024/lazy_bf262k_cms256x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_lazy_vs_traditional_bf/130100/lazy_bf262k_cms256x1024/est_chunk_00000.csv 2>&1 \
  | tee /tmp/lazy_bf262k_130100.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130100_chunk5M/chunk_00000_legacy.pcap \
  RATE=$RATE replay_count=1
```

# Block 4 — lazy_bf262k_cms256x1024, trace 130200

**Terminal A:**
```bash
$SDE/run_switchd.sh -p lazy_bf262k_cms256x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_lazy_bf262k_cms256x1024/setup_table.py
EOF

mkdir -p ~/results_lazy_vs_traditional_bf/130200/lazy_bf262k_cms256x1024
~/dainius/cpp_lazy_bf262k_cms256x1024/lazy_bf262k_cms256x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_lazy_vs_traditional_bf/130200/lazy_bf262k_cms256x1024/est_chunk_00000.csv 2>&1 \
  | tee /tmp/lazy_bf262k_130200.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130200_chunk5M/chunk_00000_legacy.pcap \
  RATE=$RATE replay_count=1
```

---

# Block 5 — lazy_bf524k_cms256x1024, trace 130100

**Terminal A:**
```bash
$SDE/run_switchd.sh -p lazy_bf524k_cms256x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_lazy_bf524k_cms256x1024/setup_table.py
EOF

mkdir -p ~/results_lazy_vs_traditional_bf/130100/lazy_bf524k_cms256x1024
~/dainius/cpp_lazy_bf524k_cms256x1024/lazy_bf524k_cms256x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_lazy_vs_traditional_bf/130100/lazy_bf524k_cms256x1024/est_chunk_00000.csv 2>&1 \
  | tee /tmp/lazy_bf524k_130100.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130100_chunk5M/chunk_00000_legacy.pcap \
  RATE=$RATE replay_count=1
```

# Block 6 — lazy_bf524k_cms256x1024, trace 130200

**Terminal A:**
```bash
$SDE/run_switchd.sh -p lazy_bf524k_cms256x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_lazy_bf524k_cms256x1024/setup_table.py
EOF

mkdir -p ~/results_lazy_vs_traditional_bf/130200/lazy_bf524k_cms256x1024
~/dainius/cpp_lazy_bf524k_cms256x1024/lazy_bf524k_cms256x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_lazy_vs_traditional_bf/130200/lazy_bf524k_cms256x1024/est_chunk_00000.csv 2>&1 \
  | tee /tmp/lazy_bf524k_130200.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130200_chunk5M/chunk_00000_legacy.pcap \
  RATE=$RATE replay_count=1
```

---

# Block 7 — lazy_bf1m_cms256x1024, trace 130100

**Terminal A:**
```bash
$SDE/run_switchd.sh -p lazy_bf1m_cms256x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_lazy_bf1m_cms256x1024/setup_table.py
EOF

mkdir -p ~/results_lazy_vs_traditional_bf/130100/lazy_bf1m_cms256x1024
~/dainius/cpp_lazy_bf1m_cms256x1024/lazy_bf1m_cms256x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_lazy_vs_traditional_bf/130100/lazy_bf1m_cms256x1024/est_chunk_00000.csv 2>&1 \
  | tee /tmp/lazy_bf1m_130100.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130100_chunk5M/chunk_00000_legacy.pcap \
  RATE=$RATE replay_count=1
```

# Block 8 — lazy_bf1m_cms256x1024, trace 130200

**Terminal A:**
```bash
$SDE/run_switchd.sh -p lazy_bf1m_cms256x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_lazy_bf1m_cms256x1024/setup_table.py
EOF

mkdir -p ~/results_lazy_vs_traditional_bf/130200/lazy_bf1m_cms256x1024
~/dainius/cpp_lazy_bf1m_cms256x1024/lazy_bf1m_cms256x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_lazy_vs_traditional_bf/130200/lazy_bf1m_cms256x1024/est_chunk_00000.csv 2>&1 \
  | tee /tmp/lazy_bf1m_130200.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130200_chunk5M/chunk_00000_legacy.pcap \
  RATE=$RATE replay_count=1
```

---

# Block 9 — lazy_bf2m_cms256x1024, trace 130100

**Terminal A:**
```bash
$SDE/run_switchd.sh -p lazy_bf2m_cms256x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_lazy_bf2m_cms256x1024/setup_table.py
EOF

mkdir -p ~/results_lazy_vs_traditional_bf/130100/lazy_bf2m_cms256x1024
~/dainius/cpp_lazy_bf2m_cms256x1024/lazy_bf2m_cms256x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_lazy_vs_traditional_bf/130100/lazy_bf2m_cms256x1024/est_chunk_00000.csv 2>&1 \
  | tee /tmp/lazy_bf2m_130100.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130100_chunk5M/chunk_00000_legacy.pcap \
  RATE=$RATE replay_count=1
```

# Block 10 — lazy_bf2m_cms256x1024, trace 130200

**Terminal A:**
```bash
$SDE/run_switchd.sh -p lazy_bf2m_cms256x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_lazy_bf2m_cms256x1024/setup_table.py
EOF

mkdir -p ~/results_lazy_vs_traditional_bf/130200/lazy_bf2m_cms256x1024
~/dainius/cpp_lazy_bf2m_cms256x1024/lazy_bf2m_cms256x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_lazy_vs_traditional_bf/130200/lazy_bf2m_cms256x1024/est_chunk_00000.csv 2>&1 \
  | tee /tmp/lazy_bf2m_130200.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130200_chunk5M/chunk_00000_legacy.pcap \
  RATE=$RATE replay_count=1
```

---

# Block 11 — traditional_bf131k_cms256x1024, trace 130100

**Terminal A:**
```bash
$SDE/run_switchd.sh -p traditional_bf131k_cms256x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_traditional_bf131k_cms256x1024/setup_table.py
EOF

mkdir -p ~/results_lazy_vs_traditional_bf/130100/traditional_bf131k_cms256x1024
~/dainius/cpp_traditional_bf131k_cms256x1024/traditional_bf131k_cms256x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_lazy_vs_traditional_bf/130100/traditional_bf131k_cms256x1024/est_chunk_00000.csv 2>&1 \
  | tee /tmp/traditional_bf131k_130100.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130100_chunk5M/chunk_00000_legacy.pcap \
  RATE=$RATE replay_count=1
```

# Block 12 — traditional_bf131k_cms256x1024, trace 130200

**Terminal A:**
```bash
$SDE/run_switchd.sh -p traditional_bf131k_cms256x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_traditional_bf131k_cms256x1024/setup_table.py
EOF

mkdir -p ~/results_lazy_vs_traditional_bf/130200/traditional_bf131k_cms256x1024
~/dainius/cpp_traditional_bf131k_cms256x1024/traditional_bf131k_cms256x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_lazy_vs_traditional_bf/130200/traditional_bf131k_cms256x1024/est_chunk_00000.csv 2>&1 \
  | tee /tmp/traditional_bf131k_130200.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130200_chunk5M/chunk_00000_legacy.pcap \
  RATE=$RATE replay_count=1
```

---

# Block 13 — traditional_bf262k_cms256x1024, trace 130100

**Terminal A:**
```bash
$SDE/run_switchd.sh -p traditional_bf262k_cms256x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_traditional_bf262k_cms256x1024/setup_table.py
EOF

mkdir -p ~/results_lazy_vs_traditional_bf/130100/traditional_bf262k_cms256x1024
~/dainius/cpp_traditional_bf262k_cms256x1024/traditional_bf262k_cms256x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_lazy_vs_traditional_bf/130100/traditional_bf262k_cms256x1024/est_chunk_00000.csv 2>&1 \
  | tee /tmp/traditional_bf262k_130100.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130100_chunk5M/chunk_00000_legacy.pcap \
  RATE=$RATE replay_count=1
```

# Block 14 — traditional_bf262k_cms256x1024, trace 130200

**Terminal A:**
```bash
$SDE/run_switchd.sh -p traditional_bf262k_cms256x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_traditional_bf262k_cms256x1024/setup_table.py
EOF

mkdir -p ~/results_lazy_vs_traditional_bf/130200/traditional_bf262k_cms256x1024
~/dainius/cpp_traditional_bf262k_cms256x1024/traditional_bf262k_cms256x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_lazy_vs_traditional_bf/130200/traditional_bf262k_cms256x1024/est_chunk_00000.csv 2>&1 \
  | tee /tmp/traditional_bf262k_130200.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130200_chunk5M/chunk_00000_legacy.pcap \
  RATE=$RATE replay_count=1
```

---

# Block 15 — traditional_bf524k_cms256x1024, trace 130100

**Terminal A:**
```bash
$SDE/run_switchd.sh -p traditional_bf524k_cms256x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_traditional_bf524k_cms256x1024/setup_table.py
EOF

mkdir -p ~/results_lazy_vs_traditional_bf/130100/traditional_bf524k_cms256x1024
~/dainius/cpp_traditional_bf524k_cms256x1024/traditional_bf524k_cms256x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_lazy_vs_traditional_bf/130100/traditional_bf524k_cms256x1024/est_chunk_00000.csv 2>&1 \
  | tee /tmp/traditional_bf524k_130100.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130100_chunk5M/chunk_00000_legacy.pcap \
  RATE=$RATE replay_count=1
```

# Block 16 — traditional_bf524k_cms256x1024, trace 130200

**Terminal A:**
```bash
$SDE/run_switchd.sh -p traditional_bf524k_cms256x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_traditional_bf524k_cms256x1024/setup_table.py
EOF

mkdir -p ~/results_lazy_vs_traditional_bf/130200/traditional_bf524k_cms256x1024
~/dainius/cpp_traditional_bf524k_cms256x1024/traditional_bf524k_cms256x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_lazy_vs_traditional_bf/130200/traditional_bf524k_cms256x1024/est_chunk_00000.csv 2>&1 \
  | tee /tmp/traditional_bf524k_130200.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130200_chunk5M/chunk_00000_legacy.pcap \
  RATE=$RATE replay_count=1
```

---

# Block 17 — traditional_bf1m_cms256x1024, trace 130100

**Terminal A:**
```bash
$SDE/run_switchd.sh -p traditional_bf1m_cms256x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_traditional_bf1m_cms256x1024/setup_table.py
EOF

mkdir -p ~/results_lazy_vs_traditional_bf/130100/traditional_bf1m_cms256x1024
~/dainius/cpp_traditional_bf1m_cms256x1024/traditional_bf1m_cms256x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_lazy_vs_traditional_bf/130100/traditional_bf1m_cms256x1024/est_chunk_00000.csv 2>&1 \
  | tee /tmp/traditional_bf1m_130100.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130100_chunk5M/chunk_00000_legacy.pcap \
  RATE=$RATE replay_count=1
```

# Block 18 — traditional_bf1m_cms256x1024, trace 130200

**Terminal A:**
```bash
$SDE/run_switchd.sh -p traditional_bf1m_cms256x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_traditional_bf1m_cms256x1024/setup_table.py
EOF

mkdir -p ~/results_lazy_vs_traditional_bf/130200/traditional_bf1m_cms256x1024
~/dainius/cpp_traditional_bf1m_cms256x1024/traditional_bf1m_cms256x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_lazy_vs_traditional_bf/130200/traditional_bf1m_cms256x1024/est_chunk_00000.csv 2>&1 \
  | tee /tmp/traditional_bf1m_130200.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130200_chunk5M/chunk_00000_legacy.pcap \
  RATE=$RATE replay_count=1
```

---

# Block 19 — traditional_bf2m_cms256x1024, trace 130100

**Terminal A:**
```bash
$SDE/run_switchd.sh -p traditional_bf2m_cms256x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_traditional_bf2m_cms256x1024/setup_table.py
EOF

mkdir -p ~/results_lazy_vs_traditional_bf/130100/traditional_bf2m_cms256x1024
~/dainius/cpp_traditional_bf2m_cms256x1024/traditional_bf2m_cms256x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_lazy_vs_traditional_bf/130100/traditional_bf2m_cms256x1024/est_chunk_00000.csv 2>&1 \
  | tee /tmp/traditional_bf2m_130100.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130100_chunk5M/chunk_00000_legacy.pcap \
  RATE=$RATE replay_count=1
```

# Block 20 — traditional_bf2m_cms256x1024, trace 130200

**Terminal A:**
```bash
$SDE/run_switchd.sh -p traditional_bf2m_cms256x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_traditional_bf2m_cms256x1024/setup_table.py
EOF

mkdir -p ~/results_lazy_vs_traditional_bf/130200/traditional_bf2m_cms256x1024
~/dainius/cpp_traditional_bf2m_cms256x1024/traditional_bf2m_cms256x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_lazy_vs_traditional_bf/130200/traditional_bf2m_cms256x1024/est_chunk_00000.csv 2>&1 \
  | tee /tmp/traditional_bf2m_130200.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130200_chunk5M/chunk_00000_legacy.pcap \
  RATE=$RATE replay_count=1
```

---

# After all 20 — pull to VM and summarise

```bash
# pull estimates (both traces)
for trace in 130100 130200; do
  for v in lazy_bf{131k,262k,524k,1m,2m}_cms256x1024 \
           traditional_bf{131k,262k,524k,1m,2m}_cms256x1024; do
      mkdir -p /home/student/Desktop/flowlidar/results/lazy_vs_traditional_bf/${trace}/${v}
      scp onie.two.hotpot:~/results_lazy_vs_traditional_bf/${trace}/${v}/est_chunk_00000.csv \
          /home/student/Desktop/flowlidar/results/lazy_vs_traditional_bf/${trace}/${v}/
  done
done

# pull truth CSVs
for trace in 130100 130200; do
    mkdir -p /home/student/Desktop/flowlidar/results/lazy_vs_traditional_bf/${trace}
    scp dgelzini@hotpot.win.tue.nl:/home2/dgelzini/chunks/${trace}_chunk5M/chunk0_truth.csv \
        /home/student/Desktop/flowlidar/results/lazy_vs_traditional_bf/${trace}/
done

# build per-trace summary CSVs
cd /home/student/Desktop/flowlidar
for trace in 130100 130200; do
    SUM=results/lazy_vs_traditional_bf/${trace}/summary_chunk0.csv
    > $SUM
    for v in lazy_bf{131k,262k,524k,1m,2m}_cms256x1024 \
             traditional_bf{131k,262k,524k,1m,2m}_cms256x1024; do
        python3 evaluation/harness/compare.py \
          results/lazy_vs_traditional_bf/${trace}/chunk0_truth.csv \
          results/lazy_vs_traditional_bf/${trace}/${v}/est_chunk_00000.csv \
          $SUM \
          --meta variant=$v,trace=$trace,chunk=00000
    done
done
```

## Estimated wall time

| Step | Time |
|---|---|
| Per run: switchd boot (~3 min) + setup (~30 s) + epoch (~25 s) + bulk read (~5 s) | ~4 min |
| **Total all 20 runs** | **~80 min** |

5M is light. The bottleneck is switchd boot, not the actual computation.
