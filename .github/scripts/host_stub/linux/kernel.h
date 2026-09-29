#pragma once

#include <stdarg.h>
#include <stddef.h>

#include "linux/errno.h"
#include "linux/types.h"

#include "linux/slab.h"

void susfs_test_pr(const char *fmt, ...);
#define pr_err(fmt, ...) susfs_test_pr(fmt, ##__VA_ARGS__)
#define pr_info(fmt, ...) susfs_test_pr(fmt, ##__VA_ARGS__)
