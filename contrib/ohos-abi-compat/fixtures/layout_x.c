#include "layout.h"
#include <stdio.h>
long callback(long value) { return value + 1; }
int layout_test(void)
{
  struct Packet packet = { 'K', 41 };
  if (packet_size() != sizeof packet)
    {
      puts("ABI_LAYOUT_MISMATCH");
      return 1;
    }
  return packet_value(packet) != 42;
}
