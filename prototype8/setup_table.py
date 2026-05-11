# FlowLiDAR Prototype 8 — table setup (Traditional BF baseline)
# Tables for the conditional BF chain are gone (BF tables are now keyless),
# but the conditional CMS increment tables stay the same: CMS still only fires
# when all 3 BF bits were already set.
#
# Works on both software model (veth ports) and real Tofino 1 hardware.
#
# On real hardware (p4switch2):
#   Ingress: port 1/0 (D_P=132) — hotpot enp172s0f0np0
#   Egress:  port 2/0 (D_P=140) — hotpot enp172s0f1np1
#
# Run with: bfshell> bfrt_python ~/dainius/prototype8/setup_table.py

p4 = bfrt.prototype8.pipe

# --- Enable ports (real hardware only — harmless on simulator) ---
try:
    bfrt.port.port.add(DEV_PORT=132, SPEED='BF_SPEED_40G',
                       FEC='BF_FEC_TYP_FIRECODE', PORT_ENABLE=True)
    bfrt.port.port.add(DEV_PORT=140, SPEED='BF_SPEED_40G',
                       FEC='BF_FEC_TYP_FIRECODE', PORT_ENABLE=True)
    print("Ports enabled: 1/0 (D_P=132) and 2/0 (D_P=140)")
except Exception as e:
    print(f"Skipping port enable (probably running on simulator): {e}")

# --- IPv4 LPM forwarding ---
tbl = p4.SwitchIngress.ipv4_lpm
tbl.clear()
tbl.add_with_hit(dst_addr='10.0.0.1', dst_addr_p_length=32, dst_port=132)
print("IPv4 LPM entry added: 10.0.0.1/32 -> port 1/0 (D_P=132)")
tbl.add_with_hit(dst_addr='0.0.0.0', dst_addr_p_length=0, dst_port=132)
print("IPv4 LPM entry added: 0.0.0.0/0 -> port 1/0 (D_P=132) [catch-all]")

# --- Conditional CMS increment tables (sub-sketch CMS, 64×1024) ---
# CMS fires only when (b0,b1,b2) = (1,1,1) — i.e. on packets after the BF
# already saturated for this flow OR for hash-collision-hidden flows.
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
