#!/usr/bin/env python3
"""Behavior tests for the v1.5.5 reply logic and config pinning."""

import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import enable_susfs_419 as enabler

LOGIC = HERE / "susfs_419_logic.h"
PREPARE = HERE / "prepare.sh"
BUILD = HERE / "build_kernel.sh"
COMPAT = HERE / "susfs_api_compat.c"
ADAPT = HERE / "adapt.py"
KCONFIG = HERE / "fixtures" / "resukisu-susfs-kconfig.fragment"
WORK_ROOT = HERE.parents[1] / "artifacts" / "actions-20260929-local" / "test-work"


def make_work(prefix):
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    path = WORK_ROOT / (prefix + os.urandom(3).hex())
    path.mkdir()
    return path

BEHAVIOR = r'''
#include <stdio.h>
#include <string.h>
#include "susfs_419_logic.h"

static int failures;

static void expect(int condition, const char *message)
{
	if (!condition) {
		fprintf(stderr, "FAIL %s\n", message);
		failures++;
	}
}

int main(void)
{
	char version[SUSFS_QUERY_BUF];
	char features[SUSFS_FEATURES_BUF];
	char tiny[4];
	int err = 99;
	unsigned int mask;

	expect(susfs_write_text(version, sizeof(version), "v1.5.5", &err) == 0, "version write");
	expect(err == 0 && strcmp(version, "v1.5.5") == 0, "version value");
	err = 0;
	expect(susfs_write_text(tiny, sizeof(tiny), "NON-GKI", &err) == -28, "short buffer");
	expect(err == -28 && tiny[0] == '\0', "short buffer clears");
	err = 0;
	expect(susfs_write_text(version, sizeof(version), "NON-GKI", &err) == 0, "variant write");
	expect(strcmp(version, "NON-GKI") == 0, "variant value");

	mask = susfs_419_feature_mask(1, 1, 1, 1, 1, 0, 1, 1, 1, 1, 1, 1, 1, 0, 1);
	expect((mask & (1u << 5)) == 0, "overlay bit off");
	expect((mask & (1u << 13)) == 0, "sus_su bit off");
	expect((mask & (1u << 14)) != 0, "magic mount bit on");
	err = 0;
	expect(susfs_format_enabled_features(features, sizeof(features), mask, 1, &err) == 0,
	       "feature format");
	expect(strstr(features, "CONFIG_KSU_SUSFS_TRY_UMOUNT\n") != NULL, "try_umount listed");
	expect(strstr(features, "CONFIG_KSU_SUSFS_HAS_MAGIC_MOUNT\n") != NULL, "magic listed");
	expect(strstr(features, "CONFIG_KSU_SUSFS_SUS_MAP\n") != NULL, "sus_map string only");
	expect(strstr(features, "CONFIG_KSU_SUSFS_SUS_OVERLAYFS\n") == NULL, "overlay omitted");
	mask = susfs_419_feature_mask(1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 0, 1);
	expect((mask & (1u << 5)) != 0, "overlay bit on");
	err = 0;
	expect(susfs_format_enabled_features(features, sizeof(features), mask, 1, &err) == 0,
	       "overlay format");
	expect(strstr(features, "CONFIG_KSU_SUSFS_SUS_OVERLAYFS\n") != NULL, "overlay listed");
	expect(strstr(features, "CONFIG_KSU_SUSFS_SUS_SU\n") == NULL, "sus_su omitted");
	expect(strstr(features, "CONFIG_KSU_SUSFS_SUS_PATH\n") <
	       strstr(features, "CONFIG_KSU_SUSFS_SUS_MAP\n"), "sus_map has no v1.5.5 bit");

	expect(susfs_hide_mnts_result(0, 1) == -14, "hide missing user");
	expect(susfs_hide_mnts_result(1, 0) == -14, "hide copy failure");
	expect(susfs_hide_mnts_result(1, 1) == SUSFS_ERR_NOT_SUPPORTED, "hide unsupported");
	expect(susfs_should_umount(0, 1, 0, 1) == 0, "missing path");
	expect(susfs_should_umount(1, 0, 0, 1) == 0, "not mount root");
	expect(susfs_should_umount(1, 1, 1, 0) == 0, "checked non-ksu");
	expect(susfs_should_umount(1, 1, 1, 1) == 1, "checked ksu");
	expect(susfs_should_umount(1, 1, 0, 0) == 1, "unchecked mount");
	expect(susfs_sdcard_monitor_result() == SUSFS_ERR_NOT_SUPPORTED, "sdcard");
	expect(susfs_extra_work_result() == SUSFS_ERR_NOT_SUPPORTED, "extra work");

	if (failures) {
		fprintf(stderr, "%d failures\n", failures);
		return 1;
	}
	puts("susfs 4.19 reply behavior: PASS");
	return 0;
}
'''


def compile_and_run():
    compiler = os.environ.get("CC") or shutil.which("clang") or shutil.which("cc") or shutil.which("gcc")
    if not compiler:
        raise SystemExit("a host C compiler is required")
    work = make_work("behavior-")
    try:
        source = work / "behavior.c"
        header = work / "susfs_419_logic.h"
        source.write_text(BEHAVIOR, encoding="utf-8", newline="\n")
        header.write_text(LOGIC.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
        executable = work / ("behavior.exe" if os.name == "nt" else "behavior")
        build = subprocess.run(
            [compiler, "-std=c11", "-Wall", "-Werror", str(source), "-o", str(executable)],
            capture_output=True, text=True)
        if build.returncode:
            raise SystemExit(build.stdout + build.stderr)
        subprocess.run([str(executable)], check=True, timeout=15)
    finally:
        shutil.rmtree(work)


def config_roundtrip():
    if not KCONFIG.is_file():
        raise SystemExit(f"missing Kconfig fixture {KCONFIG}")
    work = make_work("config-")
    try:
        kconfig = work / "Kconfig"
        defconfig = work / "defconfig"
        kconfig.write_text(KCONFIG.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
        defconfig.write_text(
            "CONFIG_LTO_CLANG=y\nCONFIG_CFI_CLANG=y\n"
            "# CONFIG_KSU_SUSFS_TRY_UMOUNT is not set\n",
            encoding="utf-8", newline="\n")
        first_k, first_d = enabler.enable(kconfig.read_text(encoding="utf-8"),
                                          defconfig.read_text(encoding="utf-8"))
        second_k, second_d = enabler.enable(first_k, first_d)
        if first_k != second_k or first_d != second_d:
            raise SystemExit("config enable is not idempotent")
        for name in enabler.ENABLED:
            if f"{name}=y" not in second_d:
                raise SystemExit(f"missing {name}")
            if f"# {name} is not set" in second_d:
                raise SystemExit(f"disabled line remained for {name}")
        if "CONFIG_LTO_CLANG=y" not in second_d or "CONFIG_CFI_CLANG=y" not in second_d:
            raise SystemExit("LTO or CFI dropped")
        if enabler.MARKER not in second_k or second_k.count(enabler.MARKER) != 1:
            raise SystemExit("Kconfig marker was not inserted once")
        for name in enabler.REJECTED:
            if f"{name}=y" in second_d:
                raise SystemExit(f"rejected option written: {name}")
        try:
            enabler.enable(second_k, second_d + "CONFIG_KSU_SUSFS_SUS_SU=y\n")
        except SystemExit:
            pass
        else:
            raise SystemExit("SUS_SU was accepted")
    finally:
        shutil.rmtree(work)
    print("susfs 4.19 config roundtrip: PASS")


def source_contract():
    prepare = PREPARE.read_text(encoding="utf-8")
    build = BUILD.read_text(encoding="utf-8")
    compat = COMPAT.read_text(encoding="utf-8")
    logic = LOGIC.read_text(encoding="utf-8")
    if "#ifdef __KERNEL__" not in logic or "#include <linux/string.h>" not in logic:
        raise SystemExit("logic header does not switch kernel headers")
    if logic.split("#else", 1)[1].find("#include <string.h>") < 0:
        raise SystemExit("host string.h is not limited to the non-kernel branch")
    adapt = ADAPT.read_text(encoding="utf-8")
    if "susfs_try_umount_all(new_uid)" not in adapt:
        raise SystemExit("adapt.py does not run the v1.5.5 try-umount list")
    required = (
        "fa8311f632a215b5381ec644627c6198d1e8a13e",
        "001e69919c6271f690fd00b17e4c721c9e599152",
        "historical CI SHA unknown",
        '#define SUSFS_VERSION "v1.5.5"',
        "susfs_419_logic.h",
    )
    for item in required:
        if item not in prepare:
            raise SystemExit(f"prepare.sh missing {item}")
    if "git clone --depth 1 -b kernel-4.19" in prepare:
        raise SystemExit("prepare.sh still floats the SUSFS branch")
    for name in enabler.ENABLED:
        if f'"{name}=y"' not in build:
            raise SystemExit(f"build validation missing {name}")
    if '"CONFIG_LTO_CLANG=y"' not in build or '"CONFIG_CFI_CLANG=y"' not in build:
        raise SystemExit("build validation lost LTO or CFI")
    for needle in (
        "susfs_write_text",
        "susfs_format_enabled_features",
        "susfs_hide_mnts_result",
        "susfs_should_umount",
        "v1.5.5 has no deferred sus_path_loop",
        "returns nothing to a caller",
        "sdcard monitor is not part of v1.5.5",
        "no error is returned to a caller",
        "#include <linux/slab.h>",
    ):
        if needle not in compat:
            raise SystemExit(f"compat missing {needle}")
    if "void susfs_show_version(void __user **user_info)\n{\n}" in compat:
        raise SystemExit("show_version is still empty")
    print("susfs 4.19 source contract: PASS")


ENTRY = r'''
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "linux/susfs_def.h"
#include "linux/workqueue.h"
#include "susfs_419_logic.h"

struct st_susfs_version {
	char susfs_version[SUSFS_QUERY_BUF];
	int err;
};

struct st_susfs_variant {
	char susfs_variant[SUSFS_QUERY_BUF];
	int err;
};

struct st_susfs_hide_sus_mnts_for_non_su_procs {
	bool enabled;
	int err;
};

struct st_susfs_enabled_features {
	char enabled_features[SUSFS_FEATURES_BUF];
	int err;
};

struct st_susfs_log {
	bool enabled;
	int err;
};

struct st_susfs_avc_log_spoofing {
	bool enabled;
	int err;
};

void susfs_test_reset(void);
extern int susfs_test_log_sets;
extern int susfs_test_log_value;
extern int susfs_test_kern_calls;
extern int susfs_test_path_puts;
extern int susfs_test_set_bits;
extern int susfs_test_last_bit;
extern int susfs_test_kern_result;
extern int susfs_test_null_inode;
extern int susfs_test_null_mapping;
extern int susfs_test_copy_from_fail;
extern int susfs_test_copy_to_fail;
extern int susfs_test_alloc_fail;
extern unsigned long susfs_test_last_copy_from_n;
extern char susfs_test_messages[8192];

void susfs_enable_log(void **user_info);
void susfs_add_sus_map(void **user_info);
void susfs_set_avc_log_spoofing(void **user_info);
void susfs_show_version(void **user_info);
void susfs_show_variant(void **user_info);
void susfs_set_hide_sus_mnts_for_non_su_procs(void **user_info);
void susfs_get_enabled_features(void **user_info);
void susfs_start_sdcard_monitor_fn(void);
void susfs_extra_works_fn(struct work_struct *work);
int susfs_host_avc_enabled(void);
unsigned susfs_host_log_copy_size(void);

static int failures;

static void expect(int condition, const char *message)
{
	if (!condition) {
		fprintf(stderr, "FAIL %s\n", message);
		failures++;
	}
}

static struct st_susfs_sus_map map_of(const char *path)
{
	struct st_susfs_sus_map info;

	memset(&info, 0, sizeof(info));
	if (path)
		memcpy(info.target_pathname, path, strlen(path) + 1);
	info.err = 77;
	return info;
}

int main(void)
{
	struct st_susfs_log log_info;
	struct st_susfs_sus_map map;
	struct st_susfs_avc_log_spoofing avc;
	struct work_struct work = {0};
	void *log_ptr;
	void *map_ptr;
	void *avc_ptr;

	expect(susfs_host_log_copy_size() == sizeof(log_info), "log struct size");

	susfs_test_reset();
	susfs_enable_log(NULL);
	expect(susfs_test_log_sets == 0, "null log pointer");
	expect(strstr(susfs_test_messages, "log state unchanged") != NULL, "null log diagnostic");

	susfs_test_reset();
	log_ptr = NULL;
	susfs_enable_log(&log_ptr);
	expect(susfs_test_log_sets == 0, "null log buffer");

	susfs_test_reset();
	memset(&log_info, 0, sizeof(log_info));
	log_info.enabled = 1;
	log_info.err = 77;
	log_ptr = &log_info;
	susfs_test_copy_from_fail = 4;
	susfs_enable_log(&log_ptr);
	expect(susfs_test_log_sets == 0, "short log copy leaves state");
	expect(log_info.err == -14, "short log copy stores EFAULT");
	expect(susfs_test_last_copy_from_n == sizeof(log_info), "log copy size");

	susfs_test_reset();
	log_info.enabled = 1;
	log_info.err = 77;
	log_ptr = &log_info;
	susfs_enable_log(&log_ptr);
	expect(susfs_test_log_sets == 1 && susfs_test_log_value == 1, "enable log");
	expect(log_info.err == 0, "enable log err");

	susfs_test_reset();
	log_info.enabled = 0;
	log_info.err = 77;
	log_ptr = &log_info;
	susfs_enable_log(&log_ptr);
	expect(susfs_test_log_value == 0 && log_info.err == 0, "disable log");

	susfs_test_reset();
	log_info.enabled = 1;
	log_info.err = 77;
	log_ptr = &log_info;
	susfs_test_copy_to_fail = 1;
	susfs_enable_log(&log_ptr);
	expect(susfs_test_log_sets == 1 && susfs_test_log_value == 1, "log changed before reply failure");
	expect(log_info.err == 77, "failed reply leaves old err");
	expect(strstr(susfs_test_messages, "enable_log state already changed") != NULL,
	       "log reply diagnostic");

	susfs_test_reset();
	susfs_add_sus_map(NULL);
	expect(susfs_test_kern_calls == 0 && susfs_test_path_puts == 0, "null map pointer");

	susfs_test_reset();
	map = map_of("/data/target");
	map_ptr = &map;
	susfs_test_copy_from_fail = 3;
	susfs_add_sus_map(&map_ptr);
	expect(susfs_test_kern_calls == 0 && map.err == -14, "short map copy");

	susfs_test_reset();
	memset(&map, 'A', sizeof(map));
	map.err = 77;
	map_ptr = &map;
	susfs_add_sus_map(&map_ptr);
	expect(susfs_test_kern_calls == 0 && susfs_test_path_puts == 0, "unterminated path");
	expect(map.err == -22, "unterminated path error");

	susfs_test_reset();
	map = map_of("");
	map_ptr = &map;
	susfs_add_sus_map(&map_ptr);
	expect(susfs_test_kern_calls == 0 && map.err == -22, "empty path");

	susfs_test_reset();
	map = map_of("/missing");
	map_ptr = &map;
	susfs_test_kern_result = -2;
	susfs_add_sus_map(&map_ptr);
	expect(susfs_test_kern_calls == 1 && susfs_test_path_puts == 0, "missing path releases nothing");
	expect(map.err == -2, "missing path error");

	susfs_test_reset();
	map = map_of("/no-inode");
	map_ptr = &map;
	susfs_test_null_inode = 1;
	susfs_add_sus_map(&map_ptr);
	expect(susfs_test_path_puts == 1 && susfs_test_set_bits == 0, "null inode path_put");
	expect(map.err == -2, "null inode error");

	susfs_test_reset();
	map = map_of("/data/target");
	map_ptr = &map;
	susfs_add_sus_map(&map_ptr);
	susfs_add_sus_map(&map_ptr);
	expect(susfs_test_kern_calls == 2 && susfs_test_path_puts == 2, "duplicate path_put");
	expect(susfs_test_set_bits == 2 && susfs_test_last_bit == 39, "duplicate set_bit");
	expect(map.err == 0, "duplicate success");

	susfs_test_reset();
	map = map_of("/data/target");
	map.err = 77;
	map_ptr = &map;
	susfs_test_copy_to_fail = 1;
	susfs_add_sus_map(&map_ptr);
	expect(susfs_test_set_bits == 1 && susfs_test_path_puts == 1, "map changed before reply failure");
	expect(map.err == 77, "map reply failure keeps old err");
	expect(strstr(susfs_test_messages, "add_sus_map state already changed") != NULL,
	       "map reply diagnostic");

	susfs_test_reset();
	avc.enabled = 0;
	avc.err = 0;
	avc_ptr = &avc;
	susfs_set_avc_log_spoofing(&avc_ptr);
	susfs_test_reset();
	avc.enabled = 1;
	avc.err = 77;
	avc_ptr = &avc;
	susfs_test_copy_from_fail = 2;
	susfs_set_avc_log_spoofing(&avc_ptr);
	expect(susfs_host_avc_enabled() == 0, "short avc copy leaves state");
	expect(avc.err == -14, "short avc copy error");

	susfs_test_reset();
	avc.enabled = 1;
	avc.err = 77;
	avc_ptr = &avc;
	susfs_set_avc_log_spoofing(&avc_ptr);
	expect(susfs_host_avc_enabled() == 1 && avc.err == 0, "avc enabled");

	susfs_test_reset();
	avc.enabled = 0;
	avc.err = 77;
	avc_ptr = &avc;
	susfs_test_copy_to_fail = 1;
	susfs_set_avc_log_spoofing(&avc_ptr);
	expect(susfs_host_avc_enabled() == 0, "avc state changed before reply failure");
	expect(avc.err == 77, "avc reply failure keeps old err");
	expect(strstr(susfs_test_messages, "avc_log_spoofing state already changed") != NULL,
	       "avc reply diagnostic");

	susfs_test_reset();
	susfs_show_version(NULL);
	susfs_show_variant(NULL);
	susfs_set_hide_sus_mnts_for_non_su_procs(NULL);
	susfs_get_enabled_features(NULL);
	expect(strstr(susfs_test_messages, "show-version missing") != NULL, "version null");
	expect(strstr(susfs_test_messages, "show-variant missing") != NULL, "variant null");
	expect(strstr(susfs_test_messages, "hide-mnts missing") != NULL, "hide null");
	expect(strstr(susfs_test_messages, "enabled-features missing") != NULL, "features null");

	{
		struct st_susfs_version version = {{0}, 0};
		struct st_susfs_variant variant = {{0}, 0};
		struct st_susfs_hide_sus_mnts_for_non_su_procs hide = {0, 0};
		void *version_ptr = &version;
		void *variant_ptr = &variant;
		void *hide_ptr = &hide;

		susfs_test_reset();
		susfs_test_copy_from_fail = 1;
		susfs_show_version(&version_ptr);
		susfs_show_variant(&variant_ptr);
		susfs_set_hide_sus_mnts_for_non_su_procs(&hide_ptr);
		expect(version.err == -14 && variant.err == -14 && hide.err == -14,
		       "short copy stores EFAULT");

		susfs_test_reset();
		version.err = 77;
		variant.err = 77;
		hide.err = 77;
		susfs_test_copy_to_fail = 1;
		susfs_show_version(&version_ptr);
		expect(version.err == 77, "version output failure keeps err");
		susfs_test_messages[0] = '\0';
		susfs_show_variant(&variant_ptr);
		expect(variant.err == 77, "variant output failure keeps err");
		susfs_set_hide_sus_mnts_for_non_su_procs(&hide_ptr);
		expect(hide.err == 77, "hide output failure keeps err");
		expect(strstr(susfs_test_messages, "copy_to_user failed") != NULL,
		       "output failure is logged");
	}

	{
		struct st_susfs_enabled_features *features =
			calloc(1, sizeof(*features));
		void *features_ptr = features;

		expect(features != NULL, "features fixture");
		susfs_test_reset();
		features->err = 0;
		susfs_test_alloc_fail = 1;
		susfs_get_enabled_features(&features_ptr);
		expect(features->err == -12, "allocation failure stores ENOMEM");

		susfs_test_reset();
		features->err = 0;
		susfs_test_copy_from_fail = 1;
		susfs_get_enabled_features(&features_ptr);
		expect(features->err == -14, "features short copy stores EFAULT");

		susfs_test_reset();
		features->err = 77;
		susfs_test_copy_to_fail = 1;
		susfs_get_enabled_features(&features_ptr);
		expect(features->err == 77, "features output failure keeps err");
		free(features);
	}

	susfs_test_reset();
	susfs_start_sdcard_monitor_fn();
	susfs_extra_works_fn(&work);
	expect(strstr(susfs_test_messages, "no error is returned to a caller") != NULL, "sdcard diagnostic");
	expect(strstr(susfs_test_messages, "returns nothing to a caller") != NULL, "extra work diagnostic");
	expect(strstr(susfs_test_messages, "returns 126") == NULL, "void diagnostics do not claim err 126");

	if (failures) {
		fprintf(stderr, "%d entry failures\n", failures);
		return 1;
	}
	puts("susfs compat entries: PASS");
	return 0;
}
'''


def compile_real_entries():
    compiler = os.environ.get("CC") or shutil.which("clang") or shutil.which("cc") or shutil.which("gcc")
    if not compiler:
        raise SystemExit("a host C compiler is required")
    work = make_work("entry-")
    try:
        source = work / "entry.c"
        source.write_text(ENTRY, encoding="utf-8", newline="\n")
        executable = work / ("entry.exe" if os.name == "nt" else "entry")
        command = [
            compiler, "-std=gnu11", "-Wall", "-Werror", "-DSUSFS_COMPAT_HOST_TEST",
            "-I", str(HERE / "host_stub"),
            "-I", str(HERE),
            str(COMPAT),
            str(HERE / "host_stub" / "host_kernel_stub.c"),
            str(source),
            "-o", str(executable),
        ]
        build = subprocess.run(command, capture_output=True, text=True)
        if build.returncode:
            raise SystemExit(build.stdout + build.stderr)
        subprocess.run([str(executable)], check=True, timeout=15)
        kernel_logic = work / "kernel_logic.c"
        kernel_logic.write_text(
            "#include \"susfs_419_logic.h\"\n"
            "int main(void){return susfs_sdcard_monitor_result()==126?0:1;}\n",
            encoding="utf-8", newline="\n")
        kernel_exe = work / ("kernel_logic.exe" if os.name == "nt" else "kernel_logic")
        kernel_build = subprocess.run(
            [compiler, "-std=gnu11", "-Wall", "-Werror", "-D__KERNEL__",
             "-I", str(HERE / "host_stub"), "-I", str(HERE),
             str(kernel_logic), "-o", str(kernel_exe)],
            capture_output=True, text=True)
        if kernel_build.returncode:
            raise SystemExit(kernel_build.stdout + kernel_build.stderr)
        subprocess.run([str(kernel_exe)], check=True, timeout=15)
        print("susfs kernel header branch: PASS")
    finally:
        shutil.rmtree(work)


if __name__ == "__main__":
    compile_and_run()
    compile_real_entries()
    config_roundtrip()
    source_contract()
