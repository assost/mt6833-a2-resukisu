#!/bin/bash
set -euo pipefail

ROOT="$(pwd)"
echo "kernel root: ${ROOT}"
MODE="${1:-resukisu}"
case "${MODE}" in
    stock|resukisu) ;;
    *) echo "Usage: $0 [stock|resukisu]" >&2; exit 2 ;;
esac
DEPS="${ROOT}/.build-deps"
mkdir -p "${DEPS}"
export TMPDIR="${DEPS}"

# Preserve the official shared vendor layout and all hardware feature macros.
MODULES_COMMIT="dd93a63de24dec560639b88d8328d4be7100a60d"
MODULES_DIR="$(mktemp -d "${DEPS}/oppo-mt6833-modules.XXXXXX")"
git -C "${MODULES_DIR}" init -q
git -C "${MODULES_DIR}" config core.autocrlf false
git -C "${MODULES_DIR}" remote add origin https://github.com/oppo-source/android_kernel_modules_oppo_mt6833.git
git -C "${MODULES_DIR}" sparse-checkout init --cone
git -C "${MODULES_DIR}" sparse-checkout set vendor/oplus
git -C "${MODULES_DIR}" fetch --depth 1 --filter=blob:none origin "${MODULES_COMMIT}"
git -C "${MODULES_DIR}" checkout --detach FETCH_HEAD
test "$(git -C "${MODULES_DIR}" rev-parse HEAD)" = "${MODULES_COMMIT}"
python3 "${ROOT}/.github/scripts/restore_vendor_sources.py" "${MODULES_DIR}" all
python3 "${ROOT}/.github/scripts/fix_missing_vendor.py" --restored-vendor
if [ "${MODE}" = stock ]; then
    echo "official vendor sources prepared; stock feature configuration preserved"
    exit 0
fi

# Historical Actions logs never retained the depth-1 SUSFS rev-parse line.
# That old SHA is unknown. The commit below is an explicit v1.5.5 baseline,
# not a claim that run 36468001631 cloned this same object.
RESUKISU_COMMIT="fa8311f632a215b5381ec644627c6198d1e8a13e"
SUSFS_COMMIT="001e69919c6271f690fd00b17e4c721c9e599152"
curl -fLSs "https://raw.githubusercontent.com/ReSukiSU/ReSukiSU/${RESUKISU_COMMIT}/kernel/setup.sh" | bash -s -- "${RESUKISU_COMMIT}"
test "$(git -C KernelSU rev-parse HEAD)" = "${RESUKISU_COMMIT}"
SUSFS_DIR="$(mktemp -d "${DEPS}/susfs4ksu.XXXXXX")"
git -C "${SUSFS_DIR}" init -q
git -C "${SUSFS_DIR}" remote add origin https://gitlab.com/simonpunk/susfs4ksu.git
git -C "${SUSFS_DIR}" fetch --depth 1 origin "${SUSFS_COMMIT}"
git -C "${SUSFS_DIR}" checkout --detach FETCH_HEAD
test "$(git -C "${SUSFS_DIR}" rev-parse HEAD)" = "${SUSFS_COMMIT}"
grep -q '#define SUSFS_VERSION "v1.5.5"' "${SUSFS_DIR}/kernel_patches/include/linux/susfs.h"
echo "SUSFS source commit: ${SUSFS_COMMIT} explicit v1.5.5 baseline; historical CI SHA unknown"
cp -a "${SUSFS_DIR}/kernel_patches/fs/." fs/
cp -a "${SUSFS_DIR}/kernel_patches/include/linux/." include/linux/
cp -a "${ROOT}/.github/scripts/susfs_api_compat.c" fs/susfs_api_compat.c
cp -a "${ROOT}/.github/scripts/susfs_419_logic.h" fs/susfs_419_logic.h
git apply --whitespace=nowarn "${ROOT}/.github/scripts/a2-susfs.patch"
python3 "${ROOT}/.github/scripts/adapt.py"
python3 "${ROOT}/.github/scripts/port_susfs_full.py"
# Hooks were inserted after the baseline compatibility pass.
python3 "${ROOT}/.github/scripts/fix_missing_vendor.py" --restored-vendor

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

python3 "${ROOT}/.github/scripts/enable_susfs_419.py" \
  "${ROOT}/KernelSU/kernel/Kconfig" "${ROOT}/${DEF}"
echo "prepared"
grep -n "CONFIG_KSU_SUSFS=\|CONFIG_LTO_CLANG=\|CONFIG_CFI_CLANG=\|CONFIG_OPLUS_ROOT_CHECK" "${DEF}"
