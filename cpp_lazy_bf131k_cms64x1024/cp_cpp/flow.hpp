// flow.hpp — 5-tuple flow key + per-flow accumulator.
#pragma once

#include <cstdint>
#include <cstring>
#include <functional>
#include <string>
#include <unordered_map>

struct FlowKey {
    uint32_t src_ip;
    uint32_t dst_ip;
    uint8_t  proto;
    uint16_t src_port;
    uint16_t dst_port;

    bool operator==(const FlowKey& o) const {
        return src_ip == o.src_ip && dst_ip == o.dst_ip &&
               proto == o.proto   && src_port == o.src_port &&
               dst_port == o.dst_port;
    }

    std::string ip_str(uint32_t a) const {
        char buf[16];
        std::snprintf(buf, sizeof(buf), "%u.%u.%u.%u",
                      (a >> 24) & 0xff, (a >> 16) & 0xff,
                      (a >> 8) & 0xff,   a        & 0xff);
        return std::string(buf);
    }

    std::string to_string() const {
        const char* pname = (proto == 6) ? "TCP" : (proto == 17) ? "UDP" : "OTHER";
        return ip_str(src_ip) + ":" + std::to_string(src_port) + " -> " +
               ip_str(dst_ip) + ":" + std::to_string(dst_port) + " " + pname;
    }
};

struct FlowKeyHash {
    size_t operator()(const FlowKey& f) const noexcept {
        // FNV-1a over the packed 5-tuple.
        uint64_t h = 1469598103934665603ULL;
        auto mix = [&](const void* p, size_t n) {
            const uint8_t* b = static_cast<const uint8_t*>(p);
            for (size_t i = 0; i < n; ++i) {
                h ^= b[i];
                h *= 1099511628211ULL;
            }
        };
        mix(&f.src_ip, 4); mix(&f.dst_ip, 4); mix(&f.proto, 1);
        mix(&f.src_port, 2); mix(&f.dst_port, 2);
        return (size_t)h;
    }
};

using FlowTable = std::unordered_map<FlowKey, uint32_t, FlowKeyHash>;
