# FlowLiDAR Prototype 1 — control plane setup
# Inserts a forwarding rule into the ipv4_lpm table.
# Run with: bfshell> bfrt_python /home/student/Desktop/flowlidar/prototype1/setup_table.py

# Get a handle to the ipv4_lpm table
p4 = bfrt.prototype1.pipe
tbl = p4.SwitchIngress.ipv4_lpm

# Clear any existing entries
tbl.clear()

# Add route: 10.0.0.1/32 -> egress port 1
tbl.add_with_hit(
    dst_addr='10.0.0.1',
    dst_addr_p_length=32,
    dst_port=1
)

# Verify the entry was installed
print("Table entries:")
tbl.dump(table=True)
