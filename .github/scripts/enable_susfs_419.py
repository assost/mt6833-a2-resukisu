#!/usr/bin/env python3
"""Insert v1.5.5 Kconfig entries and defconfig lines for this 4.19 tree."""

import sys
from pathlib import Path

MARKER = "BEGIN SUSFS 4.19 feature configs"
ENABLED = (
    "CONFIG_KSU_SUSFS_HAS_MAGIC_MOUNT",
    "CONFIG_KSU_SUSFS_AUTO_ADD_SUS_KSU_DEFAULT_MOUNT",
    "CONFIG_KSU_SUSFS_AUTO_ADD_SUS_BIND_MOUNT",
    "CONFIG_KSU_SUSFS_TRY_UMOUNT",
    "CONFIG_KSU_SUSFS_AUTO_ADD_TRY_UMOUNT_FOR_BIND_MOUNT",
    "CONFIG_KSU_SUSFS_SUS_OVERLAYFS",
)
REJECTED = (
    "CONFIG_KSU_SUSFS_SUS_SU",
)

BLOCK = """
# BEGIN SUSFS 4.19 feature configs
config KSU_SUSFS_HAS_MAGIC_MOUNT
    bool "Enable magic-mount path handling for v1.5.5 auto-umount"
    depends on KSU_SUSFS
    default y
    help
        Recognize /debug_ramdisk/workdir mounts inside the v1.5.5 auto-umount list.

config KSU_SUSFS_AUTO_ADD_SUS_KSU_DEFAULT_MOUNT
    bool "Automatically mark default KSU mounts"
    depends on KSU_SUSFS_SUS_MOUNT
    default y
    help
        Mark the v1.5.5 default KSU mount paths when a KSU-domain mount succeeds.

config KSU_SUSFS_AUTO_ADD_SUS_BIND_MOUNT
    bool "Automatically mark KSU bind mounts"
    depends on KSU_SUSFS_SUS_MOUNT
    default y
    help
        Mark a KSU-domain bind mount source unless it already has a peer group.

config KSU_SUSFS_TRY_UMOUNT
    bool "Enable the v1.5.5 try-umount list"
    depends on KSU_SUSFS
    default y
    help
        Keep the v1.5.5 umount list and run it before ReSukiSU's own umount.

config KSU_SUSFS_AUTO_ADD_TRY_UMOUNT_FOR_BIND_MOUNT
    bool "Automatically queue KSU bind mounts for try-umount"
    depends on KSU_SUSFS_TRY_UMOUNT
    default y
    help
        Add a KSU-domain bind mount target to the v1.5.5 try-umount list.

config KSU_SUSFS_SUS_OVERLAYFS
    bool "Use lowerdata paths for overlay getattr, readdir and statfs"
    depends on KSU_SUSFS
    default y
    help
        Call ovl_path_lowerdata from the A2 4.19 overlayfs sites in a2-susfs.patch.
        Public commit f68c467e defines that function.
# END SUSFS 4.19 feature configs
"""


def enable(kconfig_text, defconfig_text):
    for name in REJECTED:
        if f"{name}=y" in defconfig_text:
            raise SystemExit(f"refusing option that this phase does not enable: {name}")
    if "CONFIG_LTO_CLANG=y" not in defconfig_text or "CONFIG_CFI_CLANG=y" not in defconfig_text:
        raise SystemExit("refusing to edit a defconfig that does not keep LTO and CFI")
    if MARKER not in kconfig_text:
        anchor = "config KSU_SUSFS_SUS_MAP"
        if anchor not in kconfig_text:
            raise SystemExit("ReSukiSU SUSFS menu anchor missing")
        kconfig_text = kconfig_text.replace(anchor, BLOCK + anchor, 1)
    lines = [line for line in defconfig_text.splitlines()
             if line not in {f"# {name} is not set" for name in ENABLED}]
    present = set(lines)
    for name in ENABLED:
        item = f"{name}=y"
        if item not in present:
            lines.append(item)
            present.add(item)
    if not defconfig_text.endswith("\n"):
        defconfig_text += "\n"
    rebuilt = "\n".join(lines) + "\n"
    return kconfig_text, rebuilt


def main(argv):
    if len(argv) != 3:
        raise SystemExit("usage: enable_susfs_419.py <Kconfig> <defconfig>")
    kconfig = Path(argv[1])
    defconfig = Path(argv[2])
    new_kconfig, new_defconfig = enable(kconfig.read_text(), defconfig.read_text())
    kconfig.write_text(new_kconfig)
    defconfig.write_text(new_defconfig)
    print("susfs 4.19 configs enabled")


if __name__ == "__main__":
    main(sys.argv)
