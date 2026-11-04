#include "layout.h"
size_t packet_size(void) { return sizeof(struct Packet); }
long packet_value(struct Packet packet) { return callback(packet.value); }
