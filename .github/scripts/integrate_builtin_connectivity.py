#!/usr/bin/env python3
"""Stage the pinned MT6833 connectivity drivers for an in-tree kernel build.

Run after prepare.sh and before the kernel Image build. Only the staged driver
copies and the parent connectivity Makefile are changed; no vendor partition or
module ABI/security policy is changed.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

COMMIT = "dd93a63de24dec560639b88d8328d4be7100a60d"
PARENT = Path("drivers/misc/mediatek/connectivity")
PREFIX = Path("vendor/mediatek/kernel_modules/connectivity")
MODULES = (
    ("connfem", "connfem", "Kbuild", {}),
    ("common", "wmt_drv", "Kbuild", {}),
    ("bt/mt66xx/wmt", "bt_drv_connac1x", "Makefile",
     {"BT_PLATFORM": "connac1x", "BT_ENABLE_LOW_POWER_DEBUG": "y"}),
    ("gps", "gps_drv", "Makefile", {}),
    ("fmradio", "fmradio_drv_mt6631_6635", "Kbuild",
     {"CFG_FM_PLAT": "mt6631_6635", "CFG_FM_CHIP": "", "CFG_FM_CHIP_ID": "",
      "CFG_BUILD_CONNAC2": "false", "CONFIG_FM_USER_LOAD": "1"}),
    ("wlan/adaptor", "wmt_chrdev_wifi", "Makefile", {}),
    ("wlan/core/gen4m", "wlan_drv_gen4m", "Makefile",
     {"MTK_COMBO_CHIP": "SOC2_1X1", "WLAN_CHIP_ID": "6833",
      "CONFIG_MTK_COMBO_WIFI_HIF": "axi", "MTK_ANDROID_WMT": "y",
      "MTK_ANDROID_EMI": "y", "WIFI_IP_SET": "1", "MTK_WLAN_SERVICE": "yes"}),
)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(content, encoding="utf-8", newline="\n")
    os.replace(temp, path)


def replace_once(text, old, new, label):
    if text.count(old) != 1:
        raise ValueError(f"{label}: expected one exact source anchor, got {text.count(old)}")
    return text.replace(old, new, 1)


def transform_entry(relative, text):
    if relative in ("connfem", "bt/mt66xx/wmt", "gps"):
        text = replace_once(text, "obj-m += $(MODULE_NAME).o", "obj-y += $(MODULE_NAME).o", relative)
    if relative == "wlan/core/gen4m":
        old = """ifneq ($(filter MTK_WCN_REMOVE_KERNEL_MODULE,$(KBUILD_SUBDIR_CCFLAGS)),)
    ccflags-y += -DCFG_BUILT_IN_DRIVER=1
else
    ccflags-y += -DCFG_BUILT_IN_DRIVER=0
endif"""
        text = replace_once(text, old, "ccflags-y += -DCFG_BUILT_IN_DRIVER=1", relative + ":runtime-entry")
        start = text.index("ifeq ($(CONFIG_MTK_WIFI_ONLY),$(filter $(CONFIG_MTK_WIFI_ONLY),m y))")
        end = text.index("ifeq ($(CONFIG_MTK_WIFI_PKT_OFLD_SUPPORT), y)", start)
        expected = text[start:end]
        if "obj-m += $(MODULE_NAME).o" not in expected or "-DCONFIG_WLAN_DRV_BUILD_IN=0" not in expected:
            raise ValueError("gen4m: unexpected object-selection block")
        text = text[:start] + "obj-y += $(MODULE_NAME).o\nccflags-y += -DCONFIG_WLAN_DRV_BUILD_IN=1\n\n" + text[end:]
    return text


def transform_bluetooth_dispatch(text):
    old = """#ifdef CONFIG_MTK_COMBO_BT
int __attribute__((weak)) mtk_wcn_stpbt_drv_init()
{
\tWMT_DETECT_PR_INFO("Not implement mtk_wcn_stpbt_drv_init\\n");
\treturn 0;
}
#endif"""
    new = """#ifdef MTK_WCN_BUILT_IN_DRIVER
/* All seven in-tree drivers are selected independently of the factory BT tristate. */
extern int mtk_wcn_stpbt_drv_init(void);
#elif defined(CONFIG_MTK_COMBO_BT)
int __attribute__((weak)) mtk_wcn_stpbt_drv_init()
{
\tWMT_DETECT_PR_INFO("Not implement mtk_wcn_stpbt_drv_init\\n");
\treturn 0;
}
#endif"""
    text = replace_once(text, old, new, "BT scoped strong dependency")
    return replace_once(text, '#ifdef CONFIG_MTK_COMBO_BT\n\tWMT_DETECT_PR_INFO("start to do bluetooth driver init\\n");',
                        '#if defined(CONFIG_MTK_COMBO_BT) || defined(MTK_WCN_BUILT_IN_DRIVER)\n\tWMT_DETECT_PR_INFO("start to do bluetooth driver init\\n");',
                        "BT scoped dispatcher selection")


def patch_runtime(conn):
    path = conn / "common/common_main/linux/stp_uart.c"
    text = path.read_text(encoding="utf-8")
    # This UART-local legacy lock collides with exFAT's global buf_lock()
    # when both previously separate objects enter the same kernel link.
    # Its uses are currently disabled, so retain it without an unused warning.
    write(path, replace_once(text, "\nspinlock_t buf_lock;\n",
                            "\nstatic __maybe_unused spinlock_t buf_lock;\n",
                            "UART private buffer lock"))

    path = conn / "common/common_detect/drv_init/bluetooth_drv_init.c"
    write(path, transform_bluetooth_dispatch(path.read_text(encoding="utf-8")))

    path = conn / "gps/gps_stp/gps_emi.c"
    text = path.read_text(encoding="utf-8")
    old = """#if defined(GPS_EMI_NEW_API)
\tstruct emimpu_region_t region_info;
\tmemset((void *)&region_info, 0x0, sizeof(region_info));

\tint emimpu_ret1, emimpu_ret2, emimpu_ret3, emimpu_ret4, emimpu_ret5, emimpu_ret6;"""
    new = """#if defined(GPS_EMI_NEW_API)
\tstruct emimpu_region_t region_info;
\tint emimpu_ret1, emimpu_ret2, emimpu_ret3, emimpu_ret4, emimpu_ret5, emimpu_ret6;

\tmemset((void *)&region_info, 0x0, sizeof(region_info));"""
    write(path, replace_once(text, old, new, "gps EMI C90 declaration order"))

    path = conn / "gps/gps_stp/stp_chrdev_gps.c"
    text = path.read_text(encoding="utf-8")
    text = replace_once(text, "static int __init gps_mod_init(void)", "static int gps_mod_init(void)", "gps lifetime")
    old = """\tmtk_wcn_stpgps_drv_init();
\t#ifdef CONFIG_MTK_GPS_EMI
\tmtk_gps_emi_init();
\t#endif
\t#ifdef CONFIG_MTK_CONNSYS_DEDICATED_LOG_PATH
\tmtk_gps_fw_log_init();
\t#endif
\treturn ret;"""
    new = """\tret = mtk_wcn_stpgps_drv_init();
\tif (ret)
\t\treturn ret;
#ifdef CONFIG_MTK_GPS_EMI
\tret = mtk_gps_emi_init();
\tif (ret) {
\t\tmtk_wcn_stpgps_drv_exit();
\t\treturn ret;
\t}
#endif
#ifdef CONFIG_MTK_CONNSYS_DEDICATED_LOG_PATH
\tret = mtk_gps_fw_log_init();
\tif (ret) {
#ifdef CONFIG_MTK_GPS_EMI
\t\tmtk_gps_emi_exit();
#endif
\t\tmtk_wcn_stpgps_drv_exit();
\t\treturn ret;
\t}
#endif
\treturn 0;"""
    text = replace_once(text, old, new, "gps complete deferred init")
    old = "module_init(gps_mod_init);\nmodule_exit(gps_mod_exit);"
    new = """#ifdef MTK_WCN_REMOVE_KERNEL_MODULE
/* The loader calls this after kernel init memory has already been freed. */
int mtk_wcn_stpgps_builtin_init(void)
{
\treturn gps_mod_init();
}
EXPORT_SYMBOL(mtk_wcn_stpgps_builtin_init);
#else
module_init(gps_mod_init);
module_exit(gps_mod_exit);
#endif"""
    write(path, replace_once(text, old, new, "gps remove early initcall"))

    path = conn / "common/common_detect/drv_init/gps_drv_init.c"
    text = path.read_text(encoding="utf-8")
    old = """int __attribute__((weak)) mtk_wcn_stpgps_drv_init()
{
\tWMT_DETECT_PR_INFO("no impl. mtk_wcn_stpgps_drv_init\\n");
\treturn 0;
}"""
    text = replace_once(text, old, "extern int mtk_wcn_stpgps_builtin_init(void);", "gps strong dependency")
    write(path, replace_once(text, "i_ret = mtk_wcn_stpgps_drv_init();", "i_ret = mtk_wcn_stpgps_builtin_init();", "gps full entry"))

    path = conn / "common/common_detect/drv_init/fm_drv_init.c"
    text = path.read_text(encoding="utf-8")
    text = replace_once(text, "int do_fm_drv_init(int chip_id)\n{", "int do_fm_drv_init(int chip_id)\n{\n\tint ret = 0;", "fm error storage")
    text = replace_once(text, "\tmtk_wcn_fm_init();", "\tret = mtk_wcn_fm_init();", "fm error capture")
    text = replace_once(text, '\tWMT_DETECT_PR_INFO("finish fm module init\\n");\n\treturn 0;', '\tWMT_DETECT_PR_INFO("finish fm module init, ret:%d\\n", ret);\n\treturn ret;', "fm error return")
    write(path, text)

    path = conn / "common/common_detect/drv_init/conn_drv_init.c"
    text = path.read_text(encoding="utf-8")
    start = text.index("#if (MTK_WCN_REMOVE_KO)")
    steps = ("common", "bluetooth", "gps", "fm", "wlan")
    body = """#if (MTK_WCN_REMOVE_KO)
#include <linux/mutex.h>
static DEFINE_MUTEX(conn_builtin_init_lock);
static bool conn_builtin_attempted;
static int conn_builtin_result;

int do_connectivity_driver_init(int chip_id)
{
\tint ret;

\tmutex_lock(&conn_builtin_init_lock);
\tif (conn_builtin_attempted) {
\t\tret = conn_builtin_result;
\t\tgoto out;
\t}
\t/* A partial hardware initialization must not be retried as a fresh one. */
\tconn_builtin_attempted = true;
"""
    for step in steps:
        body += f'\tret = do_{step}_drv_init(chip_id);\n\tif (ret) {{\n\t\tWMT_DETECT_PR_ERR("built-in {step} init failed: %d\\n", ret);\n\t\tgoto save;\n\t}}\n'
    body += """\tWMT_DETECT_PR_INFO("MT6833 built-in connectivity initialization complete\\n");
save:
\tconn_builtin_result = ret;
out:
\tmutex_unlock(&conn_builtin_init_lock);
\treturn ret;
}
#endif
"""
    if "static int init_before;" not in text[start:]:
        raise ValueError("connectivity initialization source changed")
    write(path, text[:start] + body)


def stage_driver_tree(root, source, staging):
    conn = staging / PREFIX
    for relative in ("connfem", "common", "bt/mt66xx", "gps", "fmradio", "wlan/adaptor", "wlan/core/gen4m"):
        shutil.copytree(source / PREFIX / relative, conn / relative, symlinks=True)
    write(staging / "Kbuild", "# MT6833 pinned built-in connectivity; runtime order is controlled by wmt_loader.\n"
          "subdir-ccflags-y += -DMTK_WCN_REMOVE_KERNEL_MODULE -DMTK_WCN_BUILT_IN_DRIVER\n" +
          "".join(f"obj-y += {PREFIX.as_posix()}/{relative}/\n" for relative, *_ in MODULES))
    for relative, name, entry, options in MODULES:
        directory = conn / relative
        path = directory / entry
        original = path.read_text(encoding="utf-8")
        transformed = transform_entry(relative, original)
        write(directory / "Kbuild.upstream", transformed)
        common = {"TOP": f"$(srctree)/{PARENT.as_posix()}/builtin", "KERNEL_OUT": "$(abspath $(objtree))",
                  "TARGET_BUILD_VARIANT": "user", "MTK_PLATFORM": "mt6853", "MTK_PLATFORM_WMT": "mt6853",
                  "TARGET_BOARD_PLATFORM_WMT": "mt6833", "CONFIG_WLAN_DRV_BUILD_IN": "y", "MODULE_NAME": name}
        common.update(options)
        wrapper = "# Values are local to this recursive Kbuild invocation.\n"
        wrapper += "".join(f"override {key} := {value}\n" for key, value in common.items())
        wrapper += ("# Makefile.modbuiltin uppercases tristate config values.\n"
                    "ifeq ($(CONFIG_MTK_COMBO),Y)\nobj-Y += $(MODULE_NAME).o\nelse\n"
                    "include $(srctree)/$(src)/Kbuild.upstream\nendif\n")
        write(directory / "Kbuild", wrapper)
    patch_runtime(conn)
    files = {p.relative_to(staging).as_posix(): sha(p) for p in staging.rglob("*") if p.is_file()}
    return {"source_commit": COMMIT, "kernel_root": str(root), "mode": "builtin-loader-deferred",
            "drivers": [name for _, name, _, _ in MODULES], "files": files}


def integrate(root, source):
    actual = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if actual != COMMIT:
        raise ValueError(f"source commit mismatch: {actual}")
    dirty = subprocess.check_output(["git", "-C", str(source), "status", "--porcelain", "--untracked-files=all", "--", PREFIX.as_posix()], text=True).strip()
    if dirty:
        raise ValueError("pinned connectivity source has local modifications")
    parent = root / PARENT / "Makefile"
    original = parent.read_text(encoding="utf-8")
    destination = root / PARENT / "builtin"
    if destination.exists() or "obj-y += builtin/" in original:
        raise ValueError("built-in integration already exists; use the preserved build or a fresh checkout")
    deps = root / ".build-deps"
    deps.mkdir(exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="builtin-connectivity-stage-", dir=deps))
    manifest = stage_driver_tree(root, source, staging)
    manifest["integration_command"] = ["python3", "integrate_builtin_connectivity.py", "--root", str(root), "--source", str(source)]
    # The old template is inactive: enabling it would select CONNAC/6765 and a
    # three-directory symlink layout instead of this complete MT6833 tree.
    if re.search(r"^\s*export\s+CONFIG_WLAN_DRV_BUILD_IN\s*[:?+]?=\s*y", original, re.M):
        raise ValueError("legacy global built-in template is already enabled")
    backup = deps / (staging.name + ".parent-Makefile.backup")
    shutil.copy2(parent, backup)
    manifest["parent_makefile_before_sha256"] = sha(parent)
    manifest["parent_makefile_backup"] = str(backup)
    new = original + "\n# Pinned MT6833 drivers; do not activate the legacy 6765 template.\nobj-y += builtin/\n"
    manifest["parent_makefile_after_sha256"] = hashlib.sha256(new.encode()).hexdigest()
    write(staging / "integration-manifest.json", json.dumps(manifest, indent=2) + "\n")
    os.replace(staging, destination)
    write(parent, new)
    print(json.dumps({"integrated": str(destination), "manifest": str(destination / "integration-manifest.json"),
                      "parent_backup": str(backup), "build_executed": False}, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--source", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    source = args.source or Path((root / ".build-deps/connectivity-source.txt").read_text().strip())
    integrate(root, source.resolve())


if __name__ == "__main__":
    main()
