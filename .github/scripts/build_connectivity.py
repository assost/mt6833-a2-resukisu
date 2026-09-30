#!/usr/bin/env python3
"""Build the factory connectivity module set against this job's completed kernel."""
import argparse
from pathlib import Path
import re
import shutil
import subprocess
import tempfile

from verify_connectivity import verify, write_json


COMMIT = "dd93a63de24dec560639b88d8328d4be7100a60d"
MODULES = (
    ("connfem", "connfem", []),
    ("common", "wmt_drv", []),
    ("bt/mt66xx/wmt", "bt_drv_connac1x", ["common"]),
    ("gps", "gps_drv", ["common"]),
    ("fmradio", "fmradio_drv_mt6631_6635", ["common"]),
    ("wlan/adaptor", "wmt_chrdev_wifi", ["common"]),
    ("wlan/core/gen4m", "wlan_drv_gen4m", ["connfem", "common", "wlan/adaptor"]),
)



def check_modpost_log(path):
    # This 4.19 Kbuild adds -w for external modules, so these warnings are fatal here.
    errors = [line for line in path.read_text(errors="replace").splitlines()
              if re.search(r"WARNING:.*(?:undefined!|has no CRC!|version generation failed)", line)]
    if errors:
        raise ValueError("module symbol validation failed in " + str(path) + ": " + "; ".join(errors))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=("stock", "resukisu"))
    args = parser.parse_args()
    root = Path.cwd().resolve()
    out = root / "out"
    source = Path((root / ".build-deps/connectivity-source.txt").read_text().strip()).resolve()
    source.relative_to(root / ".build-deps")
    actual = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if actual != COMMIT:
        raise ValueError(f"connectivity source commit changed: {actual}")
    config = (out / ".config").read_text()
    required = ('CONFIG_MODVERSIONS=y', 'CONFIG_MODULE_SIG_FORCE=y', 'CONFIG_CFI_CLANG=y',
                'CONFIG_LTO_CLANG=y', 'CONFIG_MTK_COMBO_CHIP_CONSYS_6833=y',
                'CONFIG_MTK_PLATFORM="mt6853"', 'CONFIG_MODULE_SIG_KEY="certs/signing_key.pem"')
    if any(line not in config.splitlines() for line in required):
        raise ValueError("kernel configuration does not match the validated MT6833 module target")
    for name in ("Module.symvers", "vmlinux", "include/generated/autoconf.h", "include/config/kernel.release", "scripts/sign-file",
                 "certs/signing_key.pem", "certs/signing_key.x509", "arch/arm64/boot/Image.gz"):
        if not (out / name).is_file() or (out / name).stat().st_size == 0:
            raise ValueError(f"complete matching kernel build required: out/{name}")
    # The Android makefiles use TOP to locate sibling connectivity headers.
    # A separate copy keeps the downloaded pinned source free of build products.
    stage = Path(tempfile.mkdtemp(prefix=f"connectivity-{args.mode}-", dir=root / ".build-deps"))
    prefix = Path("vendor/mediatek/kernel_modules/connectivity")
    conn = stage / prefix
    for relative in ("connfem", "common", "bt/mt66xx", "gps", "fmradio", "wlan/adaptor", "wlan/core/gen4m"):
        shutil.copytree(source / prefix / relative, conn / relative, symlinks=True)
    destination = out / "connectivity"
    destination.mkdir(exist_ok=True)
    if any(destination.glob("*.ko")):
        raise ValueError("out/connectivity already has modules; preserve it and use a fresh build output")
    common = ["make", f"O={out}", "-j2", f"TOP={stage}", f"KERNEL_OUT={out}",
              "TARGET_BUILD_VARIANT=user", "MTK_PLATFORM=mt6853", "MTK_PLATFORM_WMT=mt6853",
              "TARGET_BOARD_PLATFORM_WMT=mt6833"]
    commands = []
    shutil.copy2(out / "include/config/kernel.release", destination / "kernel.release")
    for relative, name, dependencies in MODULES:
        directory = conn / relative
        symbols = [str(conn / dep / "Module.symvers") for dep in dependencies]
        command = common + [f"M={directory}", "modules", f"MODULE_NAME={name}",
                            "KBUILD_EXTRA_SYMBOLS=" + " ".join(symbols)]
        if name == "bt_drv_connac1x":
            command += ["BT_PLATFORM=connac1x", "BT_ENABLE_LOW_POWER_DEBUG=y"]
        elif name == "fmradio_drv_mt6631_6635":
            command += ["CFG_FM_PLAT=mt6631_6635", "CFG_FM_CHIP=", "CFG_FM_CHIP_ID=",
                        "CFG_BUILD_CONNAC2=false", "CONFIG_FM_USER_LOAD=1"]
        elif name == "wlan_drv_gen4m":
            command += ["MTK_COMBO_CHIP=SOC2_1X1", "WLAN_CHIP_ID=6833",
                        "CONFIG_MTK_COMBO_WIFI_HIF=axi", "MTK_ANDROID_WMT=y",
                        "MTK_ANDROID_EMI=y", "WIFI_IP_SET=1", "MTK_WLAN_SERVICE=yes"]
        commands.append(command)
        write_json(destination / "build-commands.json", {"mode": args.mode, "source_commit": COMMIT, "commands": commands})
        log_path = destination / (name + ".build.log")
        with log_path.open("w") as log:
            subprocess.run(command, cwd=root, stdout=log, stderr=subprocess.STDOUT, check=True)
        check_modpost_log(log_path)
        module = directory / (name + ".ko")
        if not module.is_file():
            raise ValueError(f"module build produced no {module}")
        shutil.copy2(directory / "Module.symvers", destination / (name + ".symvers"))
        final = destination / module.name
        shutil.copy2(module, final)
        subprocess.run([str(out / "scripts/sign-file"), "sha512",
                        str(out / "certs/signing_key.pem"), str(out / "certs/signing_key.x509"),
                        str(final)], check=True)
    subprocess.run(["openssl", "x509", "-inform", "DER", "-in", str(out / "certs/signing_key.x509"),
                    "-out", str(destination / "build-signing-cert.pem")], check=True)
    shutil.copy2(out / "Module.symvers", destination / "kernel.symvers")
    report = verify(destination, out / "arch/arm64/boot/Image.gz", out / ".config",
                    destination / "build-signing-cert.pem", root / ".github/certs/factory-modules.pem",
                    args.mode)
    report.update(source_commit=COMMIT, kernel_commit=subprocess.check_output(
        ["git", "rev-parse", "HEAD"], text=True).strip(), commands=commands)
    write_json(destination / "verification.json", report)
    if not report["passed"]:
        raise ValueError("connectivity validation failed; see out/connectivity/verification.json")
    deps = {item["name"]: next((info.split("=", 1)[1].split(",")
              for info in item["modinfo"] if info.startswith("depends=") and info != "depends="), [])
            for item in report["modules"]}
    (destination / "modules.dep").write_text("".join(
        name + ".ko:" + "".join(" " + dep + ".ko" for dep in required) + "\n"
        for name, required in deps.items()))
    (destination / "modules.load").write_text("".join(name + ".ko\n" for name in deps))
    print("Verified matching, signed connectivity modules:", destination)


if __name__ == "__main__":
    main()
