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

void susfs_add_sus_map(void __user **user_info)
{
	pr_info("susfs: sus_map is not part of the 4.19 patch\n");
}

void susfs_set_avc_log_spoofing(void __user **user_info)
{
	pr_info("susfs: avc log spoofing is not part of the 4.19 patch\n");
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
