#!/usr/bin/env python3
"""Require reachable AArch64 call edges in the final built-in dispatcher ELF."""
import argparse
import hashlib
import json
from pathlib import Path
import struct

EDGES = (
    ("do_connectivity_driver_init", "do_common_drv_init"),
    ("do_connectivity_driver_init", "do_bluetooth_drv_init"),
    ("do_connectivity_driver_init", "do_gps_drv_init"),
    ("do_connectivity_driver_init", "do_fm_drv_init"),
    ("do_connectivity_driver_init", "do_wlan_drv_init"),
    ("do_common_drv_init", "mtk_wcn_hif_sdio_drv_init"),
    ("do_common_drv_init", "mtk_wcn_common_drv_init"),
    ("do_common_drv_init", "mtk_wcn_stp_uart_drv_init"),
    ("do_common_drv_init", "mtk_wcn_stp_sdio_drv_init"),
    ("do_bluetooth_drv_init", "mtk_wcn_stpbt_drv_init"),
    ("do_gps_drv_init", "mtk_wcn_stpgps_builtin_init"),
    ("do_fm_drv_init", "mtk_wcn_fm_init"),
    ("do_wlan_drv_init", "mtk_wcn_wmt_wifi_init"),
    ("do_wlan_drv_init", "mtk_wcn_wlan_gen4_init"),
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def signed(value, bits):
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


class Functions:
    def __init__(self, data):
        self.data = data
        require(len(data) >= 64 and data[:7] == b"\x7fELF\x02\x01\x01", "Expected ELF64 little endian")
        header = struct.unpack_from("<HHIQQQIHHHHHH", data, 16)
        require(header[0] in (2, 3) and header[1] == 183, "Expected linked AArch64 ELF")
        shoff, shsize, shnum = header[5], header[10], header[11]
        require(shsize == 64 and 0 < shnum < 65535, "Invalid ELF section table")
        self.sections = [struct.unpack("<IIQQQQIIQQ", self.read(shoff + i * 64, 64)) for i in range(shnum)]
        tables = [s for s in self.sections if s[1] == 2]
        require(len(tables) == 1, "One preserved static symbol table is required")
        table = tables[0]
        require(table[9] == 24 and table[5] % 24 == 0 and table[6] < shnum, "Invalid symbol table")
        strings = self.sections[table[6]]
        names = self.read(strings[4], strings[5])
        self.symbols = {}
        for pos in range(table[4], table[4] + table[5], 24):
            nameoff, info, _, section, address, size = struct.unpack("<IBBHQQ", self.read(pos, 24))
            if not nameoff or section == 0:
                continue
            require(nameoff < len(names), "Invalid symbol string offset")
            end = names.find(b"\0", nameoff)
            require(end >= 0, "Unterminated symbol name")
            name = names[nameoff:end].decode()
            self.symbols.setdefault(name, []).append({"name": name, "binding": info >> 4,
                "type": info & 15, "section": section, "address": address, "size": size})

    def read(self, offset, size):
        require(0 <= offset <= len(self.data) and 0 <= size <= len(self.data) - offset, "ELF range out of bounds")
        return self.data[offset:offset + size]

    def function(self, name):
        rows = self.symbols.get(name, [])
        require(len(rows) == 1, "Missing/ambiguous dispatcher function: " + name)
        row = rows[0]
        require(row["binding"] in (0, 1) and row["type"] == 2 and row["section"] < len(self.sections),
                "Dispatcher endpoint is not a strong function: " + name)
        section = self.sections[row["section"]]
        delta = row["address"] - section[3]
        require(section[1] != 8 and section[2] & 2 and section[2] & 4,
                "Dispatcher endpoint lacks allocated executable bytes: " + name)
        require(row["address"] % 4 == 0 and 0 <= delta and 4 <= row["size"] <= 1024 * 1024
                and row["size"] % 4 == 0 and delta + row["size"] <= section[5],
                "Dispatcher function extent is invalid: " + name)
        return row, self.read(section[4] + delta, row["size"])

    def target(self, address, expected):
        callee, _ = self.function(expected)
        if address == callee["address"]:
            return {"target": expected, "target_address": address, "via_cfi": False}
        slots = self.symbols.get(expected + ".cfi_jt", [])
        if not any(row["address"] == address for row in slots):
            return None
        slot, code = self.function(expected + ".cfi_jt")
        instruction = struct.unpack_from("<I", code)[0]
        require(instruction & 0xFC000000 == 0x14000000, "Dispatcher CFI slot is not B imm26")
        target = address + (signed(instruction & 0x03FFFFFF, 26) << 2)
        require(target == callee["address"], "Dispatcher CFI slot does not reach the exact endpoint")
        return {"target": expected, "target_address": target, "via_cfi": True,
                "cfi_address": slot["address"], "cfi_instruction": code[:4].hex()}

    def edge(self, caller, callee):
        row, code = self.function(caller)
        self.function(callee)
        start, end = row["address"], row["address"] + len(code)
        pending, visited, matches = [start], set(), []
        while pending:
            pc = pending.pop()
            if pc in visited:
                continue
            require(start <= pc < end and (pc - start) % 4 == 0, "Dispatcher CFG leaves function at an invalid boundary")
            visited.add(pc)
            word = struct.unpack_from("<I", code, pc - start)[0]
            if word & 0xFC000000 in (0x14000000, 0x94000000):
                destination = pc + (signed(word & 0x03FFFFFF, 26) << 2)
                target = self.target(destination, callee)
                if target:
                    matches.append({"callsite": pc, "instruction": code[pc-start:pc-start+4].hex(),
                                    "kind": "BL" if word & 0x80000000 else "tail-B", **target})
                if word & 0x80000000:
                    if pc + 4 < end:
                        pending.append(pc + 4)
                elif start <= destination < end:
                    pending.append(destination)
                continue
            conditional, always_taken = None, False
            if word & 0xFF000010 == 0x54000000:
                conditional = pc + (signed((word >> 5) & 0x7FFFF, 19) << 2)
                always_taken = word & 0xE == 0xE
            elif word & 0x7E000000 == 0x34000000:
                conditional = pc + (signed((word >> 5) & 0x7FFFF, 19) << 2)
            elif word & 0x7E000000 == 0x36000000:
                conditional = pc + (signed((word >> 5) & 0x3FFF, 14) << 2)
            if conditional is not None:
                require(start <= conditional < end, "Dispatcher conditional branch escapes its function")
                pending.append(conditional)
                if always_taken:
                    continue
            if word & 0xFFFFFC1F in (0xD65F0000, 0xD61F0000) or word & 0xFFE0001F == 0xD4200000:
                continue
            if pc + 4 < end:
                pending.append(pc + 4)
        require(matches, "No reachable dispatcher call edge: " + caller + " -> " + callee)
        return {"caller": caller, "callee": callee, "caller_address": start, "caller_size": len(code),
                "caller_sha256": sha(code), "reachable_instruction_count": len(visited), "calls": matches}


def verify_dispatch(data):
    elf, results, errors = Functions(data), [], []
    for caller, callee in EDGES:
        try:
            results.append(elf.edge(caller, callee))
        except ValueError as error:
            errors.append(str(error))
    return {"schema_version": 1, "passed": not errors, "errors": errors, "elf_sha256": sha(data),
            "required_edge_count": len(EDGES), "verified_edges": results,
            "scope": "Conservative AArch64 CFG call/tail edges to exact strong endpoints. Conditional feasibility and runtime success are not proven."}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--elf", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = verify_dispatch(args.elf.read_bytes())
    text = json.dumps(report, indent=2) + "\n"
    if args.output:
        require(not args.output.exists(), "Refuse to overwrite dispatcher evidence")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temp = args.output.with_suffix(args.output.suffix + ".tmp")
        temp.write_text(text)
        temp.replace(args.output)
    print(json.dumps({key: report[key] for key in ("passed", "errors", "required_edge_count")}))
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
