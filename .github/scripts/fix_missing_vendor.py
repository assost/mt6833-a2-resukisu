#!/usr/bin/env python3
"""Replace broken vendor symlinks with empty build stubs and strip Kconfig CRs.

Commenting out source lines drops endif/endmenu that live in the missing
file and makes the parent endmenu unexpected. Empty files keep the parse.
"""
import fnmatch
import os
import re
from pathlib import Path

INCLUDE_RE = re.compile(r'#include\s*[<"]([^>"]+\.h)[>"]')
UPSTREAM_HEADERS = {
    "include/linux/posix_types.h":
        "https://raw.githubusercontent.com/torvalds/linux/v4.19.191/include/linux/posix_types.h",
    "include/asm-generic/posix_types.h":
        "https://raw.githubusercontent.com/torvalds/linux/v4.19.191/include/asm-generic/posix_types.h",
    "arch/arm64/include/asm/posix_types.h":
        "https://raw.githubusercontent.com/torvalds/linux/v4.19.191/arch/arm64/include/asm/posix_types.h",
}

ROOT = Path(".").resolve()


def source_paths(pattern="*"):
    # Reference clones are inputs, not part of the kernel being repaired.
    excluded = {".git", ".build-deps"}
    for directory, directories, files in os.walk(ROOT, followlinks=False):
        directories[:] = [name for name in directories if name not in excluded]
        for name in directories + files:
            if name not in excluded and fnmatch.fnmatch(name, pattern):
                yield Path(directory) / name


def broken_symlinks():
    found = []
    for path in source_paths():
        if path.is_symlink() and not path.exists():
            found.append(path)
    return found


def stub_symlink(path: Path):
    name = path.name
    path.unlink()
    if name.endswith((".c", ".h", ".S")):
        path.write_text(f"/* {STUB_MARK} */\n")
        return
    path.mkdir()
    (path / "Makefile").write_text("\n")
    (path / "Kconfig").write_text(f"# {STUB_MARK}\n")


def ensure_source_targets():
    for kconfig in source_paths("Kconfig*"):
        if not kconfig.is_file() or kconfig.is_symlink():
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
            target.write_text(f"# {STUB_MARK}\n")
            print(f"stub source {quoted}")


def strip_cr():
    for path in source_paths("Kconfig*"):
        if not path.is_file() or path.is_symlink():
            continue
        data = path.read_bytes()
        if b"\r" not in data:
            continue
        path.write_bytes(data.replace(b"\r\n", b"\n").replace(b"\r", b"\n"))


def drop_unbalanced_ends():
    starters = {"menu": "endmenu", "if": "endif", "choice": "endchoice"}
    enders = {v: k for k, v in starters.items()}
    for path in source_paths("Kconfig*"):
        if not path.is_file() or path.is_symlink():
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


STUB_MARK = "stub: vendor source is not in this kernel drop"
BASELINE_SUPPRESS = (
    "OPLUS_FEATURE_PHOENIX",
    "OPLUS_FEATURE_SCHED_ASSIST",
)
# These wrap large amounts of in-tree code. Undefining them to skip one
# missing vendor include drops the rest of that code too.
BROAD_MACROS = {
    "OPLUS_BUG_STABILITY",
    "OPLUS_BUG_COMPATIBILITY",
    "OPLUS_BUG_DEBUG",
    "OPLUS_BUG_UPDATABILITY",
    "OPLUS_ARCH_INJECT",
    "OPLUS_ARCH_EXTENDS",
    "OPLUS_FEATURE_PLATFORM",
    "OPLUS_FEATURE_PLATFORM_MTK",
}
VENDOR_PATH_BITS = (
    "oplus",
    "sched_assist",
    "klockopt",
    "healthinfo",
    "iomonitor",
    "phoenix",
    "jankinfo",
    "memleak",
    "keventupload",
)
SECURE_IFEQS = (
    "OPLUS_FEATURE_SECURE_GUARD",
    "OPLUS_FEATURE_SECURE_ROOTGUARD",
    "OPLUS_FEATURE_SECURE_MOUNTGUARD",
    "OPLUS_FEATURE_SECURE_EXECGUARD",
    "OPLUS_FEATURE_SECURE_KEVENTUPLOAD",
)
COND_RE = re.compile(r"^[ \t]*#[ \t]*(ifdef|ifndef|if|elif|else|endif)\b(.*)$")
INCLUDE_LINE = re.compile(r"^[ \t]*#[ \t]*include\s*([<\"])([^>\"]+)[>\"].*$")
OPLUS_DEFINED = re.compile(r"defined\s*\(\s*(OPLUS_[A-Z0-9_]+)\s*\)")
FOREACH_PLAIN = "$(foreach myfeature,$(ALLOWED_MCROS),"
FOREACH_FILTERED = re.compile(
    r"\$\(foreach myfeature,\$\(filter-out .*?,\$\(ALLOWED_MCROS\)\),"
)

SCHED_ASSIST_HEADERS = (
    "sched_assist_mutex.h",
    "sched_assist_status.h",
    "sched_assist_common.h",
    "sched_assist_slide.h",
    "sched_assist_locking.h",
    "sched_assist_rwsem.h",
)


def write_sched_assist_headers():
    directory = ROOT / "include/linux/sched_assist"
    if not directory.is_dir():
        return
    for name in SCHED_ASSIST_HEADERS:
        path = directory / name
        if not path.exists():
            path.write_text(f"/* {STUB_MARK} */\n")
            print(f"header {path.relative_to(ROOT).as_posix()}")


def restore_standard_headers():
    import urllib.request
    for rel, url in UPSTREAM_HEADERS.items():
        dest = ROOT / rel
        if dest.exists() and dest.stat().st_size > 200:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(url, dest)
        print(f"restored {rel}")


def create_missing_headers():
    created = 0
    for path in list(source_paths()):
        if not path.is_file() or path.is_symlink():
            continue
        if path.suffix not in {".h", ".c", ".S"}:
            continue
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        for name in INCLUDE_RE.findall(text):
            if ".." in name or not (name.startswith("linux/") or name.startswith("soc/")):
                continue
            dest = ROOT / "include" / name
            uapi = ROOT / "include" / "uapi" / name
            if dest.exists() or dest.is_symlink() or uapi.exists():
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text("/* stub: header is not in this kernel drop */\n")
            created += 1
            print(f"created {dest.relative_to(ROOT).as_posix()}")
    print(f"created headers: {created}")


def neutralize_sched_assist_macro():
    needle = b"OPLUS_FEATURE_SCHED_ASSIST"
    for path in source_paths():
        if not path.is_file() or path.is_symlink():
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


def allow_vdso_text_relocs():
    path = ROOT / "arch/arm64/kernel/vdso/Makefile"
    text = path.read_text()
    old = "--build-id -n -T"
    new = "--build-id -n -z notext -T"
    if new in text:
        return
    if old not in text:
        raise SystemExit("vdso linker flags not found")
    path.write_text(text.replace(old, new, 1))
    print("vdso: allow lld text relocations")


def _push_condition(stack, kind, rest):
    if kind == "ifdef":
        name = rest.strip().split()[0] if rest.strip() else ""
        stack.append({name} if name.startswith("OPLUS_") else set())
    elif kind == "ifndef":
        stack.append(set())
    elif kind == "if":
        stack.append(set(OPLUS_DEFINED.findall(rest)))
    elif kind == "elif":
        if stack:
            stack.pop()
        stack.append(set(OPLUS_DEFINED.findall(rest)))
    elif kind == "else":
        if stack:
            stack[-1] = set()
    elif kind == "endif" and stack:
        stack.pop()


def _generated_include(spec):
    return (
        spec.startswith("generated/")
        or "/generated/" in spec
        or spec.endswith("autoconf.h")
        or spec.endswith("compile.h")
    )


def _include_candidates(src, spec, quote):
    candidates = []
    if quote == '"':
        candidates.append(src.parent / spec)
    for base in (
        "include",
        "arch/arm64/include",
        "arch/arm64/include/uapi",
        "include/uapi",
        "drivers/misc/mediatek/include",
    ):
        candidates.append(ROOT / base / spec)
    return candidates


def _under_marked_stub(path):
    current = path if path.is_dir() else path.parent
    root = ROOT.resolve()
    while True:
        try:
            current.resolve().relative_to(root)
        except (OSError, ValueError):
            return False
        if current.resolve() == root:
            return False
        kconfig = current / "Kconfig"
        try:
            if kconfig.is_file() and kconfig.stat().st_size < 200:
                if STUB_MARK in kconfig.read_text(errors="replace"):
                    return True
        except OSError:
            return False
        parent = current.parent
        if parent == current:
            return False
        current = parent


def _is_stub_file(path):
    try:
        if path.is_file() and path.stat().st_size < 200:
            return STUB_MARK in path.read_text(errors="replace")
    except OSError:
        return False
    return False


def _vendor_missing_include(src, spec, quote):
    if _generated_include(spec):
        return False
    candidates = _include_candidates(src, spec, quote)
    hit = next((cand for cand in candidates if cand.is_file()), None)
    if hit is not None:
        return _is_stub_file(hit) or _under_marked_stub(hit)
    if any(_under_marked_stub(cand) for cand in candidates):
        return True
    lowered = spec.lower()
    return any(bit in lowered for bit in VENDOR_PATH_BITS)


def _innermost_feature(stack):
    for frame in reversed(stack):
        specific = {name for name in frame if name not in BROAD_MACROS}
        if specific:
            return specific
    return set()


def find_vendor_guard_macros():
    found = set()
    reported = 0
    # This phase only reads files. Drop cached classifications before later
    # phases create headers; quoted includes depend on the source directory.
    include_cache = {}
    for path in source_paths():
        if not path.is_file() or path.is_symlink():
            continue
        if path.suffix not in {".h", ".c", ".S"}:
            continue
        try:
            text = path.read_text(errors="replace")
        except OSError:
            continue
        stack = []
        for line in text.splitlines():
            cond = COND_RE.match(line)
            if cond:
                _push_condition(stack, cond.group(1), cond.group(2))
                continue
            include = INCLUDE_LINE.match(line)
            if not include:
                continue
            quote, spec = include.group(1), include.group(2)
            key = (path.parent if quote == '"' else None, spec, quote)
            if key not in include_cache:
                include_cache[key] = _vendor_missing_include(path, spec, quote)
            if not include_cache[key]:
                continue
            macros = _innermost_feature(stack)
            if macros:
                found.update(macros)
                continue
            if reported < 40:
                print(f"vendor include kept: {path.relative_to(ROOT).as_posix()} -> {spec}")
                reported += 1
    return found


def keep_workqueue_ux_flag():
    """Keep callers working when the vendor scheduling extension is absent."""
    path = ROOT / "include/linux/workqueue.h"
    if not path.is_file():
        return
    text = path.read_text()
    old = "#ifdef OPLUS_FEATURE_SCHED_ASSIST\n\tWQ_UX\t= 1 << 15,\n#endif\n"
    new = (
        "#ifdef OPLUS_FEATURE_SCHED_ASSIST\n"
        "\tWQ_UX\t= 1 << 15,\n"
        "#else\n"
        "\tWQ_UX\t= 0,\n"
        "#endif\n"
    )
    if new in text:
        return
    if old not in text:
        raise SystemExit("workqueue WQ_UX guard missing")
    path.write_text(text.replace(old, new, 1))
    print("workqueue: WQ_UX is zero without sched_assist")


def apply_macro_suppression(macros):
    macros = set(macros) | set(BASELINE_SUPPRESS)
    names = " ".join(sorted(macros))
    env = ROOT / "OplusKernelEnvConfig.mk"
    if env.is_file():
        text = env.read_text()
        replacement = f"$(foreach myfeature,$(filter-out {names},$(ALLOWED_MCROS)),"
        if FOREACH_PLAIN in text:
            text = text.replace(FOREACH_PLAIN, replacement, 1)
        else:
            updated, count = FOREACH_FILTERED.subn(replacement, text, count=1)
            if count != 1:
                raise SystemExit("ALLOWED_MCROS foreach not found")
            text = updated
        for name in SECURE_IFEQS:
            text = text.replace(
                f"ifeq ($({name}),yes)",
                f"ifeq ($({name}),no)",
            )
        env.write_text(text)
    else:
        print("OplusKernelEnvConfig.mk missing")
    makefile = ROOT / "Makefile"
    body = makefile.read_text()
    if not body.endswith("\n"):
        body += "\n"
    extra = []
    for name in sorted(macros):
        for var in ("KBUILD_CFLAGS", "KBUILD_CPPFLAGS", "CFLAGS_KERNEL", "CFLAGS_MODULE"):
            line = f"{var} += -U{name}\n"
            if line not in body:
                extra.append(line)
    if extra:
        makefile.write_text(body + "".join(extra))
    defconfig = ROOT / "arch/arm64/configs/k6833v1_64_k419_defconfig"
    if defconfig.is_file():
        config = defconfig.read_text()
        for name in sorted(macros):
            symbol = "CONFIG_" + name
            config = re.sub(
                rf"^{re.escape(symbol)}=[ym]$",
                f"# {symbol} is not set",
                config,
                flags=re.M,
            )
        defconfig.write_text(config)
    print(f"suppressed vendor macros: {len(macros)}")
    for name in sorted(macros):
        print(f"  undef {name}")


def keep_walt_without_sched_assist():
    """WALT demand fields were nested under the missing sched_assist macro."""
    sched_user = ROOT / "include/linux/sched.h"
    if sched_user.is_file():
        text = sched_user.read_text()
        pairs = (
            (
                "#if defined(OPLUS_FEATURE_SCHED_ASSIST) && defined(CONFIG_SCHED_WALT)\n#define RAVG_HIST_SIZE_MAX 5\n",
                "#ifdef CONFIG_SCHED_WALT\n#define RAVG_HIST_SIZE_MAX 5\n",
            ),
            (
                "#if defined(OPLUS_FEATURE_SCHED_ASSIST) && defined(CONFIG_SCHED_WALT)\n\tstruct ravg ravg;\n",
                "#ifdef CONFIG_SCHED_WALT\n\tstruct ravg ravg;\n",
            ),
            (
                "#if defined(OPLUS_FEATURE_SCHED_ASSIST) && defined(CONFIG_SCHED_WALT)\nenum task_event {\n",
                "#ifdef CONFIG_SCHED_WALT\nenum task_event {\n",
            ),
        )
        for old, new in pairs:
            if new in text:
                continue
            if old not in text:
                raise SystemExit("walt ravg guard missing in include/linux/sched.h")
            text = text.replace(old, new, 1)
        sched_user.write_text(text)
    sched = ROOT / "kernel/sched/sched.h"
    if not sched.is_file():
        return
    text = sched.read_text()
    window = (
        "#if defined(OPLUS_FEATURE_SCHED_ASSIST) && defined(CONFIG_SCHED_WALT)\n"
        "\tu64 window_start;\n"
    )
    window_new = "#ifdef CONFIG_SCHED_WALT\n\tu64 window_start;\n"
    if window_new not in text:
        if window not in text:
            raise SystemExit("rq window_start guard missing")
        text = text.replace(window, window_new, 1)
    old = (
        "#if defined(OPLUS_FEATURE_SCHED_ASSIST) && defined(CONFIG_SCHED_WALT)\n"
        "extern unsigned int sysctl_sched_use_walt_cpu_util;\n"
    )
    new = "#ifdef CONFIG_SCHED_WALT\nextern unsigned int sysctl_sched_use_walt_cpu_util;\n"
    if new not in text:
        if old not in text:
            raise SystemExit("walt externs missing in kernel/sched/sched.h")
        text = text.replace(old, new, 1)
    marker = "#endif /* __KERNEL_SCHED_H__ */\n"
    stubs = (
        "#ifndef OPLUS_FEATURE_SCHED_ASSIST\n"
        "#define SA_SLIDE 0\n"
        "#define SA_INPUT 0\n"
        "#define SA_LAUNCHER_SI 0\n"
        "#define SA_ANIM 0\n"
        "static inline void sf_task_util_record(struct task_struct *p) { }\n"
        "static inline int test_task_ux(struct task_struct *p) { return 0; }\n"
        "static inline int sched_assist_scene(int scene) { return 0; }\n"
        "static inline int is_heavy_ux_task(struct task_struct *p) { return 0; }\n"
        "static const int sysctl_sched_assist_enabled;\n"
        "#endif\n\n"
    )
    if "static inline void sf_task_util_record" not in text:
        if marker not in text:
            raise SystemExit("sched.h footer missing")
        text = text.replace(marker, stubs + marker, 1)
    sched.write_text(text)
    trace = ROOT / "include/trace/events/sched.h"
    if trace.is_file():
        body = trace.read_text()
        old_trace = (
            "#if defined(OPLUS_FEATURE_SCHED_ASSIST) && defined(CONFIG_SCHED_WALT)\n"
            "extern unsigned int walt_ravg_window;\n"
        )
        new_trace = "#ifdef CONFIG_SCHED_WALT\nextern unsigned int walt_ravg_window;\n"
        if new_trace not in body:
            if old_trace not in body:
                raise SystemExit("walt trace guard missing")
            trace.write_text(body.replace(old_trace, new_trace, 1))
    print("walt kept without sched_assist")


def write_oplus_project_header():
    path = ROOT / "include/soc/oplus/system/oplus_project.h"
    if path.is_file() and path.stat().st_size > 200 and STUB_MARK not in path.read_text(errors="replace"):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""/* {STUB_MARK} */
#ifndef _OPLUS_PROJECT_STUB_H_
#define _OPLUS_PROJECT_STUB_H_
#include <linux/types.h>
/* Engineering IDs from the official MT6833 A2 module source:
 * vendor/oplus/kernel/system/include/oplus_project_data_ocdt.h,
 * commit dd93a63de24dec560639b88d8328d4be7100a60d.
 */
enum {{
	RELEASE_VERSION = 0x00,
	AGING = 0x01,
	PREVERSION = 0x04,
	HIGH_TEMP_AGING = 0x0B,
	FACTORY = 0x0C,
}};
static inline unsigned int get_project(void) {{ return 0; }}
static inline unsigned int is_project(int project) {{ return 0; }}
static inline unsigned int get_PCB_Version(void) {{ return 0; }}
static inline unsigned int get_Operator_Version(void) {{ return 0; }}
static inline unsigned int get_Modem_Version(void) {{ return 0; }}
static inline int get_eng_version(void) {{ return 0; }}
static inline bool oplus_daily_build(void) {{ return false; }}
#endif
""",
        encoding="utf-8",
    )
    print("stub include/soc/oplus/system/oplus_project.h")



def guard_panel_project_fallbacks():
    directory = ROOT / "drivers/gpu/drm/panel"
    fallback = b"extern unsigned int __attribute((weak)) is_project(int project)  { return 0; }"
    pattern = re.compile(rb"(?m)^" + re.escape(fallback) + rb"(?=\r?$)")
    for path in sorted(directory.glob("*.c")):
        if path.is_symlink() or not path.is_file():
            continue
        original = path.read_bytes()
        changed = original
        for match in reversed(list(pattern.finditer(original))):
            newline = b"\r\n" if original[match.end():match.end() + 2] == b"\r\n" else b"\n"
            guard = b"#ifndef _OPLUS_PROJECT_STUB_H_" + newline
            if original[max(0, match.start() - len(guard)):match.start()] == guard:
                continue
            # The generated header already supplies the same zero fallback.
            replacement = guard + fallback + newline + b"#endif"
            changed = changed[:match.start()] + replacement + changed[match.end():]
        if changed != original:
            path.write_bytes(changed)
            print(f"panel: guarded zero project fallback in {path.relative_to(ROOT).as_posix()}")


def write_oppo_project_forward_header():
    path = ROOT / "include/soc/oplus/system/oppo_project.h"
    if path.is_file() and STUB_MARK not in path.read_text(errors="replace"):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"/* {STUB_MARK} */\n"
        "#ifndef _OPPO_PROJECT_FORWARD_H_\n"
        "#define _OPPO_PROJECT_FORWARD_H_\n"
        "#include <soc/oplus/system/oplus_project.h>\n"
        "#endif\n",
        encoding="utf-8",
    )
    print("forward include/soc/oplus/system/oppo_project.h")


def fix_drm_device_prototype():
    path = ROOT / "drivers/gpu/drm/mediatek/mtk_debug.c"
    if not path.is_file():
        return
    text = path.read_text()
    old = "struct drm_device *get_drm_device(){"
    new = "struct drm_device *get_drm_device(void){"
    if new in text:
        return
    if old not in text:
        raise SystemExit("get_drm_device definition missing")
    path.write_text(text.replace(old, new, 1))
    print("drm: get_drm_device has a void prototype")


def fix_sia81xx_prototypes():
    path = ROOT / "sound/soc/codecs/audio/sia81xx/sia81xx.c"
    if not path.is_file():
        return
    text = path.read_text()
    changed = text
    for name in ("sia81xx_start", "sia81xx_stop"):
        old = f"void {name}(){{"
        new = f"void {name}(void){{"
        if new in changed:
            continue
        if changed.count(old) != 1:
            raise SystemExit(f"{name} definition missing or ambiguous")
        changed = changed.replace(old, new, 1)
    if changed != text:
        path.write_text(changed)
        print("sia81xx: start/stop have void prototypes")


def mark_esd_worker_unused_locals():
    path = ROOT / "drivers/gpu/drm/mediatek/mtk_disp_recovery.c"
    if not path.is_file():
        return
    text = path.read_text()
    signature = "static int mtk_drm_esd_check_worker_kthread(void *data)\n{"
    start = text.find(signature)
    if start < 0:
        raise SystemExit("ESD worker definition missing")
    end = text.find("sched_setscheduler(current, SCHED_RR, &param);", start)
    if end < 0:
        raise SystemExit("ESD worker declaration boundary missing")
    declarations = text[start:end]
    for old, new in (
        ("struct mtk_ddp_comp *output_comp;", "struct mtk_ddp_comp *output_comp __maybe_unused;"),
        ("unsigned int prj_id = get_project();", "unsigned int prj_id __maybe_unused = get_project();"),
    ):
        if new in declarations:
            continue
        if declarations.count(old) != 1:
            raise SystemExit("ESD worker local declaration missing or ambiguous")
        declarations = declarations.replace(old, new, 1)
    changed = text[:start] + declarations + text[end:]
    if changed != text:
        path.write_text(changed)
        print("ESD worker: marked unused locals without dropping initialization")



def fix_dpmaif_dump_pointers():
    path = ROOT / "drivers/misc/mediatek/eccci/hif/ccci_hif_dpmaif.c"
    if not path.is_file():
        return
    original = path.read_bytes()
    newline = b"\r\n" if b"\r\n" in original else b"\n"
    signature = b"static void dump_drb_queue_data(unsigned int qno)" + newline + b"{"
    start = original.find(signature)
    end = original.find(newline + b"}" + newline, start)
    if start < 0 or end < 0 or original.count(signature) != 1:
        raise SystemExit("DPMAIF dump function missing or ambiguous")
    end += len(newline) * 2 + 1
    function = original[start:end]
    for old, new, count in (
        (b'DPMA_DRB_DATA_INFO("%08X(%04d):', b'DPMA_DRB_DATA_INFO("%p(%04d):', 2),
        (b"(u32)data_64ptr", b"(void *)data_64ptr", 1),
        (b"(u32)data_8ptr", b"(void *)data_8ptr", 1),
    ):
        if function.count(new) == count and old not in function:
            continue
        if function.count(old) != count or new in function:
            raise SystemExit("DPMAIF pointer log anchor missing or ambiguous")
        function = function.replace(old, new)
    changed = original[:start] + function + original[end:]
    if changed != original:
        path.write_bytes(changed)
        print("DPMAIF: dump pointer prefixes use %p without truncation")


def keep_swappiness_limit():
    path = ROOT / "kernel/sysctl.c"
    if not path.is_file():
        return
    text = path.read_text()
    old = (
        "static int one_hundred = 100;\n"
        "#if defined(OPLUS_FEATURE_ZRAM_OPT) && defined(CONFIG_OPLUS_ZRAM_OPT)\n"
        "extern int direct_vm_swappiness;\n"
        "static int two_hundred = 200;\n"
        "#endif /*OPLUS_FEATURE_ZRAM_OPT*/\n"
    )
    new = (
        "static int one_hundred = 100;\n"
        "static int two_hundred = 200;\n"
        "#if defined(OPLUS_FEATURE_ZRAM_OPT) && defined(CONFIG_OPLUS_ZRAM_OPT)\n"
        "extern int direct_vm_swappiness;\n"
        "#endif /*OPLUS_FEATURE_ZRAM_OPT*/\n"
    )
    if new in text:
        return
    if old not in text:
        raise SystemExit("swappiness limit anchor missing")
    path.write_text(text.replace(old, new, 1))
    print("kept two_hundred")


def fix_buddyinfo_index():
    path = ROOT / "kernel/trace/trace_mmstat.c"
    if not path.is_file():
        return
    text = path.read_text()
    old = "\t\t\t\t\tzone->free_area[flc][order].nr_free;\n"
    new = (
        "#if defined(OPLUS_FEATURE_MULTI_FREEAREA) && defined(CONFIG_PHYSICAL_ANTI_FRAGMENTATION)\n"
        "\t\t\t\t\tzone->free_area[flc][order].nr_free;\n"
        "#else\n"
        "\t\t\t\t\tzone->free_area[order].nr_free;\n"
        "#endif\n"
    )
    if "zone->free_area[order].nr_free;" in text:
        return
    if old not in text:
        raise SystemExit("buddyinfo free_area index missing")
    path.write_text(text.replace(old, new, 1))
    print("buddyinfo uses one free_area index")


def declare_ksu_hooks():
    hooks = (
        (
            "fs/open.c",
            "ksu_handle_faccessat(",
            "int ksu_handle_faccessat(int *dfd, const char __user **filename_user, int *mode, int *flags);\n",
        ),
        (
            "fs/stat.c",
            "ksu_handle_stat(",
            "int ksu_handle_stat(int *dfd, const char __user **filename_user, int *flags);\n",
        ),
        (
            "fs/read_write.c",
            "ksu_handle_sys_read(",
            "int ksu_handle_sys_read(unsigned int fd, char __user **buf_ptr, size_t *count_ptr);\n",
        ),
        (
            "fs/exec.c",
            "ksu_handle_execveat(",
            "int ksu_handle_execveat(int *fd, struct filename **filename_ptr, void *argv, void *envp, int *flags);\n"
            "int ksu_handle_post_execveat(int *fd, struct filename **filename_ptr, void *argv, void *envp, int *flags, int *retval);\n",
        ),
        (
            "kernel/reboot.c",
            "ksu_handle_sys_reboot(",
            "int ksu_handle_sys_reboot(int magic1, int magic2, unsigned int cmd, void __user **arg);\n",
        ),
        (
            "kernel/sys.c",
            "ksu_handle_setresuid(",
            "int ksu_handle_setresuid(uid_t ruid, uid_t euid, uid_t suid);\n",
        ),
        (
            "drivers/input/input.c",
            "ksu_handle_input_handle_event(",
            "int ksu_handle_input_handle_event(unsigned int *type, unsigned int *code, int *value);\n",
        ),
    )
    for rel, call, prototype in hooks:
        path = ROOT / rel
        if not path.is_file():
            continue
        text = path.read_text()
        if call not in text or prototype in text:
            continue
        lines = text.splitlines(keepends=True)
        insert_at = 0
        depth = 0
        for index, line in enumerate(lines[:240]):
            stripped = line.strip()
            if stripped.startswith("#if"):
                depth += 1
            elif stripped.startswith("#endif"):
                depth = max(0, depth - 1)
            elif depth == 0 and stripped.startswith("#include"):
                insert_at = index + 1
        lines.insert(insert_at, prototype)
        path.write_text("".join(lines))
        print(f"declared {rel}")


def write_healthinfo_ion_header():
    path = ROOT / "include/linux/healthinfo/ion.h"
    if path.is_file() and STUB_MARK not in path.read_text(errors="replace"):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""/* {STUB_MARK} */
#ifndef _HEALTHINFO_ION_STUB_H_
#define _HEALTHINFO_ION_STUB_H_
#include <linux/types.h>
static inline unsigned long ion_total(void) {{ return 0; }}
#endif
""",
        encoding="utf-8",
    )
    print("stub include/linux/healthinfo/ion.h")


def write_oppo_process_header():
    path = ROOT / "include/soc/oplus/system/oppo_process.h"
    if path.is_file() and STUB_MARK not in path.read_text(errors="replace"):
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"""/* {STUB_MARK} */
#ifndef _OPPO_PROCESS_STUB_H_
#define _OPPO_PROCESS_STUB_H_
struct pid;
struct task_struct;
static inline bool oppo_is_android_core_group(struct pid *pgrp) {{ return false; }}
static inline bool is_critial_process(struct task_struct *tsk) {{ return false; }}
static inline bool is_key_process(struct task_struct *tsk) {{ return false; }}
static inline void oplus_boost_kill_signal(int sig, struct task_struct *caller, struct task_struct *target) {{}}
#endif
""",
        encoding="utf-8",
    )
    print("stub include/soc/oplus/system/oppo_process.h")


def patch_known_vendor_callers():
    """Skip unpublished scheduler fields and keep the hybridswap proc node compiling."""
    core = ROOT / "kernel/sched/core.c"
    if core.is_file():
        text = core.read_text()
        turbo_fn = (
            "extern int sysctl_set_ux_uclamp_enable;\n"
            "unsigned long uclamp_eff_value(struct task_struct *p, enum uclamp_id clamp_id)\n"
            "{\n"
            "\tstruct uclamp_se uc_eff;\n"
            "\tunsigned int uc_value;\n"
            "\tif (p->ux_state & SA_TYPE_TURBO && clamp_id == UCLAMP_MIN && sysctl_set_ux_uclamp_enable) {\n"
            "\t\tuc_value = ux_uclamp_value;\n"
            "\t\tif (p->uclamp[clamp_id].active) {\n"
            "\t\t\tif (p->uclamp[clamp_id].value > uc_value)\n"
            "\t\t\t\tuc_value = p->uclamp[clamp_id].value;\n"
            "\t\t } else {\n"
            "\t\t\tuc_eff =  uclamp_eff_get(p, clamp_id);\n"
            "\t\t\tif (uc_eff.value > uc_value)\n"
            "\t\t\t\tuc_value = uc_eff.value;\n"
            "\t\t}\n"
            "\t\treturn (unsigned long)uc_value;\n"
            "\t}\n"
        )
        turbo_fn_new = (
            "#ifdef OPLUS_FEATURE_SCHED_ASSIST\n"
            "extern int sysctl_set_ux_uclamp_enable;\n"
            "#endif\n"
            "unsigned long uclamp_eff_value(struct task_struct *p, enum uclamp_id clamp_id)\n"
            "{\n"
            "\tstruct uclamp_se uc_eff;\n"
            "\tunsigned int uc_value;\n"
            "#ifdef OPLUS_FEATURE_SCHED_ASSIST\n"
            "\tif (p->ux_state & SA_TYPE_TURBO && clamp_id == UCLAMP_MIN && sysctl_set_ux_uclamp_enable) {\n"
            "\t\tuc_value = ux_uclamp_value;\n"
            "\t\tif (p->uclamp[clamp_id].active) {\n"
            "\t\t\tif (p->uclamp[clamp_id].value > uc_value)\n"
            "\t\t\t\tuc_value = p->uclamp[clamp_id].value;\n"
            "\t\t } else {\n"
            "\t\t\tuc_eff =  uclamp_eff_get(p, clamp_id);\n"
            "\t\t\tif (uc_eff.value > uc_value)\n"
            "\t\t\t\tuc_value = uc_eff.value;\n"
            "\t\t}\n"
            "\t\treturn (unsigned long)uc_value;\n"
            "\t}\n"
            "#endif\n"
        )
        turbo_rq = (
            "\ttmp_value = uc_se->value;\n"
            "\tif (p->ux_state & SA_TYPE_TURBO && clamp_id == UCLAMP_MIN && sysctl_set_ux_uclamp_enable)\n"
            "\t\ttmp_value = ux_uclamp_value;\n"
        )
        turbo_rq_new = (
            "\ttmp_value = uc_se->value;\n"
            "#ifdef OPLUS_FEATURE_SCHED_ASSIST\n"
            "\tif (p->ux_state & SA_TYPE_TURBO && clamp_id == UCLAMP_MIN && sysctl_set_ux_uclamp_enable)\n"
            "\t\ttmp_value = ux_uclamp_value;\n"
            "#endif\n"
        )
        if turbo_fn_new in text and turbo_rq_new in text:
            pass
        else:
            if turbo_fn not in text or turbo_rq not in text:
                raise SystemExit("ux uclamp call sites missing in kernel/sched/core.c")
            text = text.replace(turbo_fn, turbo_fn_new, 1).replace(turbo_rq, turbo_rq_new, 1)
            print("guarded ux uclamp uses")
        core.write_text(text)
    vmscan = ROOT / "mm/vmscan.c"
    if vmscan.is_file():
        text = vmscan.read_text()
        decl = (
            "#if defined(OPLUS_FEATURE_ZRAM_OPT) && defined(CONFIG_OPLUS_ZRAM_OPT)\n"
            "/*\n"
            " * Direct reclaim swappiness, exptct 0 - 60. Higher means more swappy and slower.\n"
            " */\n"
            "int direct_vm_swappiness = 60;\n"
            "#endif /*OPLUS_FEATURE_ZRAM_OPT*/\n"
        )
        bare = (
            "/*\n"
            " * Direct reclaim swappiness, exptct 0 - 60. Higher means more swappy and slower.\n"
            " */\n"
            "int direct_vm_swappiness = 60;\n"
        )
        if decl in text:
            text = text.replace(decl, bare, 1)
            print("kept direct_vm_swappiness")
        elif "int direct_vm_swappiness = 60;" not in text:
            raise SystemExit("direct_vm_swappiness declaration missing")
        anchor = "#include <linux/debugfs.h>\n"
        if "#include <linux/proc_fs.h>" not in text:
            if anchor not in text:
                raise SystemExit("debugfs include missing in mm/vmscan.c")
            text = text.replace(anchor, anchor + "#include <linux/proc_fs.h>\n", 1)
            print("included proc_fs.h")
        vmscan.write_text(text)
    slub = ROOT / "mm/slub.c"
    if slub.is_file():
        text = slub.read_text()
        old = (
            "#else\n"
            "static inline void setup_object_debug(struct kmem_cache *s,\n"
            "\t\t\tstruct page *page, void *object) {}\n"
            "\n"
            "static inline int alloc_debug_processing(struct kmem_cache *s,\n"
        )
        new = (
            "#else\n"
            "static inline void setup_object_debug(struct kmem_cache *s,\n"
            "\t\t\tstruct page *page, void *object) {}\n"
            "static inline void setup_page_debug(struct kmem_cache *s,\n"
            "\t\t\tvoid *addr, int order) {}\n"
            "\n"
            "static inline int alloc_debug_processing(struct kmem_cache *s,\n"
        )
        if new not in text:
            if old not in text:
                raise SystemExit("slub debug fallback missing")
            text = text.replace(old, new, 1)
            print("stubbed setup_page_debug")
        slub.write_text(text)


def main():
    missing = broken_symlinks()
    print(f"broken symlinks: {len(missing)}")
    for path in missing:
        print(f"  stub {path.relative_to(ROOT).as_posix()}")
        stub_symlink(path)
    ensure_source_targets()
    macros = find_vendor_guard_macros()
    write_sched_assist_headers()
    version = ROOT / "include/linux/version.h"
    if not version.exists():
        version.write_text("#include <generated/uapi/linux/version.h>\n")
        print("restored include/linux/version.h")
    neutralize_sched_assist_macro()
    allow_vdso_text_relocs()
    strip_cr()
    disable_vendor_configs()
    apply_macro_suppression(macros)
    patch_known_vendor_callers()
    keep_walt_without_sched_assist()
    keep_workqueue_ux_flag()
    write_oplus_project_header()
    guard_panel_project_fallbacks()
    write_oppo_project_forward_header()
    fix_drm_device_prototype()
    fix_sia81xx_prototypes()
    mark_esd_worker_unused_locals()
    fix_dpmaif_dump_pointers()
    write_healthinfo_ion_header()
    write_oppo_process_header()
    keep_swappiness_limit()
    fix_buddyinfo_index()
    declare_ksu_hooks()


if __name__ == "__main__":
    main()
