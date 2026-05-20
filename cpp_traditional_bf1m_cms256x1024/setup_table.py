# FlowLiDAR cpp_traditional_bf1m_cms256x1024 — table setup.
# For real Tofino 1 hardware (p4switch2).
#   Ingress: port 2/0 (D_P=140) — hotpot enp172s0f0np0 connects here
#   Egress:  port 1/0 (D_P=132) — hotpot enp172s0f1np1
#
# Run with: bfshell> bfrt_python ~/dainius/cpp_traditional_bf1m_cms256x1024/setup_table.py

p4 = bfrt.traditional_bf1m_cms256x1024.pipe

# --- Enable ports ---
bfrt.port.port.add(DEV_PORT=132, SPEED='BF_SPEED_40G',
                   FEC='BF_FEC_TYP_FIRECODE', PORT_ENABLE=True)
bfrt.port.port.add(DEV_PORT=140, SPEED='BF_SPEED_40G',
                   FEC='BF_FEC_TYP_FIRECODE', PORT_ENABLE=True)
print("Ports enabled: 1/0 (D_P=132) and 2/0 (D_P=140)")

# --- IPv4 LPM forwarding ---
# Packets to 10.0.0.1 enter on port 2/0 and exit on port 1/0 (D_P=132)
tbl = p4.SwitchIngress.ipv4_lpm
tbl.clear()
tbl.add_with_hit(dst_addr='10.0.0.1', dst_addr_p_length=32, dst_port=132)
print("IPv4 LPM entry added: 10.0.0.1/32 -> port 1/0 (D_P=132)")
tbl.add_with_hit(dst_addr='0.0.0.0', dst_addr_p_length=0, dst_port=132)
print("IPv4 LPM entry added: 0.0.0.0/0 -> port 1/0 (D_P=132) [catch-all]")

# --- Traditional BF: no conditional bf_1/bf_2 chain to set up ---
# (all 3 BF tables fire unconditionally via default_action)

# --- Conditional CMS increment tables (sub-sketch CMS, 64*1024) ---
# Only the 2nd-and-later packets of a flow (b0=b1=b2=1) increment CMS;
# the 1st packet of a visible flow is accounted for by its digest.
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
print("Setup complete. Run traditional_bf_cp to receive flow digests and CMS reports.")
