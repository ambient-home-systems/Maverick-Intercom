#include "../firmware/components/maverick_intercom/wire.h"
#include <cassert>
#include <cstring>
using namespace esphome::maverick_intercom;
int main() {
  uint8_t header[12];
  encode_header(header, AUDIO, 640, 0x10203040);
  const uint8_t expected[] = {0x4d,0x56,0x49,0x43,0x01,0x03,0x02,0x80,0x10,0x20,0x30,0x40};
  assert(std::memcmp(header, expected, 12) == 0);
  uint8_t kind; uint16_t length; uint32_t sequence;
  assert(decode_header(header, kind, length, sequence));
  assert(kind == AUDIO && length == 640 && sequence == 0x10203040);
  header[7] = 0x81;
  assert(!decode_header(header, kind, length, sequence));
  encode_header(header, PING, 0, 0);
  assert(decode_header(header, kind, length, sequence));
  header[4] = 2;
  assert(!decode_header(header, kind, length, sequence));
  encode_header(header, STATUS, 2049, 0);
  assert(!decode_header(header, kind, length, sequence));
}
