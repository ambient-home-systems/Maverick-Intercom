#pragma once
#include <cstddef>
#include <cstdint>
#include <cstring>

namespace esphome::maverick_intercom {
constexpr size_t HEADER_SIZE = 12;
constexpr size_t AUDIO_SIZE = 640;
constexpr size_t MAX_CONTROL_SIZE = 2048;
enum Kind : uint8_t { HELLO = 1, STATUS = 2, AUDIO = 3, PING = 4, PONG = 5 };

inline void encode_header(uint8_t *out, uint8_t kind, uint16_t length, uint32_t sequence) {
  std::memcpy(out, "MVIC", 4);
  out[4] = 1;
  out[5] = kind;
  out[6] = length >> 8;
  out[7] = length;
  for (int i = 0; i < 4; i++) out[8 + i] = sequence >> (24 - i * 8);
}

inline bool decode_header(const uint8_t *in, uint8_t &kind, uint16_t &length, uint32_t &sequence) {
  if (std::memcmp(in, "MVIC", 4) != 0 || in[4] != 1) return false;
  kind = in[5];
  length = (uint16_t(in[6]) << 8) | in[7];
  sequence = 0;
  for (int i = 0; i < 4; i++) sequence = (sequence << 8) | in[8 + i];
  if (kind == AUDIO) return length == AUDIO_SIZE;
  if (kind == PING || kind == PONG) return length == 0;
  return (kind == HELLO || kind == STATUS) && length > 0 && length <= MAX_CONTROL_SIZE;
}
}  // namespace esphome::maverick_intercom
