#!/usr/bin/env python3
"""Run fix_missing_vendor.py on a fixture and check vendor macros are undefined."""
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent / "fix_missing_vendor.py"
STUB = "stub: vendor source is not in this kernel drop"


def write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def main():
    work = Path(sys.argv[1])
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    real_mk = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    if real_mk is not None:
        write(work / "OplusKernelEnvConfig.mk", real_mk.read_text(encoding="utf-8"))
    else:
        write(
            work / "OplusKernelEnvConfig.mk",
            """
ALLOWED_MCROS := OPLUS_FEATURE_PHOENIX \\
OPLUS_FEATURE_SCHED_ASSIST \\
OPLUS_FEATURE_SENSOR \\
OPLUS_BUG_STABILITY

$(foreach myfeature,$(ALLOWED_MCROS),\\
         $(eval KBUILD_CFLAGS += -D$(myfeature)) \\
)

ifeq ($(OPLUS_FEATURE_SECURE_GUARD),yes)
KBUILD_CFLAGS += -DCONFIG_OPLUS_SECURE_GUARD
endif
ifeq ($(OPLUS_FEATURE_SECURE_ROOTGUARD),yes)
export CONFIG_OPLUS_ROOT_CHECK=y
endif
ifeq ($(OPLUS_FEATURE_SECURE_MOUNTGUARD),yes)
KBUILD_CFLAGS += -DCONFIG_OPLUS_MOUNT_BLOCK
endif
ifeq ($(OPLUS_FEATURE_SECURE_EXECGUARD),yes)
KBUILD_CFLAGS += -DCONFIG_OPLUS_EXECVE_BLOCK
endif
ifeq ($(OPLUS_FEATURE_SECURE_KEVENTUPLOAD),yes)
KBUILD_CFLAGS += -DCONFIG_OPLUS_KEVENT_UPLOAD
endif
""",
        )
    write(work / "Makefile", "KBUILD_CFLAGS += -Wall\n")
    write(
        work / "arch/arm64/configs/k6833v1_64_k419_defconfig",
        "\n".join(
            [
                "CONFIG_LTO_CLANG=y",
                "CONFIG_CFI_CLANG=y",
                "CONFIG_OPLUS_FEATURE_SCHED_ASSIST=y",
                "CONFIG_OPLUS_FEATURE_PHOENIX=y",
                "CONFIG_OPLUS_FEATURE_SENSOR=y",
                "CONFIG_LOCKING_PROTECT=y",
                "CONFIG_KERNEL_LOCK_OPT=y",
                "CONFIG_OPLUS_LOCKING_STRATEGY=y",
                "",
            ]
        ),
    )
    write(
        work / "arch/arm64/kernel/vdso/Makefile",
        "ldflags-y := --build-id -n -T\n",
    )
    write(
        work / "init/main.c",
        """
#ifdef OPLUS_FEATURE_PHOENIX
#include "../drivers/soc/oplus/system/oplus_phoenix/oplus_phoenix.h"
#endif
#ifdef OPLUS_BUG_STABILITY
#include "../drivers/soc/oplus/system/oplus_broad.h"
#endif
""",
    )
    write(
        work / "include/linux/mutex.h",
        """
#ifdef OPLUS_FEATURE_SCHED_ASSIST
#include <linux/sched_assist/sched_assist_mutex.h>
#endif
#ifdef OPLUS_FEATURE_SENSOR
#include <linux/existing.h>
#endif
""",
    )
    write(work / "include/linux/existing.h", "/* in-tree header */\n")
    write(
        work / "include/linux/sched_assist/Kconfig",
        f"# {STUB}\n",
    )
    write(
        work / "include/linux/sched_assist/sched_assist_mutex.h",
        f"/* {STUB} */\n",
    )
    write(work / "drivers/soc/oplus/system/Kconfig", f"# {STUB}\n")
    write(
        work / "include/uapi/linux/posix_types.h",
        "typedef struct { unsigned long fds_bits[1]; } __kernel_fd_set;\n",
    )
    write(
        work / "include/linux/shadow_check.c",
        "#include <linux/posix_types.h>\n#include <generated/autoconf.h>\n",
    )
    write(
        work / "kernel/trace/trace_mmstat.c",
        "\t\t\t\tbuddyinfo[order + 1] =\n\t\t\t\t\tzone->free_area[flc][order].nr_free;\n",
    )
    write(
        work / "fs/open.c",
        "#include <linux/fs.h>\n"
        "#if defined(OPLUS_FEATURE_IOMONITOR)\n"
        "#include <linux/existing.h>\n"
        "#endif\n"
        "int sys_faccessat(void)\n"
        "{\n"
        "\tksu_handle_faccessat(&dfd, &filename, &mode, NULL);\n"
        "\treturn 0;\n"
        "}\n",
    )
    write(
        work / "init/extra.c",
        "#include <linux/not_a_vendor_header.h>\n",
    )
    write(
        work / "kernel/sched/core.c",
        """
extern int sysctl_set_ux_uclamp_enable;
unsigned long uclamp_eff_value(struct task_struct *p, enum uclamp_id clamp_id)
{
	struct uclamp_se uc_eff;
	unsigned int uc_value;
	if (p->ux_state & SA_TYPE_TURBO && clamp_id == UCLAMP_MIN && sysctl_set_ux_uclamp_enable) {
		uc_value = ux_uclamp_value;
		if (p->uclamp[clamp_id].active) {
			if (p->uclamp[clamp_id].value > uc_value)
				uc_value = p->uclamp[clamp_id].value;
		 } else {
			uc_eff =  uclamp_eff_get(p, clamp_id);
			if (uc_eff.value > uc_value)
				uc_value = uc_eff.value;
		}
		return (unsigned long)uc_value;
	}
	if (p->uclamp[clamp_id].active)
		return (unsigned long)p->uclamp[clamp_id].value;
}
	tmp_value = uc_se->value;
	if (p->ux_state & SA_TYPE_TURBO && clamp_id == UCLAMP_MIN && sysctl_set_ux_uclamp_enable)
		tmp_value = ux_uclamp_value;
""",
    )
    write(
        work / "include/linux/sched.h",
        """
#if defined(OPLUS_FEATURE_SCHED_ASSIST) && defined(CONFIG_SCHED_WALT)
#define RAVG_HIST_SIZE_MAX 5
struct ravg { u32 demand; };
#endif
#if defined(OPLUS_FEATURE_SCHED_ASSIST) && defined(CONFIG_SCHED_WALT)
	struct ravg ravg;
#endif
#if defined(OPLUS_FEATURE_SCHED_ASSIST) && defined(CONFIG_SCHED_WALT)
enum task_event {
	TASK_WAKE = 2,
	IRQ_UPDATE = 5,
};
#endif
""",
    )
    write(
        work / "kernel/sched/sched.h",
        """
#if defined(OPLUS_FEATURE_SCHED_ASSIST) && defined(CONFIG_SCHED_WALT)
	u64 window_start;
#endif
#if defined(OPLUS_FEATURE_SCHED_ASSIST) && defined(CONFIG_SCHED_WALT)
extern unsigned int sysctl_sched_use_walt_cpu_util;
extern unsigned int sysctl_sched_use_walt_task_util;
extern unsigned int walt_ravg_window;
extern bool walt_disabled;
#endif
#endif /* __KERNEL_SCHED_H__ */
""",
    )
    write(
        work / "include/trace/events/sched.h",
        """
#if defined(OPLUS_FEATURE_SCHED_ASSIST) && defined(CONFIG_SCHED_WALT)
extern unsigned int walt_ravg_window;
#endif
""",
    )
    write(
        work / "mm/vmscan.c",
        """
#include <linux/debugfs.h>
int vm_swappiness = 60;
#if defined(OPLUS_FEATURE_ZRAM_OPT) && defined(CONFIG_OPLUS_ZRAM_OPT)
/*
 * Direct reclaim swappiness, exptct 0 - 60. Higher means more swappy and slower.
 */
int direct_vm_swappiness = 60;
#endif /*OPLUS_FEATURE_ZRAM_OPT*/
""",
    )
    write(
        work / "mm/slub.c",
        """
#else
static inline void setup_object_debug(struct kmem_cache *s,
			struct page *page, void *object) {}

static inline int alloc_debug_processing(struct kmem_cache *s,
	struct page *page, void *object, unsigned long addr) { return 0; }
""",
    )
    proc = subprocess.run(
        [sys.executable, str(SCRIPT)],
        cwd=work,
        text=True,
        capture_output=True,
    )
    sys.stdout.write(proc.stdout)
    sys.stderr.write(proc.stderr)
    if proc.returncode != 0:
        raise SystemExit(proc.returncode)

    makefile = (work / "Makefile").read_text(encoding="utf-8")
    env = (work / "OplusKernelEnvConfig.mk").read_text(encoding="utf-8")
    defconfig = (work / "arch/arm64/configs/k6833v1_64_k419_defconfig").read_text(
        encoding="utf-8"
    )
    version = (work / "include/linux/version.h").read_text(encoding="utf-8")
    required = [
        "CFLAGS_KERNEL += -UOPLUS_FEATURE_PHOENIX\n",
        "CFLAGS_MODULE += -UOPLUS_FEATURE_PHOENIX\n",
        "KBUILD_CPPFLAGS += -UOPLUS_FEATURE_PHOENIX\n",
        "CFLAGS_KERNEL += -UOPLUS_FEATURE_SCHED_ASSIST\n",
    ]
    for line in required:
        if line not in makefile:
            raise SystemExit(f"missing flag {line.strip()}")
    for banned in ("-UOPLUS_BUG_STABILITY", "-UOPLUS_FEATURE_SENSOR"):
        if banned in makefile:
            raise SystemExit(f"broad or in-tree macro was undefined: {banned}")
    if "filter-out" not in env or "OPLUS_FEATURE_PHOENIX" not in env.split("filter-out", 1)[1].split(")", 1)[0]:
        raise SystemExit("PHOENIX was not filtered out of ALLOWED_MCROS")
    if "OPLUS_FEATURE_SCHED_ASSIST" not in env.split("filter-out", 1)[1].split(")", 1)[0]:
        raise SystemExit("SCHED_ASSIST was not filtered out of ALLOWED_MCROS")
    if "OPLUS_BUG_STABILITY" in env.split("filter-out", 1)[1].split(")", 1)[0]:
        raise SystemExit("BUG_STABILITY was filtered out")
    for name in (
        "OPLUS_FEATURE_SECURE_GUARD",
        "OPLUS_FEATURE_SECURE_ROOTGUARD",
        "OPLUS_FEATURE_SECURE_MOUNTGUARD",
        "OPLUS_FEATURE_SECURE_EXECGUARD",
        "OPLUS_FEATURE_SECURE_KEVENTUPLOAD",
    ):
        if f"ifeq ($({name}),yes)" in env:
            raise SystemExit(f"{name} is still forced on")
        if f"ifeq ($({name}),no)" not in env:
            raise SystemExit(f"{name} ifeq missing")
    if "CONFIG_LTO_CLANG=y" not in defconfig or "CONFIG_CFI_CLANG=y" not in defconfig:
        raise SystemExit("LTO or CFI was dropped")
    if "CONFIG_OPLUS_FEATURE_PHOENIX=y" in defconfig:
        raise SystemExit("PHOENIX config stayed enabled")
    if "CONFIG_OPLUS_FEATURE_SENSOR=y" not in defconfig:
        raise SystemExit("in-tree SENSOR config was disabled")
    if version.strip() != "#include <generated/uapi/linux/version.h>":
        raise SystemExit(f"version.h is {version!r}")
    if (work / "include/linux/posix_types.h").exists():
        raise SystemExit("posix_types.h shadowed the uapi header")
    if (work / "include/linux/not_a_vendor_header.h").exists():
        raise SystemExit("created an unrelated header stub")
    vdso = (work / "arch/arm64/kernel/vdso/Makefile").read_text(encoding="utf-8")
    if "-z notext" not in vdso:
        raise SystemExit("vdso linker flag was not updated")
    if "suppressed vendor macros: 2" not in proc.stdout:
        raise SystemExit("expected exactly the two baseline vendor macros")
    if "vendor include kept:" not in proc.stdout:
        raise SystemExit("broad-guarded vendor include was not reported")
    core = (work / "kernel/sched/core.c").read_text(encoding="utf-8")
    if core.count("#ifdef OPLUS_FEATURE_SCHED_ASSIST\n") < 3:
        raise SystemExit("ux uclamp uses were not guarded")
    if "\tif (p->uclamp[clamp_id].active)\n" not in core:
        raise SystemExit("stock uclamp path was dropped")
    vmscan = (work / "mm/vmscan.c").read_text(encoding="utf-8")
    if "#if defined(OPLUS_FEATURE_ZRAM_OPT) && defined(CONFIG_OPLUS_ZRAM_OPT)\n/*\n * Direct reclaim" in vmscan:
        raise SystemExit("direct_vm_swappiness stayed behind ZRAM_OPT")
    if "int direct_vm_swappiness = 60;" not in vmscan:
        raise SystemExit("direct_vm_swappiness declaration missing")
    if "#include <linux/proc_fs.h>" not in vmscan:
        raise SystemExit("proc_fs.h was not included")
    user_sched = (work / "include/linux/sched.h").read_text(encoding="utf-8")
    if "#ifdef CONFIG_SCHED_WALT\n#define RAVG_HIST_SIZE_MAX 5\n" not in user_sched:
        raise SystemExit("ravg struct stayed behind sched_assist")
    if "#ifdef CONFIG_SCHED_WALT\n\tstruct ravg ravg;\n" not in user_sched:
        raise SystemExit("task ravg field stayed behind sched_assist")
    if "#ifdef CONFIG_SCHED_WALT\nenum task_event {\n" not in user_sched:
        raise SystemExit("walt task_event stayed behind sched_assist")
    trace = (work / "include/trace/events/sched.h").read_text(encoding="utf-8")
    if "#ifdef CONFIG_SCHED_WALT\nextern unsigned int walt_ravg_window;\n" not in trace:
        raise SystemExit("walt trace events stayed behind sched_assist")
    kernel_sched = (work / "kernel/sched/sched.h").read_text(encoding="utf-8")
    if "#ifdef CONFIG_SCHED_WALT\n\tu64 window_start;\n" not in kernel_sched:
        raise SystemExit("rq window_start stayed behind sched_assist")
    if "#ifdef CONFIG_SCHED_WALT\nextern unsigned int sysctl_sched_use_walt_cpu_util;\n" not in kernel_sched:
        raise SystemExit("walt externs stayed behind sched_assist")
    if "static inline void sf_task_util_record" not in kernel_sched:
        raise SystemExit("fair.c assist stubs were not inserted")
    if "static inline int is_heavy_ux_task" not in kernel_sched:
        raise SystemExit("is_heavy_ux_task stub missing")
    slub = (work / "mm/slub.c").read_text(encoding="utf-8")
    if "static inline void setup_page_debug" not in slub:
        raise SystemExit("setup_page_debug fallback missing")
    adapt = SCRIPT.parent / "adapt.py"
    if "#include <linux/cred.h>" not in adapt.read_text(encoding="utf-8"):
        raise SystemExit("susfs uid helper cannot see current_uid")
    project = (work / "include/soc/oplus/system/oplus_project.h").read_text(encoding="utf-8")
    if "is_project" not in project or "get_project" not in project or "AGING" not in project:
        raise SystemExit("oplus project stub is missing the callers used by fair.c")
    ion = (work / "include/linux/healthinfo/ion.h").read_text(encoding="utf-8")
    if "ion_total" not in ion:
        raise SystemExit("healthinfo ion stub missing")
    mmstat = (work / "kernel/trace/trace_mmstat.c").read_text(encoding="utf-8")
    if "zone->free_area[order].nr_free;" not in mmstat:
        raise SystemExit("buddyinfo still requires the vendor free-area index")
    opened = (work / "fs/open.c").read_text(encoding="utf-8")
    proto = "int ksu_handle_faccessat(int *dfd, const char __user **filename_user, int *mode, int *flags);"
    if proto not in opened.split("#if", 1)[0] and proto not in opened.split("#endif", 1)[-1]:
        raise SystemExit("faccessat prototype was hidden inside an ifdef")
    process = (work / "include/soc/oplus/system/oppo_process.h").read_text(encoding="utf-8")
    if "oppo_is_android_core_group" not in process or "is_critial_process" not in process:
        raise SystemExit("oppo_process stub missing")
    print("vendor macro suppression ok")


if __name__ == "__main__":
    main()
