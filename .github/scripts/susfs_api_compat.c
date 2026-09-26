#include <linux/kernel.h>
#include <linux/types.h>
#include <linux/uaccess.h>
#include <linux/workqueue.h>
#include <linux/susfs_def.h>

extern void susfs_set_log(bool enabled);

struct work_struct susfs_extra_works;

void susfs_extra_works_fn(struct work_struct *work)
{
}

void susfs_set_hide_sus_mnts_for_non_su_procs(void __user **user_info)
{
	pr_info("susfs: hide-mnts command has no 4.19 implementation\n");
}

void susfs_enable_log(void __user **user_info)
{
	bool enabled = true;

	if (user_info && *user_info)
		copy_from_user(&enabled, *user_info, sizeof(enabled));
	susfs_set_log(enabled);
}

#include <linux/fs.h>
#include <linux/namei.h>
#include <linux/bitops.h>
#include <linux/static_key.h>

DEFINE_STATIC_KEY_FALSE(susfs_is_avc_log_spoofing_enabled);

struct st_susfs_avc_log_spoofing {
	bool enabled;
	int err;
};

void susfs_add_sus_map(void __user **user_info)
{
	struct st_susfs_sus_map info = {0};
	struct path path;
	struct inode *inode;

	if (!user_info || !*user_info ||
	    copy_from_user(&info, (struct st_susfs_sus_map __user *)*user_info,
			   sizeof(info))) {
		info.err = -EFAULT;
		goto out;
	}
	info.err = kern_path(info.target_pathname, LOOKUP_FOLLOW, &path);
	if (info.err)
		goto out;
	inode = d_backing_inode(path.dentry);
	if (!inode || !inode->i_mapping) {
		info.err = -ENOENT;
		path_put(&path);
		goto out;
	}
	set_bit(AS_FLAGS_SUS_MAP, &inode->i_mapping->flags);
	path_put(&path);
	info.err = 0;
out:
	if (user_info && *user_info)
		copy_to_user(&((struct st_susfs_sus_map __user *)*user_info)->err,
			     &info.err, sizeof(info.err));
}

void susfs_set_avc_log_spoofing(void __user **user_info)
{
	struct st_susfs_avc_log_spoofing info = {0};

	if (!user_info || !*user_info ||
	    copy_from_user(&info, (struct st_susfs_avc_log_spoofing __user *)*user_info,
			   sizeof(info))) {
		info.err = -EFAULT;
		goto out;
	}
	if (info.enabled)
		static_branch_enable(&susfs_is_avc_log_spoofing_enabled);
	else
		static_branch_disable(&susfs_is_avc_log_spoofing_enabled);
	info.err = 0;
out:
	if (user_info && *user_info)
		copy_to_user(&((struct st_susfs_avc_log_spoofing __user *)*user_info)->err,
			     &info.err, sizeof(info.err));
}

void susfs_get_enabled_features(void __user **user_info)
{
}

void susfs_show_variant(void __user **user_info)
{
}

void susfs_show_version(void __user **user_info)
{
}

void susfs_start_sdcard_monitor_fn(void)
{
}
