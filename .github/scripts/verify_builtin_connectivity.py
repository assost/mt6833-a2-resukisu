#!/usr/bin/env python3
"""Verify integration evidence and final built-in driver linkage, not radio operation."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import zipfile

from integrate_builtin_connectivity import COMMIT, MODULES, PARENT, PREFIX, sha, write
from verify_builtin_dispatch import verify_dispatch

ENTRIES = (
    "mtk_wcn_common_drv_init", "mtk_wcn_stpbt_drv_init", "mtk_wcn_stpgps_builtin_init",
    "mtk_wcn_fm_init", "mtk_wcn_wmt_wifi_init", "mtk_wcn_wlan_gen4_init",
)
CONNFEM_ENTRY = "connfem_epaelna_get_fem_info"
RUNTIME_NAMES = ENTRIES + (CONNFEM_ENTRY,) + (
    "do_connectivity_driver_init", "do_common_drv_init", "do_bluetooth_drv_init",
    "do_gps_drv_init", "do_fm_drv_init", "do_wlan_drv_init", "WMT_init", "BT_init",
    "GPS_init", "gps_mod_init", "mt_fm_init", "WIFI_init", "initWlan",
    "mtk_gps_emi_init", "gps_emi_mod_init", "mtk_gps_fw_log_init", "gps_fw_log_init",
)


def verify_source(root):
    tree = root / PARENT / "builtin"
    manifest = json.loads((tree / "integration-manifest.json").read_text())
    if manifest["source_commit"] != COMMIT or manifest["drivers"] != [m[1] for m in MODULES]:
        raise ValueError("wrong source manifest identity")
    changed = [name for name, digest in manifest["files"].items() if sha(tree / name) != digest]
    if changed:
        raise ValueError("staged driver sources changed: " + ", ".join(changed))
    parent = root / PARENT / "Makefile"
    if sha(parent) != manifest["parent_makefile_after_sha256"]:
        raise ValueError("parent Makefile changed after integration")
    gps = (tree / PREFIX / "gps/gps_stp/stp_chrdev_gps.c").read_text()
    if "static int __init gps_mod_init" in gps or "int mtk_wcn_stpgps_builtin_init(void)" not in gps:
        raise ValueError("GPS late-entry lifetime or full-init wrapper missing")
    bluetooth = (tree / PREFIX / "common/common_detect/drv_init/bluetooth_drv_init.c").read_text()
    if ('#ifdef MTK_WCN_BUILT_IN_DRIVER' not in bluetooth
            or 'extern int mtk_wcn_stpbt_drv_init(void);' not in bluetooth
            or '#if defined(CONFIG_MTK_COMBO_BT) || defined(MTK_WCN_BUILT_IN_DRIVER)' not in bluetooth):
        raise ValueError("BT built-in dispatcher selection/strong dependency missing")
    return manifest


def verify(root, out, nm, mode):
    manifest = verify_source(root)
    config = (out / ".config").read_text().splitlines()
    required = ('CONFIG_MTK_COMBO=y', 'CONFIG_MTK_COMBO_CHIP_CONSYS_6833=y',
                'CONFIG_MTK_PLATFORM="mt6853"', 'CONFIG_MTK_GPS_SUPPORT=y',
                'CONFIG_MTK_COMBO_GPS=y', 'CONFIG_MTK_FMRADIO=y',
                'CONFIG_MODVERSIONS=y', 'CONFIG_MODULE_SIG_FORCE=y',
                'CONFIG_LTO_CLANG=y', 'CONFIG_CFI_CLANG=y')
    missing = [line for line in required if line not in config]
    if missing:
        raise ValueError("required configuration missing: " + ", ".join(missing))
    if "CONFIG_WLAN_DRV_BUILD_IN=y" in config:
        raise ValueError("global legacy built-in template must stay disabled")
    if ("CONFIG_KSU=y" in config) != (mode == "resukisu"):
        raise ValueError("report variant does not match CONFIG_KSU")
    builtins = (out / "modules.builtin").read_text().splitlines()
    missing = [name for _, name, _, _ in MODULES if not any(p.endswith("/" + name + ".ko") for p in builtins)]
    if missing:
        raise ValueError("modules.builtin missing: " + ", ".join(missing))
    evidence = out / "builtin-connectivity"
    evidence.mkdir(exist_ok=True)
    symbol_file = evidence / "vmlinux.nm.txt"
    elf = out / "vmlinux.symbols"
    if not elf.is_file():
        raise ValueError("out/vmlinux.symbols is required; preserve a --strip-debug copy of final vmlinux")
    command = [nm, "-n", "--defined-only", str(elf)]
    with symbol_file.open("w") as stream:
        subprocess.run(command, stdout=stream, check=True)
    symbols = {}
    with symbol_file.open() as stream:
        for line in stream:
            parts = line.split()
            if len(parts) == 3 and re.fullmatch("[0-9a-fA-F]+", parts[0]):
                symbols[parts[2]] = {"address": int(parts[0], 16), "type": parts[1]}
    for name in ENTRIES + (CONNFEM_ENTRY,):
        item = symbols.get(name)
        if not item or item["type"] not in ("T", "t"):
            raise ValueError("required real (non-weak) driver entry missing: " + name)
        if not any(key.startswith("__ksymtab_" + name) for key in symbols):
            raise ValueError("required driver export missing: " + name)
    if "__init_begin" not in symbols or "__init_end" not in symbols:
        raise ValueError("cannot establish freed initialization-memory bounds")
    lower, upper = symbols["__init_begin"]["address"], symbols["__init_end"]["address"]
    lifetime = {}
    for name in RUNTIME_NAMES:
        matches = {key: value for key, value in symbols.items() if key == name or key.startswith(name + ".")}
        for key, value in matches.items():
            if lower <= value["address"] < upper:
                raise ValueError("late driver path is inside freed init memory: " + key)
        lifetime[name] = matches or "inlined/internalized; section-mismatch build audit also required"
    for name in ("wmt_detect_driver_init", "connfem_mod_init"):
        if not any(key.startswith("__initcall_") and name in key for key in symbols):
            raise ValueError("bootstrap initcall missing: " + name)
    if any(key.startswith("__initcall_") and "gps_mod_init" in key for key in symbols):
        raise ValueError("GPS still initializes before the loader")
    dispatch = verify_dispatch(elf.read_bytes())
    if not dispatch["passed"]:
        raise ValueError("Built-in runtime dispatcher gate failed: " + "; ".join(dispatch["errors"]))
    build_log = (out / "build.log").read_text(errors="replace")
    errors = [line for line in build_log.splitlines() if re.search(
        r"section mismatch|WARNING:.*(?:undefined!|has no CRC!|version generation failed)|duplicate symbol|multiple definition", line, re.I)]
    if errors:
        raise ValueError("kernel build linkage/lifetime diagnostics: " + "; ".join(errors[:20]))
    image = out / "arch/arm64/boot/Image.gz"
    if image.stat().st_size == 0:
        raise ValueError("empty kernel Image")
    source_manifest = out / "builtin-connectivity-source-manifest.json"
    write(source_manifest, (root / PARENT / "builtin/integration-manifest.json").read_text())
    commands = out / "builtin-connectivity-commands.json"
    write(commands, json.dumps({"schema_version": 1, "mode": mode,
                                "verification_commands": [command],
                                "integration": manifest["integration_command"]}, indent=2) + "\n")
    kernel_commit = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    source_evidence = out / "builtin-connectivity-source-evidence.zip"
    temp_zip = source_evidence.with_suffix(".tmp")
    tree = root / PARENT / "builtin"
    with zipfile.ZipFile(temp_zip, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name in sorted(manifest["files"]):
            archive.write(tree / name, name)
        archive.write(tree / "integration-manifest.json", "integration-manifest.json")
        archive.write(root / PARENT / "Makefile", "_integration/parent-Makefile")
    temp_zip.replace(source_evidence)
    tracked = {"Image.gz": image, "config": out / ".config", "System.map": out / "System.map",
               "Module.symvers": out / "Module.symvers", "vmlinux.symbols": elf,
               "source_manifest": source_manifest, "commands": commands,
               "source_evidence": source_evidence, "modules.builtin": out / "modules.builtin"}
    driver_entries = {"connfem": [CONNFEM_ENTRY], "wmt_drv": [ENTRIES[0]], "bt_drv_connac1x": [ENTRIES[1]],
                      "gps_drv": [ENTRIES[2]], "fmradio_drv_mt6631_6635": [ENTRIES[3]],
                      "wmt_chrdev_wifi": [ENTRIES[4]], "wlan_drv_gen4m": [ENTRIES[5]]}
    report = {"schema_version": 1, "passed": True, "runtime_tested": False, "source_commit": COMMIT,
              "mode": mode, "kernel_commit": kernel_commit, "integration_mode": manifest["mode"],
              "drivers": [{"name": name, "source": (PREFIX / relative).as_posix(),
                           "strong_symbols": driver_entries[name]} for relative, name, _, _ in MODULES],
              "files": {name: {"path": path.relative_to(out).as_posix(), "sha256": sha(path)}
                        for name, path in tracked.items()},
              "strong_entries": {key: symbols[key] for key in ENTRIES + (CONNFEM_ENTRY,)}, "lifetime": lifetime,
              "runtime_dispatch": dispatch,
              "initialization": "connfem/wmtdetect bootstrap; wmt_loader ioctl common, BT, GPS, FM, WLAN",
              "limitations": ["Device-node permissions, firmware initialization and Wi-Fi/BT hardware require a fresh boot test.",
                              "Remaining legacy vendor insmod errors do not establish driver initialization success."]}
    write(out / "builtin-connectivity-report.json", json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--out", type=Path)
    parser.add_argument("--nm", default="aarch64-linux-gnu-nm")
    parser.add_argument("--mode", choices=("stock", "resukisu"), required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    verify(root, (args.out or root / "out").resolve(), args.nm, args.mode)


if __name__ == "__main__":
    main()
