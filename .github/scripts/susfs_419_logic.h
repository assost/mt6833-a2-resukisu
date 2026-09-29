#ifndef SUSFS_419_LOGIC_H
#define SUSFS_419_LOGIC_H

/* v1.5.5 command results shared by the 4.19 kernel and the host regression. */

#ifdef __KERNEL__
#include <linux/types.h>
#include <linux/string.h>
#else
#include <stddef.h>
#include <string.h>
#endif

#define SUSFS_ERR_NOT_SUPPORTED 126
#define SUSFS_QUERY_BUF 16
#define SUSFS_FEATURES_BUF 8192

struct susfs_feature_bit {
	unsigned int bit;
	const char *line;
};

/* Bit positions match ksu_susfs v1.5.5. Bit 13 is SUS_SU and stays off here. */
static const struct susfs_feature_bit susfs_419_feature_bits[] = {
	{1u << 0, "CONFIG_KSU_SUSFS_SUS_PATH\n"},
	{1u << 1, "CONFIG_KSU_SUSFS_SUS_MOUNT\n"},
	{1u << 2, "CONFIG_KSU_SUSFS_AUTO_ADD_SUS_KSU_DEFAULT_MOUNT\n"},
	{1u << 3, "CONFIG_KSU_SUSFS_AUTO_ADD_SUS_BIND_MOUNT\n"},
	{1u << 4, "CONFIG_KSU_SUSFS_SUS_KSTAT\n"},
	{1u << 5, "CONFIG_KSU_SUSFS_SUS_OVERLAYFS\n"},
	{1u << 6, "CONFIG_KSU_SUSFS_TRY_UMOUNT\n"},
	{1u << 7, "CONFIG_KSU_SUSFS_AUTO_ADD_TRY_UMOUNT_FOR_BIND_MOUNT\n"},
	{1u << 8, "CONFIG_KSU_SUSFS_SPOOF_UNAME\n"},
	{1u << 9, "CONFIG_KSU_SUSFS_ENABLE_LOG\n"},
	{1u << 10, "CONFIG_KSU_SUSFS_HIDE_KSU_SUSFS_SYMBOLS\n"},
	{1u << 11, "CONFIG_KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG\n"},
	{1u << 12, "CONFIG_KSU_SUSFS_OPEN_REDIRECT\n"},
	{1u << 13, "CONFIG_KSU_SUSFS_SUS_SU\n"},
	{1u << 14, "CONFIG_KSU_SUSFS_HAS_MAGIC_MOUNT\n"},
};

static inline unsigned int susfs_419_feature_mask(int path, int mount,
		int auto_ksu, int auto_bind, int kstat, int overlay,
		int try_umount, int auto_try, int uname, int log_on,
		int hide_symbols, int cmdline, int open_redirect,
		int sus_su, int magic_mount)
{
	unsigned int mask = 0;

	if (path)
		mask |= 1u << 0;
	if (mount)
		mask |= 1u << 1;
	if (auto_ksu)
		mask |= 1u << 2;
	if (auto_bind)
		mask |= 1u << 3;
	if (kstat)
		mask |= 1u << 4;
	if (overlay)
		mask |= 1u << 5;
	if (try_umount)
		mask |= 1u << 6;
	if (auto_try)
		mask |= 1u << 7;
	if (uname)
		mask |= 1u << 8;
	if (log_on)
		mask |= 1u << 9;
	if (hide_symbols)
		mask |= 1u << 10;
	if (cmdline)
		mask |= 1u << 11;
	if (open_redirect)
		mask |= 1u << 12;
	if (sus_su)
		mask |= 1u << 13;
	if (magic_mount)
		mask |= 1u << 14;
	return mask;
}

static inline int susfs_write_text(char *dst, size_t dst_size, const char *text,
		int *err)
{
	size_t length;

	if (!dst || !err || dst_size == 0)
		return -22;
	if (!text) {
		dst[0] = '\0';
		*err = -22;
		return *err;
	}
	length = strlen(text);
	if (length + 1 > dst_size) {
		dst[0] = '\0';
		*err = -28;
		return *err;
	}
	memcpy(dst, text, length + 1);
	*err = 0;
	return 0;
}

/* SUS_MAP has no v1.5.5 feature bit. It is appended only for the ReSukiSU reply. */
static inline int susfs_format_enabled_features(char *dst, size_t dst_size,
		unsigned int mask, int sus_map, int *err)
{
	size_t used = 0;
	size_t index;

	if (!dst || !err || dst_size == 0)
		return -22;
	dst[0] = '\0';
	for (index = 0; index < sizeof(susfs_419_feature_bits) /
			sizeof(susfs_419_feature_bits[0]); index++) {
		const char *line = susfs_419_feature_bits[index].line;
		size_t length;

		if ((mask & susfs_419_feature_bits[index].bit) == 0)
			continue;
		length = strlen(line);
		if (used + length + 1 > dst_size) {
			dst[0] = '\0';
			*err = -22;
			return *err;
		}
		memcpy(dst + used, line, length);
		used += length;
		dst[used] = '\0';
	}
	if (sus_map) {
		const char *line = "CONFIG_KSU_SUSFS_SUS_MAP\n";
		size_t length = strlen(line);

		if (used + length + 1 > dst_size) {
			dst[0] = '\0';
			*err = -22;
			return *err;
		}
		memcpy(dst + used, line, length + 1);
	}
	*err = 0;
	return 0;
}

static inline int susfs_hide_mnts_result(int user_present, int copied)
{
	if (!user_present || !copied)
		return -14;
	return SUSFS_ERR_NOT_SUPPORTED;
}

static inline int susfs_should_umount(int path_ok, int is_mount_root,
		int check_mnt, int is_ksu_dev)
{
	if (!path_ok || !is_mount_root)
		return 0;
	if (check_mnt && !is_ksu_dev)
		return 0;
	return 1;
}

static inline int susfs_sdcard_monitor_result(void)
{
	return SUSFS_ERR_NOT_SUPPORTED;
}

static inline int susfs_extra_work_result(void)
{
	return SUSFS_ERR_NOT_SUPPORTED;
}

#endif
