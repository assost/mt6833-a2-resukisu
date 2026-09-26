#!/usr/bin/env python3
"""Skip vendor/oplus trees that this kernel drop only references by broken symlink."""
from pathlib import Path

ROOT = Path(".").resolve()


def broken_symlinks():
    found = []
    for path in ROOT.rglob("*"):
        if ".git" in path.parts:
            continue
        if path.is_symlink() and not path.exists():
            found.append(path.relative_to(ROOT).as_posix())
    return found


def comment_matching_lines(path: Path, needles):
    if not path.is_file():
        return False
    lines = path.read_text(errors="replace").splitlines(keepends=True)
    changed = False
    out = []
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("#"):
            out.append(line)
            continue
        if any(needle in line for needle in needles):
            out.append("# missing vendor source: " + line)
            changed = True
        else:
            out.append(line)
    if changed:
        path.write_text("".join(out))
    return changed


def main():
    missing = broken_symlinks()
    print(f"broken symlinks: {len(missing)}")
    for item in missing:
        print(f"  {item}")

    for item in missing:
        parent = str(Path(item).parent).replace("\\", "/")
        name = Path(item).name
        makefile = ROOT / parent / "Makefile"
        if comment_matching_lines(makefile, [f"{name}/", f"{name}\\"]):
            print(f"makefile {parent}/Makefile skipped {name}")

    for kconfig in ROOT.rglob("Kconfig*"):
        if ".git" in kconfig.parts or not kconfig.is_file():
            continue
        text = kconfig.read_text(errors="replace")
        lines = text.splitlines(keepends=True)
        changed = False
        out = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("source "):
                quoted = stripped.split("source ", 1)[1].strip().strip('"')
                target = (kconfig.parent / quoted).resolve() if False else ROOT / quoted
                if not (ROOT / quoted).exists():
                    out.append("# missing vendor source: " + line)
                    changed = True
                    continue
            out.append(line)
        if changed:
            kconfig.write_text("".join(out))
            print(f"kconfig {kconfig.relative_to(ROOT)}")

    defconfig = ROOT / "arch/arm64/configs/k6833v1_64_k419_defconfig"
    text = defconfig.read_text()
    for name in (
        "CONFIG_LOCKING_PROTECT",
        "CONFIG_KERNEL_LOCK_OPT",
        "CONFIG_OPLUS_FEATURE_SCHED_ASSIST",
        "CONFIG_OPLUS_LOCKING_STRATEGY",
    ):
        text = text.replace(f"{name}=y", f"# {name} is not set")
    defconfig.write_text(text)


if __name__ == "__main__":
    main()
