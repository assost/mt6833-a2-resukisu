#!/usr/bin/env python3
"""Check signed ELF64 module imports against the exact kernel/module symvers."""
import argparse
import base64
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import tempfile
import time


NAMES = ("connfem", "wmt_drv", "bt_drv_connac1x", "gps_drv",
         "fmradio_drv_mt6631_6635", "wmt_chrdev_wifi", "wlan_drv_gen4m")
MAGIC = b"~Module signature appended~\n"


def write_json(path, data):
    payload = (json.dumps(data, indent=2) + "\n").encode()
    if path.exists():
        shutil.copy2(path, path.with_name(path.name + f".bak-{time.time_ns()}"))
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as stream:
        stream.write(payload)
        temporary = stream.name
    os.replace(temporary, path)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sections(data):
    if len(data) < 64 or data[:6] != b"\x7fELF\x02\x01" or struct.unpack_from("<H", data, 18)[0] != 183:
        raise ValueError("expected little-endian AArch64 ELF64")
    offset = struct.unpack_from("<Q", data, 40)[0]
    size, count, names_index = struct.unpack_from("<HHH", data, 58)
    if size != 64 or not count or names_index >= count or offset + size * count > len(data):
        raise ValueError("invalid ELF section table")
    headers = [struct.unpack_from("<IIQQQQIIQQ", data, offset + i * size) for i in range(count)]
    def contents(header):
        start, length = header[4:6]
        if header[1] != 8 and start + length > len(data):
            raise ValueError("ELF section outside file")
        return data[start:start + length] if header[1] != 8 else b""
    names = contents(headers[names_index])
    return {names[h[0]:].split(b"\0", 1)[0].decode(): contents(h) for h in headers}


def versions(data):
    raw = sections(data).get("__versions", b"")
    if not raw or len(raw) % 64:
        raise ValueError("missing or malformed module symbol versions")
    result = {}
    for start in range(0, len(raw), 64):
        name = raw[start + 8:start + 64].split(b"\0", 1)[0].decode()
        value = struct.unpack_from("<Q", raw, start)[0]
        if not name or name in result:
            raise ValueError("duplicate or empty module version")
        result[name] = value
    if "module_layout" not in result:
        raise ValueError("module_layout version missing")
    return result



def undefined_symbols(data):
    """Read strong undefined symbols even when modpost omitted their CRCs."""
    table = sections(data)
    if struct.unpack_from("<H", data, 16)[0] != 1:
        raise ValueError("expected relocatable module ELF")
    symbols, strings = table.get(".symtab", b""), table.get(".strtab", b"")
    if not symbols or len(symbols) % 24 or not strings:
        raise ValueError("missing or malformed module symbol table")
    required = set()
    for offset in range(0, len(symbols), 24):
        name, info, _, section, _, _ = struct.unpack_from("<IBBHQQ", symbols, offset)
        # Unresolved weak imports may legally resolve to zero in the loader.
        if section != 0 or info >> 4 in (0, 2):
            continue
        end = strings.find(b"\0", name)
        if not name or name >= len(strings) or end < 0:
            raise ValueError("invalid undefined symbol name")
        required.add(strings[name:end].decode())
    return required

def certificate(path):
    pem = path.read_text()
    match = re.search(r"-----BEGIN CERTIFICATE-----\s*(.*?)\s*-----END CERTIFICATE-----", pem, re.S)
    if not match:
        raise ValueError(f"public certificate missing: {path}")
    return base64.b64decode(re.sub(r"\s", "", match[1]), validate=True)


def verify(directory, image, config, cert, factory_cert, mode, openssl="openssl"):
    exports = {}
    for source in (directory / "kernel.symvers", *(directory / (name + ".symvers") for name in NAMES)):
        for line in source.read_text().splitlines():
            fields = line.split()
            if len(fields) < 3:
                raise ValueError(f"malformed symvers line in {source}")
            value = int(fields[0], 16)
            if fields[1] in exports and exports[fields[1]] != value:
                raise ValueError(f"conflicting exported version for {fields[1]}")
            exports[fields[1]] = value
    kernel = gzip.decompress(image.read_bytes())
    config_lines = config.read_text().splitlines()
    failures = []
    release = (directory / "kernel.release").read_text().strip()
    if not release or any(char.isspace() for char in release):
        raise ValueError("invalid kernel release")
    if (mode == "resukisu") != ("CONFIG_KSU=y" in config_lines):
        failures.append("kernel root configuration does not match variant")
    for line in ("CONFIG_MODULE_SIG_FORCE=y", "CONFIG_MODVERSIONS=y", "CONFIG_CFI_CLANG=y", "CONFIG_LTO_CLANG=y"):
        if line not in config_lines:
            failures.append("required configuration absent: " + line)
    for name, path in (("build", cert), ("factory", factory_cert)):
        if certificate(path) not in kernel:
            failures.append(name + " certificate is absent from Image")
    modules = []
    with tempfile.TemporaryDirectory(prefix="verify-connectivity-") as temporary:
        temp = Path(temporary)
        for name in NAMES:
            path = directory / (name + ".ko")
            data = path.read_bytes()
            if not data.endswith(MAGIC) or len(data) < len(MAGIC) + 12:
                raise ValueError(f"{path.name}: signed module required")
            descriptor = len(data) - len(MAGIC) - 12
            _, _, kind, signer, key, length = struct.unpack_from(">5B3xI", data, descriptor)
            start = descriptor - length
            if kind != 2 or signer or key or length == 0 or start < 64:
                raise ValueError(f"{path.name}: invalid PKCS#7 trailer")
            (temp / "signature.der").write_bytes(data[start:descriptor])
            (temp / "unsigned.ko").write_bytes(data[:start])
            command = [openssl, "cms", "-verify", "-binary", "-inform", "DER", "-in", str(temp / "signature.der"),
                       "-content", str(temp / "unsigned.ko"), "-certfile", str(cert), "-CAfile", str(cert),
                       "-purpose", "any", "-no_check_time", "-out", os.devnull]
            result = subprocess.run(command, capture_output=True, text=True)
            imports = versions(data[:start])
            required_symbols = undefined_symbols(data[:start])
            missing_versions = sorted(required_symbols - imports.keys())
            unresolved_symbols = sorted(required_symbols - exports.keys())
            mismatches = [{"symbol": key, "module": f"0x{value:08x}",
                           "provider": f"0x{exports[key]:08x}" if key in exports else None}
                          for key, value in imports.items() if exports.get(key) != value]
            modinfo = [part.decode() for part in sections(data[:start]).get(".modinfo", b"").split(b"\0") if part]
            identity_valid = "name=" + name in modinfo and any(
                item.startswith("vermagic=" + release + " ") for item in modinfo)
            passed = (result.returncode == 0 and not mismatches and identity_valid
                      and not missing_versions and not unresolved_symbols)
            modules.append({"name": name, "sha256": sha(path), "import_count": len(imports),
                            "identity_verified": identity_valid, "signature_verified": result.returncode == 0, "signature_output": result.stderr.strip(),
                            "strong_import_count": len(required_symbols), "missing_versions": missing_versions,
                            "unresolved_symbols": unresolved_symbols,
                            "mismatches": mismatches, "modinfo": modinfo, "passed": passed})
    return {"schema_version": 1, "mode": mode, "passed": not failures and all(m["passed"] for m in modules),
            "kernel_release": release, "kernel_image_sha256": sha(image), "kernel_config_sha256": sha(config),
            "build_certificate_sha256": hashlib.sha256(certificate(cert)).hexdigest(),
            "factory_certificate_sha256": hashlib.sha256(certificate(factory_cert)).hexdigest(),
            "symbol_file_sha256": {p.name: sha(p) for p in sorted(directory.glob("*.symvers"))},
            "errors": failures, "modules": modules, "runtime_verified": False,
            "scope": "Connectivity module set: Wi-Fi/BT/GPS/FM. Other vendor modules, including fpsgo and trace_mmstat, remain unverified."}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--factory-cert", required=True, type=Path)
    parser.add_argument("--mode", choices=("stock", "resukisu"), required=True)
    parser.add_argument("--openssl", default="openssl")
    args = parser.parse_args()
    report = verify(args.directory, args.image, args.config, args.directory / "build-signing-cert.pem",
                    args.factory_cert, args.mode, args.openssl)
    write_json(args.directory / "verification.json", report)
    print(json.dumps({"passed": report["passed"], "errors": report["errors"]}))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
