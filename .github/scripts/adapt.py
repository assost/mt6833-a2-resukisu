#!/usr/bin/env python3
"""Adapt the A2 4.19 tree and current ReSukiSU to the kernel-4.19 SUSFS sources."""
from pathlib import Path

ROOT = Path(".").resolve()


def must_replace(path: Path, old: str, new: str) -> None:
    file = ROOT / path
    text = file.read_text()
    if old not in text:
        raise SystemExit(f"anchor missing in {path}")
    if new in text:
        return
    file.write_text(text.replace(old, new, 1))


def insert_once(path: Path, anchor: str, insertion: str) -> None:
    file = ROOT / path
    text = file.read_text()
    if insertion in text:
        return
    if anchor not in text:
        raise SystemExit(f"anchor missing in {path}")
    file.write_text(text.replace(anchor, insertion + anchor, 1))


must_replace(
    Path("fs/exec.c"),
    """static int do_execveat_common(int fd, struct filename *filename,
			      struct user_arg_ptr argv,
			      struct user_arg_ptr envp,
			      int flags)
{
	return __do_execve_file(fd, filename, argv, envp, flags, NULL);
}""",
    """static int do_execveat_common(int fd, struct filename *filename,
			      struct user_arg_ptr argv,
			      struct user_arg_ptr envp,
			      int flags)
{
	int retval;

	ksu_handle_execveat(&fd, &filename, &argv, &envp, &flags);
	retval = __do_execve_file(fd, filename, argv, envp, flags, NULL);
	ksu_handle_post_execveat(&fd, &filename, &argv, &envp, &flags, &retval);
	return retval;
}""",
)

must_replace(
    Path("fs/open.c"),
    """SYSCALL_DEFINE3(faccessat, int, dfd, const char __user *, filename, int, mode)
{
	return do_faccessat(dfd, filename, mode);
}""",
    """SYSCALL_DEFINE3(faccessat, int, dfd, const char __user *, filename, int, mode)
{
	ksu_handle_faccessat(&dfd, &filename, &mode, NULL);
	return do_faccessat(dfd, filename, mode);
}""",
)

must_replace(
    Path("fs/stat.c"),
    """	error = vfs_fstatat(dfd, filename, &stat, flag);""",
    """	ksu_handle_stat(&dfd, &filename, &flag);
	error = vfs_fstatat(dfd, filename, &stat, flag);""",
)

must_replace(
    Path("fs/read_write.c"),
    """SYSCALL_DEFINE3(read, unsigned int, fd, char __user *, buf, size_t, count)
{
	return ksys_read(fd, buf, count);
}""",
    """SYSCALL_DEFINE3(read, unsigned int, fd, char __user *, buf, size_t, count)
{
	char __user *kbuf = buf;

	ksu_handle_sys_read(fd, &kbuf, &count);
	return ksys_read(fd, kbuf, count);
}""",
)

must_replace(
    Path("kernel/reboot.c"),
    """	struct pid_namespace *pid_ns = task_active_pid_ns(current);
	char buffer[256];
	int ret = 0;

	/* We only trust the superuser with rebooting the system. */""",
    """	struct pid_namespace *pid_ns = task_active_pid_ns(current);
	char buffer[256];
	int ret = 0;

	ksu_handle_sys_reboot(magic1, magic2, cmd, &arg);

	/* We only trust the superuser with rebooting the system. */""",
)

must_replace(
    Path("kernel/sys.c"),
    """long __sys_setresuid(uid_t ruid, uid_t euid, uid_t suid)
{
	struct user_namespace *ns = current_user_ns();""",
    """long __sys_setresuid(uid_t ruid, uid_t euid, uid_t suid)
{
	ksu_handle_setresuid(ruid, euid, suid);

	struct user_namespace *ns = current_user_ns();""",
)

must_replace(
    Path("drivers/input/input.c"),
    """	unsigned long flags;

	if (is_event_supported(type, dev->evbit, EV_MAX)) {""",
    """	unsigned long flags;

	ksu_handle_input_handle_event(&type, &code, &value);

	if (is_event_supported(type, dev->evbit, EV_MAX)) {""",
)

# Current ReSukiSU selects the struct filename hook when SUSFS is on.
# This 4.19 tree still passes a user pointer into do_faccessat().
must_replace(
    Path("KernelSU/kernel/feature/sucompat.h"),
    """#ifdef CONFIG_KSU_SUSFS
int ksu_handle_faccessat(int *dfd, struct filename **filename, int *mode, int *__unused_flags);
int ksu_handle_stat(int *dfd, struct filename **filename, int *flags);
#else
""",
    """#if 0
int ksu_handle_faccessat(int *dfd, struct filename **filename, int *mode, int *__unused_flags);
int ksu_handle_stat(int *dfd, struct filename **filename, int *flags);
#else
""",
)
must_replace(
    Path("KernelSU/kernel/feature/sucompat.c"),
    """#ifdef CONFIG_KSU_SUSFS
int ksu_handle_faccessat(int *dfd, struct filename **filename, int *mode, int *__unused_flags)
""",
    """#if 0
int ksu_handle_faccessat(int *dfd, struct filename **filename, int *mode, int *__unused_flags)
""",
)
must_replace(
    Path("KernelSU/kernel/feature/sucompat.c"),
    """#ifdef CONFIG_KSU_SUSFS
int ksu_handle_stat(int *dfd, struct filename **filename, int *flags)
""",
    """#if 0
int ksu_handle_stat(int *dfd, struct filename **filename, int *flags)
""",
)

dispatch = ROOT / "KernelSU/kernel/supercall/dispatch.c"
text = dispatch.read_text()
replacements = {
    "susfs_add_sus_path(arg);": "susfs_add_sus_path((struct st_susfs_sus_path __user *)*arg);",
    "susfs_add_sus_path_loop(arg);": "susfs_add_sus_path((struct st_susfs_sus_path __user *)*arg);",
    "susfs_add_sus_kstat(arg);": "susfs_add_sus_kstat((struct st_susfs_sus_kstat __user *)*arg);",
    "susfs_update_sus_kstat(arg);": "susfs_update_sus_kstat((struct st_susfs_sus_kstat __user *)*arg);",
    "susfs_set_uname(arg);": "susfs_set_uname((struct st_susfs_uname __user *)*arg);",
    "susfs_set_cmdline_or_bootconfig(arg);": "susfs_set_cmdline_or_bootconfig((char __user *)*arg);",
    "susfs_add_open_redirect(arg);": "susfs_add_open_redirect((struct st_susfs_open_redirect __user *)*arg);",
}
for old, new in replacements.items():
    if old not in text:
        raise SystemExit(f"dispatch anchor missing: {old}")
    text = text.replace(old, new)
if '#include <linux/susfs.h>' not in text:
    text = text.replace('#include <linux/susfs_def.h>', '#include <linux/susfs_def.h>\n#include <linux/susfs.h>')
dispatch.write_text(text)

header = ROOT / "include/linux/susfs_def.h"
extra = """
#include <linux/sched.h>
#include <linux/cred.h>
#include <linux/types.h>

void susfs_set_hide_sus_mnts_for_non_su_procs(void __user **user_info);
void susfs_enable_log(void __user **user_info);
void susfs_add_sus_map(void __user **user_info);
void susfs_set_avc_log_spoofing(void __user **user_info);
void susfs_get_enabled_features(void __user **user_info);
void susfs_show_variant(void __user **user_info);
void susfs_show_version(void __user **user_info);
void susfs_start_sdcard_monitor_fn(void);

static inline bool susfs_is_current_proc_no_su(void)
{
	return likely(current->susfs_task_state & TASK_STRUCT_NON_ROOT_USER_APP_PROC);
}
static inline void susfs_set_current_proc_no_su(void)
{
	current->susfs_task_state |= TASK_STRUCT_NON_ROOT_USER_APP_PROC;
}
static inline void susfs_clear_current_proc_no_su(void)
{
	current->susfs_task_state &= ~TASK_STRUCT_NON_ROOT_USER_APP_PROC;
}
static inline bool susfs_is_current_proc_umounted(void)
{
	return susfs_is_current_proc_no_su();
}
static inline void susfs_set_current_proc_umounted(void)
{
	susfs_set_current_proc_no_su();
}
static inline void susfs_clear_current_proc_umounted(void)
{
	susfs_clear_current_proc_no_su();
}
static inline bool susfs_is_current_proc_umounted_for_zygote_next(void)
{
	return susfs_is_current_proc_umounted();
}
static inline void susfs_set_current_proc_umounted_for_zygote_next(void)
{
	susfs_set_current_proc_umounted();
}
static inline void susfs_clear_current_proc_umounted_for_zygote_next(void)
{
	susfs_clear_current_proc_umounted();
}
static inline bool susfs_is_current_proc_umounted_app(void)
{
	return susfs_is_current_proc_umounted() && current_uid().val >= 10000;
}
"""
body = header.read_text()
if "susfs_set_current_proc_no_su" not in body:
    body = body.replace("#endif // #ifndef KSU_SUSFS_DEF_H", extra + "\n#endif // #ifndef KSU_SUSFS_DEF_H")
    header.write_text(body)

init = ROOT / "fs/susfs.c"
init_text = init.read_text()
needle = 'SUSFS_LOGI("susfs is initialized! version: " SUSFS_VERSION " \\n");'
addition = """extern struct work_struct susfs_extra_works;
	extern void susfs_extra_works_fn(struct work_struct *work);
	INIT_WORK(&susfs_extra_works, susfs_extra_works_fn);
	""" + needle
if "susfs_extra_works_fn" not in init_text:
    if needle not in init_text:
        raise SystemExit("susfs_init anchor missing")
    init.write_text(init_text.replace(needle, addition, 1))

print("adapt.py done")
