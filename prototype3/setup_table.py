# FlowLiDAR Prototype 3 — forwarding table setup
# Adds the IPv4 LPM entry needed to forward test packets.
# Run with: bfshell> bfrt_python /home/student/Desktop/flowlidar/prototype3/setup_table.py

p4 = bfrt.prototype3.pipe
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
print("Setup complete. Run control_plane.py to receive flow digests and CMS reports.")
