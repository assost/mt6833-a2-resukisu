#!/usr/bin/env python3
"""Restore the two required sources from the pinned OPPO modules checkout."""
import argparse
import hashlib
import os
from pathlib import Path
import shutil
import tempfile


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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("modules", type=Path)
    parser.add_argument("kind", choices=SOURCES)
    args = parser.parse_args()
    restore(Path.cwd().resolve(), args.modules.resolve(), args.kind)
