#pragma once

#define SUSFS_MAX_LEN_PATHNAME 256
#define AS_FLAGS_SUS_MAP 39

struct st_susfs_sus_map {
	char target_pathname[SUSFS_MAX_LEN_PATHNAME];
	int err;
};
