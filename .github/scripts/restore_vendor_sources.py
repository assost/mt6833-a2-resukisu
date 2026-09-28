#!/usr/bin/env python3
"""Restore exact OPPO vendor sources while preserving their link topology."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import posixpath
import shutil
import subprocess
import tempfile

SOURCE_REPOSITORY = "https://github.com/oppo-source/android_kernel_modules_oppo_mt6833"
SOURCE_COMMIT = "dd93a63de24dec560639b88d8328d4be7100a60d"
MODULE_PREFIX = "vendor/oplus"


SOURCES = {
    "audio": (
        "vendor/oplus/kernel_4.19/audio",
        "sound/soc/codecs/audio",
    ),
    "feedback": (
        "vendor/oplus/kernel/system/include/oplus_mm_kevent_fb.h",
        "include/soc/oplus/system/oplus_mm_kevent_fb.h",
    ),
}


def manifest(path):
    paths = sorted(path.rglob("*")) if path.is_dir() else [path]
    result = {}
    for entry in paths:
        name = entry.relative_to(path).as_posix() if path.is_dir() else entry.name
        if entry.is_symlink():
            result[name] = ("symlink", os.readlink(entry))
        elif entry.is_file():
            result[name] = ("file", hashlib.sha256(entry.read_bytes()).hexdigest())
    return result


def restore(root, modules, kind):
    source_name, target_name = SOURCES[kind]
    source = modules / source_name
    target = root / target_name
    if not source.exists():
        raise FileNotFoundError(source)
    # The old audio entry is a dangling link out of this kernel checkout.
    # Check its parent without following that final link.
    target.parent.resolve().relative_to(root)
    if not target.parent.is_dir():
        raise FileNotFoundError(target.parent)
    deps = root / ".build-deps"
    deps.mkdir(exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=f"restore-{kind}-", dir=deps))
    staged = work / target.name
    if source.is_dir():
        shutil.copytree(source, staged, symlinks=True)
    else:
        shutil.copy2(source, staged)
    expected = manifest(source)
    if manifest(staged) != expected:
        raise RuntimeError(f"copy verification failed for {kind}")
    backup = work / "previous"
    existed = target.exists() or target.is_symlink()
    if existed:
        os.replace(target, backup)
    try:
        os.replace(staged, target)
    except BaseException:
        if existed:
            os.replace(backup, target)
        raise
    if manifest(target) != expected:
        raise RuntimeError(f"installed source verification failed for {kind}")
    print(f"restored {target_name}: {len(expected)} source files verified")
    if existed:
        print(f"previous {target_name} preserved at {backup.relative_to(root)}")


def _git(modules, *args):
    return subprocess.run(
        ["git", "-C", str(modules), *args], check=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    ).stdout


def _git_blob(data):
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def module_tree(modules):
    commit = _git(modules, "rev-parse", "HEAD").decode().strip()
    if commit != SOURCE_COMMIT:
        raise RuntimeError(f"modules HEAD {commit} does not match pinned {SOURCE_COMMIT}")
    entries = {}
    for record in _git(modules, "ls-tree", "-r", "-z", SOURCE_COMMIT, "--", MODULE_PREFIX).split(b"\0"):
        if not record:
            continue
        metadata, name = record.split(b"\t", 1)
        mode, kind, blob = metadata.decode().split()
        name = name.decode("utf-8")
        if kind != "blob" or mode not in {"100644", "100755", "120000"}:
            raise RuntimeError(f"unsupported vendor entry: {name} ({mode} {kind})")
        if not name.startswith(MODULE_PREFIX + "/") or ".." in name.split("/"):
            raise RuntimeError(f"unsafe vendor path: {name}")
        entries[name] = {"mode": mode, "git_blob": blob}
    if not entries:
        raise RuntimeError("pinned modules commit has no vendor/oplus tree")
    return entries


def vendor_source_name(path, original_link):
    # The kernel and vendor are siblings in OPPO's original source layout.
    # A sentinel parent prevents excess '..' from matching an unrelated path.
    if "\\" in original_link or posixpath.isabs(original_link):
        return None
    resolved = posixpath.normpath(posixpath.join("/__oppo__/kernel", path.parent.as_posix(), original_link))
    prefix = "/__oppo__/vendor/oplus/"
    if not resolved.startswith(prefix):
        return None
    return MODULE_PREFIX + "/" + resolved[len(prefix):]


def vendor_aliases(root):
    aliases = []
    for record in _git(root, "ls-files", "--stage", "-z").split(b"\0"):
        if not record:
            continue
        metadata, name = record.split(b"\t", 1)
        mode, blob, stage = metadata.decode().split()
        if mode != "120000":
            continue
        if stage != "0":
            raise RuntimeError("unmerged symlink in kernel index; use a fresh kernel checkout")
        relative = Path(name.decode("utf-8"))
        original_bytes = _git(root, "cat-file", "blob", blob)
        original = original_bytes.decode("utf-8")
        source = vendor_source_name(relative, original)
        if source is None:
            continue
        path = root / relative
        path.parent.resolve().relative_to(root)
        if not path.is_symlink() or os.fsencode(os.readlink(path)) != original_bytes:
            raise RuntimeError(f"original vendor alias changed or became a stub: {relative}; use a fresh kernel checkout")
        aliases.append({"path": relative.as_posix(), "original_link": original, "source": source})
    return sorted(aliases, key=lambda item: item["path"])


def _write_json(path, value):
    staged = path.with_suffix(path.suffix + ".new")
    with staged.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    os.replace(staged, path)


def _verify_tree(base, entries):
    problems = []
    boundary = base.resolve()
    checked_parents = set()
    for name, entry in entries.items():
        path = base / name
        try:
            if path.parent not in checked_parents:
                path.parent.resolve().relative_to(boundary)
                checked_parents.add(path.parent)
            if entry["mode"] == "120000":
                if not path.is_symlink():
                    raise ValueError("expected a real symbolic link")
                data = os.fsencode(os.readlink(path))
            else:
                if path.is_symlink() or not path.is_file():
                    raise ValueError("expected a regular file")
                data = path.read_bytes()
            if _git_blob(data) != entry["git_blob"]:
                raise ValueError("bytes differ from pinned Git blob")
        except (OSError, ValueError) as error:
            problems.append({"source": name, "reason": str(error)})
    return problems


def _verify_inner_links(base, entries):
    boundary = (base / MODULE_PREFIX).resolve()
    for name, entry in entries.items():
        if entry["mode"] != "120000":
            continue
        path = base / name
        try:
            path.resolve(strict=True).relative_to(boundary)
        except (OSError, ValueError, RuntimeError) as error:
            raise RuntimeError(f"vendor link is dangling, cyclic or outside vendor/oplus: {name} -> {os.readlink(path)}") from error


def restore_all(root, modules):
    root, modules = root.resolve(), modules.resolve()
    deps = root / ".build-deps"
    if deps.is_symlink():
        raise ValueError(".build-deps must be a real workspace directory")
    deps.mkdir(exist_ok=True)
    report_path = deps / "vendor-restore-manifest.json"
    entries = module_tree(modules)
    if report_path.exists():
        report = json.loads(report_path.read_text(encoding="utf-8"))
        if report.get("source_commit") != SOURCE_COMMIT or report.get("status") not in {"complete", "partial"}:
            raise RuntimeError("existing vendor restoration must be inspected before retrying")
        installed = root / report["installed_tree"]
        installed.resolve().relative_to(deps.resolve())
        problems = _verify_tree(installed, entries)
        if problems:
            raise RuntimeError(f"previously restored vendor tree changed: {problems[0]}")
        _verify_inner_links(installed, entries)
        for item in report["restored"]:
            path = root / item["path"]
            if not path.is_symlink() or os.readlink(path) != item["installed_link"]:
                raise RuntimeError(f"restored alias changed: {item['path']}")
            if path.resolve(strict=True) != (installed / item["source"]).resolve(strict=True):
                raise RuntimeError(f"restored alias target changed: {item['path']}")
        print(f"vendor restoration already verified: {len(report['restored'])} aliases")
        return report

    aliases = vendor_aliases(root)
    if not aliases:
        raise RuntimeError("no original vendor/oplus symlinks found; use a fresh kernel checkout")
    report = {
        "schema_version": 1, "mode": "all", "source_repository": SOURCE_REPOSITORY,
        "source_commit": SOURCE_COMMIT, "status": "preflight", "restored": [], "unavailable": [],
    }
    available = []
    for item in aliases:
        source = item["source"]
        if source not in entries and not any(name.startswith(source + "/") for name in entries):
            report["unavailable"].append({**item, "reason": "path is absent from pinned modules tree"})
        else:
            available.append(item)
    problems = _verify_tree(modules, entries)
    if problems:
        report["status"] = "incomplete_source"
        report["source_errors"] = problems
        _write_json(report_path, report)
        raise RuntimeError(f"pinned vendor checkout is incomplete or modified ({len(problems)} entries); see {report_path}")
    try:
        _verify_inner_links(modules, entries)
    except RuntimeError as error:
        report["status"] = "invalid_source_links"
        report["source_errors"] = [{"reason": str(error)}]
        _write_json(report_path, report)
        raise
    if not available:
        report["status"] = "unavailable"
        _write_json(report_path, report)
        raise RuntimeError(f"no original aliases exist in pinned modules tree; see {report_path}")

    work = Path(tempfile.mkdtemp(prefix="restore-all-", dir=deps))
    installed = work / "source"
    # Copy only tracked entries, retaining one shared topology. Copying each
    # alias separately breaks links whose target is in a sibling directory.
    for name, entry in entries.items():
        source, target = modules / name, installed / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if entry["mode"] == "120000":
            target.symlink_to(os.readlink(source), target_is_directory=source.is_dir())
        else:
            shutil.copy2(source, target)
            target.chmod(0o755 if entry["mode"] == "100755" else 0o644)
    problems = _verify_tree(installed, entries)
    if problems:
        raise RuntimeError(f"staged vendor copy verification failed: {problems[0]}")
    _verify_inner_links(installed, entries)
    report["installed_tree"] = installed.relative_to(root).as_posix()
    report["verified_source_entries"] = len(entries)
    _write_json(work / "source-manifest.json", entries)
    report["source_manifest"] = (work / "source-manifest.json").relative_to(root).as_posix()
    try:
        for item in available:
            target = root / item["path"]
            target.parent.resolve().relative_to(root)
            if not target.is_symlink() or os.readlink(target) != item["original_link"]:
                raise RuntimeError(f"original alias changed during restoration: {item['path']}")
            backup = work / "previous" / item["path"]
            backup.parent.mkdir(parents=True, exist_ok=True)
            replacement = work / "links" / item["path"]
            replacement.parent.mkdir(parents=True, exist_ok=True)
            link = os.path.relpath(installed / item["source"], target.parent)
            replacement.symlink_to(link, target_is_directory=(installed / item["source"]).is_dir())
            os.replace(target, backup)
            try:
                os.replace(replacement, target)
            except BaseException:
                os.replace(backup, target)
                raise
            report["restored"].append({**item, "installed_link": link, "backup": backup.relative_to(root).as_posix()})
            if target.resolve(strict=True) != (installed / item["source"]).resolve(strict=True):
                raise RuntimeError(f"installed alias verification failed: {item['path']}")
        report["status"] = "partial" if report["unavailable"] else "complete"
        _write_json(report_path, report)
    except BaseException:
        for item in reversed(report["restored"]):
            os.replace(root / item["backup"], root / item["path"])
        report["status"] = "rolled_back"
        report["restored"] = []
        _write_json(report_path, report)
        raise
    print(f"restored {len(report['restored'])} exact vendor aliases; {len(report['unavailable'])} unavailable; {len(entries)} pinned blobs verified")
    for item in report["unavailable"]:
        print(f"unavailable {item['path']} -> {item['source']}: {item['reason']}")
    print(f"vendor restoration manifest: {report_path.relative_to(root)}")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("modules", type=Path)
    parser.add_argument("kind", choices=[*SOURCES, "all"])
    args = parser.parse_args()
    if args.kind == "all":
        restore_all(Path.cwd(), args.modules)
    else:
        restore(Path.cwd().resolve(), args.modules.resolve(), args.kind)
