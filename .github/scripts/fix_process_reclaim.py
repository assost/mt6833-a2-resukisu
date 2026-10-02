#!/usr/bin/env python3
"""Overlay the pinned vendor process-reclaim fix after prepare.sh, before build."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import uuid

SOURCE_COMMIT = "dd93a63de24dec560639b88d8328d4be7100a60d"
SOURCE_PATH = "vendor/oplus/kernel/oplus_performance/process_reclaim/process_mm_reclaim.c"
BEFORE_SHA256 = "355f0cd1c545d521bbb7a20fd3f6648d7598dfda99f540160980131a4d80d996"
AFTER_SHA256 = "a5668719a8c462110e7175e2282afd5ac28a03f561e49d19229de45e8fc3c68e"
TARGET = "mm/process_mm_reclaim.c"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def atomic_write(path, data, mode=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_bytes() == data:
        return
    if path.exists() or path.is_symlink():
        backup = path.with_name(path.name + ".bak-" + uuid.uuid4().hex)
        shutil.copy2(path, backup, follow_symlinks=False)
    temporary = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex)
    try:
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        if mode is not None:
            os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def json_bytes(value):
    return (json.dumps(value, indent=2) + "\n").encode()


def transform(data):
    require(sha(data) == BEFORE_SHA256, "Pinned vendor source SHA256 mismatch")
    old = b"\t\tpage = vm_normal_page(vma, addr, ptent);\n\t\tif (!page)\n\t\t\tcontinue;\n"
    addition = b"""
\t\t/*
\t\t * Splitting a PMD leaves PTEs mapping compound tails. The PTE
\t\t * lock stabilizes this mapping until isolate_lru_page pins the
\t\t * head. Use that same head for all following LRU/list operations.
\t\t */
\t\tpage = compound_head(page);
"""
    require(data.count(old) == 1, "Expected one exact vm_normal_page source anchor")
    fixed = data.replace(old, old + addition, 1)
    require(sha(fixed) == AFTER_SHA256, "Transformed source differs from reviewed fix")
    return fixed


def apply(root, out):
    root = root.resolve(strict=True)
    out = (out if out.is_absolute() else root / out).resolve()
    require(out.is_relative_to(root), "Build evidence directory must stay inside kernel root")
    manifest_path = root / ".build-deps/vendor-restore-manifest.json"
    restored = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    canonical_manifest_sha256 = sha(json.dumps(restored, sort_keys=True, separators=(",", ":")).encode("utf-8"))
    require(restored.get("status") == "complete" and restored.get("source_commit") == SOURCE_COMMIT,
            "A completed pinned vendor restoration is required")
    aliases = [row for row in restored.get("restored", []) if row.get("path") == TARGET]
    require(len(aliases) == 1 and aliases[0].get("source") == SOURCE_PATH,
            "Restoration manifest does not identify the expected process-reclaim source")
    installed = (root / restored["installed_tree"]).resolve(strict=True)
    require(installed.is_relative_to(root / ".build-deps"), "Restored vendor tree escaped build dependencies")
    source = (installed / SOURCE_PATH).resolve(strict=True)
    require(source.is_relative_to(installed) and source.is_file(), "Pinned vendor source escaped its restored tree")
    original = source.read_bytes()
    fixed = transform(original)
    target = root / TARGET
    require(target.parent.resolve(strict=True).is_relative_to(root), "Kernel target parent escaped root")
    evidence = root / ".build-deps/process-reclaim-repair"
    saved_report = evidence / "report.json"
    if target.is_symlink():
        require(target.resolve(strict=True) == source, "Kernel alias does not resolve to the pinned restored vendor source")
        link = os.readlink(target)
        require(link == aliases[0].get("installed_link"), "Kernel alias differs from the restoration manifest")
        evidence.mkdir(parents=True, exist_ok=True)
        before = evidence / "source-before.c"
        link_backup = evidence / "original-symlink.txt"
        if before.exists():
            require(before.read_bytes() == original, "Existing source backup differs")
        if link_backup.exists():
            require(link_backup.read_text() == link, "Existing original-link backup differs")
        atomic_write(before, original)
        atomic_write(link_backup, link.encode())
        # Replace only the kernel alias itself. Never follow it when writing;
        # the restored vendor cache and its source manifest remain unchanged.
        temporary = target.with_name(target.name + ".reclaim-" + uuid.uuid4().hex)
        try:
            with temporary.open("xb") as stream:
                stream.write(fixed)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, stat.S_IMODE(source.stat().st_mode))
            os.replace(temporary, target)
        finally:
            if temporary.exists():
                temporary.unlink()
        report = {"schema_version": 1, "status": "applied", "source_commit": SOURCE_COMMIT,
                  "kernel_target": TARGET, "original_symlink": link,
                  "original_resolved_target": str(source), "kernel_root": str(root),
                  "before_sha256": BEFORE_SHA256, "after_sha256": AFTER_SHA256,
                  "backup_source": str(before), "backup_symlink_text": str(link_backup),
                  "restoration_manifest_sha256": sha(manifest_path.read_bytes()),
                  "restoration_manifest_canonical_sha256": canonical_manifest_sha256,
                  "source_artifact": "process-reclaim-source.c", "runtime_verified": False,
                  "scope": "Canonical compound head before all LRU/list operations; source overlay only."}
    else:
        require(target.is_file() and sha(target.read_bytes()) == AFTER_SHA256 and saved_report.is_file(),
                "Kernel target is neither the original alias nor a previously verified overlay")
        report = json.loads(saved_report.read_text())
        require(report.get("before_sha256") == BEFORE_SHA256 and report.get("after_sha256") == AFTER_SHA256
                and report.get("original_resolved_target") == str(source)
                and report.get("restoration_manifest_canonical_sha256") == canonical_manifest_sha256
                and report.get("restoration_manifest_sha256") == sha(manifest_path.read_bytes()),
                "Existing repair report does not match this restored tree")
        require(Path(report["backup_source"]).read_bytes() == original, "Original source backup changed")
    require(not target.is_symlink() and target.read_bytes() == fixed, "Kernel overlay readback failed")
    require(source.read_bytes() == original, "Restored vendor cache changed during overlay")
    report["vendor_cache_unchanged"] = True
    report["vendor_cache_sha256_after"] = sha(source.read_bytes())
    atomic_write(saved_report, json_bytes(report))
    atomic_write(out / "process-reclaim-source.c", fixed)
    atomic_write(out / "process-reclaim-repair.json", json_bytes(report))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--out", type=Path, default=Path("out"))
    args = parser.parse_args()
    report = apply(args.root, args.out)
    print(json.dumps({key: report[key] for key in ("status", "kernel_target", "before_sha256",
                                                  "after_sha256", "vendor_cache_unchanged")}, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise SystemExit("RECLAIM REPAIR NOT APPLIED: " + str(error))
