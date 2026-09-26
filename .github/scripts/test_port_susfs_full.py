#!/usr/bin/env python3
"""Drive port_susfs_full against the real A2 sources and check the call sites."""
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE.parents[2] / "a2-fixtures"
# Fixtures are passed as argv so the test does not bake in expected output.
fixture = Path(sys.argv[1])
work = Path(sys.argv[2])
if work.exists():
    shutil.rmtree(work)
shutil.copytree(fixture, work)
script = HERE / "port_susfs_full.py"
proc = subprocess.run([sys.executable, str(script)], cwd=work, text=True, capture_output=True)
sys.stdout.write(proc.stdout)
sys.stderr.write(proc.stderr)
if proc.returncode != 0:
    raise SystemExit(proc.returncode)

checks = {

    "mm/memory.c": [
        "SUSFS_IS_INODE_SUS_MAP(file_inode(vma->vm_file))",
        "#include <linux/susfs_def.h>",
    ],
    "fs/proc/task_mmu.c": [
        "SUSFS_IS_INODE_SUS_MAP(inode)",
        "SUSFS_IS_INODE_SUS_MAP(file_inode(vma->vm_file))",
        "SUSFS_IS_INODE_SUS_MAP(file_inode(map_vma->vm_file))",
        "#include <linux/susfs_def.h>",
    ],
    "security/selinux/avc.c": [
        "susfs_is_avc_log_spoofing_enabled",
        "u:r:priv_app:s0:c512,c768",
    ],
    "include/linux/susfs_def.h": ["AS_FLAGS_SUS_MAP", "SUSFS_IS_INODE_SUS_MAP"],
}
for rel, needles in checks.items():
    text = (work / rel).read_text()
    for needle in needles:
        if needle not in text:
            raise SystemExit(f"missing {needle} in {rel}")
    if "susfs: sus_map is not part" in text or "susfs: avc log spoofing is not part" in text:
        raise SystemExit(f"stub text left in {rel}")
print("port call sites present")
