# Build the C++ bfrt-grpc bulk register I/O helper for FlowLiDAR prototype 9.
#
# Requires $SDE and $SDE/install set up the same way as for the P4 build.
# Usage:
#   make             - generates grpc stubs and builds ./fast_io
#   make clean       - removes build artefacts

SDE          ?= /home/student/Desktop/open-p4studio
SDE_INSTALL  ?= $(SDE)/install

PROTOC       := $(SDE_INSTALL)/bin/protoc
GRPC_PLUGIN  := $(SDE_INSTALL)/bin/grpc_cpp_plugin

PROTO_DIR    := $(SDE_INSTALL)/share/bf_rt_shared/proto
THIRDPARTY   := $(SDE)/pkgsrc/bf-drivers/third-party

GEN_DIR      := build_gen
GEN_SRCS     := $(GEN_DIR)/bfruntime.pb.cc \
                $(GEN_DIR)/bfruntime.grpc.pb.cc \
                $(GEN_DIR)/google/rpc/status.pb.cc

CXX          := g++
CXXFLAGS     := -std=c++17 -O2 -Wall \
                -I$(SDE_INSTALL)/include \
                -I$(GEN_DIR)
PKGCONFIG    := PKG_CONFIG_PATH=$(SDE_INSTALL)/lib/pkgconfig pkg-config
LDFLAGS      := -L$(SDE_INSTALL)/lib \
                -Wl,-rpath,$(SDE_INSTALL)/lib \
                -Wl,--copy-dt-needed-entries
LIBS         := $(shell $(PKGCONFIG) --libs grpc++) \
                -lgrpc++_reflection -lprotobuf -lpthread

TARGET       := fast_io
SRCS         := fast_io.cpp $(GEN_SRCS)

all: $(TARGET)

$(TARGET): $(SRCS)
	$(CXX) $(CXXFLAGS) -o $@ $(SRCS) $(LDFLAGS) $(LIBS)

# Generate C++ gRPC stubs from bfruntime.proto.
$(GEN_DIR)/bfruntime.pb.cc $(GEN_DIR)/bfruntime.grpc.pb.cc: $(PROTO_DIR)/bfruntime.proto $(GEN_DIR)/google/rpc/status.pb.cc
	$(PROTOC) -I$(PROTO_DIR) -I$(THIRDPARTY) \
	          --cpp_out=$(GEN_DIR) \
	          --grpc_out=$(GEN_DIR) \
	          --plugin=protoc-gen-grpc=$(GRPC_PLUGIN) \
	          $(PROTO_DIR)/bfruntime.proto

# Generate google/rpc/status proto bindings (no gRPC service in this one).
$(GEN_DIR)/google/rpc/status.pb.cc: $(THIRDPARTY)/google/rpc/status.proto
	mkdir -p $(GEN_DIR)/google/rpc
	$(PROTOC) -I$(THIRDPARTY) --cpp_out=$(GEN_DIR) $(THIRDPARTY)/google/rpc/status.proto

clean:
	rm -rf $(TARGET) $(GEN_DIR)

.PHONY: all clean
