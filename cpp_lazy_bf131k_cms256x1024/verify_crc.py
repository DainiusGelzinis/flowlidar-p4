#!/usr/bin/env python3
"""
verify_crc.py — for one known flow (Flow A: 10.1.0.1:1000 -> 10.0.0.1:80 TCP),
print the expected master bucket and CMS column hashes using the same crcmod
config the Python control_plane uses. Compare against the C++ control plane's
diagnostic output to confirm whether C++ matches Python (and therefore Tofino).
"""

import socket, struct, crcmod

def pack(src, sport, dst, dport, proto=6):
    s = struct.unpack('!I', socket.inet_aton(src))[0]
    d = struct.unpack('!I', socket.inet_aton(dst))[0]
    return struct.pack('>IIBHH', s, d, proto, sport, dport)

# Same crcmod config as hardware_version2/control_plane.py uses.
# Mapping: crcmod poly = 0x1<P4_poly>, init = P4_init XOR P4_residue, xorOut = P4_residue
master = crcmod.mkCrcFun(0x1F4ACFB13, rev=True,  initCrc=0x00000000, xorOut=0xFFFFFFFF)
cms0   = crcmod.mkCrcFun(0x1A833982B, rev=True,  initCrc=0x00000000, xorOut=0xFFFFFFFF)
cms1   = crcmod.mkCrcFun(0x1814141AB, rev=False, initCrc=0x00000000, xorOut=0x00000000)
cms2   = crcmod.mkCrcFun(0x104C11DB7, rev=False, initCrc=0xFFFFFFFF, xorOut=0xFFFFFFFF)

flow_a = pack('10.1.0.1', 1000, '10.0.0.1', 80, proto=6)

mh = master(flow_a)
print(f'master_hash full crc       : 0x{mh:08x}')
print(f'master bucket (low16, &0xFC00 >> 10) = {((mh & 0xFFFF) & 0xFC00) >> 10}')
for name, fn in (('cms_0', cms0), ('cms_1', cms1), ('cms_2', cms2)):
    c = fn(flow_a)
    print(f'{name} full crc=0x{c:08x}  low10={c & 0x3FF}'
          f'  high10={(c >> 22) & 0x3FF}'
          f'  no-xor-low10={(c ^ 0xFFFFFFFF) & 0x3FF}')
