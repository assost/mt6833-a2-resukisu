#!/bin/bash
set -euo pipefail

MODE="${1:-resukisu}"
case "${MODE}" in
    stock|resukisu) ;;
    *) echo "Usage: $0 [stock|resukisu]" >&2; exit 2 ;;
esac
export ARCH=arm64 SUBARCH=arm64 LLVM=1 LLVM_IAS=1
export CROSS_COMPILE=aarch64-linux-gnu-
export CC=clang LD=ld.lld AR=llvm-ar NM=llvm-nm
export OBJCOPY=llvm-objcopy OBJDUMP=llvm-objdump READELF=llvm-readelf
export STRIP=llvm-strip HOSTCC=clang HOSTLD=ld.lld
export PATH="${GITHUB_WORKSPACE:-$(pwd)}/clang/bin:${PATH}"
# Keep known legacy diagnostics visible; real compile/link errors remain fatal.
export KCFLAGS="-Wno-error=strict-prototypes -Wno-error=unused-variable -Wno-error=unused-function"
export TMPDIR="$(pwd)/.build-deps"
mkdir -p "${TMPDIR}" out

# Bind the seven drivers into this Image before compilation.
python3 .github/scripts/integrate_builtin_connectivity.py

make O=out k6833v1_64_k419_defconfig
# Trust the factory public module certificate while preserving forced verification.
cp .github/certs/factory-modules.pem certs/factory-modules.pem
scripts/config --file out/.config --set-str SYSTEM_TRUSTED_KEYS certs/factory-modules.pem
make O=out olddefconfig
cp out/.config out/kernel.config
python3 .github/scripts/verify_factory_config.py "${MODE}"
python3 - "${MODE}" <<'PY'
import json
import sys
from pathlib import Path

mode = sys.argv[1]
config = set(Path("out/.config").read_text().splitlines())
required = ["CONFIG_LTO_CLANG=y", "CONFIG_CFI_CLANG=y"]
if mode == "resukisu":
    required += ['CONFIG_KSU=y', 'CONFIG_KSU_SUSFS=y', 'CONFIG_KSU_SUSFS_SUS_PATH=y', 'CONFIG_KSU_SUSFS_SUS_MOUNT=y', 'CONFIG_KSU_SUSFS_SUS_KSTAT=y', 'CONFIG_KSU_SUSFS_SPOOF_UNAME=y', 'CONFIG_KSU_SUSFS_ENABLE_LOG=y', 'CONFIG_KSU_SUSFS_HIDE_KSU_SUSFS_SYMBOLS=y', 'CONFIG_KSU_SUSFS_SPOOF_CMDLINE_OR_BOOTCONFIG=y', 'CONFIG_KSU_SUSFS_OPEN_REDIRECT=y', 'CONFIG_KSU_SUSFS_SUS_MAP=y']
elif "CONFIG_KSU=y" in config:
    raise SystemExit("stock baseline unexpectedly enables KSU")
missing = [value for value in required if value not in config]
if missing:
    raise SystemExit("missing required configuration: " + ", ".join(missing))
for rejected in ("CONFIG_KSU_SUSFS_SUS_SU=y",):
    if rejected in config:
        raise SystemExit("SUSFS option is outside this phase: " + rejected)
if "CONFIG_KSU_TRACEPOINT_HOOK=y" in config:
    raise SystemExit("unexpected tracepoint hook configuration")
manifest = Path(".build-deps/vendor-restore-manifest.json")
vendor = json.loads(manifest.read_text())
Path("out/vendor-restore-manifest.json").write_text(json.dumps(vendor, indent=2))
Path("out/build-validation.json").write_text(json.dumps({"mode": mode, "required": required, "config_passed": True}, indent=2))
print("configuration validated:", mode, ", ".join(required))
PY
{
    git rev-parse HEAD
    if [ "${MODE}" = resukisu ]; then
        git -C KernelSU rev-parse HEAD
        grep 'SUSFS_VERSION "v2.3.0"' include/linux/susfs.h
        test ! -f fs/susfs_api_compat.c
        sha256sum fs/susfs.c include/linux/susfs.h include/linux/susfs_def.h
        grep -n 'susfs_start_sdcard_monitor_fn\|susfs_run_extra_works\|susfs_set_hide_sus_mnts_for_non_su_procs' fs/susfs.c
        for source in mm/memory.c fs/proc/task_mmu.c; do
            grep -n "SUSFS_IS_INODE_SUS_MAP" "${source}"
        done
        grep -n "susfs_is_avc_log_spoofing_enabled" security/selinux/avc.c
    fi
} > out/integration-evidence.txt

# Reject loader-incompatible vDSO metadata before the full kernel build.
make O=out -j2 V=1 vdso_prepare 2>&1 | tee out/vdso-build.log
python3 .github/scripts/verify_vdso.py --elf out/arch/arm64/kernel/vdso/vdso.so.dbg --output out/vdso-early-validation.json

# Android.mk / kenv.mk select Image.gz. Stock DTBO is retained on the device;
# building all OEM overlays would additionally require external DWS generation.
make O=out -k -j2 Image.gz 2>&1 | tee out/build.log
cp out/.config out/kernel.config
test "$(stat -c %s out/arch/arm64/boot/Image.gz)" -gt 1048576
sha256sum out/arch/arm64/boot/Image.gz > out/kernel.sha256
python3 .github/scripts/verify_vdso.py --elf out/arch/arm64/kernel/vdso/vdso.so --image-gz out/arch/arm64/boot/Image.gz --output out/vdso-validation.json
ls -lh out/arch/arm64/boot/Image.gz

# Preserve evidence that the drivers are linked into this exact Image.
make O=out modules.builtin
llvm-objcopy --strip-debug out/vmlinux out/vmlinux.symbols
python3 .github/scripts/verify_builtin_connectivity.py --mode "${MODE}" --nm llvm-nm
