"""Host-only contract checks. All ADB/bridge objects below are synthetic."""
import contextlib
import copy
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

MODULE = Path(__file__).resolve().parents[1] / "hibreak_aa.py"
SPEC = importlib.util.spec_from_file_location("hibreak_aa", MODULE)
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)


def identity(serial="USB", hardware="SYNTHETIC-HARDWARE"):
    return {"adb_serial": serial, "hardware_serial": hardware, "manufacturer": "Bigme",
            "model": "HiBreak", "fingerprint": "SYNTHETIC/FIRMWARE", "sdk": "34", "initial_dpi": "276"}


def fields(package, dpi=276):
    return {"packageName": package, "appDpi": dpi, "isDpiSetting": 1,
            "appTextEnhance": 0, "appContrast": 20, "appDpiScale": 1,
            "refreshMode": 178, "appColorEnhance": 30, "appBrightnessLevel": 20,
            "appAutoClean": 1, "appAntiFlicker": 1, "appColorMode": 0, "appDarkLevel": 0}


def dump_rows(rows):
    lines = ["Top app:", "  synthetic", "Policy list:"]
    for package, values in rows.items():
        line = ", ".join(f"{key}='{value}'" if isinstance(value, str) else f"{key}={value}"
                         for key, value in values.items())
        lines.append(f"  DisplayPolicy{{{line}}}")
    return "\n".join(lines) + "\n"


class MemoryAudit:
    def __init__(self):
        self.value = {"events": []}

    def event(self, kind, **details):
        self.value["events"].append({"kind": kind, **details})

    def update(self, **details):
        self.value.update(details)


class FakeADB:
    def __init__(self, audit=None, devices=None):
        self.audit = audit or MemoryAudit()
        self.serial = "USB"
        self.identities = devices or {"USB": identity()}
        self.policies = {package: fields(package) for package in tool.PACKAGES}
        # A saved Maps row and a saved unrelated row; AA/Google are defaults.
        self.rows = {tool.PACKAGES[1]: copy.deepcopy(self.policies[tool.PACKAGES[1]]),
                     "example.unrelated": fields("example.unrelated", 300)}
        self.fail_persistence = False
        self.mutation_seen = False
        self.initial_policies = copy.deepcopy(self.policies)

    def run(self, *args, selected=True, check=True):
        if args == ("devices", "-l"):
            return SimpleNamespace(stdout="List of devices attached\n" + "".join(f"{serial}\tdevice model:HiBreak\n" for serial in self.identities))
        raise AssertionError(f"Unexpected synthetic ADB call: {args}")

    def identity(self, serial):
        return copy.deepcopy(self.identities[serial])

    def shell(self, *args, check=True):
        if args == ("dumpsys", tool.SERVICE):
            if self.fail_persistence and self.mutation_seen:
                self.policies = copy.deepcopy(self.initial_policies)
            return SimpleNamespace(stdout=dump_rows(self.rows), returncode=0)
        if args[:2] == ("pm", "path"):
            return SimpleNamespace(stdout=f"package:/synthetic/{args[2]}.apk\n", returncode=0)
        if args[:2] == ("dumpsys", "package"):
            return SimpleNamespace(stdout="versionCode=123 minSdk=28\nversionName=synthetic-1\n", returncode=0)
        raise AssertionError(f"Unexpected synthetic shell call: {args}")


class FakeBridge:
    def __init__(self, adb, collateral=False, false_result=False):
        self.adb = adb
        self.collateral = collateral
        self.false_result = false_result
        self.calls = []
        self.schema = {"sha256": "synthetic-schema", "instance_fields": {
            "packageName": "java.lang.String", "appDpi": "int", "isDpiSetting": "int",
            "appTextEnhance": "int", "appContrast": "int", "appDpiScale": "float"}}
        self.inspect = {"synthetic": True}
        self.jar_digest = "synthetic-jar"

    def get(self, package):
        return copy.deepcopy(self.adb.policies[package])

    def call(self, command, package, value, allow_failure=False):
        self.calls.append((command, package, int(value)))
        key = next(field for field, (operation, _) in tool.SETTERS.items() if operation == command)
        before = self.get(package)
        self.adb.policies[package][key] = int(value)
        if self.collateral:
            self.adb.policies[package]["appContrast"] = 99
        self.adb.mutation_seen = True
        if not self.adb.fail_persistence:
            if package in self.adb.rows:
                self.adb.rows[package][key] = int(value)
                if self.collateral:
                    self.adb.rows[package]["appContrast"] = 99
            else:
                self.adb.rows[package] = self.get(package)
        return {"beforePolicy": {"class": tool.POLICY_CLASS, "fields": before},
                "afterPolicy": {"class": tool.POLICY_CLASS, "fields": self.get(package)},
                "ok": not self.false_result, "setterResult": not self.false_result}


class IdentityTests(unittest.TestCase):
    def test_multiple_physical_phones_refused_without_serial(self):
        adb = FakeADB(devices={"USB": identity(), "OTHER": identity("OTHER", "BROTHER")})
        with self.assertRaisesRegex(tool.Refusal, "Multiple authorized physical devices"):
            tool.select_device(adb, None)

    def test_same_phone_two_transports_defaults_to_usb(self):
        adb = FakeADB(devices={"192.0.2.1:1234": identity("192.0.2.1:1234"), "USB": identity()})
        chosen = tool.select_device(adb, None)
        self.assertEqual(chosen["adb_serial"], "USB")
        self.assertEqual(adb.serial, "USB")

    def test_restore_guard_rejects_brother_and_firmware_drift(self):
        for changed in ({**identity(), "hardware_serial": "BROTHER"},
                        {**identity(), "fingerprint": "SYNTHETIC/OTHER-BUILD"}):
            with self.assertRaises(tool.Refusal):
                tool.guard_identity(identity(), changed)


class BackupTests(unittest.TestCase):
    def test_absent_rows_are_not_invented_and_exact_fields_survive(self):
        adb = FakeADB()
        bridge = FakeBridge(adb)
        versions = {package: {"version_code": 123} for package in tool.PACKAGES}
        original = tool.snapshot(adb, bridge, identity(), versions, [])
        self.assertFalse(original["packages"][tool.PACKAGES[0]]["row_present"])
        self.assertTrue(original["packages"][tool.PACKAGES[1]]["row_present"])
        self.assertEqual(original["packages"][tool.PACKAGES[1]]["fields"]["appContrast"], 20)
        tool.validate_backup(original)
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "backup.json"
            tool.atomic_json(path, original, new=True)
            self.assertEqual(json.loads(path.read_text()), original)
            if os.name == 'posix':
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with self.assertRaises(tool.Refusal):
                tool.atomic_json(path, {"overwrite": True}, new=True)
            self.assertEqual(json.loads(path.read_text()), original)

    def test_backup_row_presence_tampering_is_rejected(self):
        adb = FakeADB()
        original = tool.snapshot(adb, FakeBridge(adb), identity(), {tool.PACKAGES[0]: {}}, [])
        original["packages"][tool.PACKAGES[0]]["row_present"] = True
        with self.assertRaisesRegex(tool.Refusal, "row-presence evidence"):
            tool.validate_backup(original)


class WriteFailureTests(unittest.TestCase):
    def test_false_changed_setter_is_refused_despite_matching_live_readback(self):
        adb = FakeADB()
        bridge = FakeBridge(adb, false_result=True)
        mutator = tool.Mutator(adb, bridge, identity(), adb.audit)
        current = bridge.get(tool.PACKAGES[0])
        with self.assertRaisesRegex(tool.Refusal, "did not confirm persistence"):
            mutator.set_field(tool.PACKAGES[0], "appDpi", 160, current)
        self.assertEqual(bridge.get(tool.PACKAGES[0])["appDpi"], 160)
        self.assertEqual(mutator.writes, 1)

    def test_unchanged_value_does_not_call_vendor_setter(self):
        adb = FakeADB()
        bridge = FakeBridge(adb, false_result=True)
        current = bridge.get(tool.PACKAGES[0])
        after = tool.Mutator(adb, bridge, identity(), adb.audit).set_field(
            tool.PACKAGES[0], "appDpi", 276, current)
        self.assertEqual(after, current)
        self.assertEqual(bridge.calls, [])

    def test_flag_change_at_initial_dpi_is_staged_then_exactly_restored(self):
        adb = FakeADB()
        bridge = FakeBridge(adb)
        package = tool.PACKAGES[0]
        current = bridge.get(package)
        final = tool.Mutator(adb, bridge, identity(), adb.audit).configure(
            package, {"appDpi": 276, "isDpiSetting": 0, "appTextEnhance": 0}, current)
        self.assertEqual([entry[0] for entry in bridge.calls], ["set-dpi", "set-dpi-enabled", "set-dpi"])
        self.assertNotEqual(bridge.calls[0][2], 276)
        self.assertEqual(final["appDpi"], 276)
        self.assertEqual(final["isDpiSetting"], 0)

    def test_collateral_write_stops_and_keeps_saved_backup_path(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            instances = []
            def make_adb(executable, audit):
                adb = FakeADB(audit)
                instances.append(adb)
                return adb
            def make_bridge(adb, jar, device_identity):
                return FakeBridge(adb, collateral=True)
            stream = io.StringIO()
            with mock.patch.object(tool, "locate_adb", return_value="synthetic-adb"), \
                 mock.patch.object(tool, "locate_jar", return_value=Path("synthetic.jar")), \
                 mock.patch.object(tool, "ADB", side_effect=make_adb), \
                 mock.patch.object(tool, "Bridge", side_effect=make_bridge), \
                 contextlib.redirect_stdout(stream):
                code = tool.main(["--serial", "USB", "--state-dir", str(state), "apply", "--dpi", "160"])
            result = json.loads(stream.getvalue())
            self.assertEqual(code, 1)
            self.assertEqual(result["status"], "partial-failure")
            backup = Path(result["backup_path"])
            self.assertTrue(backup.is_file())
            saved = json.loads(backup.read_text())
            self.assertEqual(saved["packages"][tool.PACKAGES[0]]["fields"]["appDpi"], 276)
            self.assertEqual(saved["packages"][tool.PACKAGES[0]]["fields"]["appContrast"], 20)
            audit = json.loads(Path(result["audit_path"]).read_text())
            self.assertEqual(audit["backup_path"], str(backup))
            self.assertEqual(audit["status"], "partial-failure")
            self.assertEqual(instances[0].policies[tool.PACKAGES[1]]["appDpi"], 276)

    def test_failed_db_insert_is_detected_after_dumpsys_reload(self):
        with tempfile.TemporaryDirectory() as temporary:
            def make_adb(executable, audit):
                adb = FakeADB(audit)
                adb.fail_persistence = True
                return adb
            stream = io.StringIO()
            with mock.patch.object(tool, "locate_adb", return_value="synthetic-adb"), \
                 mock.patch.object(tool, "locate_jar", return_value=Path("synthetic.jar")), \
                 mock.patch.object(tool, "ADB", side_effect=make_adb), \
                 mock.patch.object(tool, "Bridge", side_effect=lambda adb, jar, chosen: FakeBridge(adb)), \
                 contextlib.redirect_stdout(stream):
                code = tool.main(["--serial", "USB", "--state-dir", temporary, "apply", "--dpi", "160"])
            result = json.loads(stream.getvalue())
            self.assertEqual(code, 1)
            self.assertEqual(result["status"], "partial-failure")
            self.assertIn("after service reload", result["error"])
            self.assertTrue(Path(result["backup_path"]).is_file())

    def test_apply_nonunit_scale_refuses_before_setter(self):
        with tempfile.TemporaryDirectory() as temporary:
            bridges = []
            def make_adb(executable, audit):
                adb = FakeADB(audit)
                adb.policies[tool.PACKAGES[0]]["appDpiScale"] = 1.25
                return adb
            def make_bridge(adb, jar, chosen):
                bridge = FakeBridge(adb)
                bridges.append(bridge)
                return bridge
            stream = io.StringIO()
            with mock.patch.object(tool, "locate_adb", return_value="synthetic-adb"), \
                 mock.patch.object(tool, "locate_jar", return_value=Path("synthetic.jar")), \
                 mock.patch.object(tool, "ADB", side_effect=make_adb), \
                 mock.patch.object(tool, "Bridge", side_effect=make_bridge), \
                 contextlib.redirect_stdout(stream):
                code = tool.main(["--serial", "USB", "--state-dir", temporary, "apply", "--dpi", "160"])
            result = json.loads(stream.getvalue())
            self.assertEqual(code, 1)
            self.assertEqual(result["status"], "refused-before-settings-write")
            self.assertIn("appDpiScale == 1", result["error"])
            self.assertEqual(bridges[0].calls, [])

    def test_normalized_raw_rows_and_effective_fields_are_independent(self):
        with tempfile.TemporaryDirectory() as temporary:
            def make_adb(executable, audit):
                adb = FakeADB(audit)
                raw = adb.rows[tool.PACKAGES[1]]
                raw.update(refreshMode=-1, appContrast=0, appColorEnhance=0,
                           appBrightnessLevel=0, appAutoClean=0, appAntiFlicker=0)
                return adb
            stream = io.StringIO()
            with mock.patch.object(tool, "locate_adb", return_value="synthetic-adb"), \
                 mock.patch.object(tool, "locate_jar", return_value=Path("synthetic.jar")), \
                 mock.patch.object(tool, "ADB", side_effect=make_adb), \
                 mock.patch.object(tool, "Bridge", side_effect=lambda adb, jar, chosen: FakeBridge(adb)), \
                 contextlib.redirect_stdout(stream):
                code = tool.main(["--serial", "USB", "--state-dir", temporary, "apply", "--dpi", "160"])
            result = json.loads(stream.getvalue())
            self.assertEqual(code, 0, result)
            self.assertEqual(result["status"], "applied-fields")
            saved = json.loads(Path(result["backup_path"]).read_text())
            maps = saved["packages"][tool.PACKAGES[1]]
            self.assertEqual(maps["fields"]["appContrast"], 20)
            self.assertEqual(maps["dump_row"]["appContrast"], 0)
            self.assertEqual(maps["dump_row"]["refreshMode"], -1)


if __name__ == "__main__":
    unittest.main()
