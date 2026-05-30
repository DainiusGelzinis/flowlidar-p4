# Phase 3 — Multi-trace E8 sweep (traces 130100 + 130200)

Repeats the existing E8 sweep from `runbook.md` against two additional
1-minute CAIDA traces (13:01 and 13:02 UTC). Adds variance bars to the
1M-16M load-sweep plots without re-running 130000.

5 loads × 2 variants × 2 traces = **20 runs**. 32M is intentionally
out of scope. P4 + CP are already built on the switch from the 130000
sweep.

Order: 130100 lazy → 130100 trad → 130200 lazy → 130200 trad.

---

## One-time shell setup

**Switch terminal A and B (paste once per ssh session):**
```bash
ssh onie.two.hotpot
export BF_IDS=2338372543,2333775667,2347111112
export CMS_IDS=2346354927,2339499036,2335880110
```

**Hotpot (paste once per ssh session):**
```bash
ssh dgelzini@hotpot.win.tue.nl
RATE=2Gbps
```

---

## Run pattern (applies to every block below)

1. **Terminal A:** start switchd line.
2. **Terminal B:** wait for switchd "INFO: Ready" → run the `bfshell` block
   (it enters bfrt_python, runs setup_table, exits, then runs the CP).
3. **Hotpot:** when CP prints "Listening for digests" → run the replay line.
4. **After CP exits (clean stats printed):** Ctrl+\ in Terminal A.

Sanity check after each run:
```bash
grep -E "Resolved by Alg|Sub-sketch buckets|cms_[012] :" /tmp/$LOG
```

---

# Group 1 — 130100 × lazy_bf2m_cms64x1024

## Run 1/20 — 130100 lazy 1M

**Terminal A:**
```bash
$SDE/run_switchd.sh -p lazy_bf2m_cms64x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_lazy_bf2m_cms64x1024/setup_table.py
EOF

mkdir -p ~/results_traffic_load_test/130100/lazy_bf2m_cms64x1024
~/dainius/cpp_lazy_bf2m_cms64x1024/lazy_bf2m_cms64x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_traffic_load_test/130100/lazy_bf2m_cms64x1024/est_load_1000000.csv 2>&1 \
  | tee /tmp/lazy_130100_load1000000.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130100_loads/load_1000000_legacy.pcap \
  RATE=$RATE replay_count=1
```

## Run 2/20 — 130100 lazy 2M

**Terminal A:**
```bash
$SDE/run_switchd.sh -p lazy_bf2m_cms64x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_lazy_bf2m_cms64x1024/setup_table.py
EOF

~/dainius/cpp_lazy_bf2m_cms64x1024/lazy_bf2m_cms64x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_traffic_load_test/130100/lazy_bf2m_cms64x1024/est_load_2000000.csv 2>&1 \
  | tee /tmp/lazy_130100_load2000000.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130100_loads/load_2000000_legacy.pcap \
  RATE=$RATE replay_count=1
```

## Run 3/20 — 130100 lazy 4M

**Terminal A:**
```bash
$SDE/run_switchd.sh -p lazy_bf2m_cms64x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_lazy_bf2m_cms64x1024/setup_table.py
EOF

~/dainius/cpp_lazy_bf2m_cms64x1024/lazy_bf2m_cms64x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_traffic_load_test/130100/lazy_bf2m_cms64x1024/est_load_4000000.csv 2>&1 \
  | tee /tmp/lazy_130100_load4000000.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130100_loads/load_4000000_legacy.pcap \
  RATE=$RATE replay_count=1
```

## Run 4/20 — 130100 lazy 8M

**Terminal A:**
```bash
$SDE/run_switchd.sh -p lazy_bf2m_cms64x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_lazy_bf2m_cms64x1024/setup_table.py
EOF

~/dainius/cpp_lazy_bf2m_cms64x1024/lazy_bf2m_cms64x1024_cp \
  --epoch 30 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_traffic_load_test/130100/lazy_bf2m_cms64x1024/est_load_8000000.csv 2>&1 \
  | tee /tmp/lazy_130100_load8000000.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130100_loads/load_8000000_legacy.pcap \
  RATE=$RATE replay_count=1
```

## Run 5/20 — 130100 lazy 16M

**Terminal A:**
```bash
$SDE/run_switchd.sh -p lazy_bf2m_cms64x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_lazy_bf2m_cms64x1024/setup_table.py
EOF

~/dainius/cpp_lazy_bf2m_cms64x1024/lazy_bf2m_cms64x1024_cp \
  --epoch 45 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_traffic_load_test/130100/lazy_bf2m_cms64x1024/est_load_16000000.csv 2>&1 \
  | tee /tmp/lazy_130100_load16000000.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130100_loads/load_16000000_legacy.pcap \
  RATE=$RATE replay_count=1
```

---

# Group 2 — 130100 × traditional_bf2m_cms64x1024

## Run 6/20 — 130100 trad 1M

**Terminal A:**
```bash
$SDE/run_switchd.sh -p traditional_bf2m_cms64x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_traditional_bf2m_cms64x1024/setup_table.py
EOF

mkdir -p ~/results_traffic_load_test/130100/traditional_bf2m_cms64x1024
~/dainius/cpp_traditional_bf2m_cms64x1024/traditional_bf2m_cms64x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_traffic_load_test/130100/traditional_bf2m_cms64x1024/est_load_1000000.csv 2>&1 \
  | tee /tmp/trad_130100_load1000000.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130100_loads/load_1000000_legacy.pcap \
  RATE=$RATE replay_count=1
```

## Run 7/20 — 130100 trad 2M

**Terminal A:**
```bash
$SDE/run_switchd.sh -p traditional_bf2m_cms64x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_traditional_bf2m_cms64x1024/setup_table.py
EOF

~/dainius/cpp_traditional_bf2m_cms64x1024/traditional_bf2m_cms64x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_traffic_load_test/130100/traditional_bf2m_cms64x1024/est_load_2000000.csv 2>&1 \
  | tee /tmp/trad_130100_load2000000.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130100_loads/load_2000000_legacy.pcap \
  RATE=$RATE replay_count=1
```

## Run 8/20 — 130100 trad 4M

**Terminal A:**
```bash
$SDE/run_switchd.sh -p traditional_bf2m_cms64x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_traditional_bf2m_cms64x1024/setup_table.py
EOF

~/dainius/cpp_traditional_bf2m_cms64x1024/traditional_bf2m_cms64x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_traffic_load_test/130100/traditional_bf2m_cms64x1024/est_load_4000000.csv 2>&1 \
  | tee /tmp/trad_130100_load4000000.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130100_loads/load_4000000_legacy.pcap \
  RATE=$RATE replay_count=1
```

## Run 9/20 — 130100 trad 8M

**Terminal A:**
```bash
$SDE/run_switchd.sh -p traditional_bf2m_cms64x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_traditional_bf2m_cms64x1024/setup_table.py
EOF

~/dainius/cpp_traditional_bf2m_cms64x1024/traditional_bf2m_cms64x1024_cp \
  --epoch 30 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_traffic_load_test/130100/traditional_bf2m_cms64x1024/est_load_8000000.csv 2>&1 \
  | tee /tmp/trad_130100_load8000000.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130100_loads/load_8000000_legacy.pcap \
  RATE=$RATE replay_count=1
```

## Run 10/20 — 130100 trad 16M

**Terminal A:**
```bash
$SDE/run_switchd.sh -p traditional_bf2m_cms64x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_traditional_bf2m_cms64x1024/setup_table.py
EOF

~/dainius/cpp_traditional_bf2m_cms64x1024/traditional_bf2m_cms64x1024_cp \
  --epoch 45 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_traffic_load_test/130100/traditional_bf2m_cms64x1024/est_load_16000000.csv 2>&1 \
  | tee /tmp/trad_130100_load16000000.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130100_loads/load_16000000_legacy.pcap \
  RATE=$RATE replay_count=1
```

---

# Group 3 — 130200 × lazy_bf2m_cms64x1024

## Run 11/20 — 130200 lazy 1M

**Terminal A:**
```bash
$SDE/run_switchd.sh -p lazy_bf2m_cms64x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_lazy_bf2m_cms64x1024/setup_table.py
EOF

mkdir -p ~/results_traffic_load_test/130200/lazy_bf2m_cms64x1024
~/dainius/cpp_lazy_bf2m_cms64x1024/lazy_bf2m_cms64x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_traffic_load_test/130200/lazy_bf2m_cms64x1024/est_load_1000000.csv 2>&1 \
  | tee /tmp/lazy_130200_load1000000.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130200_loads/load_1000000_legacy.pcap \
  RATE=$RATE replay_count=1
```

## Run 12/20 — 130200 lazy 2M

**Terminal A:**
```bash
$SDE/run_switchd.sh -p lazy_bf2m_cms64x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_lazy_bf2m_cms64x1024/setup_table.py
EOF

~/dainius/cpp_lazy_bf2m_cms64x1024/lazy_bf2m_cms64x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_traffic_load_test/130200/lazy_bf2m_cms64x1024/est_load_2000000.csv 2>&1 \
  | tee /tmp/lazy_130200_load2000000.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130200_loads/load_2000000_legacy.pcap \
  RATE=$RATE replay_count=1
```

## Run 13/20 — 130200 lazy 4M

**Terminal A:**
```bash
$SDE/run_switchd.sh -p lazy_bf2m_cms64x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_lazy_bf2m_cms64x1024/setup_table.py
EOF

~/dainius/cpp_lazy_bf2m_cms64x1024/lazy_bf2m_cms64x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_traffic_load_test/130200/lazy_bf2m_cms64x1024/est_load_4000000.csv 2>&1 \
  | tee /tmp/lazy_130200_load4000000.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130200_loads/load_4000000_legacy.pcap \
  RATE=$RATE replay_count=1
```

## Run 14/20 — 130200 lazy 8M

**Terminal A:**
```bash
$SDE/run_switchd.sh -p lazy_bf2m_cms64x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_lazy_bf2m_cms64x1024/setup_table.py
EOF

~/dainius/cpp_lazy_bf2m_cms64x1024/lazy_bf2m_cms64x1024_cp \
  --epoch 30 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_traffic_load_test/130200/lazy_bf2m_cms64x1024/est_load_8000000.csv 2>&1 \
  | tee /tmp/lazy_130200_load8000000.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130200_loads/load_8000000_legacy.pcap \
  RATE=$RATE replay_count=1
```

## Run 15/20 — 130200 lazy 16M

**Terminal A:**
```bash
$SDE/run_switchd.sh -p lazy_bf2m_cms64x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_lazy_bf2m_cms64x1024/setup_table.py
EOF

~/dainius/cpp_lazy_bf2m_cms64x1024/lazy_bf2m_cms64x1024_cp \
  --epoch 45 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_traffic_load_test/130200/lazy_bf2m_cms64x1024/est_load_16000000.csv 2>&1 \
  | tee /tmp/lazy_130200_load16000000.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130200_loads/load_16000000_legacy.pcap \
  RATE=$RATE replay_count=1
```

---

# Group 4 — 130200 × traditional_bf2m_cms64x1024

## Run 16/20 — 130200 trad 1M

**Terminal A:**
```bash
$SDE/run_switchd.sh -p traditional_bf2m_cms64x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_traditional_bf2m_cms64x1024/setup_table.py
EOF

mkdir -p ~/results_traffic_load_test/130200/traditional_bf2m_cms64x1024
~/dainius/cpp_traditional_bf2m_cms64x1024/traditional_bf2m_cms64x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_traffic_load_test/130200/traditional_bf2m_cms64x1024/est_load_1000000.csv 2>&1 \
  | tee /tmp/trad_130200_load1000000.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130200_loads/load_1000000_legacy.pcap \
  RATE=$RATE replay_count=1
```

## Run 17/20 — 130200 trad 2M

**Terminal A:**
```bash
$SDE/run_switchd.sh -p traditional_bf2m_cms64x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_traditional_bf2m_cms64x1024/setup_table.py
EOF

~/dainius/cpp_traditional_bf2m_cms64x1024/traditional_bf2m_cms64x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_traffic_load_test/130200/traditional_bf2m_cms64x1024/est_load_2000000.csv 2>&1 \
  | tee /tmp/trad_130200_load2000000.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130200_loads/load_2000000_legacy.pcap \
  RATE=$RATE replay_count=1
```

## Run 18/20 — 130200 trad 4M

**Terminal A:**
```bash
$SDE/run_switchd.sh -p traditional_bf2m_cms64x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_traditional_bf2m_cms64x1024/setup_table.py
EOF

~/dainius/cpp_traditional_bf2m_cms64x1024/traditional_bf2m_cms64x1024_cp \
  --epoch 20 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_traffic_load_test/130200/traditional_bf2m_cms64x1024/est_load_4000000.csv 2>&1 \
  | tee /tmp/trad_130200_load4000000.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130200_loads/load_4000000_legacy.pcap \
  RATE=$RATE replay_count=1
```

## Run 19/20 — 130200 trad 8M

**Terminal A:**
```bash
$SDE/run_switchd.sh -p traditional_bf2m_cms64x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_traditional_bf2m_cms64x1024/setup_table.py
EOF

~/dainius/cpp_traditional_bf2m_cms64x1024/traditional_bf2m_cms64x1024_cp \
  --epoch 30 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_traffic_load_test/130200/traditional_bf2m_cms64x1024/est_load_8000000.csv 2>&1 \
  | tee /tmp/trad_130200_load8000000.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130200_loads/load_8000000_legacy.pcap \
  RATE=$RATE replay_count=1
```

## Run 20/20 — 130200 trad 16M

**Terminal A:**
```bash
$SDE/run_switchd.sh -p traditional_bf2m_cms64x1024
```

**Terminal B:**
```bash
bfshell <<'EOF'
bfrt_python /home/onie/dainius/cpp_traditional_bf2m_cms64x1024/setup_table.py
EOF

~/dainius/cpp_traditional_bf2m_cms64x1024/traditional_bf2m_cms64x1024_cp \
  --epoch 45 --pipe 1 --epochs 1 \
  --bf-ids $BF_IDS --cms-ids $CMS_IDS \
  --csv-out ~/results_traffic_load_test/130200/traditional_bf2m_cms64x1024/est_load_16000000.csv 2>&1 \
  | tee /tmp/trad_130200_load16000000.log
```

**Hotpot:**
```bash
/opt/p4eval/bin/click --dpdk -a 0000:ac:00.0 -l 0-3 -- \
  ~/simple_pcap_replay.click \
  trace=/home2/dgelzini/chunks/130200_loads/load_16000000_legacy.pcap \
  RATE=$RATE replay_count=1
```

---

# After all 20 runs — pull to VM

```bash
# from VM — pull estimates
for trace in 130100 130200; do
  for v in lazy_bf2m_cms64x1024 traditional_bf2m_cms64x1024; do
    for n in 1000000 2000000 4000000 8000000 16000000; do
        mkdir -p /home/student/Desktop/flowlidar/results/traffic_load_test/${trace}/${v}
        scp onie.two.hotpot:~/results_traffic_load_test/${trace}/${v}/est_load_${n}.csv \
            /home/student/Desktop/flowlidar/results/traffic_load_test/${trace}/${v}/
    done
  done
done

# pull truth CSVs (from hotpot — different host)
for trace in 130100 130200; do
    mkdir -p /home/student/Desktop/flowlidar/results/traffic_load_test/${trace}
    for n in 1000000 2000000 4000000 8000000 16000000; do
        scp dgelzini@hotpot.win.tue.nl:/home2/dgelzini/chunks/${trace}_loads/load_${n}_truth.csv \
            /home/student/Desktop/flowlidar/results/traffic_load_test/${trace}/
    done
done

# build per-trace summary CSVs
cd /home/student/Desktop/flowlidar
for trace in 130100 130200; do
    SUM=results/traffic_load_test/${trace}/summary.csv
    > $SUM
    for v in lazy_bf2m_cms64x1024 traditional_bf2m_cms64x1024; do
        for n in 1000000 2000000 4000000 8000000 16000000; do
            python3 evaluation/harness/compare.py \
              results/traffic_load_test/${trace}/load_${n}_truth.csv \
              results/traffic_load_test/${trace}/${v}/est_load_${n}.csv \
              $SUM \
              --meta variant=$v,load=$n,trace=$trace
        done
    done
done
```

---

## Estimated wall time

| Phase | Time |
|---|---|
| 5 light runs (1-4M) per group, ~5 min each | 25 min × 4 = 100 min |
| 2 heavy runs (8-16M) per group, ~12 min each | 24 min × 4 = 100 min |
| **Total all 20 runs** | **~3.5 hours** |
