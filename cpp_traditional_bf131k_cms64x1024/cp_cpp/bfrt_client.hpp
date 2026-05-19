// bfrt_client.hpp — minimal bfrt-grpc client wrapping subscribe + bind +
// register read/write + digest stream. Single-process pure C++ control plane,
// so this owns the only client_id 0 session.
#pragma once

#include <atomic>
#include <cstdint>
#include <functional>
#include <map>
#include <memory>
#include <string>
#include <thread>
#include <vector>
#include <mutex>

#include <grpcpp/grpcpp.h>
#include "bfruntime.pb.h"
#include "bfruntime.grpc.pb.h"

#include "flow.hpp"

namespace bf = bfrt_proto;

class BfrtClient {
public:
    BfrtClient(std::string addr, std::string p4_name,
               uint32_t device_id, uint32_t client_id, uint32_t pipe_id);
    ~BfrtClient();

    // Open StreamChannel, send Subscribe, then BIND. Returns false on failure.
    bool connect_and_bind();

    // Resolve the named register tables to their IDs. Names must match what
    // the P4 program defined (e.g. "pipe.SwitchIngress.bf_0").
    bool resolve_table_id(const std::string& full_name, uint32_t& out_id);

    // Bulk read. Returns one entry per cell in `out` (index 0..size-1).
    bool read_register(uint32_t table_id, uint32_t expected_size,
                        std::vector<uint64_t>& out);

    // Targeted clear: write 0 to each given index of `table_id`. We don't
    // touch cells we know are already 0 — that's the snapshot's job.
    // `value_field_id` is the bfrt id of the register's `f1` data field
    // (typically 1 for register tables; we discover it lazily on first call
    // by reading one entry).
    bool clear_register_indices(uint32_t table_id,
                                const std::vector<uint32_t>& indices,
                                uint32_t value_bytes /* 1 for BF, 2 for CMS */);

    // Spawn a background thread that reads digests off the StreamChannel and
    // calls `cb(flow_key)` for each digest entry. The callback runs on the
    // thread, so the caller is responsible for any synchronization.
    void start_digest_stream(std::function<void(const FlowKey&)> cb);
    void stop_digest_stream();

private:
    bool load_bfrt_info();
    bool parse_table_ids(const std::string& info);
    static uint32_t extract_register_index(const bf::TableEntry& te);
    static uint64_t extract_register_value(const bf::TableEntry& te);

    std::string addr_, p4_name_;
    uint32_t device_id_, client_id_, pipe_id_;

    std::shared_ptr<grpc::Channel>             channel_;
    std::unique_ptr<bf::BfRuntime::Stub>       stub_;
    std::unique_ptr<grpc::ClientContext>       stream_ctx_;
    std::unique_ptr<grpc::ClientReaderWriter<bf::StreamMessageRequest,
                                              bf::StreamMessageResponse>> stream_;

    // Map of bfrt table NAME -> table_id. Populated from bfrt_info.
    std::map<std::string, uint32_t>            table_id_;

    // Cached per-table field ids, learned from the first Read response.
    struct FieldIds { uint32_t key_fid = 0; uint32_t data_fid = 0; };
    std::map<uint32_t, FieldIds>               field_ids_;

    // Digest stream
    std::thread                                 digest_thread_;
    std::atomic<bool>                           stop_digests_{false};
};
