#!/usr/bin/env python3
"""Run fix_missing_vendor.py on a fixture and check vendor macros are undefined."""
import contextlib
import io
import os
import shutil
import subprocess
import sys
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).resolve().parent / "fix_missing_vendor.py"
STUB = "stub: vendor source is not in this kernel drop"
LINK_PLACEHOLDER = b"/* Windows test: broken symlink placeholder */\n"


def write(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def main():
    work_arg = Path(sys.argv[1])
    if work_arg.is_symlink():
        raise SystemExit("test work directory must not be a symlink")
    work = work_arg.resolve()
    workspace = Path.cwd().resolve()
    if work == workspace or not work.is_relative_to(workspace):
        raise SystemExit("test work directory must be inside the workspace")
    marker = work / ".vendor-test-work"
    if work.exists():
        if not marker.is_file():
            raise SystemExit("refusing to remove a directory not created by this test")
        shutil.rmtree(work)
    work.mkdir(parents=True)
    marker.write_text("fix_missing_vendor test workspace\n")
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
    if len(sys.argv) > 3:
        workqueue_header = Path(sys.argv[3]).read_text()
    else:
        workqueue_header = (
            "enum {\n\tWQ_UNBOUND = 1 << 1,\n\tWQ_HIGHPRI = 1 << 4,\n"
            "#ifdef OPLUS_FEATURE_SCHED_ASSIST\n\tWQ_UX\t= 1 << 15,\n#endif\n"
            "\t__WQ_DRAINING = 1 << 16,\n};\n"
        )
    write(work / "include/linux/workqueue.h", workqueue_header)
    if len(sys.argv) > 4:
        drm_source = Path(sys.argv[4]).read_text()
    else:
        drm_source = (
            "struct drm_device *get_drm_device(){\n"
            "    return drm_dev;\n}\nEXPORT_SYMBOL(get_drm_device);\n"
        )
    write(work / "drivers/gpu/drm/mediatek/mtk_debug.c", drm_source)
    if len(sys.argv) > 5:
        audio_source = Path(sys.argv[5]).read_text()
    else:
        audio_source = (
            "void sia81xx_start(){\n        sia81xx_resume(g_sia81xx);\n}\n"
            "void sia81xx_stop(){\n        sia81xx_suspend(g_sia81xx);\n}\n"
        )
    write(work / "sound/soc/codecs/audio/sia81xx/sia81xx.c", audio_source)
    if len(sys.argv) > 6:
        recovery_source = Path(sys.argv[6]).read_text()
    else:
        recovery_source = (
            "static int mtk_drm_esd_check_worker_kthread(void *data)\n{\n"
            "        struct mtk_ddp_comp *output_comp;\n"
            "        unsigned int prj_id = get_project();\n"
            "        sched_setscheduler(current, SCHED_RR, &param);\n}\n"
        )
    write(work / "drivers/gpu/drm/mediatek/mtk_disp_recovery.c", recovery_source)
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
        work / "kernel/sysctl.c",
        "static int one_hundred = 100;\n"
        "#if defined(OPLUS_FEATURE_ZRAM_OPT) && defined(CONFIG_OPLUS_ZRAM_OPT)\n"
        "extern int direct_vm_swappiness;\n"
        "static int two_hundred = 200;\n"
        "#endif /*OPLUS_FEATURE_ZRAM_OPT*/\n",
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
    excluded_files = {}
    excluded_links = []
    for excluded_name in (".build-deps", ".git"):
        directory = work / excluded_name / "reference"
        directory.mkdir(parents=True)
        kconfig = directory / "Kconfig"
        kconfig.write_bytes(
            f'source "{excluded_name}/reference/generated/Kconfig"\r\n'.encode()
        )
        source = directory / "vendor.c"
        source.write_bytes(
            b"#define OPLUS_FEATURE_SCHED_ASSIST\r\n"
            b"#ifdef OPLUS_FEATURE_DEPS_ONLY\r\n"
            b"#include <linux/oplus_missing_reference.h>\r\n#endif\r\n"
        )
        excluded_files[kconfig] = kconfig.read_bytes()
        excluded_files[source] = source.read_bytes()
        link = directory / "broken.c"
        if os.name == "nt":
            link.write_bytes(LINK_PLACEHOLDER)
        else:
            link.symlink_to("missing-reference.c")
        excluded_links.append(link)
    normal_link = work / "normal/broken.c"
    normal_link.parent.mkdir()
    if os.name == "nt":
        normal_link.write_bytes(LINK_PLACEHOLDER)
    else:
        normal_link.symlink_to("missing-normal.c")
    normal_kconfig = work / "normal/Kconfig"
    normal_kconfig.write_bytes(b'source "normal/generated/Kconfig"\r\n')
    check_source_pruning(work, normal_link, excluded_links)
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
    for path, before in excluded_files.items():
        assert path.read_bytes() == before, f"reference input modified: {path}"
    for link in excluded_links:
        if os.name == "nt":
            assert link.read_bytes() == LINK_PLACEHOLDER
        else:
            assert link.is_symlink() and not link.exists(), f"reference symlink modified: {link}"
            assert link.readlink() == Path("missing-reference.c")
        assert not (link.parent / "generated/Kconfig").exists()
    assert "OPLUS_FEATURE_DEPS_ONLY" not in makefile + env
    assert not normal_link.is_symlink() and STUB in normal_link.read_text()
    assert b"\r" not in normal_kconfig.read_bytes()
    assert STUB in (work / "normal/generated/Kconfig").read_text()
    print("source scan exclusions: reference links/Kconfig/includes untouched; normal repairs passed")
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
    sysctl = (work / "kernel/sysctl.c").read_text(encoding="utf-8")
    if not sysctl.startswith("static int one_hundred = 100;\nstatic int two_hundred = 200;\n"):
        raise SystemExit("two_hundred stayed behind ZRAM_OPT")
    if "zone->free_area[order].nr_free;" not in mmstat:
        raise SystemExit("buddyinfo still requires the vendor free-area index")
    opened = (work / "fs/open.c").read_text(encoding="utf-8")
    proto = "int ksu_handle_faccessat(int *dfd, const char __user **filename_user, int *mode, int *flags);"
    if proto not in opened.split("#if", 1)[0] and proto not in opened.split("#endif", 1)[-1]:
        raise SystemExit("faccessat prototype was hidden inside an ifdef")
    process = (work / "include/soc/oplus/system/oppo_process.h").read_text(encoding="utf-8")
    if "oppo_is_android_core_group" not in process or "is_critial_process" not in process or "is_key_process" not in process:
        raise SystemExit("oppo_process stub missing")
    print("vendor macro suppression ok")
    audio_after = (work / "sound/soc/codecs/audio/sia81xx/sia81xx.c").read_text()
    for name in ("sia81xx_start", "sia81xx_stop"):
        audio_after = audio_after.replace(f"void {name}(void){{", f"void {name}(){{", 1)
    assert audio_after == audio_source, "audio function bodies or unrelated source changed"
    recovery_after = (work / "drivers/gpu/drm/mediatek/mtk_disp_recovery.c").read_text()
    recovery_after = recovery_after.replace("*output_comp __maybe_unused;", "*output_comp;", 1)
    recovery_after = recovery_after.replace("prj_id __maybe_unused = get_project();", "prj_id = get_project();", 1)
    assert recovery_after == recovery_source, "unrelated ESD source or initializer changed"
    check_vendor_compat(work)
    check_include_cache(work)


def check_source_pruning(work, normal_link, excluded_links):
    scope = {"__name__": "vendor_source_test"}
    exec(compile(SCRIPT.read_text(), str(SCRIPT), "exec"), scope)
    scope["ROOT"] = work
    original_scandir = os.scandir
    original_exists = Path.exists
    original_is_symlink = Path.is_symlink
    mock_links = {normal_link, *excluded_links}

    def guarded_scandir(path):
        assert not ({".git", ".build-deps"} & set(Path(path).relative_to(work).parts))
        return original_scandir(path)

    def emulated_link(path):
        return path in mock_links and original_exists(path) and path.read_bytes() == LINK_PLACEHOLDER

    def is_symlink(path):
        return emulated_link(path) or original_is_symlink(path)

    def exists(path):
        return not emulated_link(path) and original_exists(path)

    with contextlib.ExitStack() as stack:
        stack.enter_context(mock.patch.object(os, "scandir", guarded_scandir))
        if os.name == "nt":
            stack.enter_context(mock.patch.object(Path, "is_symlink", is_symlink))
            stack.enter_context(mock.patch.object(Path, "exists", exists))
        paths = list(scope["source_paths"]())
        assert normal_link in paths and not any(link in paths for link in excluded_links)
        assert scope["broken_symlinks"]() == [normal_link]
        if os.name == "nt":
            scope["stub_symlink"](normal_link)
    mode = "mocked broken links on Windows" if os.name == "nt" else "native broken links"
    print(f"source pruning: no descent into reference directories; {mode} passed")


def check_vendor_compat(work):
    workqueue = (work / "include/linux/workqueue.h").read_text()
    position = workqueue.index("WQ_UX")
    start = workqueue.rfind("enum {", 0, position)
    end = workqueue.index("};", position) + 2
    if start < 0:
        raise SystemExit("WQ_UX workqueue enum was not found")
    enum_source = workqueue[start:end]
    drm_path = work / "drivers/gpu/drm/mediatek/mtk_debug.c"
    drm = drm_path.read_text()
    start = drm.index("struct drm_device *get_drm_device(")
    end = drm.index("}", start) + 1
    drm_function = drm[start:end]
    audio_path = work / "sound/soc/codecs/audio/sia81xx/sia81xx.c"
    audio = audio_path.read_text()
    audio_functions = []
    for name in ("sia81xx_start", "sia81xx_stop"):
        start = audio.index(f"void {name}(")
        end = audio.index("}", start) + 1
        audio_functions.append(audio[start:end])
    recovery_path = work / "drivers/gpu/drm/mediatek/mtk_disp_recovery.c"
    recovery = recovery_path.read_text()
    start = recovery.index("static int mtk_drm_esd_check_worker_kthread(void *data)")
    end = recovery.index("sched_setscheduler(current, SCHED_RR, &param);", start)
    declarations = [line for line in recovery[start:end].splitlines()
                    if "*output_comp" in line or "prj_id" in line]
    assert len(declarations) == 2
    audio_checks = r'''
static int left_amp, right_amp;
static void *g_sia81xx, *resume_target, *suspend_target;
static unsigned int resume_calls, suspend_calls, project_calls;
static void sia81xx_resume(void *amp) { resume_target = amp; resume_calls++; }
static void sia81xx_suspend(void *amp) { suspend_target = amp; suspend_calls++; }
static unsigned int tracked_get_project(void) { project_calls++; return 42; }
#define __maybe_unused __attribute__((unused))
#define get_project tracked_get_project
static void exercise_esd_locals(void) {
''' + "\n".join(declarations) + "\n}\n#undef get_project\n" + "\n".join(audio_functions)
    write(work / "include/linux/types.h", "#include <stdbool.h>\n")
    source = (
        "#include <soc/oplus/system/oppo_project.h>\n"
        "#include <soc/oplus/system/oppo_project.h>\n"
        "extern unsigned int get_PCB_Version(void);\n"
        "struct drm_device { int id; };\n"
        "static struct drm_device device;\n"
        "static struct drm_device *drm_dev = &device;\n"
    ) + drm_function + "\n" + enum_source + "\n" + audio_checks + r'''
_Static_assert(RELEASE_VERSION == 0x00 && AGING == 0x01 && PREVERSION == 0x04 &&
               HIGH_TEMP_AGING == 0x0B && FACTORY == 0x0C, "official engineering IDs changed");
#ifdef OPLUS_FEATURE_SCHED_ASSIST
_Static_assert(WQ_UX == (1 << 15), "vendor-enabled flag changed");
_Static_assert((WQ_HIGHPRI | WQ_UNBOUND | WQ_UX) == ((1 << 4) | (1 << 1) | (1 << 15)), "enabled Mali flags changed");
#else
_Static_assert(WQ_UX == 0, "disabled vendor extension is not neutral");
_Static_assert((WQ_HIGHPRI | WQ_UNBOUND | WQ_UX) == ((1 << 4) | (1 << 1)), "Mali stock flags changed");
#endif
int main(void) {
    g_sia81xx = &left_amp;
    sia81xx_start();
    g_sia81xx = &right_amp;
    sia81xx_stop();
    exercise_esd_locals();
    return get_eng_version() != RELEASE_VERSION || get_eng_version() == AGING ||
           get_eng_version() == PREVERSION || get_eng_version() == HIGH_TEMP_AGING ||
           get_eng_version() == FACTORY || get_PCB_Version() != 0 ||
           get_drm_device() != drm_dev || project_calls != 1 ||
           resume_calls != 1 || suspend_calls != 1 ||
           resume_target != &left_amp || suspend_target != &right_amp;
}
'''
    c_file = work / "vendor_compat.c"
    write(c_file, source)
    compiler = os.environ.get("CC") or shutil.which("clang") or shutil.which("cc")
    if not compiler:
        raise SystemExit("a host C compiler is required for vendor compatibility checks")
    for enabled in (False, True):
        name = "vendor_enabled" if enabled else "vendor_disabled"
        executable = work / (name + (".exe" if os.name == "nt" else ""))
        command = [compiler, "-std=gnu11", "-Wall", "-Wstrict-prototypes", "-Werror", "-I", str(work / "include")]
        if enabled:
            command.append("-DOPLUS_FEATURE_SCHED_ASSIST=1")
        command.extend([str(c_file), "-o", str(executable)])
        result = subprocess.run(command, cwd=work, capture_output=True, text=True)
        if result.returncode:
            raise SystemExit(result.stdout + result.stderr)
        subprocess.run([str(executable)], cwd=work, check=True, timeout=15)
        print(f"{name}: strict prototypes, legacy include, release, DRM, audio targets and ESD initializer passed")
    mutant = work / "legacy_prototype_mutant.c"
    write(mutant, source.replace("get_drm_device(void)", "get_drm_device()"))
    command = [compiler, "-std=gnu11", "-Wstrict-prototypes", "-Werror", "-fsyntax-only",
               "-I", str(work / "include"), str(mutant)]
    result = subprocess.run(command, cwd=work, capture_output=True, text=True)
    if result.returncode == 0:
        raise SystemExit("strict-prototypes regression was not rejected")
    print("legacy DRM prototype regression rejected")
    scope = {"__name__": "vendor_compat_test"}
    exec(compile(SCRIPT.read_text(), str(SCRIPT), "exec"), scope)
    scope["ROOT"] = work
    project = work / "include/soc/oplus/system/oplus_project.h"
    legacy_project = work / "include/soc/oplus/system/oppo_project.h"
    before = project.read_bytes()
    legacy_before = legacy_project.read_bytes()
    with contextlib.redirect_stdout(io.StringIO()):
        scope["keep_workqueue_ux_flag"]()
        scope["write_oplus_project_header"]()
        scope["write_oppo_project_forward_header"]()
        scope["fix_drm_device_prototype"]()
        scope["fix_sia81xx_prototypes"]()
        scope["mark_esd_worker_unused_locals"]()
    assert project.read_bytes() == before
    assert legacy_project.read_bytes() == legacy_before
    assert drm_path.read_text() == drm
    assert audio_path.read_text() == audio
    assert recovery_path.read_text() == recovery
    assert (work / "include/linux/workqueue.h").read_text() == workqueue
    print("vendor compatibility patches: idempotent")


def check_include_cache(work):
    scope = {"__name__": "vendor_cache_test"}
    exec(compile(SCRIPT.read_text(), str(SCRIPT), "exec"), scope)
    root = work / "cache-fixture"
    root.mkdir()
    scope["ROOT"] = root
    present = root / "include/linux/present.h"
    write(present, "/* existing public header */\n" * 20)
    common = (
        "#ifdef OPLUS_FEATURE_EXISTING\n#include <linux/present.h>\n#endif\n"
        "#ifdef OPLUS_FEATURE_MISSING\n#include <linux/oplus_missing.h>\n#endif\n"
    )
    write(root / "left/a.c", common * 20 +
          '#ifdef OPLUS_FEATURE_LOCAL_PRESENT\n#include "oplus_local.h"\n#endif\n')
    write(root / "right/b.c", common * 20 +
          '#ifdef OPLUS_FEATURE_LOCAL_MISSING\n#include "oplus_local.h"\n#endif\n')
    write(root / "left/oplus_local.h", "/* real local header */\n" * 20)
    original = scope["_vendor_missing_include"]
    calls = []

    def counted(src, spec, quote):
        calls.append((src.parent, spec, quote))
        return original(src, spec, quote)

    scope["_vendor_missing_include"] = counted
    with contextlib.redirect_stdout(io.StringIO()):
        actual = scope["find_vendor_guard_macros"]()
    assert actual == {"OPLUS_FEATURE_MISSING", "OPLUS_FEATURE_LOCAL_MISSING"}, actual
    assert len(calls) == 4, calls
    # A new phase must observe changed files instead of reusing stale entries.
    write(present, f"/* {STUB} */\n")
    calls.clear()
    with contextlib.redirect_stdout(io.StringIO()):
        changed = scope["find_vendor_guard_macros"]()
    assert changed == actual | {"OPLUS_FEATURE_EXISTING"}, changed
    assert len(calls) == 4, calls

    class Candidate:
        def __init__(self, exists):
            self.exists = exists
            self.calls = 0

        def is_file(self):
            self.calls += 1
            return self.exists

    first, second = Candidate(True), Candidate(True)
    scope["_include_candidates"] = lambda *args: [first, second]
    scope["_is_stub_file"] = lambda path: False
    scope["_under_marked_stub"] = lambda path: False
    assert original(root / "sample.c", "linux/present.h", "<") is False
    assert first.calls == 1 and second.calls == 0
    print("include cache: 82 includes / 4 classifications, quoted scope, invalidation and candidate short-circuit passed")


if __name__ == "__main__":
    main()
