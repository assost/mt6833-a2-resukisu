#pragma once

#include "linux/path.h"

struct address_space {
	unsigned long flags;
};

struct inode {
	struct address_space *i_mapping;
};

int kern_path(const char *name, unsigned int flags, struct path *path);
void path_put(struct path *path);
struct inode *d_backing_inode(struct dentry *dentry);
