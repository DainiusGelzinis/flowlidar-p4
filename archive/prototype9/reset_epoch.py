# FlowLiDAR Prototype 9 — epoch reset (Traditional BF baseline, 131072 cells/array)
# Clears all BF and CMS register arrays to start a new measurement epoch.
# Run with: bfshell> bfrt_python /home/student/Desktop/flowlidar/prototype9/reset_epoch.py

p4 = bfrt.prototype9.pipe

# Clear Bloom Filter arrays (3 × 131072 cells, traditional BF)
p4.SwitchIngress.bf_0.clear()
p4.SwitchIngress.bf_1.clear()
p4.SwitchIngress.bf_2.clear()

# Clear Count-Min Sketch arrays (3 × 65536 cells, sub-sketch partitioned)
p4.SwitchIngress.cms_0.clear()
p4.SwitchIngress.cms_1.clear()
p4.SwitchIngress.cms_2.clear()

print("BF + CMS cleared — new epoch started.")
