#pragma once

struct dentry {
	int dummy;
};

struct vfsmount {
	int dummy;
};

struct path {
	struct vfsmount *mnt;
	struct dentry *dentry;
};
