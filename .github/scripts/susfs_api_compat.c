#include <linux/kernel.h>
#include <linux/slab.h>
#include <linux/string.h>
#include <linux/types.h>
#include <linux/uaccess.h>
#include <linux/workqueue.h>
#include <linux/fs.h>
#include <linux/namei.h>
#include <linux/path.h>
#include <linux/mount.h>
#include <linux/bitops.h>
#include <linux/static_key.h>
#include <linux/susfs_def.h>
#include <linux/susfs.h>
#include "susfs_419_logic.h"

extern void susfs_set_log(bool enabled);
extern void try_umount(const char *mnt, int flags);
extern bool susfs_is_mnt_devname_ksu(struct path *path);
extern void susfs_try_umount(uid_t target_uid);

struct work_struct susfs_extra_works;
static int susfs_extra_work_logged;

struct st_susfs_hide_sus_mnts_for_non_su_procs {
	bool enabled;
	int err;
};

struct st_susfs_enabled_features {
	char enabled_features[SUSFS_FEATURES_BUF];
	int err;
};

struct st_susfs_variant {
	char susfs_variant[SUSFS_QUERY_BUF];
	int err;
};

struct st_susfs_version {
	char susfs_version[SUSFS_QUERY_BUF];
	int err;
};

static unsigned int susfs_compiled_feature_mask(void)
{
	return susfs_419_feature_mask(
#ifdef CONFIG_KSU_SUSFS_SUS_PATH
		1,
#else
		0,
#endif
#ifdef CONFIG_KSU_SUSFS_SUS_MOUNT
		1,
#else
		0,
#endif
#ifdef CONFIG_KSU_SUSFS_AUTO_ADD_SUS_KSU_DEFAULT_MOUNT
		1,
#else
		0,
#endif
#ifdef CONFIG_KSU_SUSFS_AUTO_ADD_SUS_BIND_MOUNT
		1,
#else
		0,
#endif
#ifdef CONFIG_KSU_SUSFS_SUS_KSTAT
		1,
#else
		0,
#endif
#ifdef CONFIG_KSU_SUSFS_SUS_OVERLAYFS
		1,
#else
		0,
#endif
#ifdef CONFIG_KSU_SUSFS_TRY_UMOUNT
		1,
#else
		0,
#endif
#ifdef CONFIG_KSU_SUSFS_AUTO_ADD_TRY_UMOUNT_FOR_BIND_MOUNT
		1,
#else
		0,
#endif
#ifdef CONFIG_KSU_SUSFS_SPOOF_UNAME
		1,
#else
		0,
#endif
#ifdef CONFIG_KSU_SUSFS_ENABLE_LOG
		1,
#else
		0,
#endif
#ifdef CONFIG_KSU_SUSFS_HIDE_KSU_SUSFS_SYMBOLS
		1,
#else
		0,
#endif
#ifdef CONFIG_KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG
		1,
#else
		0,
#endif
#ifdef CONFIG_KSU_SUSFS_OPEN_REDIRECT
		1,
#else
		0,
#endif
		0,
#ifdef CONFIG_KSU_SUSFS_HAS_MAGIC_MOUNT
		1
#else
		0
#endif
	);
}

void susfs_extra_works_fn(struct work_struct *work)
{
	(void)work;
	if (!susfs_extra_work_logged) {
		susfs_extra_work_logged = 1;
		pr_err("susfs: v1.5.5 has no deferred sus_path_loop; extra work is an unsupported diagnostic and returns nothing to a caller\n");
	}
}

void susfs_set_hide_sus_mnts_for_non_su_procs(void __user **user_info)
{
	struct st_susfs_hide_sus_mnts_for_non_su_procs info;
	int result;

	if (!user_info || !*user_info) {
		pr_err("susfs: hide-mnts missing userspace buffer\n");
		return;
	}
	if (copy_from_user(&info, (struct st_susfs_hide_sus_mnts_for_non_su_procs __user *)*user_info,
			   sizeof(info))) {
		int err = -EFAULT;

		if (copy_to_user(&((struct st_susfs_hide_sus_mnts_for_non_su_procs __user *)*user_info)->err,
				 &err, sizeof(err)))
			pr_err("susfs: hide-mnts short copy, err write failed\n");
		return;
	}
	result = susfs_hide_mnts_result(1, 1);
	info.err = result;
	if (copy_to_user(&((struct st_susfs_hide_sus_mnts_for_non_su_procs __user *)*user_info)->err,
			 &info.err, sizeof(info.err)))
		pr_err("susfs: hide-mnts copy_to_user failed\n");
	else
		pr_err("susfs: hide-mnts is not implemented on 4.19 v1.5.5, err %d\n", result);
}

struct st_susfs_log {
	bool enabled;
	int err;
};

void susfs_enable_log(void __user **user_info)
{
	struct st_susfs_log info = {0};

	if (!user_info || !*user_info) {
		pr_err("susfs: enable_log missing userspace buffer; log state unchanged\n");
		return;
	}
	if (copy_from_user(&info, (struct st_susfs_log __user *)*user_info,
			   sizeof(info))) {
		info.err = -EFAULT;
		goto out;
	}
	susfs_set_log(info.enabled);
	info.err = 0;
out:
	if (copy_to_user(&((struct st_susfs_log __user *)*user_info)->err,
			 &info.err, sizeof(info.err))) {
		if (info.err == 0)
			pr_err("susfs: enable_log state already changed, copy_to_user failed\n");
		else
			pr_err("susfs: enable_log copy_to_user failed, log state unchanged\n");
	}
}

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
	if (!memchr(info.target_pathname, '\0', sizeof(info.target_pathname)) ||
	    info.target_pathname[0] == '\0') {
		info.err = -EINVAL;
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
	if (user_info && *user_info &&
	    copy_to_user(&((struct st_susfs_sus_map __user *)*user_info)->err,
			 &info.err, sizeof(info.err))) {
		if (info.err == 0)
			pr_err("susfs: add_sus_map state already changed, copy_to_user failed\n");
		else
			pr_err("susfs: add_sus_map copy_to_user failed\n");
	}
}

DEFINE_STATIC_KEY_FALSE(susfs_is_avc_log_spoofing_enabled);

struct st_susfs_avc_log_spoofing {
	bool enabled;
	int err;
};

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
	if (user_info && *user_info &&
	    copy_to_user(&((struct st_susfs_avc_log_spoofing __user *)*user_info)->err,
			 &info.err, sizeof(info.err))) {
		if (info.err == 0)
			pr_err("susfs: avc_log_spoofing state already changed, copy_to_user failed\n");
		else
			pr_err("susfs: avc_log_spoofing copy_to_user failed\n");
	}
}

void susfs_get_enabled_features(void __user **user_info)
{
	struct st_susfs_enabled_features *info;
	int sus_map =
#ifdef CONFIG_KSU_SUSFS_SUS_MAP
		1
#else
		0
#endif
		;

	if (!user_info || !*user_info) {
		pr_err("susfs: enabled-features missing userspace buffer\n");
		return;
	}
	info = kzalloc(sizeof(*info), GFP_KERNEL);
	if (!info) {
		int err = -ENOMEM;

		if (copy_to_user(&((struct st_susfs_enabled_features __user *)*user_info)->err,
				 &err, sizeof(err)))
			pr_err("susfs: enabled-features allocation failed, err write failed\n");
		return;
	}
	if (copy_from_user(info, (struct st_susfs_enabled_features __user *)*user_info,
			   sizeof(*info))) {
		int err = -EFAULT;

		kfree(info);
		if (copy_to_user(&((struct st_susfs_enabled_features __user *)*user_info)->err,
				 &err, sizeof(err)))
			pr_err("susfs: enabled-features short copy, err write failed\n");
		return;
	}
	susfs_format_enabled_features(info->enabled_features,
				      sizeof(info->enabled_features),
				      susfs_compiled_feature_mask(), sus_map,
				      &info->err);
	if (copy_to_user((struct st_susfs_enabled_features __user *)*user_info,
			 info, sizeof(*info)))
		pr_err("susfs: enabled-features copy_to_user failed\n");
	kfree(info);
}

void susfs_show_variant(void __user **user_info)
{
	struct st_susfs_variant info;

	if (!user_info || !*user_info) {
		pr_err("susfs: show-variant missing userspace buffer\n");
		return;
	}
	if (copy_from_user(&info, (struct st_susfs_variant __user *)*user_info,
			   sizeof(info))) {
		int err = -EFAULT;

		if (copy_to_user(&((struct st_susfs_variant __user *)*user_info)->err,
				 &err, sizeof(err)))
			pr_err("susfs: show-variant short copy, err write failed\n");
		return;
	}
	susfs_write_text(info.susfs_variant, sizeof(info.susfs_variant),
			 SUSFS_VARIANT, &info.err);
	if (copy_to_user((struct st_susfs_variant __user *)*user_info, &info,
			 sizeof(info)))
		pr_err("susfs: show-variant copy_to_user failed\n");
}

void susfs_show_version(void __user **user_info)
{
	struct st_susfs_version info;

	if (!user_info || !*user_info) {
		pr_err("susfs: show-version missing userspace buffer\n");
		return;
	}
	if (copy_from_user(&info, (struct st_susfs_version __user *)*user_info,
			   sizeof(info))) {
		int err = -EFAULT;

		if (copy_to_user(&((struct st_susfs_version __user *)*user_info)->err,
				 &err, sizeof(err)))
			pr_err("susfs: show-version short copy, err write failed\n");
		return;
	}
	susfs_write_text(info.susfs_version, sizeof(info.susfs_version),
			 SUSFS_VERSION, &info.err);
	if (copy_to_user((struct st_susfs_version __user *)*user_info, &info,
			 sizeof(info)))
		pr_err("susfs: show-version copy_to_user failed\n");
}

void susfs_start_sdcard_monitor_fn(void)
{
	pr_err("susfs: sdcard monitor is not part of v1.5.5; unsupported diagnostic, no error is returned to a caller\n");
}

#ifdef CONFIG_KSU_SUSFS_TRY_UMOUNT
void ksu_try_umount(const char *mnt, bool check_mnt, int flags, uid_t uid)
{
	struct path path;
	int err;
	int is_root = 0;
	int is_ksu = 0;

	(void)uid;
	err = kern_path(mnt, 0, &path);
	if (!err) {
		is_root = path.dentry == path.mnt->mnt_root;
		is_ksu = susfs_is_mnt_devname_ksu(&path);
		path_put(&path);
	}
	if (!susfs_should_umount(!err, is_root, check_mnt, is_ksu))
		return;
	try_umount(mnt, flags);
}

void susfs_try_umount_all(uid_t uid)
{
	susfs_try_umount(uid);
	ksu_try_umount("/system", true, 0, uid);
	ksu_try_umount("/system_ext", true, 0, uid);
	ksu_try_umount("/vendor", true, 0, uid);
	ksu_try_umount("/product", true, 0, uid);
	ksu_try_umount("/odm", true, 0, uid);
	ksu_try_umount("/data/adb/modules", false, MNT_DETACH, uid);
	ksu_try_umount("/debug_ramdisk", true, MNT_DETACH, uid);
}
#endif

#ifdef SUSFS_COMPAT_HOST_TEST
int susfs_host_avc_enabled(void)
{
	return susfs_is_avc_log_spoofing_enabled.enabled;
}

unsigned susfs_host_log_copy_size(void)
{
	return sizeof(struct st_susfs_log);
}
#endif
