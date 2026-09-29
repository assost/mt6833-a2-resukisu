#pragma once

#include <stddef.h>

void *kzalloc(size_t size, int flags);
void kfree(void *ptr);

#ifndef GFP_KERNEL
#define GFP_KERNEL 0
#endif
