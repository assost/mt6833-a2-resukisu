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

# Real SUSFS v2.3.0, backported to the pinned A2 4.19 source tree.
RESUKISU_COMMIT="94dd3c93c2053a84fd752df6eb85db99b7d70ab8"
SUSFS_COMMIT="9892175b4acec7ee844e113b8d02c0f4d12cdfac"
curl -fLSs "https://raw.githubusercontent.com/ReSukiSU/ReSukiSU/${RESUKISU_COMMIT}/kernel/setup.sh" | bash -s -- "${RESUKISU_COMMIT}"
test "$(git -C KernelSU rev-parse HEAD)" = "${RESUKISU_COMMIT}"
SUSFS_DIR="$(mktemp -d "${DEPS}/susfs23.XXXXXX")"
git -C "${SUSFS_DIR}" init -q
git -C "${SUSFS_DIR}" remote add origin https://gitlab.com/simonpunk/susfs4ksu.git
git -C "${SUSFS_DIR}" fetch --depth 1 origin "${SUSFS_COMMIT}"
git -C "${SUSFS_DIR}" checkout --detach FETCH_HEAD
test "$(git -C "${SUSFS_DIR}" rev-parse HEAD)" = "${SUSFS_COMMIT}"
grep -q '#define SUSFS_VERSION "v2.3.0"' "${SUSFS_DIR}/kernel_patches/include/linux/susfs.h"
cp -a "${SUSFS_DIR}/kernel_patches/fs/." fs/
cp -a "${SUSFS_DIR}/kernel_patches/include/linux/." include/linux/
git apply --whitespace=nowarn "${ROOT}/.github/scripts/susfs-2.3-core.patch"
git apply --whitespace=nowarn "${ROOT}/.github/scripts/a2-susfs-2.3.patch"
python3 "${ROOT}/.github/scripts/fix_missing_vendor.py" --restored-vendor
python3 "${ROOT}/.github/scripts/configure_susfs23.py"
echo "SUSFS source commit: ${SUSFS_COMMIT}; version v2.3.0; A2 4.19 port"
sha256sum fs/susfs.c include/linux/susfs.h include/linux/susfs_def.h
