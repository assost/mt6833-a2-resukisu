#!/usr/bin/env python3
"""Exercise real Kbuild addtree and real sensor proc-ID definitions."""
import importlib.util
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def run(args, cwd, success=True):
    result = subprocess.run(args, cwd=cwd, text=True, capture_output=True)
    if (result.returncode == 0) != success:
        raise AssertionError(result.stdout + result.stderr)
    return result.stdout + result.stderr


def main():
    source = Path(sys.argv[1]).resolve()
    modules = Path(sys.argv[2]).resolve()
    temp = Path(sys.argv[3]).resolve()
    temp.mkdir(parents=True, exist_ok=True)
    compiler = shutil.which("cc")
    assert compiler and shutil.which("make")
    spec = importlib.util.spec_from_file_location("fix", Path(__file__).with_name("fix_missing_vendor.py"))
    fix = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fix)
    with tempfile.TemporaryDirectory(dir=temp) as name:
        root = Path(name)
        out = root / "out"
        out.mkdir()
        (root / "drivers").mkdir()
        (root / "drivers/probe.h").write_text("#define VALUE 42\n")
        (out / "probe.c").write_text('#include <drivers/probe.h>\n_Static_assert(VALUE == 42, "value");\n')
        # Use the exact kernel's transformation rather than reimplementing it.
        kbuild = source / "scripts/Kbuild.include"
        assert kbuild.is_file()
        shutil.copyfile(kbuild, out / "Kbuild.include")
        (out / "probe.mk").write_text(
            "include Kbuild.include\n"
            "srctree := ..\n"
            "probe_flags := $(INPUT)\n"
            "$(info FLAGS=$(call flags,probe_flags))\n"
            "all: ; @:\n")
        for raw, expected, success in (("-I..", "-I../..", False), ("-I../", "-I../", True)):
            output = run(["make", "-f", "probe.mk", f"INPUT={raw}"], out)
            actual = next(line[6:] for line in output.splitlines() if line.startswith("FLAGS=")).strip()
            assert actual == expected, (actual, expected)
            run([compiler, "-Werror", actual, "-fsyntax-only", "probe.c"], out, success)
        print("real Kbuild: old -I.. reproduced missing header; -I../ compiled with O=out")

        rel = Path("drivers/misc/mediatek/sensor/2.0/oplus_sensor_devinfo/sensor_devinfo.c")
        original = (modules / "vendor/oplus/sensor/kernel/oplus_sensor_devinfo/sensor_devinfo.c").read_bytes()
        target = root / rel
        target.parent.mkdir(parents=True)
        target.write_bytes(original)
        fix.ROOT = root
        fix.fix_sensor_proc_id_cast()
        patched = target.read_bytes()
        old = b"#define Ptr2UINT32(p)   (uint32_t)(p)"
        new = b"#define Ptr2UINT32(p)   (uint32_t)(unsigned long)(p)"
        assert patched.replace(new, old) == original
        fix.fix_sensor_proc_id_cast()
        assert target.read_bytes() == patched
        text = patched.decode()
        ids = sorted(set(re.findall(r"UINT2Ptr\(([A-Z][A-Z0-9_]*)\)", text)))
        assert len(ids) == 23, ids
        defines = dict(re.findall(r"^#define\s+(\w+)\s+(\(0x[0-9a-fA-F]+\))", text, re.M))
        macros = "\n".join(line for line in text.splitlines() if line.startswith(("#define UINT2Ptr", "#define Ptr2UINT32")))
        probe = "#include <stdint.h>\n#include <assert.h>\n" + macros + "\n"
        probe += "\n".join(f"#define {ident} {defines[ident]}" for ident in ids)
        probe += "\nuint32_t decode(void *p) { return Ptr2UINT32(p); }\nint main(void) {\n"
        probe += "\n".join(f"assert(decode(UINT2Ptr({ident})) == {ident});" for ident in ids)
        probe += "\nreturn 0; }\n"
        (out / "sensor.c").write_text(probe)
        run([compiler, "-Wall", "-Werror", "sensor.c", "-o", "sensor"], out)
        run([str(out / "sensor")], out)
        (out / "sensor.c").write_text(probe.replace(new.decode(), old.decode()))
        rejected = run([compiler, "-Wall", "-Werror", "-fsyntax-only", "sensor.c"], out, False)
        assert "pointer" in rejected
        print("sensor: all 23 actual proc IDs round-trip; original cast fails; exact scope and idempotence PASS")


if __name__ == "__main__":
    main()
