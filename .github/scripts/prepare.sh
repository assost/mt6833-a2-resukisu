#!/bin/bash
set -euo pipefail

ROOT="$(pwd)"
echo "kernel root: ${ROOT}"
DEPS="${ROOT}/.build-deps"
mkdir -p "${DEPS}"
export TMPDIR="${DEPS}"

curl -LSs "https://raw.githubusercontent.com/ReSukiSU/ReSukiSU/main/kernel/setup.sh" | bash

SUSFS_DIR="$(mktemp -d "${DEPS}/susfs4ksu.XXXXXX")"
git clone --depth 1 -b kernel-4.19 https://gitlab.com/simonpunk/susfs4ksu.git "${SUSFS_DIR}"
cp -a "${SUSFS_DIR}/kernel_patches/fs/." fs/
cp -a "${SUSFS_DIR}/kernel_patches/include/linux/." include/linux/
cp -a "${ROOT}/.github/scripts/susfs_api_compat.c" fs/susfs_api_compat.c
git apply --whitespace=nowarn "${ROOT}/.github/scripts/a2-susfs.patch"

python3 "${ROOT}/.github/scripts/adapt.py"
python3 "${ROOT}/.github/scripts/port_susfs_full.py"
# This kernel drop points outside the checkout for audio. Restore the matching
# official implementation before generic missing-vendor handling can stub it.
MODULES_COMMIT="dd93a63de24dec560639b88d8328d4be7100a60d"
MODULES_DIR="$(mktemp -d "${DEPS}/oppo-mt6833-modules.XXXXXX")"
git -C "${MODULES_DIR}" init -q
git -C "${MODULES_DIR}" config core.autocrlf false
git -C "${MODULES_DIR}" remote add origin https://github.com/oppo-source/android_kernel_modules_oppo_mt6833.git
git -C "${MODULES_DIR}" sparse-checkout init --cone
git -C "${MODULES_DIR}" sparse-checkout set vendor/oplus/kernel_4.19/audio vendor/oplus/kernel/system/include
git -C "${MODULES_DIR}" fetch --depth 1 --filter=blob:none origin "${MODULES_COMMIT}"
git -C "${MODULES_DIR}" checkout --detach FETCH_HEAD
test "$(git -C "${MODULES_DIR}" rev-parse HEAD)" = "${MODULES_COMMIT}"
python3 "${ROOT}/.github/scripts/restore_vendor_sources.py" "${MODULES_DIR}" audio
python3 "${ROOT}/.github/scripts/fix_missing_vendor.py"
# The fixer materializes the previously missing system include directory.
# This official header supplies its own fallback when MM_FEEDBACK is disabled.
python3 "${ROOT}/.github/scripts/restore_vendor_sources.py" "${MODULES_DIR}" feedback

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
CONFIG_KSU_SUSFS_SUS_MAP=y
"""
if "CONFIG_KSU_SUSFS=y" not in text:
    text += extra
p.write_text(text)
PY

echo "prepared"
grep -n "CONFIG_KSU_SUSFS=\|CONFIG_LTO_CLANG=\|CONFIG_CFI_CLANG=\|CONFIG_OPLUS_ROOT_CHECK" "${DEF}"
