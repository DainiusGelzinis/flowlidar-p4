# FlowLiDAR Prototype 2 — control plane setup
# Inserts the forwarding rule and configures the digest.
# Run with: bfshell> bfrt_python /home/student/Desktop/flowlidar/prototype2/setup_table.py

p4 = bfrt.prototype2.pipe
tbl = p4.SwitchIngress.ipv4_lpm

# Clear any existing entries
tbl.clear()

# Add route: 10.0.0.1/32 -> egress port 1
tbl.add_with_hit(
    dst_addr='10.0.0.1',
    dst_addr_p_length=32,
    dst_port=1
)

print("Forwarding table entries:")
tbl.dump(table=True)
print("Setup complete. Run control_plane.py to receive flow digests.")
