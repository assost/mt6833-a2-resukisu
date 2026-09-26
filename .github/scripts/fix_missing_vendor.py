#!/usr/bin/env python3
"""Replace broken vendor symlinks with empty build stubs and strip Kconfig CRs.

Commenting out source lines drops endif/endmenu that live in the missing
file and makes the parent endmenu unexpected. Empty files keep the parse.
"""
import os
from pathlib import Path

ROOT = Path(".").resolve()


def broken_symlinks():
    found = []
    for path in ROOT.rglob("*"):
        if ".git" in path.parts:
            continue
        if path.is_symlink() and not path.exists():
            found.append(path)
    return found


def stub_symlink(path: Path):
    name = path.name
    path.unlink()
    if name.endswith((".c", ".h", ".S")):
        path.write_text("/* stub: vendor source is not in this kernel drop */\n")
        return
    path.mkdir()
    (path / "Makefile").write_text("\n")
    (path / "Kconfig").write_text("# stub: vendor source is not in this kernel drop\n")


def ensure_source_targets():
    for kconfig in ROOT.rglob("Kconfig*"):
        if ".git" in kconfig.parts or not kconfig.is_file() or kconfig.is_symlink():
            continue
        text = kconfig.read_text(errors="replace")
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped.startswith("source "):
                continue
            quoted = stripped.split(None, 1)[1].strip()
            if quoted.startswith('"') and '"' in quoted[1:]:
                quoted = quoted[1:quoted.find('"', 1)]
            else:
                continue
            target = ROOT / quoted
            if target.exists():
                continue
            if target.is_symlink():
                target.unlink()
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("# stub: vendor source is not in this kernel drop\n")
            print(f"stub source {quoted}")


def strip_cr():
    for path in ROOT.rglob("Kconfig*"):
        if ".git" in path.parts or not path.is_file() or path.is_symlink():
            continue
        data = path.read_bytes()
        if b"\r" not in data:
            continue
        path.write_bytes(data.replace(b"\r\n", b"\n").replace(b"\r", b"\n"))


def drop_unbalanced_ends():
    starters = {"menu": "endmenu", "if": "endif", "choice": "endchoice"}
    enders = {v: k for k, v in starters.items()}
    for path in ROOT.rglob("Kconfig*"):
        if ".git" in path.parts or not path.is_file() or path.is_symlink():
            continue
        lines = path.read_text(errors="replace").splitlines(keepends=True)
        stack = []
        out = []
        changed = False
        for line in lines:
            token = line.strip().split(" ", 1)[0]
            if token in starters:
                stack.append(starters[token])
                out.append(line)
            elif token in enders:
                if stack and stack[-1] == token:
                    stack.pop()
                    out.append(line)
                else:
                    out.append("# unbalanced vendor kconfig: " + line)
                    changed = True
            else:
                out.append(line)
        if changed:
            path.write_text("".join(out))
            print(f"balanced {path.relative_to(ROOT)}")


SCHED_ASSIST_HEADERS = (
    "sched_assist_mutex.h",
    "sched_assist_status.h",
    "sched_assist_common.h",
    "sched_assist_slide.h",
    "sched_assist_locking.h",
)


def write_sched_assist_headers():
    directory = ROOT / "include/linux/sched_assist"
    if not directory.is_dir():
        return
    for name in SCHED_ASSIST_HEADERS:
        path = directory / name
        if not path.exists():
            path.write_text("/* stub: vendor sched_assist header is not in this kernel drop */\n")
            print(f"header {path.relative_to(ROOT).as_posix()}")


def neutralize_sched_assist_macro():
    needle = b"OPLUS_FEATURE_SCHED_ASSIST"
    for path in ROOT.rglob("*"):
        if ".git" in path.parts or not path.is_file() or path.is_symlink():
            continue
        if path.suffix not in {".h", ".c", ".S", ".mk"} and path.name != "Makefile":
            continue
        data = path.read_bytes()
        if needle not in data:
            continue
        text = data.decode("utf-8", "replace")
        new = text.replace(
            "#define OPLUS_FEATURE_SCHED_ASSIST",
            "/* vendor absent */ #undef OPLUS_FEATURE_SCHED_ASSIST",
        )
        new = new.replace("-DOPLUS_FEATURE_SCHED_ASSIST", "-UOPLUS_FEATURE_SCHED_ASSIST")
        if new != text:
            path.write_text(new)
            print(f"neutralized {path.relative_to(ROOT).as_posix()}")


def disable_vendor_configs():
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
    makefile = ROOT / "Makefile"
    extra = "\nKBUILD_CFLAGS += -UOPLUS_FEATURE_SCHED_ASSIST\nKBUILD_CPPFLAGS += -UOPLUS_FEATURE_SCHED_ASSIST\n"
    body = makefile.read_text()
    if "-UOPLUS_FEATURE_SCHED_ASSIST" not in body:
        makefile.write_text(body + extra)


def main():
    missing = broken_symlinks()
    print(f"broken symlinks: {len(missing)}")
    for path in missing:
        print(f"  stub {path.relative_to(ROOT).as_posix()}")
        stub_symlink(path)
    ensure_source_targets()
    write_sched_assist_headers()
    neutralize_sched_assist_macro()
    strip_cr()
    disable_vendor_configs()


if __name__ == "__main__":
    main()
