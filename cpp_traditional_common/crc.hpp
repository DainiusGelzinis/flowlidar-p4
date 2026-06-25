// crc.hpp — CRC implementation that mirrors Python crcmod exactly.

#pragma once

#include <cstdint>
#include <cstring>
#include <vector>

class Crc32 {
public:
    Crc32(uint64_t poly_full, bool refl, uint32_t init_crc, uint32_t xor_out)
        : refl_{refl}, init_{init_crc}, xor_out_{xor_out} {
        if (refl_) {
            uint32_t p32 = (uint32_t)(poly_full & 0xFFFFFFFFULL);
            poly_ = bit_reverse32(p32);
        } else {
            poly_ = (uint32_t)(poly_full & 0xFFFFFFFFULL);
        }
    }

    // Convenience ctor matching the P4 -> crcmod mapping:
    static Crc32 from_p4(uint32_t poly, bool refl,
                         uint32_t p4_init, uint32_t p4_residue) {
        uint64_t poly_full = (1ULL << 32) | poly;
        return Crc32(poly_full, refl, p4_init ^ p4_residue, p4_residue);
    }

    uint32_t compute(const uint8_t* data, size_t len) const {
        uint32_t crc = init_ ^ xor_out_;
        if (refl_) {
            for (size_t i = 0; i < len; ++i) {
                crc ^= (uint32_t)data[i];
                for (int b = 0; b < 8; ++b) {
                    if (crc & 1) crc = (crc >> 1) ^ poly_;
                    else         crc =  crc >> 1;
                }
            }
        } else {
            for (size_t i = 0; i < len; ++i) {
                crc ^= (uint32_t)data[i] << 24;
                for (int b = 0; b < 8; ++b) {
                    if (crc & 0x80000000U) crc = (crc << 1) ^ poly_;
                    else                    crc =  crc << 1;
                }
            }
        }
        return crc ^ xor_out_;
    }

private:
    static uint32_t bit_reverse32(uint32_t x) {
        x = ((x & 0x55555555U) <<  1) | ((x & 0xAAAAAAAAU) >>  1);
        x = ((x & 0x33333333U) <<  2) | ((x & 0xCCCCCCCCU) >>  2);
        x = ((x & 0x0F0F0F0FU) <<  4) | ((x & 0xF0F0F0F0U) >>  4);
        x = ((x & 0x00FF00FFU) <<  8) | ((x & 0xFF00FF00U) >>  8);
        x = ( x                << 16) | ( x                >> 16);
        return x;
    }

    bool     refl_;
    uint32_t init_;
    uint32_t xor_out_;
    uint32_t poly_ = 0;
};

// Polynomials for lazy_bf.p4 — these MUST mirror what
namespace polys {
    inline const Crc32 bf0    {0x104C11DB7ULL, true,  0x00000000, 0xFFFFFFFF};
    inline const Crc32 bf1    {0x104C11DB7ULL, false, 0x00000000, 0xFFFFFFFF};
    inline const Crc32 bf2    {0x11EDC6F41ULL, true,  0x00000000, 0xFFFFFFFF};
    inline const Crc32 master {0x1F4ACFB13ULL, true,  0x00000000, 0xFFFFFFFF};
    inline const Crc32 cms0   {0x1A833982BULL, true,  0x00000000, 0xFFFFFFFF};
    inline const Crc32 cms1   {0x1814141ABULL, false, 0x00000000, 0x00000000};
    inline const Crc32 cms2   {0x104C11DB7ULL, false, 0xFFFFFFFF, 0xFFFFFFFF};
}

// Pack the 5-tuple in the same byte order the P4 hashes them:
inline std::vector<uint8_t> pack_5tuple(uint32_t src_ip, uint32_t dst_ip,
                                        uint8_t proto,
                                        uint16_t src_port, uint16_t dst_port) {
    std::vector<uint8_t> out(13);
    out[0]  = (src_ip   >> 24) & 0xff;
    out[1]  = (src_ip   >> 16) & 0xff;
    out[2]  = (src_ip   >>  8) & 0xff;
    out[3]  =  src_ip          & 0xff;
    out[4]  = (dst_ip   >> 24) & 0xff;
    out[5]  = (dst_ip   >> 16) & 0xff;
    out[6]  = (dst_ip   >>  8) & 0xff;
    out[7]  =  dst_ip          & 0xff;
    out[8]  =  proto;
    out[9]  = (src_port >>  8) & 0xff;
    out[10] =  src_port        & 0xff;
    out[11] = (dst_port >>  8) & 0xff;
    out[12] =  dst_port        & 0xff;
    return out;
}
