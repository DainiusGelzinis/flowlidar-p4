// fast_io.cpp — bulk-read FlowLiDAR Prototype 9 BF + CMS register arrays
// over bfrt-gRPC using the C++ stubs. Dumps each register as a binary file
// with one entry per cell, then optionally clears the arrays in bulk.
//
// Usage:
//   ./fast_io snapshot <out_dir>            // read 6 register tables -> bins
//   ./fast_io clear                         // bulk-clear all 6 register tables
//   ./fast_io snapshot_and_clear <out_dir>  // both, in one connection
//
// Output binary format (one file per register):
//   bf_0.bin / bf_1.bin / bf_2.bin    : BF_SIZE bytes,    1 byte per cell (0/1)
//   cms_0.bin / cms_1.bin / cms_2.bin : CMS_SIZE × 2 bytes, uint16_t LE per cell
//
// Connection: localhost:50052, P4 program "prototype9", device 0, pipe 0.
// (For real hardware change pipe to 1 with --pipe 1; matches control_plane.py.)

#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iostream>
#include <memory>
#include <string>
#include <thread>
#include <vector>

#include <grpcpp/grpcpp.h>
#include "bfruntime.pb.h"
#include "bfruntime.grpc.pb.h"

namespace bf  = bfrt_proto;

// --------------------------------------------------------------------------
// Configuration
// --------------------------------------------------------------------------
static constexpr const char* kP4Name      = "prototype9";
static constexpr uint32_t    kDeviceId    = 0;
// Reuse the Python CP's client_id (0). bfrt-grpc tracks clients by id, not
// per TCP connection, so we can issue Read/Write under the same id from a
// different process. No subscribe / no BIND needed — Python already did them.
static constexpr uint32_t    kClientId    = 0;
static constexpr uint32_t    kBfSize      = 131072;     // 2^17 cells per BF row
static constexpr uint32_t    kCmsSize     = 65536;      // 64 buckets × 1024 cols

// Short tail used in the on-disk filename (bf_0.bin, cms_0.bin, ...).
// Table IDs come from the command line — Python knows them already from
// bfrt_info and can pass them in to skip the JSON-parsing nightmare.
struct RegisterSpec {
    std::string short_name;
    uint32_t    table_id;
};

// --------------------------------------------------------------------------
// gRPC client wrapper
// --------------------------------------------------------------------------
class BfRtClient {
public:
    BfRtClient(const std::string& addr, uint32_t pipe_id)
        : pipe_id_(pipe_id) {
        channel_ = grpc::CreateChannel(addr, grpc::InsecureChannelCredentials());
        stub_    = bf::BfRuntime::NewStub(channel_);
    }

    // No-op: Python CP already established the session under client_id 0.
    bool subscribe() { return true; }

    // Bulk-read every entry in a register table. Caller supplies the table id
    // (from Python's bfrt_info) and the expected cell count.
    bool read_register(const std::string& tag, uint32_t table_id,
                        uint32_t expected_size, std::vector<uint64_t>& out) {
        out.assign(expected_size, 0);

        grpc::ClientContext ctx;
        ctx.AddMetadata("client_id", std::to_string(kClientId));
        bf::ReadRequest req;
        req.set_client_id(kClientId);
        req.set_p4_name(kP4Name);                   // scope without BIND
        req.mutable_target()->set_device_id(kDeviceId);
        req.mutable_target()->set_pipe_id(pipe_id_);
        req.mutable_target()->set_direction(0xFF);
        req.mutable_target()->set_prsr_id(0xFF);

        auto* entity = req.add_entities();
        auto* tbl    = entity->mutable_table_entry();
        tbl->set_table_id(table_id);
        tbl->mutable_table_flags()->set_from_hw(true);

        auto reader = stub_->Read(&ctx, req);
        bf::ReadResponse rsp;
        size_t total = 0;
        while (reader->Read(&rsp)) {
            for (const auto& ent : rsp.entities()) {
                if (!ent.has_table_entry()) continue;
                uint32_t idx = extract_register_index(ent.table_entry());
                uint64_t val = extract_register_value(ent.table_entry());
                if (idx < expected_size) {
                    out[idx] = val;
                    ++total;
                }
            }
        }
        auto status = reader->Finish();
        if (!status.ok()) {
            std::cerr << "[fast_io] read " << tag
                      << " failed: " << status.error_message() << "\n";
            return false;
        }
        std::cerr << "[fast_io] read " << tag
                  << " (id=" << table_id << "): " << total << " cells\n";
        return true;
    }

    // Bulk-clear — MODIFY of the table's default entry resets all cells to 0
    // in the SDE for register tables.
    bool clear_register(const std::string& tag, uint32_t table_id) {
        grpc::ClientContext ctx;
        ctx.AddMetadata("client_id", std::to_string(kClientId));
        bf::WriteRequest req;
        req.set_client_id(kClientId);
        req.set_p4_name(kP4Name);
        req.mutable_target()->set_device_id(kDeviceId);
        req.mutable_target()->set_pipe_id(pipe_id_);
        req.mutable_target()->set_direction(0xFF);
        req.mutable_target()->set_prsr_id(0xFF);
        req.set_atomicity(bf::WriteRequest::CONTINUE_ON_ERROR);

        auto* update = req.add_updates();
        update->set_type(bf::Update::MODIFY);
        auto* tbl = update->mutable_entity()->mutable_table_entry();
        tbl->set_table_id(table_id);
        tbl->set_is_default_entry(true);

        bf::WriteResponse rsp;
        auto status = stub_->Write(&ctx, req, &rsp);
        if (!status.ok()) {
            std::cerr << "[fast_io] clear " << tag
                      << " failed: " << status.error_message() << "\n";
            return false;
        }
        std::cerr << "[fast_io] cleared " << tag << " (id=" << table_id << ")\n";
        return true;
    }

private:
    std::shared_ptr<grpc::Channel>           channel_;
    std::unique_ptr<bf::BfRuntime::Stub>     stub_;
    std::unique_ptr<grpc::ClientContext>     ctx_;
    std::unique_ptr<grpc::ClientReaderWriter<bf::StreamMessageRequest,
                                              bf::StreamMessageResponse>> stream_;
    uint32_t                                  pipe_id_;

    static uint32_t extract_register_index(const bf::TableEntry& te) {
        if (!te.has_key()) return 0;
        for (const auto& f : te.key().fields()) {
            if (f.has_exact()) {
                const std::string& v = f.exact().value();
                uint32_t out = 0;
                for (char c : v) out = (out << 8) | (uint8_t)c;
                return out;
            }
        }
        return 0;
    }

    static uint64_t extract_register_value(const bf::TableEntry& te) {
        // Register cells come back as a "stream" data field: the value is a
        // packed bytes blob, big-endian. For a single-pipe read there's one
        // entry per pipe; we just take the first.
        for (const auto& f : te.data().fields()) {
            if (f.has_stream()) {
                const std::string& s = f.stream();
                uint64_t out = 0;
                for (char c : s) out = (out << 8) | (uint8_t)c;
                return out;
            }
            if (f.has_int_arr_val()) {
                if (f.int_arr_val().val_size() > 0) return f.int_arr_val().val(0);
            }
        }
        return 0;
    }
};

// --------------------------------------------------------------------------
// Disk I/O
// --------------------------------------------------------------------------
static bool write_bf_file(const std::string& dir, const std::string& tail,
                          const std::vector<uint64_t>& cells) {
    std::string path = dir + "/" + tail + ".bin";
    std::ofstream out(path, std::ios::binary | std::ios::trunc);
    if (!out) { std::cerr << "[fast_io] cannot open " << path << "\n"; return false; }
    std::vector<uint8_t> packed(cells.size());
    for (size_t i = 0; i < cells.size(); ++i) packed[i] = (uint8_t)(cells[i] & 1);
    out.write(reinterpret_cast<const char*>(packed.data()), packed.size());
    return out.good();
}

static bool write_cms_file(const std::string& dir, const std::string& tail,
                           const std::vector<uint64_t>& cells) {
    std::string path = dir + "/" + tail + ".bin";
    std::ofstream out(path, std::ios::binary | std::ios::trunc);
    if (!out) { std::cerr << "[fast_io] cannot open " << path << "\n"; return false; }
    std::vector<uint16_t> packed(cells.size());
    for (size_t i = 0; i < cells.size(); ++i) packed[i] = (uint16_t)(cells[i] & 0xffff);
    out.write(reinterpret_cast<const char*>(packed.data()),
              packed.size() * sizeof(uint16_t));
    return out.good();
}

// --------------------------------------------------------------------------
// Main
// --------------------------------------------------------------------------
static void usage() {
    std::cerr << "usage:\n"
              << "  fast_io <mode> <out_dir> --bf id0,id1,id2 --cms id0,id1,id2 [--pipe N]\n"
              << "where <mode> is: snapshot | clear | snapshot_and_clear\n"
              << "                                                                                   \n"
              << "Table IDs are typically extracted by control_plane.py from bfrt_info\n"
              << "and passed in. The 6 ids correspond to the bf_0/1/2 + cms_0/1/2 register\n"
              << "tables of prototype9.\n";
}

static std::vector<uint32_t> parse_id_list(const std::string& csv) {
    std::vector<uint32_t> out;
    size_t i = 0;
    while (i < csv.size()) {
        size_t j = csv.find(',', i);
        if (j == std::string::npos) j = csv.size();
        out.push_back((uint32_t)std::strtoul(csv.substr(i, j - i).c_str(), nullptr, 10));
        i = j + 1;
    }
    return out;
}

int main(int argc, char** argv) {
    if (argc < 2) { usage(); return 2; }

    std::string mode = argv[1];
    std::string out_dir;
    uint32_t pipe_id = 0;
    std::vector<uint32_t> bf_ids, cms_ids;

    for (int i = 2; i < argc; ++i) {
        std::string a = argv[i];
        if      (a == "--pipe" && i + 1 < argc) pipe_id = std::atoi(argv[++i]);
        else if (a == "--bf"   && i + 1 < argc) bf_ids  = parse_id_list(argv[++i]);
        else if (a == "--cms"  && i + 1 < argc) cms_ids = parse_id_list(argv[++i]);
        else if (a.rfind("--", 0) != 0)         out_dir = a;
    }

    bool need_snapshot = (mode == "snapshot" || mode == "snapshot_and_clear");
    bool need_clear    = (mode == "clear"    || mode == "snapshot_and_clear");
    if (!need_snapshot && !need_clear)              { usage(); return 2; }
    if (need_snapshot && out_dir.empty())           { usage(); return 2; }
    if (bf_ids.size() != 3 || cms_ids.size() != 3)  {
        std::cerr << "[fast_io] need exactly 3 ids each in --bf and --cms\n";
        return 2;
    }

    BfRtClient client("localhost:50052", pipe_id);
    if (!client.subscribe()) return 1;

    if (need_snapshot) {
        for (size_t i = 0; i < 3; ++i) {
            std::string tag = "bf_" + std::to_string(i);
            std::vector<uint64_t> cells;
            if (!client.read_register(tag, bf_ids[i], kBfSize, cells)) return 1;
            if (!write_bf_file(out_dir, tag, cells)) return 1;
        }
        for (size_t i = 0; i < 3; ++i) {
            std::string tag = "cms_" + std::to_string(i);
            std::vector<uint64_t> cells;
            if (!client.read_register(tag, cms_ids[i], kCmsSize, cells)) return 1;
            if (!write_cms_file(out_dir, tag, cells)) return 1;
        }
    }
    if (need_clear) {
        for (size_t i = 0; i < 3; ++i)
            if (!client.clear_register("bf_"  + std::to_string(i),  bf_ids[i]))  return 1;
        for (size_t i = 0; i < 3; ++i)
            if (!client.clear_register("cms_" + std::to_string(i), cms_ids[i])) return 1;
    }
    return 0;
}
