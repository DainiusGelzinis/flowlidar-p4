// bfrt_client.cpp — implementation. See bfrt_client.hpp.

#include "bfrt_client.hpp"

#include <cstring>
#include <iostream>
#include <chrono>

BfrtClient::BfrtClient(std::string addr, std::string p4_name,
                       uint32_t device_id, uint32_t client_id, uint32_t pipe_id)
    : addr_{std::move(addr)}, p4_name_{std::move(p4_name)},
      device_id_{device_id}, client_id_{client_id}, pipe_id_{pipe_id} {
    constexpr int kMaxMsgBytes = 256 * 1024 * 1024;
    grpc::ChannelArguments args;
    args.SetMaxReceiveMessageSize(kMaxMsgBytes);
    args.SetMaxSendMessageSize(kMaxMsgBytes);
    channel_ = grpc::CreateCustomChannel(addr_,
                                         grpc::InsecureChannelCredentials(),
                                         args);
    stub_    = bf::BfRuntime::NewStub(channel_);
}

BfrtClient::~BfrtClient() {
    stop_digest_stream();
}

bool BfrtClient::connect_and_bind() {
    stream_ctx_ = std::make_unique<grpc::ClientContext>();
    stream_ctx_->AddMetadata("client_id", std::to_string(client_id_));
    stream_      = stub_->StreamChannel(stream_ctx_.get());

    bf::StreamMessageRequest req;
    req.set_client_id(client_id_);
    auto* sub = req.mutable_subscribe();
    sub->set_device_id(device_id_);
    sub->mutable_notifications()->set_enable_learn_notifications(true);
    sub->mutable_notifications()->set_enable_idletimeout_notifications(false);
    sub->mutable_notifications()->set_enable_port_status_change_notifications(false);
    if (!stream_->Write(req)) {
        std::cerr << "[bfrt] subscribe write failed\n";
        return false;
    }

    bf::StreamMessageResponse rsp;
    if (!stream_->Read(&rsp)) {
        std::cerr << "[bfrt] subscribe stream closed\n";
        return false;
    }
    if (rsp.update_case() != bf::StreamMessageResponse::kSubscribe) {
        std::cerr << "[bfrt] subscribe response missing (got case=" << rsp.update_case() << ")\n";
        return false;
    }
    if (rsp.subscribe().status().code() != 0) {
        std::cerr << "[bfrt] subscribe rejected: " << rsp.subscribe().status().message() << "\n";
        return false;
    }
    std::cerr << "[bfrt] subscribed (client_id=" << client_id_ << ")\n";

    grpc::ClientContext bind_ctx;
    bind_ctx.AddMetadata("client_id", std::to_string(client_id_));
    bf::SetForwardingPipelineConfigRequest bind_req;
    bind_req.set_device_id(device_id_);
    bind_req.set_client_id(client_id_);
    bind_req.set_action(bf::SetForwardingPipelineConfigRequest::BIND);
    auto* cfg = bind_req.add_config();
    cfg->set_p4_name(p4_name_);
    bf::SetForwardingPipelineConfigResponse bind_rsp;
    auto status = stub_->SetForwardingPipelineConfig(&bind_ctx, bind_req, &bind_rsp);
    if (!status.ok()) {
        std::cerr << "[bfrt] BIND failed: " << status.error_message() << "\n";
        return false;
    }
    std::cerr << "[bfrt] bound to " << p4_name_ << "\n";

    return load_bfrt_info();
}

bool BfrtClient::load_bfrt_info() {
    grpc::ClientContext ctx;
    ctx.AddMetadata("client_id", std::to_string(client_id_));
    bf::GetForwardingPipelineConfigRequest req;
    req.set_device_id(device_id_);
    bf::GetForwardingPipelineConfigResponse rsp;
    auto status = stub_->GetForwardingPipelineConfig(&ctx, req, &rsp);
    if (!status.ok() || rsp.config_size() == 0) {
        std::cerr << "[bfrt] GetForwardingPipelineConfig failed: " << status.error_message() << "\n";
        return false;
    }
    return parse_table_ids(rsp.config(0).bfruntime_info());
}

// Tiny ad-hoc JSON scan that pairs each "name" with the next "id".
bool BfrtClient::parse_table_ids(const std::string& info) {
    size_t pos = 0;
    while ((pos = info.find("\"name\"", pos)) != std::string::npos) {
        size_t qstart = info.find('"', pos + 6); if (qstart == std::string::npos) break;
        size_t qend   = info.find('"', qstart + 1); if (qend == std::string::npos) break;
        std::string name = info.substr(qstart + 1, qend - qstart - 1);

        size_t idpos = info.find("\"id\"", qend);
        if (idpos == std::string::npos) break;
        size_t colon = info.find(':', idpos); if (colon == std::string::npos) break;
        size_t i = colon + 1;
        while (i < info.size() && (info[i] == ' ' || info[i] == '\t')) ++i;
        uint32_t id = 0;
        while (i < info.size() && info[i] >= '0' && info[i] <= '9') {
            id = id * 10 + (info[i] - '0'); ++i;
        }
        table_id_[name] = id;
        pos = i;
    }
    std::cerr << "[bfrt] parsed " << table_id_.size() << " name->id pairs\n";
    return !table_id_.empty();
}

bool BfrtClient::resolve_table_id(const std::string& full_name, uint32_t& out_id) {
    auto try_one = [&](const std::string& s) -> bool {
        auto it = table_id_.find(s);
        if (it == table_id_.end()) return false;
        out_id = it->second;
        return true;
    };
    if (try_one(full_name)) return true;
    if (full_name.rfind("pipe.", 0) == 0 && try_one(full_name.substr(5))) return true;
    if (try_one(full_name + ".f1")) return true;
    if (full_name.rfind("pipe.", 0) == 0 && try_one(full_name.substr(5) + ".f1")) return true;
    for (auto& kv : table_id_) {
        if (kv.first.size() >= full_name.size() &&
            kv.first.compare(kv.first.size() - full_name.size(),
                              full_name.size(), full_name) == 0) {
            out_id = kv.second;
            return true;
        }
    }
    return false;
}

bool BfrtClient::read_register(uint32_t table_id, uint32_t expected_size,
                                std::vector<uint64_t>& out) {
    out.assign(expected_size, 0);

    grpc::ClientContext ctx;
    ctx.AddMetadata("client_id", std::to_string(client_id_));
    bf::ReadRequest req;
    req.set_client_id(client_id_);
    req.mutable_target()->set_device_id(device_id_);
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
    FieldIds fids;
    while (reader->Read(&rsp)) {
        for (const auto& ent : rsp.entities()) {
            if (!ent.has_table_entry()) continue;
            const auto& te = ent.table_entry();
            if (fids.key_fid == 0 && te.has_key() && te.key().fields_size() > 0) {
                fids.key_fid = te.key().fields(0).field_id();
            }
            if (fids.data_fid == 0 && te.data().fields_size() > 0) {
                fids.data_fid = te.data().fields(0).field_id();
            }
            uint32_t idx = extract_register_index(te);
            uint64_t val = extract_register_value(te);
            if (idx < expected_size) { out[idx] = val; ++total; }
        }
    }
    if (fids.key_fid && fids.data_fid) field_ids_[table_id] = fids;
    auto status = reader->Finish();
    if (!status.ok()) {
        std::cerr << "[bfrt] read table_id=" << table_id
                  << " failed: code=" << status.error_code()
                  << " msg=" << status.error_message() << "\n";
        return false;
    }
    return true;
}

bool BfrtClient::clear_register_indices(uint32_t table_id,
                                         const std::vector<uint32_t>& indices,
                                         uint32_t value_bytes) {
    if (indices.empty()) return true;
    auto it = field_ids_.find(table_id);
    if (it == field_ids_.end()) {
        std::cerr << "[bfrt] clear: no cached field_ids for table_id=" << table_id
                  << " — call read_register first\n";
        return false;
    }
    uint32_t key_fid  = it->second.key_fid;
    uint32_t data_fid = it->second.data_fid;

    constexpr size_t kBatch = 4096;
    for (size_t off = 0; off < indices.size(); off += kBatch) {
        size_t end = std::min(off + kBatch, indices.size());

        grpc::ClientContext ctx;
        ctx.AddMetadata("client_id", std::to_string(client_id_));
        bf::WriteRequest req;
        req.set_client_id(client_id_);
        req.mutable_target()->set_device_id(device_id_);
        req.mutable_target()->set_pipe_id(pipe_id_);
        req.mutable_target()->set_direction(0xFF);
        req.mutable_target()->set_prsr_id(0xFF);
        req.set_atomicity(bf::WriteRequest::CONTINUE_ON_ERROR);

        for (size_t k = off; k < end; ++k) {
            uint32_t idx = indices[k];

            auto* update = req.add_updates();
            update->set_type(bf::Update::MODIFY);
            auto* tbl = update->mutable_entity()->mutable_table_entry();
            tbl->set_table_id(table_id);

            auto* kf = tbl->mutable_key()->add_fields();
            kf->set_field_id(key_fid);
            std::string keybytes(4, '\0');
            keybytes[0] = (idx >> 24) & 0xff; keybytes[1] = (idx >> 16) & 0xff;
            keybytes[2] = (idx >>  8) & 0xff; keybytes[3] =  idx        & 0xff;
            kf->mutable_exact()->set_value(keybytes);

            auto* df = tbl->mutable_data()->add_fields();
            df->set_field_id(data_fid);
            std::string val(value_bytes, '\0');
            df->set_stream(val);
        }

        bf::WriteResponse rsp;
        auto status = stub_->Write(&ctx, req, &rsp);
        if (!status.ok()) {
            std::cerr << "[bfrt] batched clear table_id=" << table_id
                      << " (batch " << off << "/" << indices.size()
                      << ") failed: " << status.error_message() << "\n";
            return false;
        }
    }
    return true;
}

uint32_t BfrtClient::extract_register_index(const bf::TableEntry& te) {
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

uint64_t BfrtClient::extract_register_value(const bf::TableEntry& te) {
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

void BfrtClient::start_digest_stream(std::function<void(const FlowKey&)> cb) {
    digest_thread_ = std::thread([this, cb = std::move(cb)]() {
        bf::StreamMessageResponse rsp;
        while (!stop_digests_.load() && stream_->Read(&rsp)) {
            if (rsp.update_case() != bf::StreamMessageResponse::kDigest) continue;
            const auto& dl = rsp.digest();
            for (const auto& entry : dl.data()) {
                FlowKey k{};
                int slot = 0;
                for (const auto& f : entry.fields()) {
                    if (!f.has_stream()) continue;
                    const std::string& s = f.stream();
                    uint64_t v = 0;
                    for (char c : s) v = (v << 8) | (uint8_t)c;
                    switch (slot) {
                        case 0: k.src_ip   = (uint32_t)v; break;
                        case 1: k.dst_ip   = (uint32_t)v; break;
                        case 2: k.proto    = (uint8_t)v;  break;
                        case 3: k.src_port = (uint16_t)v; break;
                        case 4: k.dst_port = (uint16_t)v; break;
                    }
                    ++slot;
                }
                if (slot == 5) cb(k);
            }
        }
    });
}

void BfrtClient::stop_digest_stream() {
    if (!digest_thread_.joinable()) return;
    stop_digests_.store(true);
    if (stream_ctx_) stream_ctx_->TryCancel();
    digest_thread_.join();
}
