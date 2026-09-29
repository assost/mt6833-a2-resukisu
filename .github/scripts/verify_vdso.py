#!/usr/bin/env python3
"""Reject vDSOs Android's 64-bit linker cannot load, including embedded copies."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import struct


def parse_elf(data):
    if len(data) < 64 or data[:6] != b"\x7fELF\x02\x01":
        raise ValueError("Not a little-endian ELF64 image")
    if struct.unpack_from("<HH", data, 16) != (3, 183):
        raise ValueError("Expected AArch64 ET_DYN")
    phoff, shoff = struct.unpack_from("<QQ", data, 32)
    phent, phnum, shent, shnum = struct.unpack_from("<HHHH", data, 54)
    if phent != 56 or not 0 < phnum < 32 or shent != 64 or not 0 < shnum < 128:
        raise ValueError("Invalid ELF tables")
    end = max(phoff + phent * phnum, shoff + shent * shnum)
    if end > len(data) or end > 2 * 1024 * 1024:
        raise ValueError("ELF headers exceed bounds")
    loads, dynamic = [], []
    for index in range(phnum):
        kind, flags, offset, vaddr, _, size, memsize, _ = struct.unpack_from("<IIQQQQQQ", data, phoff + index * phent)
        if offset + size > len(data) or offset + size > 2 * 1024 * 1024:
            raise ValueError("ELF segment exceeds bounds")
        end = max(end, offset + size)
        if kind == 1:
            loads.append({"flags":flags, "vaddr":vaddr, "size":size, "memsize":memsize})
        if kind == 2:
            if size % 16:
                raise ValueError("Unaligned ELF dynamic table")
            for pos in range(offset, offset + size, 16):
                tag, value = struct.unpack_from("<QQ", data, pos)
                dynamic.append((tag, value))
                if tag == 0:
                    break
    blob = data[:end]
    if b"__kernel_clock_gettime\0" not in blob:
        raise ValueError("Not the expected AArch64 kernel vDSO")
    errors = []
    if not dynamic or dynamic[-1][0] != 0:
        errors.append("Missing terminated dynamic table")
    if any(tag == 22 for tag, value in dynamic) or any(tag == 30 and value & 4 for tag, value in dynamic):
        errors.append("DT_TEXTREL/DF_TEXTREL rejected by Android 64-bit linker")
    if any(tag in (7, 17, 23) and value for tag, value in dynamic):
        errors.append("Dynamic relocations are unsupported for this kernel vDSO")
    if not loads or any(segment["flags"] & 2 for segment in loads):
        errors.append("Missing or writable PT_LOAD")
    for symbol in ("__kernel_gettimeofday", "__kernel_clock_gettime", "__kernel_clock_getres", "__kernel_rt_sigreturn"):
        if symbol.encode() + b"\0" not in blob:
            errors.append("Missing export: " + symbol)
    return {"size":end, "sha256":hashlib.sha256(blob).hexdigest(), "passed":not errors,
            "errors":errors, "load_segments":loads, "dynamic_tags":[tag for tag, value in dynamic]}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--elf", type=Path, required=True)
    parser.add_argument("--image-gz", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    elf = parse_elf(args.elf.read_bytes())
    report = {"linked_elf":elf, "embedded":[], "passed":elf["passed"]}
    if args.image_gz:
        image = gzip.decompress(args.image_gz.read_bytes())
        if image[56:60] != b"ARM\x64":
            raise SystemExit("Image is not ARM64")
        position = 0
        while True:
            offset = image.find(b"\x7fELF", position)
            if offset < 0:
                break
            position = offset + 4
            try:
                item = parse_elf(image[offset:])
            except (ValueError, struct.error):
                continue
            item["image_offset"] = offset
            report["embedded"].append(item)
        embedded = report["embedded"]
        report["passed"] = (report["passed"] and len(embedded) == 1 and
                            embedded[0]["passed"] and embedded[0]["sha256"] == elf["sha256"])
        report["image_sha256"] = hashlib.sha256(args.image_gz.read_bytes()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({"passed":report["passed"], "linked_errors":elf["errors"], "embedded_count":len(report["embedded"])}))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
