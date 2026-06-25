# FlowLiDAR cpp_traditional_bf2m_cms256x1024 — table setup.

p4 = bfrt.traditional_bf2m_cms256x1024.pipe

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

print("")
print("Setup complete. Run traditional_bf_cp to receive flow digests and CMS reports.")
