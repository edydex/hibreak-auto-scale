"""Installer checks use a synthetic APK, transport, and grants; never a phone."""
import contextlib
import copy
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SPEC = importlib.util.spec_from_file_location("install_on_mac", ROOT / "install_on_mac.py")
installer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(installer)


def identity():
    return {"adb_serial": "USB", "hardware_serial": "SYNTHETIC", "manufacturer": "Bigme",
            "model": "HiBreak", "fingerprint": "SYNTHETIC/FIRMWARE", "sdk": "34", "initial_dpi": "276"}


class FakeInstallerADB:
    def __init__(self, executable, audit, timeout=120, preexisting=False, fail_install=False):
        self.executable, self.audit, self.serial = executable, audit, "USB"
        self.installed = preexisting
        self.permissions = {installer.DUMP: preexisting, installer.NOTIFICATIONS: preexisting}
        self.whitelisted = preexisting
        self.fail_install = fail_install
        self.commands = []

    def identity(self, serial):
        return identity()

    def run(self, *args, selected=True, check=True):
        self.commands.append(args)
        if args[:2] == ("install", "-r"):
            if self.fail_install:
                raise installer.shared.Refusal("SYNTHETIC signing mismatch")
            self.installed = True
            return SimpleNamespace(stdout="Performing Streamed Install\nSuccess\n", stderr="", returncode=0)
        raise AssertionError(args)

    def shell(self, *args, check=True):
        self.commands.append(args)
        output = ""
        if args == ("pm", "path", installer.APP):
            output = "package:/synthetic/companion.apk\n" if self.installed else ""
        elif args == ("dumpsys", "package", installer.APP):
            output = "versionName=SYNTHETIC\n" + "\n".join(
                f"{permission}: granted={str(granted).lower()}" for permission, granted in self.permissions.items())
        elif args == ("dumpsys", "deviceidle", "whitelist"):
            # Lookalikes must not count as this app's exact package.
            output = "user,org.hibreak.autoscale.lookalike,10001\n"
            if self.whitelisted:
                output += f"user,{installer.APP},10002\n"
        elif args == ("dumpsys", "display"):
            output = "DisplayDeviceInfo{\"GhFacetBar\": type VIRTUAL, state ON, owner com.google.android.projection.gearhead (uid 99)}"
        elif args[:2] == ("pm", "grant"):
            self.permissions[args[3]] = True
        elif args == ("dumpsys", "deviceidle", "whitelist", "+" + installer.APP):
            self.whitelisted = True
        elif args == ("am", "start", "-n", installer.ACTIVITY):
            output = "Starting: Intent { cmp=org.hibreak.autoscale/.MainActivity }\n"
        else:
            raise AssertionError(args)
        return SimpleNamespace(stdout=output, stderr="", returncode=0)


class InstallerTests(unittest.TestCase):
    def run_installer(self, preexisting=False, fail_install=False):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        apk = root / "HiBreak-Auto-Scale.apk"
        with zipfile.ZipFile(apk, "w") as archive:
            archive.writestr("AndroidManifest.xml", b"SYNTHETIC")
            archive.writestr("classes.dex", b"SYNTHETIC")
        instances = []
        def factory(executable, audit, timeout=120):
            adb = FakeInstallerADB(executable, audit, timeout, preexisting, fail_install)
            instances.append(adb)
            return adb
        stream = io.StringIO()
        with mock.patch.object(installer, "locate_adb", return_value="synthetic-adb"), \
             mock.patch.object(installer.shared, "select_device", return_value=identity()), \
             mock.patch.object(installer.shared, "ADB", side_effect=factory), \
             contextlib.redirect_stdout(stream):
            code = installer.main(["--serial", "USB", "--apk", str(apk), "--state-dir", str(root / "records")])
        audit_path = next((root / "records").glob("*-audit.json"))
        return code, json.loads(audit_path.read_text()), instances[0], stream.getvalue()

    def test_fresh_install_preserves_data_and_never_enables(self):
        code, audit, adb, output = self.run_installer()
        self.assertEqual(code, 0, output)
        self.assertEqual(audit["status"], "installed-and-opened")
        self.assertFalse(audit["automatic_scaling_enabled_by_installer"])
        self.assertFalse(audit["app_before"]["installed"])
        self.assertTrue(audit["added_idle_whitelist"])
        self.assertTrue(audit["android_auto_displays_before"])
        self.assertEqual(len(audit["undo_advisory"]["commands_for_this_install"]), 3)
        self.assertIn("Disconnect Android Auto", output)
        self.assertTrue(any(command[:2] == ("install", "-r") for command in adb.commands))
        self.assertIn(("dumpsys", "deviceidle", "whitelist", "+" + installer.APP), adb.commands)
        self.assertEqual([command[3] for command in adb.commands if command[:2] == ("pm", "grant")],
                         [installer.DUMP, installer.NOTIFICATIONS])
        self.assertFalse(any("uninstall" in command or "clear" in command for command in adb.commands))
        self.assertFalse(any("enable" in word.lower() for command in adb.commands for word in command))

    def test_preexisting_exception_and_grants_are_preserved_in_undo(self):
        code, audit, adb, output = self.run_installer(preexisting=True)
        self.assertEqual(code, 0, output)
        self.assertFalse(audit["added_idle_whitelist"])
        self.assertEqual(audit["undo_advisory"]["commands_for_this_install"], [])
        self.assertNotIn(("dumpsys", "deviceidle", "whitelist", "+" + installer.APP), adb.commands)

    def test_signer_failure_stops_without_uninstall_or_permission_changes(self):
        code, audit, adb, output = self.run_installer(preexisting=True, fail_install=True)
        self.assertEqual(code, 1)
        self.assertEqual(audit["status"], "installation-partial-failure")
        self.assertTrue(audit["app_before"]["installed"])
        self.assertFalse(any(command[:2] in (("pm", "grant"), ("pm", "clear")) for command in adb.commands))
        self.assertFalse(any("uninstall" in command for command in adb.commands))


if __name__ == "__main__":
    unittest.main()
