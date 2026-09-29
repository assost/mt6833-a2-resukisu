#!/usr/bin/env python3
"""Verify factory-critical configuration and record every remaining difference."""
import hashlib
import json
from pathlib import Path
import re
import sys


def parse(path):
    result = {}
    for line in path.read_text().splitlines():
        match = re.fullmatch(r"(CONFIG_[A-Za-z0-9_]+)=(.*)", line)
        if match:
            result[match[1]] = match[2]
        match = re.fullmatch(r"# (CONFIG_[A-Za-z0-9_]+) is not set", line)
        if match:
            result[match[1]] = "n"
    return result


mode = sys.argv[1]
if mode not in {"stock", "resukisu"}:
    raise SystemExit("Expected stock or resukisu")
reference_path = Path(".github/scripts/factory-boot.config")
reference, actual = parse(reference_path), parse(Path("out/.config"))
critical = ["ARM64_4K_PAGES", "ARM64_VA_BITS", "ARM64_PA_BITS", "MODVERSIONS", "LTO_CLANG", "CFI_CLANG",
            "CFI_PERMISSIVE", "HZ", "PREEMPT", "LOCALVERSION", "LOCALVERSION_AUTO", "NR_CPUS",
            "TRANSPARENT_HUGEPAGE", "TRANSPARENT_HUGEPAGE_ALWAYS", "MTK_HIGH_FRAME_RATE", "MTK_MT6382_BDG",
            "PSTORE", "PSTORE_RAM", "PSTORE_CONSOLE", "IKCONFIG", "CLANG_VERSION"]
errors = []
for name in critical:
    key = "CONFIG_" + name
    if key in reference and actual.get(key) != reference[key]:
        errors.append(f"{key}: factory={reference[key]} actual={actual.get(key, 'absent')}")
if mode == "stock" and actual.get("CONFIG_KSU") == "y":
    errors.append("Stock baseline must not enable KSU")
if mode == "resukisu" and actual.get("CONFIG_KSU_SUSFS") != "y":
    errors.append("Rooted build must retain SUSFS")
diff = {name:{"factory":reference.get(name, "absent"), "actual":actual.get(name, "absent")}
        for name in sorted(reference.keys() | actual.keys()) if reference.get(name) != actual.get(name)}
report = {"mode":mode, "factory_boot_sha256":"947c13e9e0d069ba26e5e35da155c0e595f0c399064e5dc3893a7bac90fc5189",
          "reference_config_sha256":hashlib.sha256(reference_path.read_bytes()).hexdigest(),
          "critical_configuration_passed":not errors, "errors":errors,
          "differences":diff, "runtime_verified":False,
          "scope":"Critical config alignment; remaining differences and device boot still require validation"}
Path("out/factory-config-audit.json").write_text(json.dumps(report,indent=2)+"\n")
if errors:
    raise SystemExit("Factory configuration check failed: " + "; ".join(errors))
print(f"Factory configuration critical checks passed; {len(diff)} total differences recorded")
