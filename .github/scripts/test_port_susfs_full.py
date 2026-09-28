#!/usr/bin/env python3
"""Drive port_susfs_full against the real A2 sources and check the call sites."""
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Fixtures are passed as argv so the test does not bake in expected output.
fixture = Path(sys.argv[1]).resolve()
work_arg = Path(sys.argv[2])
if work_arg.is_symlink():
    raise SystemExit("test work directory must not be a symlink")
work = work_arg.resolve()
workspace = Path.cwd().resolve()
if (work == workspace or not work.is_relative_to(workspace) or
        work == fixture or fixture.is_relative_to(work) or work.is_relative_to(fixture)):
    raise SystemExit("test work directory must be inside the workspace and separate from fixtures")
marker = work / ".port-susfs-test-work"
if work.exists():
    if not marker.is_file():
        raise SystemExit("refusing to remove a directory not created by this test")
    shutil.rmtree(work)
shutil.copytree(fixture, work)
if len(sys.argv) > 3:
    shutil.copyfile(Path(sys.argv[3]).resolve(), work / "include/linux/susfs_def.h")
marker.write_text("port_susfs_full test workspace\n")
script = HERE / "port_susfs_full.py"
proc = subprocess.run([sys.executable, str(script)], cwd=work, text=True, capture_output=True)
sys.stdout.write(proc.stdout)
sys.stderr.write(proc.stderr)
if proc.returncode != 0:
    raise SystemExit(proc.returncode)

checks = {

    "mm/memory.c": [
        "SUSFS_IS_INODE_SUS_MAP(file_inode(vma->vm_file))",
        "#include <linux/susfs_def.h>",
    ],
    "fs/proc/task_mmu.c": [
        "SUSFS_IS_INODE_SUS_MAP(inode)",
        "SUSFS_IS_INODE_SUS_MAP(file_inode(vma->vm_file))",
        "pagemap_hide_sus_map(mm, start_vaddr, &pm)",
        "#include <linux/susfs_def.h>",
    ],
    "security/selinux/avc.c": [
        "susfs_is_avc_log_spoofing_enabled",
        "u:r:priv_app:s0:c512,c768",
    ],
    "include/linux/susfs_def.h": ["AS_FLAGS_SUS_MAP", "SUSFS_IS_INODE_SUS_MAP"],
}
for rel, needles in checks.items():
    text = (work / rel).read_text()
    for needle in needles:
        if needle not in text:
            raise SystemExit(f"missing {needle} in {rel}")
    if "susfs: sus_map is not part" in text or "susfs: avc log spoofing is not part" in text:
        raise SystemExit(f"stub text left in {rel}")
print("port call sites present")

# Reapplying the port must not insert duplicate call sites or helpers.
first_pass = {rel: (work / rel).read_bytes() for rel in checks}
subprocess.run([sys.executable, str(script)], cwd=work, check=True)
assert first_pass == {rel: (work / rel).read_bytes() for rel in checks}


def function_source(text, signature):
    start = text.index(signature)
    brace = text.index("{", start)
    depth = 1
    end = brace + 1
    while depth:
        if text[end] == "{":
            depth += 1
        elif text[end] == "}":
            depth -= 1
        end += 1
    return text[start:end]


task_mmu = (work / "fs/proc/task_mmu.c").read_text()
definitions = task_mmu[task_mmu.index("typedef struct {\n\tu64 pme;"):
                       task_mmu.index("static int pagemap_pte_hole(")]
helper = function_source(task_mmu, "static void pagemap_hide_sus_map(")
reader = function_source(task_mmu, "static ssize_t pagemap_read(")

# Compile the actual patched reader/helper against an instrumented MM boundary.
# The walker emits deterministic entries; reference counts, buffer guards and
# the VMA lookup enforce the contracts relevant to this port without a kernel.
prefix = r'''
#include <assert.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#undef assert
#define assert(c) do { if (!(c)) { \
    fprintf(stderr, "assertion failed: %s at line %d\n", #c, __LINE__); \
    exit(2); \
} } while (0)
#define __user
#define loff_t int64_t
#define ssize_t ptrdiff_t
typedef uint64_t u64;
#define PAGE_SHIFT 12
#define PAGE_SIZE (1UL << PAGE_SHIFT)
#define PMD_SIZE (512UL * PAGE_SIZE)
#define PMD_MASK (~(PMD_SIZE - 1))
#define BIT_ULL(n) (1ULL << (n))
#define GENMASK_ULL(h, l) ((~0ULL >> (63 - (h))) & (~0ULL << (l)))
#define GFP_KERNEL 0
#define CAP_SYS_ADMIN 0
#define min(a, b) ((a) < (b) ? (a) : (b))
#define untagged_addr(addr) (addr)
struct inode { bool hidden; };
struct file { void *private_data; struct inode *inode; };
struct vm_area_struct {
    unsigned long vm_start, vm_end;
    struct file *vm_file;
    struct vm_area_struct *vm_next;
};
struct mm_struct {
    unsigned long task_size;
    int mmap_sem, refs;
    struct vm_area_struct *mmap;
};
struct mm_walk {
    int (*pmd_entry)(void), (*pte_hole)(void);
    struct mm_struct *mm;
    void *private;
};
static bool hide_enabled = true;
static int lock_error, copy_error, init_user_ns;
static size_t allocation_size;
static unsigned char *allocation;
#define file_inode(f) ((f)->inode)
#define SUSFS_IS_INODE_SUS_MAP(i) ((i)->hidden && hide_enabled)
static int mmget_not_zero(struct mm_struct *mm) { return mm->refs++ > 0; }
static void mmput(struct mm_struct *mm) { assert(--mm->refs == 1); }
static int down_read_killable(int *lock) {
    assert(!*lock);
    if (lock_error) return lock_error;
    *lock = 1;
    return 0;
}
static void up_read(int *lock) { assert(*lock == 1); *lock = 0; }
static struct vm_area_struct *find_vma(struct mm_struct *mm, unsigned long addr) {
    struct vm_area_struct *vma = mm->mmap;
    assert(mm->mmap_sem == 1);
    while (vma && vma->vm_end <= addr) vma = vma->vm_next;
    return vma;
}
static bool file_ns_capable(struct file *file, int *ns, int capability) {
    (void)file; (void)ns; (void)capability;
    return true;
}
static void *kmalloc_array(size_t n, size_t size, int flags) {
    (void)flags;
    assert(!allocation);
    allocation_size = n * size;
    allocation = malloc(allocation_size + 16);
    assert(allocation);
    memset(allocation, 0xA5, allocation_size + 16);
    return allocation + 8;
}
static void kfree(void *p) {
    size_t i;
    assert(p == allocation + 8);
    for (i = 0; i < 8; i++) {
        assert(allocation[i] == 0xA5);
        assert(allocation[allocation_size + 8 + i] == 0xA5);
    }
    free(allocation);
    allocation = NULL;
}
static int copy_to_user(void *dst, const void *src, size_t len) {
    if (copy_error) return 1;
    memcpy(dst, src, len);
    return 0;
}
static int pagemap_pmd_range(void) { return 0; }
static int pagemap_pte_hole(void) { return 0; }
'''
walker = r'''
static int walk_page_range(unsigned long addr, unsigned long end, struct mm_walk *walk) {
    struct pagemapread *pm = walk->private;
    assert(walk->mm->mmap_sem == 1);
    for (; addr < end; addr += PAGE_SIZE) {
        struct vm_area_struct *vma = find_vma(walk->mm, addr);
        bool mapped = vma && vma->vm_start <= addr;
        pagemap_entry_t pme = mapped ? make_pme((addr >> PAGE_SHIFT) + 1,
                                               PM_PRESENT | PM_SOFT_DIRTY) : make_pme(0, 0);
        int ret = add_to_pagemap(addr, &pme, pm);
        if (ret) return ret;
    }
    return 0;
}
'''
main = r'''
static struct inode visible_inode = {false}, hidden_inode = {true};
static struct file visible_file = {NULL, &visible_inode}, hidden_file = {NULL, &hidden_inode};
static struct vm_area_struct vmas[] = {
    {0 * PAGE_SIZE, 2 * PAGE_SIZE, &visible_file, &vmas[1]},
    {2 * PAGE_SIZE, 5 * PAGE_SIZE, &hidden_file, &vmas[2]},
    {6 * PAGE_SIZE, 510 * PAGE_SIZE, &visible_file, &vmas[3]},
    {510 * PAGE_SIZE, 514 * PAGE_SIZE, &hidden_file, &vmas[4]},
    {514 * PAGE_SIZE, 520 * PAGE_SIZE, NULL, &vmas[5]},
    {520 * PAGE_SIZE, 1030 * PAGE_SIZE, &hidden_file, &vmas[6]},
    {1030 * PAGE_SIZE, 1040 * PAGE_SIZE, &visible_file, NULL},
};
static struct mm_struct mm = {1040 * PAGE_SIZE, 0, 1, vmas};
static struct file input = {&mm, NULL};
static uint64_t expected(unsigned long page) {
    size_t i;
    for (i = 0; i < sizeof(vmas) / sizeof(vmas[0]); i++) {
        struct vm_area_struct *vma = &vmas[i];
        if (page * PAGE_SIZE < vma->vm_start || page * PAGE_SIZE >= vma->vm_end) continue;
#ifdef CONFIG_KSU_SUSFS_SUS_MAP
        if (hide_enabled && vma->vm_file && vma->vm_file->inode->hidden) return 0;
#endif
        return (page + 1) | PM_PRESENT | PM_SOFT_DIRTY;
    }
    return 0;
}
static void check_read(loff_t *pos, size_t pages) {
    uint64_t output[1042];
    size_t i, start = (size_t)*pos / 8;
    size_t wanted = start < 1040 ? min(pages, 1040 - start) : 0;
    memset(output, 0xA5, sizeof(output));
    ssize_t got = pagemap_read(&input, (char *)output, pages * 8, pos);
    assert(got == (ssize_t)(wanted * 8));
    assert(*pos == (loff_t)((start + wanted) * 8));
    for (i = 0; i < wanted; i++) assert(output[i] == expected(start + i));
    assert(output[wanted] == 0xA5A5A5A5A5A5A5A5ULL);
    assert(mm.mmap_sem == 0 && mm.refs == 1 && !allocation);
}
int main(void) {
    loff_t pos = 510 * 8;
    uint64_t output;
    /* Begin inside a hidden VMA and cross a PMD buffer boundary. */
    check_read(&pos, 4);
    check_read(&pos, 7);
    pos = 0; check_read(&pos, 1040);
    pos = 1 * 8; check_read(&pos, 2); check_read(&pos, 3);
    pos = 512 * 8; check_read(&pos, 517);
    pos = 1039 * 8; check_read(&pos, 4); check_read(&pos, 1);
    hide_enabled = false;
    pos = 510 * 8; check_read(&pos, 17);
    hide_enabled = true;
    pos = 1;
    assert(pagemap_read(&input, (char *)&output, 8, &pos) == -EINVAL && pos == 1);
    pos = 0;
    assert(pagemap_read(&input, (char *)&output, 7, &pos) == -EINVAL && pos == 0);
    assert(pagemap_read(&input, (char *)&output, 0, &pos) == 0 && pos == 0);
    lock_error = -EINTR;
    assert(pagemap_read(&input, (char *)&output, 8, &pos) == -EINTR && pos == 0);
    lock_error = 0; copy_error = 1;
    assert(pagemap_read(&input, (char *)&output, 8, &pos) == -EFAULT && pos == 0);
    assert(mm.mmap_sem == 0 && mm.refs == 1 && !allocation);
    puts("pagemap slots, offsets, bounds, lock and references: PASS");
    return 0;
}
'''
compiler = os.environ.get("CC") or shutil.which("clang") or shutil.which("cc")
if not compiler:
    raise SystemExit("a host C compiler is required for the pagemap regression test")



def check_command_ids():
    expected = {
        "SUSFS_MAGIC": 0xFAFAFAFA,
        "CMD_SUSFS_ADD_SUS_PATH_LOOP": 0x55553,
        "CMD_SUSFS_HIDE_SUS_MNTS_FOR_NON_SU_PROCS": 0x55561,
        "CMD_SUSFS_ADD_SUS_MAP": 0x60020,
        "CMD_SUSFS_ENABLE_AVC_LOG_SPOOFING": 0x60010,
    }
    if len(sys.argv) > 4:
        reference = Path(sys.argv[4]).read_text()
        for name, value in expected.items():
            match = re.search(r"(?m)^#define " + name + r"\s+(0x[0-9a-fA-F]+)\b", reference)
            assert match and int(match.group(1), 16) == value, name
        print("SUSFS command IDs and magic match the supplied upstream ABI header")
    rel = "include/linux/susfs_def.h"
    generated = (work / rel).read_text()
    without_commands = generated
    for name in expected:
        without_commands, count = re.subn(
            r"#ifndef " + name + r"\n#define " + name + r" [^\n]+\n#endif\n",
            "", without_commands,
        )
        assert count == 1, name
    assert "AS_FLAGS_SUS_MAP" in without_commands
    custom_values = {name: value + 0x100000 for name, value in expected.items()}
    custom_defines = "".join(f"#define {name} {value:#x}\n" for name, value in custom_values.items())
    custom = without_commands.replace("#define KSU_SUSFS_DEF_H\n",
                                      "#define KSU_SUSFS_DEF_H\n" + custom_defines, 1)
    cases = [("generated", generated, expected),
             ("map_already_present", without_commands, expected),
             ("existing_values", custom, custom_values)]
    for name, header_text, values in cases:
        case = work / "command-header-cases" / name
        for source_rel, data in first_pass.items():
            destination = case / source_rel
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(data)
        header = case / rel
        header.write_text(header_text, encoding="utf-8", newline="\n")
        result = subprocess.run([sys.executable, str(script)], cwd=case, capture_output=True, text=True)
        if result.returncode:
            raise SystemExit(result.stdout + result.stderr)
        after = header.read_text()
        for command in expected:
            assert after.count("#ifndef " + command + "\n") == 1, command
        assert after.count("#define AS_FLAGS_SUS_MAP 39") == 1
        assert after.count("struct st_susfs_sus_map {") == 1
        if name == "existing_values":
            assert custom_defines in after
        assert all((case / source_rel).read_bytes() == data
                   for source_rel, data in first_pass.items() if source_rel != rel)
        snapshot = header.read_bytes()
        subprocess.run([sys.executable, str(script)], cwd=case, check=True, capture_output=True)
        assert header.read_bytes() == snapshot
        for stub_name in ("bits.h", "bitops.h"):
            (case / "include/linux" / stub_name).write_text("#define BIT(n) (1UL << (n))\n")
        unit = case / "command_ids.c"
        includes = "#include <linux/susfs_def.h>\n#include <linux/susfs_def.h>\n"
        unit.write_text(includes)
        base = [compiler, "-std=gnu11", "-Wall", "-Werror", "-I", str(case / "include")]
        macros = subprocess.run(base + ["-E", "-dM", str(unit)], capture_output=True, text=True)
        if macros.returncode:
            raise SystemExit(macros.stdout + macros.stderr)
        abi_macros = dict(re.findall(r"(?m)^#define ((?:CMD_)?SUSFS_\w+) ([^\n]+)$", macros.stdout))
        command_macros = {name: value for name, value in abi_macros.items() if name.startswith("CMD_")}
        for command, value in values.items():
            assert int(abi_macros[command], 0) == value, command
        assertions = "".join(f'_Static_assert({command} == {value:#x}, "{command}");\n'
                             for command, value in values.items())
        switch_cases = "".join(f"case {command}: return {index};\n"
                               for index, command in enumerate(sorted(command_macros), 1))
        behavior = "!valid_magic(SUSFS_MAGIC) || valid_magic(SUSFS_MAGIC ^ 1U) || " + " || ".join(f"dispatch({command}) != {index}"
                               for index, command in enumerate(sorted(command_macros), 1))
        unit.write_text(includes + assertions +
                        "static int valid_magic(unsigned int magic) { return magic == SUSFS_MAGIC; }\n" +
                        "static int dispatch(unsigned int command) { switch (command) {\n" +
                        switch_cases + "default: return 0; } }\nint main(void) { return " +
                        behavior + "; }\n")
        executable = case / ("command_ids.exe" if os.name == "nt" else "command_ids")
        build = subprocess.run(base + [str(unit), "-o", str(executable)], capture_output=True, text=True)
        if build.returncode:
            raise SystemExit(build.stdout + build.stderr)
        subprocess.run([str(executable)], check=True, timeout=15)
        guarded = subprocess.run(base + ["-DKSU_SUSFS_DEF_H", "-E", "-dM", str(unit)],
                                 capture_output=True, text=True)
        assert guarded.returncode == 0, guarded.stderr
        assert not any(re.search(r"(?m)^#define " + command + r"\b", guarded.stdout)
                       for command in expected), "command definitions escaped the header guard"
        print(f"SUSFS {name}: macro values and magic, {len(command_macros)} switch cases, header guard and idempotence PASS")


check_command_ids()


def replay(name, read_source, enabled=True, should_pass=True):
    source = prefix + definitions + walker
    source += "\n#ifdef CONFIG_KSU_SUSFS_SUS_MAP\n" + helper + "\n#endif\n"
    source += read_source + main
    c_file = work / (name + ".c")
    exe_file = work / (name + (".exe" if os.name == "nt" else ""))
    c_file.write_text(source)
    command = [compiler, "-std=gnu11", "-O0", "-Wall"]
    if enabled:
        command.append("-DCONFIG_KSU_SUSFS_SUS_MAP=1")
    command.extend([str(c_file), "-o", str(exe_file)])
    build = subprocess.run(command, cwd=work, capture_output=True, text=True)
    if build.returncode:
        raise SystemExit(build.stdout + build.stderr)
    result = subprocess.run([str(exe_file)], cwd=work, capture_output=True, text=True, timeout=15)
    if (result.returncode == 0) != should_pass:
        raise SystemExit(f"{name}: unexpected exit {result.returncode}\n{result.stdout}{result.stderr}")
    print(f"{name}: {'PASS' if should_pass else 'regression rejected'}")


replay("pagemap_enabled", reader)
replay("pagemap_disabled", reader, enabled=False)
call = "\t\tpagemap_hide_sus_map(mm, start_vaddr, &pm);"
outside_lock = reader.replace(call, "").replace(
    "\t\tup_read(&mm->mmap_sem);",
    "\t\tup_read(&mm->mmap_sem);\n" + call,
)
replay("pagemap_unlocked_mutant", outside_lock, should_pass=False)
old_skip = r'''
        {
            struct vm_area_struct *map_vma = find_vma(mm, start_vaddr);
            if (map_vma && map_vma->vm_start <= start_vaddr && map_vma->vm_file &&
                SUSFS_IS_INODE_SUS_MAP(file_inode(map_vma->vm_file))) {
                up_read(&mm->mmap_sem);
                start_vaddr = map_vma->vm_end;
                continue;
            }
        }
'''
old_reader = reader.replace(call, "").replace(
    "\t\tret = walk_page_range(start_vaddr, end, &pagemap_walk);",
    old_skip + "\t\tret = walk_page_range(start_vaddr, end, &pagemap_walk);",
)
replay("pagemap_skipped_slots_mutant", old_reader, should_pass=False)
