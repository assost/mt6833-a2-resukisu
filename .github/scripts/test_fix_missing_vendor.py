#!/usr/bin/env python3
"""Run fix_missing_vendor.py on a fixture and check vendor macros are undefined."""
import contextlib
import io
import json
import os
import shutil
import shlex
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
    check_panel_project_fallbacks(work)
    check_dpmaif_dump_pointers(work)
    platform_fixtures = check_platform_vendor_fixes(work)
    platform_fixtures.update(check_baseline_include_layout(work))
    check_restored_vendor_mode(work, platform_fixtures)
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



def check_panel_project_fallbacks(work):
    scope = {"__name__": "panel_project_test"}
    exec(compile(SCRIPT.read_text(), str(SCRIPT), "exec"), scope)
    root = work / "panel-project-fixture"
    scope["ROOT"] = root
    fallback = "extern unsigned int __attribute((weak)) is_project(int project)  { return 0; }"
    if len(sys.argv) > 7:
        source = Path(sys.argv[7]).read_bytes()
    else:
        source = ("#include <soc/oplus/system/oplus_project.h>\n" + fallback +
                  "\nextern int __attribute((weak)) other_fallback(void) { return 7; }\n").encode()
    assert fallback.encode() in source
    panel = root / "drivers/gpu/drm/panel/confirmed.c"
    panel.parent.mkdir(parents=True)
    panel.write_bytes(source)
    crlf_panel = panel.with_name("same_fallback_crlf.c")
    crlf_source = (fallback + "\r\n").encode()
    crlf_panel.write_bytes(crlf_source)
    unchanged = {
        panel.with_name("nonzero.c"): fallback.replace("return 0;", "return 1;"),
        panel.with_name("other_signature.c"): fallback.replace("int project)", "int project_id)"),
        panel.with_suffix(".h"): fallback,
        root / "drivers/gpu/drm/other.c": fallback,
    }
    for path, content in unchanged.items():
        write(path, content + "\n")
    before = {path: path.read_bytes() for path in root.rglob("*") if path.is_file()}
    scope["guard_panel_project_fallbacks"]()
    for path in (panel, crlf_panel):
        newline = b"\r\n" if b"\r\n" in before[path] else b"\n"
        guarded = b"#ifndef _OPLUS_PROJECT_STUB_H_" + newline + fallback.encode() + newline + b"#endif"
        assert path.read_bytes().count(guarded) == 1
        assert path.read_bytes().replace(guarded, fallback.encode(), 1) == before[path], path
    for path in unchanged:
        assert path.read_bytes() == before[path], path
    after = {path: path.read_bytes() for path in before}
    scope["guard_panel_project_fallbacks"]()
    assert all(path.read_bytes() == content for path, content in after.items())
    print("panel fallback: exact zero definition only, unrelated files and CRLF preserved, idempotent")

    stub_include = root / "stub/include"
    real_include = root / "real/include"
    write(stub_include / "linux/types.h", "#include <stdbool.h>\n")
    write(stub_include / "soc/oplus/system/oplus_project.h",
          (work / "include/soc/oplus/system/oplus_project.h").read_text())
    write(real_include / "soc/oplus/system/oplus_project.h",
          "extern unsigned int is_project(int project);\n")
    patched = panel.read_text()
    start = patched.index("#ifndef _OPLUS_PROJECT_STUB_H_\n" + fallback)
    end = patched.index("#endif", start) + len("#endif")
    source = ("#include <soc/oplus/system/oplus_project.h>\n" + patched[start:end] +
              "\n#ifndef EXPECT_REAL\n#define EXPECT_REAL 0\n#endif\n"
              "int main(void) { return is_project(22083) != EXPECT_REAL || is_project(-1) != 0; }\n")
    translation_unit = root / "panel_project.c"
    write(translation_unit, source)
    strong = root / "real_project.c"
    write(strong, "unsigned int is_project(int project) { return project == 22083; }\n")
    compiler = os.environ.get("CC") or shutil.which("clang") or shutil.which("cc")
    if not compiler:
        raise SystemExit("a host C compiler is required for panel project checks")
    for mode, include in (("stub", stub_include), ("real_fallback", real_include),
                          ("real_override", real_include)):
        executable = root / (mode + (".exe" if os.name == "nt" else ""))
        command = [compiler, "-std=gnu11", "-Wall", "-Wstrict-prototypes", "-Werror",
                   "-I", str(include), str(translation_unit)]
        if mode == "real_override":
            command.extend(["-DEXPECT_REAL=1", str(strong)])
        command.extend(["-o", str(executable)])
        result = subprocess.run(command, capture_output=True, text=True)
        if result.returncode:
            raise SystemExit(result.stdout + result.stderr)
        subprocess.run([str(executable)], check=True, timeout=15)
        print(f"panel {mode}: strict compilation and is_project behavior passed")
    mutant = root / "panel_project_unguarded.c"
    write(mutant, source.replace(patched[start:end], fallback, 1))
    result = subprocess.run([compiler, "-std=gnu11", "-fsyntax-only", "-I", str(stub_include),
                             str(mutant)], capture_output=True, text=True)
    assert result.returncode != 0 and "is_project" in result.stderr and "redefinition" in result.stderr
    print("panel fallback: original stub redefinition reproduced and rejected")



def check_dpmaif_dump_pointers(work):
    scope = {"__name__": "dpmaif_pointer_test"}
    exec(compile(SCRIPT.read_text(), str(SCRIPT), "exec"), scope)
    root = work / "dpmaif-pointer-fixture"
    scope["ROOT"] = root
    signature = "static void dump_drb_queue_data(unsigned int qno)\n{"
    if len(sys.argv) > 8:
        original = Path(sys.argv[8]).read_bytes()
    else:
        original = (signature + '\nDPMA_DRB_DATA_INFO("%08X(%04d): %016llX %016llX %016llX %016llX %016llX %016llX %016llX %016llX\\n",\n'
                    '(u32)data_64ptr, (i * 8), *data_64ptr, *(data_64ptr + 1), *(data_64ptr + 2), *(data_64ptr + 3), *(data_64ptr + 4), *(data_64ptr + 5), *(data_64ptr + 6), *(data_64ptr + 7));\n'
                    'DPMA_DRB_DATA_INFO("%08X(%04d):", (u32)data_8ptr, count * 8);\n}\n').encode()
    path = root / "drivers/misc/mediatek/eccci/hif/ccci_hif_dpmaif.c"
    path.parent.mkdir(parents=True)
    path.write_bytes(original)
    scope["fix_dpmaif_dump_pointers"]()
    patched = path.read_bytes()
    restored = patched.replace(b'DPMA_DRB_DATA_INFO("%p(%04d):', b'DPMA_DRB_DATA_INFO("%08X(%04d):')
    restored = restored.replace(b"(void *)data_64ptr", b"(u32)data_64ptr")
    restored = restored.replace(b"(void *)data_8ptr", b"(u32)data_8ptr")
    assert restored == original, "DPMAIF data, loop or unrelated source changed"
    scope["fix_dpmaif_dump_pointers"]()
    assert path.read_bytes() == patched
    function = patched.decode().replace("\r\n", "\n")
    start = function.index(signature)
    function = function[start:function.index("\n}\n", start) + 3]
    calls = []
    position = 0
    while True:
        position = function.find('DPMA_DRB_DATA_INFO("%p(%04d):', position)
        if position < 0:
            break
        end = function.index(");", position) + 2
        calls.append(function[position:end])
        position = end
    assert len(calls) == 2
    source = r'''
#include <stdarg.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
typedef uint32_t u32;
static void *pointers[2];
static int offsets[2], call_count;
static unsigned long long data[8];
static void record(const char *format, ...) __attribute__((format(printf, 1, 2)));
static void record(const char *format, ...) {
    va_list args;
    int index;
    if (call_count >= 2 || strncmp(format, "%p(%04d):", 9)) abort();
    va_start(args, format);
    pointers[call_count] = va_arg(args, void *);
    offsets[call_count] = va_arg(args, int);
    if (call_count == 0)
        for (index = 0; index < 8; index++) data[index] = va_arg(args, unsigned long long);
    va_end(args);
    call_count++;
}
#define DPMA_DRB_DATA_INFO record
_Static_assert(sizeof(void *) > sizeof(u32), "the regression requires 64-bit pointers");
int main(void) {
    unsigned long long values[8] = {0x1122334455667788ULL, 2, 3, 4, 5, 6, 7, 8};
    unsigned long long *data_64ptr = values;
    unsigned char *data_8ptr = (unsigned char *)(uintptr_t)0x1234567887654321ULL;
    int i = 3, count = 7;
''' + "\n".join(calls) + r'''
    return call_count != 2 || pointers[0] != values || pointers[1] != data_8ptr ||
           (uintptr_t)pointers[1] != (uintptr_t)0x1234567887654321ULL ||
           offsets[0] != 24 || offsets[1] != 56 || memcmp(values, data, sizeof(values)) != 0;
}
'''
    unit = root / "pointer_logs.c"
    write(unit, source)
    compiler = os.environ.get("CC") or shutil.which("clang") or shutil.which("cc")
    if not compiler:
        raise SystemExit("a host C compiler is required for DPMAIF pointer checks")
    base = [compiler, "-std=gnu11", "-Wall", "-Wformat=2", "-Wpointer-to-int-cast", "-Werror"]
    executable = root / ("pointer_logs.exe" if os.name == "nt" else "pointer_logs")
    result = subprocess.run(base + [str(unit), "-o", str(executable)], capture_output=True, text=True)
    if result.returncode:
        raise SystemExit(result.stdout + result.stderr)
    subprocess.run([str(executable)], check=True, timeout=15)
    mutant = root / "pointer_logs_truncating.c"
    write(mutant, source.replace('(void *)data_64ptr', '(u32)data_64ptr').replace('(void *)data_8ptr', '(u32)data_8ptr'))
    result = subprocess.run(base + ["-fsyntax-only", str(mutant)], capture_output=True, text=True)
    assert result.returncode != 0 and "pointer-to-int-cast" in result.stderr
    print("DPMAIF: strict format check, full pointer width, offsets/data, source preservation and idempotence PASS; truncation regression rejected")




def check_platform_vendor_fixes(work):
    scope = {"__name__": "platform_vendor_test"}
    exec(compile(SCRIPT.read_text(), str(SCRIPT), "exec"), scope)
    root = work / "platform-full-vendor-fixture"
    scope["ROOT"] = root
    fhctl = "drivers/misc/mediatek/freqhopping/fhctl_new/clk-fhctl-mcupm.c"
    pmu = "drivers/misc/mediatek/pmic/mt6360/v1/pmu/"
    old_expr = b"+ (unsigned int)match_data->reg_tr;"
    new_expr = b"+ (unsigned long)match_data->reg_tr;"
    old_include = b'#include "../../../../../power/oplus/oplus_chg_track.h"'
    new_include = b'#include "../../../../../../power/oplus/oplus_chg_track.h"'
    inputs = {fhctl: b"priv_data->reg_tr = array->fhctl_base\n\t\t\t" + old_expr + b"\n",
              pmu + "mt6360_pmu_chg.c": old_include + b"\n",
              pmu + "mt6360_pmu_irq.c": old_include + b"\n"}
    if len(sys.argv) > 10:
        inputs = {rel: (Path(sys.argv[10]) / rel).read_bytes() for rel in inputs}
    for rel, content in inputs.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    target = root / "drivers/power/oplus/oplus_chg_track.h"
    write(target, "#define CHARGING_TRACK_MARKER 0x6360\n")
    scope["fix_fhctl_register_offset"]()
    scope["fix_pmu_charger_track_includes"]()
    outputs = {rel: (root / rel).read_bytes() for rel in inputs}
    assert outputs[fhctl].replace(new_expr, old_expr, 1) == inputs[fhctl]
    for rel in inputs:
        if rel != fhctl:
            assert outputs[rel].replace(new_include, old_include, 1) == inputs[rel]
            assert ((root / rel).parent / "../../../../../../power/oplus/oplus_chg_track.h").resolve() == target.resolve()
            assert not ((root / rel).parent / "../../../../../power/oplus/oplus_chg_track.h").exists()
    scope["fix_fhctl_register_offset"]()
    scope["fix_pmu_charger_track_includes"]()
    assert all((root / rel).read_bytes() == content for rel, content in outputs.items())
    compiler = os.environ.get("CC") or shutil.which("clang") or shutil.which("cc")
    if not compiler:
        raise SystemExit("clang is required for the ARM64 FHCTL regression")
    expression_text = outputs[fhctl].decode().replace("\r\n", "\n")
    start = expression_text.index("priv_data->reg_tr = array->fhctl_base")
    expression = expression_text[start:expression_text.index(";", start) + 1]
    source = ('struct registers { void *reg_tr; };\nstruct pll { void *fhctl_base; };\n'
              '_Static_assert(sizeof(unsigned long) == 8 && sizeof(void *) == 8, "ARM64 width");\n')
    for name, offset in (("high_offset", "0x200000090UL"), ("hardware_offset", "0xCCUL")):
        source += (f"unsigned long {name}(void) {{\n"
                   "struct registers match = {.reg_tr = (void *)" + offset + "}, output;\n"
                   "struct registers *match_data = &match, *priv_data = &output;\n"
                   "struct pll instance = {.fhctl_base = (void *)0x100000000UL}, *array = &instance;\n" +
                   expression + "\nreturn (unsigned long)priv_data->reg_tr;\n}\n")
    unit = root / "fhctl_width.c"
    write(unit, source)
    llvm = root / "fhctl_width.ll"
    base = [compiler, "--target=aarch64-linux-gnu", "-std=gnu11", "-ffreestanding", "-nostdinc", "-Wall", "-Werror"]
    result = subprocess.run(base + ["-O2", "-S", "-emit-llvm", str(unit), "-o", str(llvm)], capture_output=True, text=True)
    if result.returncode:
        raise SystemExit(result.stdout + result.stderr)
    ir = llvm.read_text()
    assert "ret i64 12884902032" in ir and "ret i64 4294967500" in ir, ir
    mutant = root / "fhctl_width_truncating.c"
    write(mutant, source.replace("(unsigned long)match_data->reg_tr", "(unsigned int)match_data->reg_tr"))
    result = subprocess.run(base + ["-fsyntax-only", str(mutant)], capture_output=True, text=True)
    assert result.returncode != 0 and "void-pointer-to-int-cast" in result.stderr
    probe = root / pmu / "charger_include_probe.c"
    write(probe, new_include.decode() + '\n_Static_assert(CHARGING_TRACK_MARKER == 0x6360, "correct charging header");\n')
    result = subprocess.run(base + ["-fsyntax-only", str(probe)], capture_output=True, text=True)
    if result.returncode:
        raise SystemExit(result.stdout + result.stderr)
    print("platform fixes: ARM64 high and 0xCC offsets, truncation rejection, real charging include path, exact source scope and idempotence PASS")
    return {rel: (inputs[rel], outputs[rel]) for rel in inputs}



def check_baseline_include_layout(work):
    scope = {"__name__": "baseline_include_test"}
    exec(compile(SCRIPT.read_text(), str(SCRIPT), "exec"), scope)
    root = work / "baseline-include-layout-fixture"
    scope["ROOT"] = root
    tree = root / ".build-deps/source"
    charger = tree / "vendor/oplus/kernel/charger"
    sensor = tree / "vendor/oplus/sensor/kernel/oplus_sensor_devinfo"
    header_name = "charger_ic/oplus_battery_mtk6833R.h"
    c_name = "charger_ic/oplus_battery_mtk6833R.c"
    header_targets = ["drivers/misc/mediatek/typec/tcpc/inc/tcpm.h",
                      "drivers/misc/mediatek/typec/tcpc/inc/mtk_direct_charge_vdm.h"]
    header_targets += ["drivers/power/supply/mediatek/charger/" + name for name in
                       ("mtk_pe_intf.h", "mtk_pe20_intf.h", "mtk_pdc_intf.h", "mtk_charger_init.h", "mtk_charger_intf.h")]
    c_targets = ["drivers/misc/mediatek/typec/tcpc/inc/tcpci.h",
                 "drivers/misc/mediatek/pmic/mt6360/inc/mt6360_pmu.h"]
    targets = header_targets + c_targets
    original = {}
    if len(sys.argv) > 9:
        modules = Path(sys.argv[9])
        sources = [(charger / name, modules / "vendor/oplus/kernel/charger" / name)
                   for name in ("Makefile", "v1/Makefile", "test-kit/Makefile", header_name, c_name)]
        sources += [(sensor / name, modules / "vendor/oplus/sensor/kernel/oplus_sensor_devinfo" / name)
                    for name in ("Makefile", "oplus_sensor_feedback/Makefile")]
        original = {source: source.read_bytes() for _, source in sources}
        for destination, source in sources:
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(original[source])
    else:
        write(charger / "Makefile", "obj-y += v1/\nobj-y += test-kit/\n")
        write(charger / "v1/Makefile", "obj-y += charger_ic/\n")
        write(charger / "test-kit/Makefile", "obj-y += test-kit.o\n")
        write(charger / header_name, '#if LINUX_VERSION_CODE < KERNEL_VERSION(4, 19, 0)\n/* 4.14 branch retained */\n#else\n' +
              "".join(f'#include "../../../../kernel-4.19/{target}"\n' for target in header_targets) + '#endif\n')
        write(charger / c_name, "".join(f'#include "../../../{target.removeprefix("drivers/")}"\n' for target in c_targets))
        write(sensor / "Makefile", 'ifeq ($(findstring k419, $(TARGET_PRODUCT)), k419)\nsubdir-ccflags-y += -D LINUX_KERNEL_VERSION_419\nsubdir-ccflags-y += -I$(srctree)/drivers/misc/mediatek/scp/include\nendif\nsubdir-ccflags-y += -I$(srctree)/drivers/misc/mediatek/scp/rv\n')
        write(sensor / "oplus_sensor_feedback/Makefile", "obj-y += sensor_feedback.o\n")

    def link_directory(alias, destination):
        alias.parent.mkdir(parents=True, exist_ok=True)
        if os.name == "nt":
            result = subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(alias), str(destination)], capture_output=True, text=True)
            if result.returncode:
                raise SystemExit(result.stdout + result.stderr)
        else:
            alias.symlink_to(os.path.relpath(destination, alias.parent), target_is_directory=True)

    link_directory(root / "drivers/power/oplus", charger)
    link_directory(charger / "v1/charger_ic", charger / "charger_ic")
    sensor_alias = root / "drivers/misc/mediatek/sensor/2.0/oplus_sensor_devinfo"
    link_directory(sensor_alias, sensor)
    for index, target in enumerate(targets):
        write(root / target, f"#define INCLUDED_KERNEL_HEADER_{index} {index + 1}\n")
    scp_header = "drivers/misc/mediatek/scp/include/scp.h"
    write(root / scp_header, "#define SCP_PUBLIC_HEADER_PRESENT 1\n")
    write(root / "drivers/misc/mediatek/scp/rv/scp_helper.h", '#include "scp_feature_define.h"\n')
    write(root / "drivers/misc/mediatek/scp/rv/scp_feature_define.h", '#include "scp.h"\n')
    kernel_paths = {"drivers/power/oplus/Makefile": charger / "Makefile",
                    "drivers/power/oplus/" + header_name: charger / header_name,
                    "drivers/power/oplus/" + c_name: charger / c_name,
                    "drivers/misc/mediatek/sensor/2.0/oplus_sensor_devinfo/Makefile": sensor / "Makefile"}
    before = {rel: path.read_bytes() for rel, path in kernel_paths.items()}
    scope["fix_sensor_scp_include_gate"]()
    scope["fix_charger_kernel_include_layout"]()
    after = {rel: path.read_bytes() for rel, path in kernel_paths.items()}
    restored_header = after["drivers/power/oplus/" + header_name]
    for target in header_targets:
        restored_header = restored_header.replace(f"#include <{target}>".encode(), f'#include "../../../../kernel-4.19/{target}"'.encode(), 1)
    assert restored_header == before["drivers/power/oplus/" + header_name], "4.14 branch or charger declarations changed"
    restored_c = after["drivers/power/oplus/" + c_name]
    for target in c_targets:
        restored_c = restored_c.replace(f"#include <{target}>".encode(), f'#include "../../../{target.removeprefix("drivers/")}"'.encode(), 1)
    assert restored_c == before["drivers/power/oplus/" + c_name]
    sensor_rel = "drivers/misc/mediatek/sensor/2.0/oplus_sensor_devinfo/Makefile"
    assert after[sensor_rel].replace(b"ifeq ($(VERSION).$(PATCHLEVEL),4.19)", b"ifeq ($(findstring k419, $(TARGET_PRODUCT)), k419)", 1) == before[sensor_rel]
    scope["fix_sensor_scp_include_gate"]()
    scope["fix_charger_kernel_include_layout"]()
    assert all(path.read_bytes() == after[rel] for rel, path in kernel_paths.items())
    assert (charger / "Makefile").read_text().splitlines().count("subdir-ccflags-y += -I$(srctree)") == 1
    assert all(source.read_bytes() == data for source, data in original.items()), "read-only reference clone changed"
    compiler = os.environ.get("CC") or shutil.which("clang") or shutil.which("cc")
    make = shutil.which("make")
    if not compiler or (not make and os.name != "nt"):
        raise SystemExit("C compiler and GNU make are required for include-layout checks")
    out = root / "out"
    out.mkdir()

    def make_flags(files, version, patchlevel, product=""):
        probe = out / "probe.mk"
        includes = "".join("include ../" + file.relative_to(root).as_posix() + "\n" for file in files)
        write(probe, includes + '$(info CHECK_FLAGS=$(subdir-ccflags-y))\n.PHONY: all\nall: ; @:\n')
        command = [make] if make else ["wsl.exe", "--cd", "/mnt/" + out.drive[0].lower() + out.as_posix()[2:], "--exec", "make"]
        result = subprocess.run(command + ["--no-print-directory", "-f", "probe.mk", "srctree=..", "src=drivers/power/oplus/v1",
                                f"VERSION={version}", f"PATCHLEVEL={patchlevel}", f"TARGET_PRODUCT={product}",
                                "CONFIG_MTK_SENSOR_ARCHITECTURE=2.0", "CONFIG_MTK_TINYSYS_SCP_RV_SUPPORT=y", "CONFIG_MTK_PLATFORM=mt6833"],
                                cwd=out, capture_output=True, text=True)
        if result.returncode:
            raise SystemExit(result.stdout + result.stderr)
        line = next(line for line in result.stdout.splitlines() if line.startswith("CHECK_FLAGS="))
        return shlex.split(line.split("=", 1)[1])

    sensor_files = [sensor / "Makefile", sensor / "oplus_sensor_feedback/Makefile"]
    flags = make_flags(sensor_files, 4, 19)
    assert "LINUX_KERNEL_VERSION_419" in flags and "-I../drivers/misc/mediatek/scp/include" in flags
    for version, patchlevel, product in ((4, 14, "k414"), (5, 10, "k419")):
        other = make_flags(sensor_files, version, patchlevel, product)
        assert "LINUX_KERNEL_VERSION_419" not in other and "-I../drivers/misc/mediatek/scp/include" not in other
    sensor_units = {'sensor_devinfo_probe.c': '#ifdef LINUX_KERNEL_VERSION_419\n#include "scp.h"\n#else\n#error wrong sensor kernel branch\n#endif\n',
                    'sensor_feedback_probe.c': '#include "scp_helper.h"\n'}
    for name, content in sensor_units.items():
        unit = out / name
        write(unit, content + '_Static_assert(SCP_PUBLIC_HEADER_PRESENT == 1, "SCP public path");\n')
        result = subprocess.run([compiler, "-std=gnu11", "-Werror", *flags, "-fsyntax-only", str(unit)], cwd=out, capture_output=True, text=True)
        if result.returncode:
            raise SystemExit(result.stdout + result.stderr)
    assertions = "".join(f'_Static_assert(INCLUDED_KERNEL_HEADER_{index} == {index + 1}, "header {index}");\n' for index in range(9))
    include_lines = [line for line in (charger / header_name).read_text().splitlines() + (charger / c_name).read_text().splitlines()
                     if line.startswith("#include <drivers/")]
    assert len(include_lines) == 9
    write(charger / "charger_ic/include_layout_probe.h", "\n".join(include_lines) + "\n" + assertions)
    write(charger / "charger_ic/include_layout_probe.c", '#include "include_layout_probe.h"\n')
    write(charger / "test-kit/include_layout_probe.c", '#include "../charger_ic/include_layout_probe.h"\n')
    for rel, child in (("charger_ic", charger / "v1/Makefile"), ("v1/charger_ic", charger / "v1/Makefile"), ("test-kit", charger / "test-kit/Makefile")):
        inherited = make_flags([charger / "Makefile", child], 4, 19)
        assert inherited.count("-I..") == 1
        unit = root / "drivers/power/oplus" / rel / "include_layout_probe.c"
        result = subprocess.run([compiler, "-std=gnu11", "-Werror", *inherited, "-fsyntax-only", str(unit)], cwd=out, capture_output=True, text=True)
        if result.returncode:
            raise SystemExit(result.stdout + result.stderr)
    print("include layout: GNU make 4.19/4.14/5.10 gates, both SCP consumers, nine charger headers through root/v1/test-kit aliases with O=out, scope and idempotence PASS")
    fixtures = {rel: (before[rel], after[rel]) for rel in kernel_paths}
    fixtures.update({target: ((root / target).read_bytes(), (root / target).read_bytes()) for target in targets + [scp_header]})
    return fixtures


def check_restored_vendor_mode(work, platform_fixtures):
    root = work / "restored-vendor-fixture"
    tree = root / ".build-deps/restore-all-test/source"
    system = tree / "vendor/oplus/kernel/system/include"
    system.mkdir(parents=True)
    if len(sys.argv) > 9:
        real_headers = Path(sys.argv[9]) / "vendor/oplus/kernel/system/include"
        shutil.copytree(real_headers, system, dirs_exist_ok=True)
        print(f"restored mode: checking original system headers from {real_headers}")
    else:
        write(system / "oplus_project.h", "extern unsigned int get_project(void);\nextern unsigned int is_project(int project);\n")
        write(system / "boot_mode.h", "extern int get_boot_mode(void);\n")
    alias = root / "include/soc/oplus/system"
    alias.parent.mkdir(parents=True)
    if os.name == "nt":
        linked = subprocess.run(["cmd.exe", "/d", "/c", "mklink", "/J", str(alias), str(system)],
                                capture_output=True, text=True)
        if linked.returncode:
            raise SystemExit(linked.stdout + linked.stderr)
    else:
        alias.symlink_to(system, target_is_directory=True)
    originals = {
        "Makefile": b"KBUILD_CFLAGS += -Wall\n",
        "OplusKernelEnvConfig.mk": Path(sys.argv[2]).read_bytes() if len(sys.argv) > 2 else b"ALLOWED_MCROS := OPLUS_FEATURE_CHG_BASIC OPLUS_FEATURE_CAMERA_COMMON OPLUS_FEATURE_SENSOR OPLUS_FEATURE_SCHED_ASSIST\n",
        "arch/arm64/configs/k6833v1_64_k419_defconfig": b"CONFIG_LTO_CLANG=y\nCONFIG_CFI_CLANG=y\nCONFIG_LOCKING_PROTECT=y\nCONFIG_KERNEL_LOCK_OPT=y\nCONFIG_OPLUS_LOCKING_STRATEGY=y\nCONFIG_OPLUS_FEATURE_SCHED_ASSIST=y\nCONFIG_OPLUS_HVDCP_SUPPORT=y\n",
        "include/linux/version.h": b"#include <generated/uapi/linux/version.h>\n",
        "include/linux/workqueue.h": Path(sys.argv[3]).read_bytes() if len(sys.argv) > 3 else b"enum { WQ_UX = 1 << 15 };\n",
        "kernel/sched/core.c": b"unsigned long vendor_uclamp(void) { return ux_uclamp_value; }\n",
        "kernel/sched/sched.h": b"extern int is_heavy_ux_task(struct task_struct *task);\n",
        "mm/vmscan.c": b"#ifdef OPLUS_FEATURE_ZRAM_OPT\nint direct_vm_swappiness = 60;\n#endif\n",
        "mm/slub.c": b"/* original allocator implementation */\n",
        "kernel/trace/trace_mmstat.c": b"/* original two-dimensional vendor free-area layout */\n",
    }
    for rel, data in originals.items():
        destination = root / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(data)
    for rel, (before, _) in platform_fixtures.items():
        destination = root / rel
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(before)
    write(root / "drivers/power/oplus/oplus_chg_track.h", "#define CHARGING_TRACK_MARKER 0x6360\n")
    header_bytes = {path: path.read_bytes() for path in system.rglob("*") if path.is_file()}
    write(root / "arch/arm64/kernel/vdso/Makefile", "ldflags-y := --build-id -n -T\n")
    write(root / "fs/open.c", '#include <linux/cred.h>\nint invoke(void) { return ksu_handle_faccessat(0, 0, 0, 0); }\n')
    configs = [root / "Kconfig", tree / "vendor/oplus/kernel/system/Kconfig"]
    for config in configs:
        config.write_bytes(b'config VENDOR_PRESENT\r\n\tbool "vendor implementation"\r\n')
    manifest_path = root / ".build-deps/vendor-restore-manifest.json"
    manifest = {"schema_version": 1, "mode": "all", "status": "complete", "unavailable": [],
                "installed_tree": tree.relative_to(root).as_posix(),
                "source_commit": "dd93a63de24dec560639b88d8328d4be7100a60d",
                "restored": [{"path": alias.relative_to(root).as_posix(),
                              "source": system.relative_to(tree).as_posix()}]}

    def snapshot():
        return {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}

    def rejected(expected):
        before = snapshot()
        result = subprocess.run([sys.executable, str(SCRIPT), "--restored-vendor"], cwd=root,
                                capture_output=True, text=True)
        assert result.returncode != 0 and expected in result.stderr, result.stdout + result.stderr
        assert snapshot() == before, "invalid restoration was modified before rejection"

    rejected("manifest is missing or invalid")
    manifest_path.write_text(json.dumps({**manifest, "status": "partial", "unavailable": [{"path": "drivers/power/oplus"}]}))
    rejected("incomplete")
    manifest_path.write_text(json.dumps({**manifest, "restored": [{"path": alias.relative_to(root).as_posix(), "source": "missing-required-source"}]}))
    rejected("required restored source is unavailable")
    manifest_path.write_text(json.dumps(manifest))
    result = subprocess.run([sys.executable, str(SCRIPT), "--restored-vendor"], cwd=root,
                            capture_output=True, text=True)
    if result.returncode:
        raise SystemExit(result.stdout + result.stderr)
    assert "restored vendor mode:" in result.stdout
    assert all((root / rel).read_bytes() == after for rel, (_, after) in platform_fixtures.items())
    assert all((root / rel).read_bytes() == data for rel, data in originals.items())
    assert all(path.read_bytes() == data for path, data in header_bytes.items())
    assert all(config.read_bytes() == b'config VENDOR_PRESENT\n\tbool "vendor implementation"\n' for config in configs)
    assert "-z notext" in (root / "arch/arm64/kernel/vdso/Makefile").read_text()
    assert "int ksu_handle_faccessat(int *dfd" in (root / "fs/open.c").read_text()
    assert not (root / "include/linux/healthinfo/ion.h").exists()
    assert not (root / "include/soc/oplus/system/oppo_process.h").exists() or (system / "oppo_process.h") in header_bytes
    before = snapshot()
    subprocess.run([sys.executable, str(SCRIPT), "--restored-vendor"], cwd=root,
                   check=True, capture_output=True)
    assert snapshot() == before
    (root / "Makefile").write_bytes(originals["Makefile"] + b"KBUILD_CFLAGS += -UOPLUS_FEATURE_CHG_BASIC\n")
    rejected("legacy vendor suppression remains")
    (root / "Makefile").write_bytes(originals["Makefile"])
    print(f"restored mode: {len(header_bytes)} real header files and factory macro/config/performance bytes retained; required-source failures, CR-only normalization, KSU declarations and idempotence PASS")


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
