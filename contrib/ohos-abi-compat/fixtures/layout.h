#include <stddef.h>

#if defined(ABI_NEGATIVE)
#pragma pack(push, 1)
#endif
struct Packet { char tag; long value; };
#if defined(ABI_NEGATIVE)
#pragma pack(pop)
#endif

size_t packet_size(void);
long packet_value(struct Packet);
long callback(long);
int layout_test(void);
