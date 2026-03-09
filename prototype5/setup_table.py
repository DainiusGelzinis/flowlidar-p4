# FlowLiDAR Prototype 5 — table setup
# Identical to prototype4: lazy BF conditional tables + CMS conditional tables.
# Run with: bfshell> bfrt_python /home/student/Desktop/flowlidar/prototype5/setup_table.py

p4 = bfrt.prototype5.pipe

# --- IPv4 LPM forwarding ---
tbl = p4.SwitchIngress.ipv4_lpm
tbl.clear()
tbl.add_with_hit(
    dst_addr='10.0.0.1',
    dst_addr_p_length=32,
    dst_port=1
)
print("IPv4 LPM entry added: 10.0.0.1/32 -> port 1")

# --- Lazy BF conditional tables ---
tbl_bf1 = p4.SwitchIngress.tbl_bf1
tbl_bf1.clear()
tbl_bf1.add_with_run_bf1(b0=1)
print("tbl_bf1: entry (b0=1) -> run_bf1")

tbl_bf2 = p4.SwitchIngress.tbl_bf2
tbl_bf2.clear()
tbl_bf2.add_with_run_bf2(b0=1, b1=1)
print("tbl_bf2: entry (b0=1, b1=1) -> run_bf2")

# --- Conditional CMS increment tables ---
tbl_cms_0 = p4.SwitchIngress.tbl_cms_0
tbl_cms_0.clear()
tbl_cms_0.add_with_do_cms_inc_0(b0=1, b1=1, b2=1)
print("tbl_cms_0: entry (1,1,1) -> do_cms_inc_0")

tbl_cms_1 = p4.SwitchIngress.tbl_cms_1
tbl_cms_1.clear()
tbl_cms_1.add_with_do_cms_inc_1(b0=1, b1=1, b2=1)
print("tbl_cms_1: entry (1,1,1) -> do_cms_inc_1")

tbl_cms_2 = p4.SwitchIngress.tbl_cms_2
tbl_cms_2.clear()
tbl_cms_2.add_with_do_cms_inc_2(b0=1, b1=1, b2=1)
print("tbl_cms_2: entry (1,1,1) -> do_cms_inc_2")

print("")
print("Setup complete. Run control_plane.py to receive flow digests and CMS reports.")
