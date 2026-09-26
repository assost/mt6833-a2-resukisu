#!/bin/bash
set -euo pipefail

ROOT="$(pwd)"
echo "kernel root: ${ROOT}"

curl -LSs "https://raw.githubusercontent.com/ReSukiSU/ReSukiSU/main/kernel/setup.sh" | bash

rm -rf /tmp/susfs4ksu
git clone --depth 1 -b kernel-4.19 https://gitlab.com/simonpunk/susfs4ksu.git /tmp/susfs4ksu
cp -a /tmp/susfs4ksu/kernel_patches/fs/. fs/
cp -a /tmp/susfs4ksu/kernel_patches/include/linux/. include/linux/
cp -a "${ROOT}/.github/scripts/susfs_api_compat.c" fs/susfs_api_compat.c
git apply --whitespace=nowarn "${ROOT}/.github/scripts/a2-susfs.patch"

python3 "${ROOT}/.github/scripts/adapt.py"
python3 "${ROOT}/.github/scripts/fix_missing_vendor.py"

if ! grep -q 'susfs_api_compat.o' fs/Makefile; then
  sed -i 's/obj-$(CONFIG_KSU_SUSFS) += susfs.o/obj-$(CONFIG_KSU_SUSFS) += susfs.o susfs_api_compat.o/' fs/Makefile
fi

DEF="arch/arm64/configs/k6833v1_64_k419_defconfig"
python3 - <<'PY'
from pathlib import Path
p = Path("arch/arm64/configs/k6833v1_64_k419_defconfig")
text = p.read_text()
for name in (
    "CONFIG_OPLUS_ROOT_CHECK",
    "CONFIG_OPLUS_EXECVE_BLOCK",
    "CONFIG_OPLUS_MOUNT_BLOCK",
    "CONFIG_OPLUS_SECURE_GUARD",
):
    text = text.replace(f"{name}=y", f"# {name} is not set")
extra = """
# ReSukiSU + SUSFS 4.19. LTO and CFI stay at the stock values above.
CONFIG_KSU=y
CONFIG_KSU_SUSFS=y
CONFIG_KSU_SUSFS_SUS_PATH=y
CONFIG_KSU_SUSFS_SUS_MOUNT=y
CONFIG_KSU_SUSFS_SUS_KSTAT=y
CONFIG_KSU_SUSFS_SPOOF_UNAME=y
CONFIG_KSU_SUSFS_ENABLE_LOG=y
CONFIG_KSU_SUSFS_HIDE_KSU_SUSFS_SYMBOLS=y
CONFIG_KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG=y
CONFIG_KSU_SUSFS_OPEN_REDIRECT=y
# CONFIG_KSU_SUSFS_SUS_MAP is not set
"""
if "CONFIG_KSU_SUSFS=y" not in text:
    text += extra
p.write_text(text)
PY

echo "prepared"
grep -n "CONFIG_KSU_SUSFS=\|CONFIG_LTO_CLANG=\|CONFIG_CFI_CLANG=\|CONFIG_OPLUS_ROOT_CHECK" "${DEF}"
