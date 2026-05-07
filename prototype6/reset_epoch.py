# FlowLiDAR Prototype 6 — epoch reset
# Clears all BF and CMS register arrays to start a new measurement epoch.
# Run with: bfshell> bfrt_python /home/student/Desktop/flowlidar/prototype6/reset_epoch.py

p4 = bfrt.prototype6.pipe

# Clear Bloom Filter arrays
p4.SwitchIngress.bf_0.clear()
p4.SwitchIngress.bf_1.clear()
p4.SwitchIngress.bf_2.clear()

# Clear Count-Min Sketch arrays (now 65536 cells per row)
p4.SwitchIngress.cms_0.clear()
p4.SwitchIngress.cms_1.clear()
p4.SwitchIngress.cms_2.clear()

print("BF + CMS cleared — new epoch started.")
