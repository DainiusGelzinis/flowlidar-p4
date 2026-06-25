# FlowLiDAR cpp_lazy_bf131k_cms256x1024 — table setup for lazy_bf131k_cms256x1024.

p4 = bfrt.lazy_bf131k_cms256x1024.pipe

bfrt.port.port.add(DEV_PORT=132, SPEED='BF_SPEED_40G',
                   FEC='BF_FEC_TYP_FIRECODE', PORT_ENABLE=True)
bfrt.port.port.add(DEV_PORT=140, SPEED='BF_SPEED_40G',
                   FEC='BF_FEC_TYP_FIRECODE', PORT_ENABLE=True)
print("Ports enabled: 1/0 (D_P=132) and 2/0 (D_P=140)")

tbl = p4.SwitchIngress.ipv4_lpm
tbl.clear()
tbl.add_with_hit(dst_addr='10.0.0.1', dst_addr_p_length=32, dst_port=132)
print("IPv4 LPM entry added: 10.0.0.1/32 -> port 1/0 (D_P=132)")
tbl.add_with_hit(dst_addr='0.0.0.0', dst_addr_p_length=0, dst_port=132)
print("IPv4 LPM entry added: 0.0.0.0/0 -> port 1/0 (D_P=132) [catch-all]")

tbl_bf1 = p4.SwitchIngress.tbl_bf1
tbl_bf1.clear()
tbl_bf1.add_with_run_bf1(b0=1)
print("tbl_bf1: entry (b0=1) -> run_bf1")

tbl_bf2 = p4.SwitchIngress.tbl_bf2
tbl_bf2.clear()
tbl_bf2.add_with_run_bf2(b0=1, b1=1)
print("tbl_bf2: entry (b0=1, b1=1) -> run_bf2")

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
