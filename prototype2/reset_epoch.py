# FlowLiDAR Prototype 2 — epoch reset
# Clears all 4 BF register arrays to start a new measurement epoch.
# Run with: bfshell> bfrt_python /home/student/Desktop/flowlidar/prototype2/reset_epoch.py

p4 = bfrt.prototype2.pipe

p4.SwitchIngress.bf_0.clear()
p4.SwitchIngress.bf_1.clear()
p4.SwitchIngress.bf_2.clear()
p4.SwitchIngress.bf_3.clear()

print("BF reset complete — new epoch started.")
