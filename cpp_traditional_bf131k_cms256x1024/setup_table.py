# FlowLiDAR cpp_traditional_bf131k_cms256x1024 — table setup.
# For real Tofino 1 hardware (p4switch2).
#   Ingress: port 2/0 (D_P=140) — hotpot enp172s0f0np0 connects here
#   Egress:  port 1/0 (D_P=132) — hotpot enp172s0f1np1
#
# Run with: bfshell> bfrt_python ~/dainius/cpp_traditional_bf131k_cms256x1024/setup_table.py

p4 = bfrt.traditional_bf131k_cms256x1024.pipe

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

# --- Paper Algorithm 1: CMS fires unconditionally (no gate entries) ---

print("")
print("Setup complete. Run traditional_bf_cp to receive flow digests and CMS reports.")
