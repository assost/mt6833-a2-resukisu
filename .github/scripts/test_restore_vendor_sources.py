#!/usr/bin/env python3
"""Offline regressions for replacing the broken vendor links safely."""
from pathlib import Path
import os
import json
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from restore_vendor_sources import restore, restore_all, vendor_source_name, SOURCES


class RestoreVendorTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory(prefix="vendor-restore-test-", dir=Path.cwd())
        self.addCleanup(self.work.cleanup)
        self.base = Path(self.work.name).resolve()
        self.root = self.base / "kernel"
        self.modules = self.root / ".build-deps/modules"
        self.modules.mkdir(parents=True)
        source, target = SOURCES["audio"]
        self.audio_source = self.modules / source
        self.audio = self.root / target
        self.audio_source.mkdir(parents=True)
        (self.audio_source / "Makefile").write_bytes(b"obj-y += real_driver.o\r\n")
        (self.audio_source / "real_driver.c").write_bytes(b"int real_driver(void) { return 7; }\n")
        self.audio.parent.mkdir(parents=True)

    def test_broken_link_is_backed_up_and_real_sources_installed(self):
        self.audio.symlink_to("../../../../vendor/missing/audio", target_is_directory=True)
        restore(self.root, self.modules, "audio")
        self.assertFalse(self.audio.is_symlink())
        self.assertEqual((self.audio / "Makefile").read_bytes(), (self.audio_source / "Makefile").read_bytes())
        self.assertEqual((self.audio / "real_driver.c").read_bytes(), (self.audio_source / "real_driver.c").read_bytes())
        previous = list((self.root / ".build-deps").glob("restore-audio-*/previous"))
        self.assertEqual(len(previous), 1)
        self.assertTrue(previous[0].is_symlink())

    def test_existing_tree_preserved_without_stale_files_in_replacement(self):
        self.audio.mkdir()
        (self.audio / "old-stub.c").write_text("old content")
        restore(self.root, self.modules, "audio")
        self.assertFalse((self.audio / "old-stub.c").exists())
        previous = next((self.root / ".build-deps").glob("restore-audio-*/previous"))
        self.assertEqual((previous / "old-stub.c").read_text(), "old content")

    def test_failed_install_rolls_back_original(self):
        self.audio.mkdir()
        (self.audio / "old-stub.c").write_text("old content")
        replace = os.replace

        def fail_staged(source, dest):
            if Path(source).name == "audio" and Path(source).parent.name.startswith("restore-audio-"):
                raise OSError("simulated interrupted installation")
            return replace(source, dest)

        with patch("restore_vendor_sources.os.replace", side_effect=fail_staged):
            with self.assertRaisesRegex(OSError, "interrupted"):
                restore(self.root, self.modules, "audio")
        self.assertEqual((self.audio / "old-stub.c").read_text(), "old content")

    def test_feedback_rejects_parent_symlink_outside_checkout(self):
        source, target = SOURCES["feedback"]
        header = self.modules / source
        header.parent.mkdir(parents=True)
        header.write_bytes(b"official feedback header\r\n")
        dest = self.root / target
        dest.parent.parent.mkdir(parents=True)
        outside = self.base / "outside"
        outside.mkdir()
        dest.parent.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(ValueError):
            restore(self.root, self.modules, "feedback")
        self.assertFalse((outside / dest.name).exists())


class RestoreAllVendorTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory(prefix="vendor-all-test-", dir=Path.cwd())
        self.addCleanup(self.work.cleanup)
        self.base = Path(self.work.name).resolve()
        self.root = self.base / "kernel"
        self.modules = self.root / ".build-deps/modules"
        self.modules.mkdir(parents=True)
        subprocess.run(["git", "-C", str(self.root), "init", "-q"], check=True)
        self.vendor = self.modules / "vendor/oplus"
        self.charger = self.vendor / "kernel/charger"
        (self.charger / "v1").mkdir(parents=True)
        (self.charger / "oplus_charger.c").write_bytes(b"int charge(void) { return 7; }\r\n")
        (self.charger / "v1/oplus_charger.c").symlink_to("../oplus_charger.c")
        (self.charger / "oplus_ufcs.h").symlink_to("v1/oplus_ufcs.h")
        (self.charger / "v1/oplus_ufcs.h").write_bytes(b"#define UFCS 1\n")
        system = self.vendor / "kernel/system"
        (system / "include").mkdir(parents=True)
        (system / "include/oplus_project.h").write_bytes(b"unsigned int is_project(int project);\n")
        (system / "Makefile").write_bytes(b"obj-y += oplus_project/\r\n")
        self._git("init", "-q")
        self.commit()
        self.pin = patch("restore_vendor_sources.SOURCE_COMMIT", self.sha)
        self.pin.start()
        self.addCleanup(self.pin.stop)
        self.alias("drivers/power/oplus", "../../../vendor/oplus/kernel/charger")
        self.alias("drivers/soc/oplus/system", "../../../../vendor/oplus/kernel/system")
        self.alias("include/soc/oplus/system", "../../../../vendor/oplus/kernel/system/include")
        self.report_path = self.root / ".build-deps/vendor-restore-manifest.json"

    def _git(self, *args):
        return subprocess.run(
            ["git", "-C", str(self.modules), *args], check=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        ).stdout.decode().strip()

    def commit(self):
        self._git("add", "--all")
        self._git("-c", "user.name=Vendor Fixture", "-c", "user.email=fixture@example.invalid",
                  "-c", "core.autocrlf=false", "commit", "-q", "-m", "vendor fixture")
        self.sha = self._git("rev-parse", "HEAD")

    def alias(self, name, link):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.symlink_to(link, target_is_directory=True)
        subprocess.run(["git", "-C", str(self.root), "add", "--", name], check=True)
        return path

    def test_all_preserves_shared_topology_crlf_and_original_link_backups(self):
        (self.vendor / "not-tracked.txt").write_text("unrelated local file")
        report = restore_all(self.root, self.modules)
        self.assertEqual(report["status"], "complete")
        self.assertEqual(len(report["restored"]), 3)
        installed = self.root / report["installed_tree"]
        self.assertFalse((installed / "vendor/oplus/not-tracked.txt").exists())
        for entry in report["restored"]:
            path = self.root / entry["path"]
            self.assertTrue(path.is_symlink())
            self.assertEqual(os.readlink(self.root / entry["backup"]), entry["original_link"])
        self.assertEqual((self.root / "drivers/power/oplus/v1/oplus_charger.c").read_bytes(),
                         (self.charger / "oplus_charger.c").read_bytes())
        self.assertEqual(os.readlink(self.root / "drivers/power/oplus/v1/oplus_charger.c"), "../oplus_charger.c")
        self.assertEqual((self.root / "drivers/power/oplus/oplus_ufcs.h").read_bytes(), b"#define UFCS 1\n")
        self.assertEqual((self.root / "drivers/soc/oplus/system/Makefile").read_bytes(), b"obj-y += oplus_project/\r\n")
        self.assertEqual((self.root / "include/soc/oplus/system").resolve(),
                         (self.root / "drivers/soc/oplus/system/include").resolve())
        self.assertEqual(json.loads(self.report_path.read_text()), report)

    def test_missing_published_alias_is_reported_and_preserved(self):
        absent = self.alias("drivers/input/not_published", "../../../vendor/oplus/missing-driver")
        original = os.readlink(absent)
        report = restore_all(self.root, self.modules)
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["unavailable"][0]["path"], "drivers/input/not_published")
        self.assertEqual(os.readlink(absent), original)
        self.assertFalse(absent.exists())

    def test_wrong_pin_rejected_before_modification(self):
        with patch("restore_vendor_sources.SOURCE_COMMIT", "0" * 40):
            with self.assertRaisesRegex(RuntimeError, "does not match pinned"):
                restore_all(self.root, self.modules)
        self.assertFalse(self.report_path.exists())
        self.assertEqual(os.readlink(self.root / "drivers/power/oplus"), "../../../vendor/oplus/kernel/charger")

    def test_modified_source_rejected_before_any_alias_changes(self):
        (self.charger / "oplus_charger.c").write_text("modified source")
        with self.assertRaisesRegex(RuntimeError, "incomplete or modified"):
            restore_all(self.root, self.modules)
        report = json.loads(self.report_path.read_text())
        self.assertEqual(report["status"], "incomplete_source")
        self.assertEqual(report["restored"], [])
        self.assertIn("pinned Git blob", report["source_errors"][0]["reason"])
        self.assertEqual(os.readlink(self.root / "drivers/power/oplus"), "../../../vendor/oplus/kernel/charger")

    def test_incomplete_sparse_checkout_is_not_silently_staged(self):
        (self.charger / "oplus_charger.c").unlink()
        with self.assertRaisesRegex(RuntimeError, "incomplete or modified"):
            restore_all(self.root, self.modules)
        self.assertEqual(json.loads(self.report_path.read_text())["restored"], [])

    def test_windows_plaintext_link_checkout_is_rejected(self):
        link = self.charger / "v1/oplus_charger.c"
        link.unlink()
        link.write_text("../oplus_charger.c")
        with self.assertRaisesRegex(RuntimeError, "incomplete or modified"):
            restore_all(self.root, self.modules)
        self.assertIn("real symbolic link", json.loads(self.report_path.read_text())["source_errors"][0]["reason"])

    def test_unrelated_and_path_escape_aliases_are_untouched(self):
        unrelated = self.alias("drivers/input/other", "../../../somewhere-else")
        excessive = self.alias("drivers/input/excessive", "../../../../vendor/oplus/kernel/charger")
        absolute = self.alias("drivers/input/absolute", "/vendor/oplus/kernel/charger")
        report = restore_all(self.root, self.modules)
        self.assertEqual(len(report["restored"]), 3)
        self.assertEqual(os.readlink(unrelated), "../../../somewhere-else")
        self.assertEqual(os.readlink(excessive), "../../../../vendor/oplus/kernel/charger")
        self.assertEqual(os.readlink(absolute), "/vendor/oplus/kernel/charger")

    def test_source_internal_link_escape_is_rejected(self):
        (self.vendor / "escape").symlink_to("../../../outside")
        (self.modules / "outside").write_text("outside source")
        self.commit()
        with patch("restore_vendor_sources.SOURCE_COMMIT", self.sha):
            with self.assertRaisesRegex(RuntimeError, "outside vendor/oplus"):
                restore_all(self.root, self.modules)
        self.assertEqual(json.loads(self.report_path.read_text())["status"], "invalid_source_links")
        self.assertEqual(os.readlink(self.root / "drivers/power/oplus"), "../../../vendor/oplus/kernel/charger")

    def test_failed_second_alias_rolls_back_first(self):
        replace = os.replace

        def fail_second(source, target):
            if Path(target) == self.root / "drivers/soc/oplus/system" and "links" in Path(source).parts:
                raise OSError("simulated second alias failure")
            return replace(source, target)

        with patch("restore_vendor_sources.os.replace", side_effect=fail_second):
            with self.assertRaisesRegex(OSError, "second alias"):
                restore_all(self.root, self.modules)
        report = json.loads(self.report_path.read_text())
        self.assertEqual(report["status"], "rolled_back")
        self.assertEqual(report["restored"], [])
        self.assertEqual(os.readlink(self.root / "drivers/power/oplus"), "../../../vendor/oplus/kernel/charger")
        self.assertEqual(os.readlink(self.root / "drivers/soc/oplus/system"), "../../../../vendor/oplus/kernel/system")

    def test_repeated_restore_verifies_without_extra_work_or_backups(self):
        first = restore_all(self.root, self.modules)
        before = self.report_path.read_bytes()
        second = restore_all(self.root, self.modules)
        self.assertEqual(first, second)
        self.assertEqual(self.report_path.read_bytes(), before)
        self.assertEqual(len(list((self.root / ".build-deps").glob("restore-all-*"))), 1)

    def test_repeated_restore_detects_changed_installed_source(self):
        restore_all(self.root, self.modules)
        (self.root / "drivers/power/oplus/oplus_charger.c").write_text("changed after install")
        with self.assertRaisesRegex(RuntimeError, "previously restored vendor tree changed"):
            restore_all(self.root, self.modules)

    def test_source_name_requires_original_sibling_vendor_layout(self):
        self.assertEqual(vendor_source_name(Path("kernel/sched_assist"),
                         "../../vendor/oplus/kernel/oplus_performance/sched_assist/"),
                         "vendor/oplus/kernel/oplus_performance/sched_assist")
        self.assertIsNone(vendor_source_name(Path("kernel/link"), "../../../vendor/oplus/elsewhere"))
        self.assertIsNone(vendor_source_name(Path("kernel/link"), "C:\\vendor\\oplus\\something"))

    def test_old_stub_is_detected_instead_of_false_complete_status(self):
        alias = self.root / "drivers/power/oplus"
        alias.unlink()
        alias.mkdir()
        (alias / "Kconfig").write_text("# old vendor stub\n")
        with self.assertRaisesRegex(RuntimeError, "became a stub"):
            restore_all(self.root, self.modules)
        self.assertFalse(self.report_path.exists())
        self.assertEqual((alias / "Kconfig").read_text(), "# old vendor stub\n")

    def test_untracked_vendor_link_is_not_modified(self):
        untracked = self.root / "unrelated-vendor"
        untracked.symlink_to("../vendor/oplus/kernel/charger", target_is_directory=True)
        report = restore_all(self.root, self.modules)
        self.assertEqual(len(report["restored"]), 3)
        self.assertEqual(os.readlink(untracked), "../vendor/oplus/kernel/charger")


if __name__ == "__main__":
    unittest.main()
