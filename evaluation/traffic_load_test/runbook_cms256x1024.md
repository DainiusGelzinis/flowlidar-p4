# Runbook — E8 traffic-load sweep with CMS=256×1024×3 (3 traces)

Same shape as the original cms64x1024 E8 + phase 3, but uses the
paper-aligned 256×1024 CMS layout. 4× more buckets means per-bucket load
is 4× lighter — alg6 should rarely fire, validating FlowLiDAR's
coverage/ARE under the layout actually used in the paper.

5 loads × 2 variants × 3 traces = **30 runs**.

Both P4 programs (`lazy_bf2m_cms256x1024`, `traditional_bf2m_cms256x1024`)
are already built on the switch from the 10-variant sweep. No rebuild.

Order: trace-major (full 10 runs of 130000, then 130100, then 130200),
matching the phase-3 pattern.

## One-time shell setup

**Switch:**
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

## Pcap + truth paths (all already on hotpot)

```
/home2/dgelzini/chunks/130000_loads/load_{1000000,2000000,4000000,8000000,16000000}_legacy.pcap
/home2/dgelzini/chunks/130100_loads/load_{1000000,2000000,4000000,8000000,16000000}_legacy.pcap
/home2/dgelzini/chunks/130200_loads/load_{1000000,2000000,4000000,8000000,16000000}_legacy.pcap
```

## Per-load epoch table (same as cms64x1024 E8)

| Load | `--epoch` |
|---|---:|
| 1M  | 20 |
| 2M  | 20 |
| 4M  | 20 |
| 8M  | 30 |
| 16M | 45 |

Heavy runs should finish quicker than cms64 E8 because alg6 will mostly
not fire — solver phase becomes cheap.

## Run pattern (every block)

1. Terminal A: start switchd.
2. Terminal B: wait for "Ready", paste bfshell + CP.
3. Hotpot: when CP prints "Listening for digests", paste replay.
4. After CP exits: Ctrl+\ in Terminal A.

Sanity check:
```bash
grep -E "Resolved by Alg|Sub-sketch buckets|cms_[012] :" /tmp/$LOG
```

Expected: `exact: 256, Alg6 approx: 0` for lazy across all loads.
Trad may start firing alg6 around 8-16M.

---

# Group 1 — trace 130000 × lazy

## Run 1/30 — 130000 lazy 1M

**Terminal A:**
```bash
$SDE/run_switchd.sh -p lazy_bf2m_cms256x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_lazy_bf2m_cms256x1024/setup_table.py
EOF

mkdir -p ~/results_traffic_load_test_cms256/130000/lazy_bf2m_cms256x1024
~/dainius/cpp_lazy_bf2m_cms256x1024/lazy_bf2m_cms256x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_traffic_load_test_cms256/130000/lazy_bf2m_cms256x1024/est_load_1000000.csv 2>&1 \
  | tee /tmp/lazy256_130000_load1000000.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130000_loads/load_1000000_legacy.pcap \
  RATE=$RATE replay_count=1
```

## Run 2/30 — 130000 lazy 2M

**Terminal A:**
```bash
$SDE/run_switchd.sh -p lazy_bf2m_cms256x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_lazy_bf2m_cms256x1024/setup_table.py
EOF

~/dainius/cpp_lazy_bf2m_cms256x1024/lazy_bf2m_cms256x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_traffic_load_test_cms256/130000/lazy_bf2m_cms256x1024/est_load_2000000.csv 2>&1 \
  | tee /tmp/lazy256_130000_load2000000.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130000_loads/load_2000000_legacy.pcap \
  RATE=$RATE replay_count=1
```

## Run 3/30 — 130000 lazy 4M

**Terminal A:**
```bash
$SDE/run_switchd.sh -p lazy_bf2m_cms256x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_lazy_bf2m_cms256x1024/setup_table.py
EOF

~/dainius/cpp_lazy_bf2m_cms256x1024/lazy_bf2m_cms256x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_traffic_load_test_cms256/130000/lazy_bf2m_cms256x1024/est_load_4000000.csv 2>&1 \
  | tee /tmp/lazy256_130000_load4000000.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130000_loads/load_4000000_legacy.pcap \
  RATE=$RATE replay_count=1
```

## Run 4/30 — 130000 lazy 8M

**Terminal A:**
```bash
$SDE/run_switchd.sh -p lazy_bf2m_cms256x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_lazy_bf2m_cms256x1024/setup_table.py
EOF

~/dainius/cpp_lazy_bf2m_cms256x1024/lazy_bf2m_cms256x1024_cp \
  --epoch 30 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_traffic_load_test_cms256/130000/lazy_bf2m_cms256x1024/est_load_8000000.csv 2>&1 \
  | tee /tmp/lazy256_130000_load8000000.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130000_loads/load_8000000_legacy.pcap \
  RATE=$RATE replay_count=1
```

## Run 5/30 — 130000 lazy 16M

**Terminal A:**
```bash
$SDE/run_switchd.sh -p lazy_bf2m_cms256x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_lazy_bf2m_cms256x1024/setup_table.py
EOF

~/dainius/cpp_lazy_bf2m_cms256x1024/lazy_bf2m_cms256x1024_cp \
  --epoch 45 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_traffic_load_test_cms256/130000/lazy_bf2m_cms256x1024/est_load_16000000.csv 2>&1 \
  | tee /tmp/lazy256_130000_load16000000.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130000_loads/load_16000000_legacy.pcap \
  RATE=$RATE replay_count=1
```

---

# Group 2 — trace 130000 × traditional

## Run 6/30 — 130000 trad 1M

**Terminal A:**
```bash
$SDE/run_switchd.sh -p traditional_bf2m_cms256x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_traditional_bf2m_cms256x1024/setup_table.py
EOF

mkdir -p ~/results_traffic_load_test_cms256/130000/traditional_bf2m_cms256x1024
~/dainius/cpp_traditional_bf2m_cms256x1024/traditional_bf2m_cms256x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_traffic_load_test_cms256/130000/traditional_bf2m_cms256x1024/est_load_1000000.csv 2>&1 \
  | tee /tmp/trad256_130000_load1000000.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130000_loads/load_1000000_legacy.pcap \
  RATE=$RATE replay_count=1
```

## Run 7/30 — 130000 trad 2M

**Terminal A:**
```bash
$SDE/run_switchd.sh -p traditional_bf2m_cms256x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_traditional_bf2m_cms256x1024/setup_table.py
EOF

~/dainius/cpp_traditional_bf2m_cms256x1024/traditional_bf2m_cms256x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_traffic_load_test_cms256/130000/traditional_bf2m_cms256x1024/est_load_2000000.csv 2>&1 \
  | tee /tmp/trad256_130000_load2000000.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130000_loads/load_2000000_legacy.pcap \
  RATE=$RATE replay_count=1
```

## Run 8/30 — 130000 trad 4M

**Terminal A:**
```bash
$SDE/run_switchd.sh -p traditional_bf2m_cms256x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_traditional_bf2m_cms256x1024/setup_table.py
EOF

~/dainius/cpp_traditional_bf2m_cms256x1024/traditional_bf2m_cms256x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_traffic_load_test_cms256/130000/traditional_bf2m_cms256x1024/est_load_4000000.csv 2>&1 \
  | tee /tmp/trad256_130000_load4000000.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130000_loads/load_4000000_legacy.pcap \
  RATE=$RATE replay_count=1
```

## Run 9/30 — 130000 trad 8M

**Terminal A:**
```bash
$SDE/run_switchd.sh -p traditional_bf2m_cms256x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_traditional_bf2m_cms256x1024/setup_table.py
EOF

~/dainius/cpp_traditional_bf2m_cms256x1024/traditional_bf2m_cms256x1024_cp \
  --epoch 30 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_traffic_load_test_cms256/130000/traditional_bf2m_cms256x1024/est_load_8000000.csv 2>&1 \
  | tee /tmp/trad256_130000_load8000000.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130000_loads/load_8000000_legacy.pcap \
  RATE=$RATE replay_count=1
```

## Run 10/30 — 130000 trad 16M

**Terminal A:**
```bash
$SDE/run_switchd.sh -p traditional_bf2m_cms256x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_traditional_bf2m_cms256x1024/setup_table.py
EOF

~/dainius/cpp_traditional_bf2m_cms256x1024/traditional_bf2m_cms256x1024_cp \
  --epoch 45 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_traffic_load_test_cms256/130000/traditional_bf2m_cms256x1024/est_load_16000000.csv 2>&1 \
  | tee /tmp/trad256_130000_load16000000.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130000_loads/load_16000000_legacy.pcap \
  RATE=$RATE replay_count=1
```

---

# Group 3 — trace 130100 × lazy

## Run 11/30 — 130100 lazy 1M

**Terminal A:**
```bash
$SDE/run_switchd.sh -p lazy_bf2m_cms256x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_lazy_bf2m_cms256x1024/setup_table.py
EOF

mkdir -p ~/results_traffic_load_test_cms256/130100/lazy_bf2m_cms256x1024
~/dainius/cpp_lazy_bf2m_cms256x1024/lazy_bf2m_cms256x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_traffic_load_test_cms256/130100/lazy_bf2m_cms256x1024/est_load_1000000.csv 2>&1 \
  | tee /tmp/lazy256_130100_load1000000.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130100_loads/load_1000000_legacy.pcap \
  RATE=$RATE replay_count=1
```

## Run 12/30 — 130100 lazy 2M

**Terminal A:**
```bash
$SDE/run_switchd.sh -p lazy_bf2m_cms256x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_lazy_bf2m_cms256x1024/setup_table.py
EOF

~/dainius/cpp_lazy_bf2m_cms256x1024/lazy_bf2m_cms256x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_traffic_load_test_cms256/130100/lazy_bf2m_cms256x1024/est_load_2000000.csv 2>&1 \
  | tee /tmp/lazy256_130100_load2000000.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130100_loads/load_2000000_legacy.pcap \
  RATE=$RATE replay_count=1
```

## Run 13/30 — 130100 lazy 4M

**Terminal A:**
```bash
$SDE/run_switchd.sh -p lazy_bf2m_cms256x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_lazy_bf2m_cms256x1024/setup_table.py
EOF

~/dainius/cpp_lazy_bf2m_cms256x1024/lazy_bf2m_cms256x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_traffic_load_test_cms256/130100/lazy_bf2m_cms256x1024/est_load_4000000.csv 2>&1 \
  | tee /tmp/lazy256_130100_load4000000.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130100_loads/load_4000000_legacy.pcap \
  RATE=$RATE replay_count=1
```

## Run 14/30 — 130100 lazy 8M

**Terminal A:**
```bash
$SDE/run_switchd.sh -p lazy_bf2m_cms256x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_lazy_bf2m_cms256x1024/setup_table.py
EOF

~/dainius/cpp_lazy_bf2m_cms256x1024/lazy_bf2m_cms256x1024_cp \
  --epoch 30 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_traffic_load_test_cms256/130100/lazy_bf2m_cms256x1024/est_load_8000000.csv 2>&1 \
  | tee /tmp/lazy256_130100_load8000000.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130100_loads/load_8000000_legacy.pcap \
  RATE=$RATE replay_count=1
```

## Run 15/30 — 130100 lazy 16M

**Terminal A:**
```bash
$SDE/run_switchd.sh -p lazy_bf2m_cms256x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_lazy_bf2m_cms256x1024/setup_table.py
EOF

~/dainius/cpp_lazy_bf2m_cms256x1024/lazy_bf2m_cms256x1024_cp \
  --epoch 45 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_traffic_load_test_cms256/130100/lazy_bf2m_cms256x1024/est_load_16000000.csv 2>&1 \
  | tee /tmp/lazy256_130100_load16000000.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130100_loads/load_16000000_legacy.pcap \
  RATE=$RATE replay_count=1
```

---

# Group 4 — trace 130100 × traditional

## Run 16/30 — 130100 trad 1M

**Terminal A:**
```bash
$SDE/run_switchd.sh -p traditional_bf2m_cms256x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_traditional_bf2m_cms256x1024/setup_table.py
EOF

mkdir -p ~/results_traffic_load_test_cms256/130100/traditional_bf2m_cms256x1024
~/dainius/cpp_traditional_bf2m_cms256x1024/traditional_bf2m_cms256x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_traffic_load_test_cms256/130100/traditional_bf2m_cms256x1024/est_load_1000000.csv 2>&1 \
  | tee /tmp/trad256_130100_load1000000.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130100_loads/load_1000000_legacy.pcap \
  RATE=$RATE replay_count=1
```

## Run 17/30 — 130100 trad 2M

**Terminal A:**
```bash
$SDE/run_switchd.sh -p traditional_bf2m_cms256x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_traditional_bf2m_cms256x1024/setup_table.py
EOF

~/dainius/cpp_traditional_bf2m_cms256x1024/traditional_bf2m_cms256x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_traffic_load_test_cms256/130100/traditional_bf2m_cms256x1024/est_load_2000000.csv 2>&1 \
  | tee /tmp/trad256_130100_load2000000.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130100_loads/load_2000000_legacy.pcap \
  RATE=$RATE replay_count=1
```

## Run 18/30 — 130100 trad 4M

**Terminal A:**
```bash
$SDE/run_switchd.sh -p traditional_bf2m_cms256x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_traditional_bf2m_cms256x1024/setup_table.py
EOF

~/dainius/cpp_traditional_bf2m_cms256x1024/traditional_bf2m_cms256x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_traffic_load_test_cms256/130100/traditional_bf2m_cms256x1024/est_load_4000000.csv 2>&1 \
  | tee /tmp/trad256_130100_load4000000.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130100_loads/load_4000000_legacy.pcap \
  RATE=$RATE replay_count=1
```

## Run 19/30 — 130100 trad 8M

**Terminal A:**
```bash
$SDE/run_switchd.sh -p traditional_bf2m_cms256x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_traditional_bf2m_cms256x1024/setup_table.py
EOF

~/dainius/cpp_traditional_bf2m_cms256x1024/traditional_bf2m_cms256x1024_cp \
  --epoch 30 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_traffic_load_test_cms256/130100/traditional_bf2m_cms256x1024/est_load_8000000.csv 2>&1 \
  | tee /tmp/trad256_130100_load8000000.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130100_loads/load_8000000_legacy.pcap \
  RATE=$RATE replay_count=1
```

## Run 20/30 — 130100 trad 16M

**Terminal A:**
```bash
$SDE/run_switchd.sh -p traditional_bf2m_cms256x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_traditional_bf2m_cms256x1024/setup_table.py
EOF

~/dainius/cpp_traditional_bf2m_cms256x1024/traditional_bf2m_cms256x1024_cp \
  --epoch 45 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_traffic_load_test_cms256/130100/traditional_bf2m_cms256x1024/est_load_16000000.csv 2>&1 \
  | tee /tmp/trad256_130100_load16000000.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130100_loads/load_16000000_legacy.pcap \
  RATE=$RATE replay_count=1
```

---

# Group 5 — trace 130200 × lazy

## Run 21/30 — 130200 lazy 1M

**Terminal A:**
```bash
$SDE/run_switchd.sh -p lazy_bf2m_cms256x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_lazy_bf2m_cms256x1024/setup_table.py
EOF

mkdir -p ~/results_traffic_load_test_cms256/130200/lazy_bf2m_cms256x1024
~/dainius/cpp_lazy_bf2m_cms256x1024/lazy_bf2m_cms256x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_traffic_load_test_cms256/130200/lazy_bf2m_cms256x1024/est_load_1000000.csv 2>&1 \
  | tee /tmp/lazy256_130200_load1000000.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130200_loads/load_1000000_legacy.pcap \
  RATE=$RATE replay_count=1
```

## Run 22/30 — 130200 lazy 2M

**Terminal A:**
```bash
$SDE/run_switchd.sh -p lazy_bf2m_cms256x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_lazy_bf2m_cms256x1024/setup_table.py
EOF

~/dainius/cpp_lazy_bf2m_cms256x1024/lazy_bf2m_cms256x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_traffic_load_test_cms256/130200/lazy_bf2m_cms256x1024/est_load_2000000.csv 2>&1 \
  | tee /tmp/lazy256_130200_load2000000.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130200_loads/load_2000000_legacy.pcap \
  RATE=$RATE replay_count=1
```

## Run 23/30 — 130200 lazy 4M

**Terminal A:**
```bash
$SDE/run_switchd.sh -p lazy_bf2m_cms256x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_lazy_bf2m_cms256x1024/setup_table.py
EOF

~/dainius/cpp_lazy_bf2m_cms256x1024/lazy_bf2m_cms256x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_traffic_load_test_cms256/130200/lazy_bf2m_cms256x1024/est_load_4000000.csv 2>&1 \
  | tee /tmp/lazy256_130200_load4000000.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130200_loads/load_4000000_legacy.pcap \
  RATE=$RATE replay_count=1
```

## Run 24/30 — 130200 lazy 8M

**Terminal A:**
```bash
$SDE/run_switchd.sh -p lazy_bf2m_cms256x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_lazy_bf2m_cms256x1024/setup_table.py
EOF

~/dainius/cpp_lazy_bf2m_cms256x1024/lazy_bf2m_cms256x1024_cp \
  --epoch 30 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_traffic_load_test_cms256/130200/lazy_bf2m_cms256x1024/est_load_8000000.csv 2>&1 \
  | tee /tmp/lazy256_130200_load8000000.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130200_loads/load_8000000_legacy.pcap \
  RATE=$RATE replay_count=1
```

## Run 25/30 — 130200 lazy 16M

**Terminal A:**
```bash
$SDE/run_switchd.sh -p lazy_bf2m_cms256x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_lazy_bf2m_cms256x1024/setup_table.py
EOF

~/dainius/cpp_lazy_bf2m_cms256x1024/lazy_bf2m_cms256x1024_cp \
  --epoch 45 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_traffic_load_test_cms256/130200/lazy_bf2m_cms256x1024/est_load_16000000.csv 2>&1 \
  | tee /tmp/lazy256_130200_load16000000.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130200_loads/load_16000000_legacy.pcap \
  RATE=$RATE replay_count=1
```

---

# Group 6 — trace 130200 × traditional

## Run 26/30 — 130200 trad 1M

**Terminal A:**
```bash
$SDE/run_switchd.sh -p traditional_bf2m_cms256x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_traditional_bf2m_cms256x1024/setup_table.py
EOF

mkdir -p ~/results_traffic_load_test_cms256/130200/traditional_bf2m_cms256x1024
~/dainius/cpp_traditional_bf2m_cms256x1024/traditional_bf2m_cms256x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_traffic_load_test_cms256/130200/traditional_bf2m_cms256x1024/est_load_1000000.csv 2>&1 \
  | tee /tmp/trad256_130200_load1000000.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130200_loads/load_1000000_legacy.pcap \
  RATE=$RATE replay_count=1
```

## Run 27/30 — 130200 trad 2M

**Terminal A:**
```bash
$SDE/run_switchd.sh -p traditional_bf2m_cms256x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_traditional_bf2m_cms256x1024/setup_table.py
EOF

~/dainius/cpp_traditional_bf2m_cms256x1024/traditional_bf2m_cms256x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_traffic_load_test_cms256/130200/traditional_bf2m_cms256x1024/est_load_2000000.csv 2>&1 \
  | tee /tmp/trad256_130200_load2000000.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130200_loads/load_2000000_legacy.pcap \
  RATE=$RATE replay_count=1
```

## Run 28/30 — 130200 trad 4M

**Terminal A:**
```bash
$SDE/run_switchd.sh -p traditional_bf2m_cms256x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_traditional_bf2m_cms256x1024/setup_table.py
EOF

~/dainius/cpp_traditional_bf2m_cms256x1024/traditional_bf2m_cms256x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_traffic_load_test_cms256/130200/traditional_bf2m_cms256x1024/est_load_4000000.csv 2>&1 \
  | tee /tmp/trad256_130200_load4000000.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130200_loads/load_4000000_legacy.pcap \
  RATE=$RATE replay_count=1
```

## Run 29/30 — 130200 trad 8M

**Terminal A:**
```bash
$SDE/run_switchd.sh -p traditional_bf2m_cms256x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_traditional_bf2m_cms256x1024/setup_table.py
EOF

~/dainius/cpp_traditional_bf2m_cms256x1024/traditional_bf2m_cms256x1024_cp \
  --epoch 30 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_traffic_load_test_cms256/130200/traditional_bf2m_cms256x1024/est_load_8000000.csv 2>&1 \
  | tee /tmp/trad256_130200_load8000000.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130200_loads/load_8000000_legacy.pcap \
  RATE=$RATE replay_count=1
```

## Run 30/30 — 130200 trad 16M

**Terminal A:**
```bash
$SDE/run_switchd.sh -p traditional_bf2m_cms256x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_traditional_bf2m_cms256x1024/setup_table.py
EOF

~/dainius/cpp_traditional_bf2m_cms256x1024/traditional_bf2m_cms256x1024_cp \
  --epoch 45 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_traffic_load_test_cms256/130200/traditional_bf2m_cms256x1024/est_load_16000000.csv 2>&1 \
  | tee /tmp/trad256_130200_load16000000.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130200_loads/load_16000000_legacy.pcap \
  RATE=$RATE replay_count=1
```

---

# After all 30 — pull to VM and summarise

```bash
# from VM — pull estimates
for trace in 130000 130100 130200; do
  for v in lazy_bf2m_cms256x1024 traditional_bf2m_cms256x1024; do
    for n in 1000000 2000000 4000000 8000000 16000000; do
        mkdir -p /home/student/Desktop/flowlidar/results/traffic_load_test_cms256/${trace}/${v}
        scp onie.two.hotpot:~/results_traffic_load_test_cms256/${trace}/${v}/est_load_${n}.csv \
            /home/student/Desktop/flowlidar/results/traffic_load_test_cms256/${trace}/${v}/
    done
  done
done

# truth CSVs: already on VM under results/traffic_load_test/
#   130000:  results/traffic_load_test/load_<N>_truth.csv
#   130100:  results/traffic_load_test/130100/load_<N>_truth.csv
#   130200:  results/traffic_load_test/130200/load_<N>_truth.csv
# Symlink them in for clean per-trace lookup:
cd /home/student/Desktop/flowlidar/results/traffic_load_test_cms256
mkdir -p 130000 130100 130200
for n in 1000000 2000000 4000000 8000000 16000000; do
    ln -sf ../../traffic_load_test/load_${n}_truth.csv         130000/load_${n}_truth.csv
    ln -sf ../../traffic_load_test/130100/load_${n}_truth.csv  130100/load_${n}_truth.csv
    ln -sf ../../traffic_load_test/130200/load_${n}_truth.csv  130200/load_${n}_truth.csv
done

# build per-trace summary CSVs
cd /home/student/Desktop/flowlidar
for trace in 130000 130100 130200; do
    SUM=results/traffic_load_test_cms256/${trace}/summary.csv
    > $SUM
    for v in lazy_bf2m_cms256x1024 traditional_bf2m_cms256x1024; do
        for n in 1000000 2000000 4000000 8000000 16000000; do
            python3 evaluation/harness/compare.py \
              results/traffic_load_test_cms256/${trace}/load_${n}_truth.csv \
              results/traffic_load_test_cms256/${trace}/${v}/est_load_${n}.csv \
              $SUM \
              --meta variant=$v,load=$n,trace=$trace
        done
    done
done
```

## Estimated wall time

| Phase | Time |
|---|---|
| 3 light runs (1-4M) per group × 6 groups, ~5 min each | ~90 min |
| 2 heavy runs (8-16M) per group × 6 groups, ~8 min each | ~95 min |
| **Total all 30 runs** | **~3 hours** |

(Heavy runs are faster than cms64 E8 because alg6 won't dominate the
solver phase — most buckets resolve exactly, which is cheap.)
