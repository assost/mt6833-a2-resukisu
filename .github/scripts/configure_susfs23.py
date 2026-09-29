#!/usr/bin/env python3
"""Select the real SUSFS 2.3 feature set without deprecated 1.5 options."""
import re
from pathlib import Path

FEATURES = (
    "KSU", "KSU_SUSFS", "KSU_SUSFS_SUS_PATH", "KSU_SUSFS_SUS_MOUNT",
    "KSU_SUSFS_SUS_KSTAT", "KSU_SUSFS_SPOOF_UNAME", "KSU_SUSFS_ENABLE_LOG",
    "KSU_SUSFS_HIDE_KSU_SUSFS_SYMBOLS", "KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG",
    "KSU_SUSFS_OPEN_REDIRECT", "KSU_SUSFS_SUS_MAP",
)
DISABLED = (
    "OPLUS_ROOT_CHECK", "OPLUS_EXECVE_BLOCK", "OPLUS_MOUNT_BLOCK", "OPLUS_SECURE_GUARD",
    "KSU_TRACEPOINT_HOOK", "KSU_MANUAL_HOOK", "KSU_SUSFS_HAS_MAGIC_MOUNT",
    "KSU_SUSFS_AUTO_ADD_SUS_KSU_DEFAULT_MOUNT", "KSU_SUSFS_AUTO_ADD_SUS_BIND_MOUNT",
    "KSU_SUSFS_TRY_UMOUNT", "KSU_SUSFS_AUTO_ADD_TRY_UMOUNT_FOR_BIND_MOUNT",
    "KSU_SUSFS_SUS_OVERLAYFS", "KSU_SUSFS_SUS_SU",
)

def configure(root):
    header = (root / "include/linux/susfs.h").read_text()
    if '#define SUSFS_VERSION "v2.3.0"' not in header:
        raise SystemExit("Expected the pinned, real SUSFS v2.3.0 source")
    kconfig = (root / "KernelSU/kernel/Kconfig").read_text()
    for feature in FEATURES[1:]:
        if not re.search(r"^config " + feature + r"$", kconfig, re.M):
            raise SystemExit("Missing ReSukiSU Kconfig feature: " + feature)
    for rel in ("fs/susfs_api_compat.c", "fs/susfs_419_logic.h"):
        if (root / rel).exists():
            raise SystemExit("Stale v1.5 compatibility source present: " + rel)
    defconfig = root / "arch/arm64/configs/k6833v1_64_k419_defconfig"
    text = defconfig.read_text()
    names = set(FEATURES + DISABLED)
    marker = "# SUSFS v2.3.0: deprecated v1.5 features are not reused."
    lines = [line for line in text.splitlines()
             if line != marker and not any(line.startswith("CONFIG_" + name + "=") or
                        line == "# CONFIG_" + name + " is not set" for name in names)]
    while lines and not lines[-1].strip():
        lines.pop()
    lines += ["", "# SUSFS v2.3.0: deprecated v1.5 features are not reused."]
    lines += ["CONFIG_" + name + "=y" for name in FEATURES]
    lines += ["# CONFIG_" + name + " is not set" for name in DISABLED]
    defconfig.write_text("\n".join(lines).rstrip() + "\n")
    print("Configured actual SUSFS v2.3.0 features; LTO/CFI untouched")

if __name__ == "__main__":
    configure(Path.cwd())
