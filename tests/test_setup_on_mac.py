"""Guided setup contracts with synthetic APK, phone, screens and setting adapters."""
import contextlib
import copy
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
SPEC = importlib.util.spec_from_file_location("setup_on_mac", ROOT / "setup_on_mac.py")
wizard = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(wizard)

IDENTITY = {"adb_serial": "USB", "hardware_serial": "SYNTHETIC-NEW-PHONE", "manufacturer": "Bigme",
            "model": "HiBreak", "fingerprint": "SYNTHETIC/FIRMWARE", "sdk": "34", "initial_dpi": "276"}
IDLE_DISPLAY = 'DisplayDeviceInfo{"Built-in": type BUILT_IN, state ON, density 276}\n'
OFF_TEXT = "Automatic scaling is off. Owned phone preferences restored.\n\nAutomatic scaling: off\nPaired-car automatic: off"


class FakeADB:
    def __init__(self, fixture, executable="synthetic-adb", audit=None):
        self.fixture, self.executable, self.audit, self.serial = fixture, executable, audit, "USB"
        self.commands = []

    def identity(self, serial):
        return copy.deepcopy(self.fixture.identity)

    def shell(self, *args, check=True):
        self.commands.append(args)
        if args == ("dumpsys", "display"):
            text = self.fixture.display
        elif args == ("am", "get-current-user"):
            text = str(self.fixture.current_user) + "\n"
        elif args == ("dumpsys", "activity", "services", wizard.installer.APP):
            text = "ACTIVITY MANAGER SERVICES (dumpsys activity services)\n"
            if self.fixture.service_running:
                text += "ServiceRecord{123 u0 org.hibreak.autoscale/.AutoScaleService}\n"
        else:
            raise AssertionError("Unexpected phone command: " + repr(args))
        return SimpleNamespace(stdout=text, stderr="", returncode=0)


class Fixture:
    def __init__(self, root):
        self.root = root
        self.identity = copy.deepcopy(IDENTITY)
        self.current_user = 0
        self.display = IDLE_DISPLAY
        self.service_running = False
        self.preexisting = False
        self.screen_text = OFF_TEXT
        self.actions = []
        self.fail_ui = None
        self.missing_labels = []
        self.apk = root / "HiBreak-Auto-Scale.apk"
        self.apk.write_bytes(b"SYNTHETIC-APK")
        self.digest = hashlib.sha256(self.apk.read_bytes()).hexdigest()
        self.audit = wizard.shared.Audit(root / "setup-report.json", "synthetic-setup")
        self.adb = FakeADB(self, audit=self.audit)
        self.args = wizard.parser().parse_args(["--serial", "USB", "--apk", str(self.apk),
                                              "--state-dir", str(root), "--non-interactive", "--wait-seconds", "0"])
        fixture = self

        class Ui:
            def __init__(self, adb, records_dir, before_mutation=None):
                self.adb, self.before_mutation = adb, before_mutation

            def launch(self, *args):
                self.before_mutation()
                fixture.actions.append(("launch", args))

            def screen(self):
                return SimpleNamespace(nodes=[{"package": wizard.installer.APP, "text": fixture.screen_text}])

        def configure(name, report):
            def action(ui, *args, **kwargs):
                ui.before_mutation()
                fixture.actions.append((name, args))
                if fixture.fail_ui == name:
                    raise wizard.shared.Refusal("SYNTHETIC unsupported/ambiguous UI")
                value = dict(report)
                if name == "car":
                    value["requested_but_not_observed"] = fixture.missing_labels
                return value
            return action

        self.ui = SimpleNamespace(Ui=Ui,
            configure_car_preferences=configure("car", {"status": "verified"}),
            configure_phone_maps=configure("maps", {"status": "verified", "projected_raised_buildings": "pending-real-head-unit-check"}),
            configure_notification=configure("notification", {"status": "verified"}),
            enable_helper=configure("enable", {"status": "verified", "backup": "App guarded path verified"}),
            configure_vendor_lock=configure("vendor-lock", {"status": "pending-person"}),
            configure_selected_car=configure("choose-car", {"status": "pending-person"}))

        def assistant(adb, audit, identity, prompt=input):
            fixture.actions.append(("assistant", identity))
            return {"status": "configured", "head_unit_audio_tested": False}
        self.assistant = SimpleNamespace(configure_assistant=assistant)

    def snapshot(self, *args):
        self.actions.append(("backup-read", None))
        return {"format": "synthetic-own-phone", "identity": copy.deepcopy(self.identity),
                "packages": {wizard.AA: {"fields": {"appDpi": 276}}}}

    def install(self, args, audit):
        # A durable own-phone baseline must already exist before first install mutation.
        path = Path(audit.value["backup_path"])
        if not path.is_file():
            raise AssertionError("Install happened before the baseline was durable")
        audit.event("install-intent")
        self.actions.append(("install", str(path)))
        return {"status": "installed-and-opened", "identity": copy.deepcopy(self.identity)}

    @contextlib.contextmanager
    def patches(self):
        with mock.patch.object(wizard, "EXPECTED_APK_SHA256", self.digest), \
             mock.patch.object(wizard.installer, "locate_adb", return_value="synthetic-adb"), \
             mock.patch.object(wizard.shared, "ADB", return_value=self.adb), \
             mock.patch.object(wizard.shared, "select_device", return_value=copy.deepcopy(self.identity)), \
             mock.patch.object(wizard.installer, "package_state", side_effect=lambda adb: {"installed": self.preexisting}), \
             mock.patch.object(wizard.shared, "Bridge", return_value=SimpleNamespace()), \
             mock.patch.object(wizard.shared, "locate_jar", return_value=self.root / "synthetic.jar"), \
             mock.patch.object(wizard.shared, "choose_packages", return_value=({wizard.AA: {}}, [])), \
             mock.patch.object(wizard.shared, "snapshot", side_effect=self.snapshot), \
             mock.patch.object(wizard.installer, "install", side_effect=self.install), \
             mock.patch.object(wizard.shared, "installed_version", return_value={"version_code": 12, "version_name": "1.1.1"}), \
             mock.patch.object(wizard.time, "sleep"), contextlib.redirect_stdout(io.StringIO()):
            yield

    def run(self, prompt=lambda message: ""):
        return wizard.run_setup(self.args, self.audit, self.ui, self.assistant, prompt)


class WizardTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.fixture = Fixture(Path(temporary.name))

    def test_backup_is_own_phone_private_and_before_install_or_preferences(self):
        f = self.fixture
        with f.patches():
            result = f.run()
        names = [name for name, value in f.actions]
        self.assertLess(names.index("backup-read"), names.index("install"))
        self.assertLess(names.index("install"), names.index("car"))
        self.assertEqual(json.loads(Path(result["backup_path"]).read_text())["identity"], IDENTITY)
        if os.name == 'posix':
            self.assertEqual(stat.S_IMODE(Path(result["backup_path"]).stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(Path(result["backup_path"]).parent.stat().st_mode), 0o700)
        self.assertEqual(result["status"], "setup-needs-follow-up")
        self.assertIn("real_host_learning", result["pending_tasks"])
        self.assertEqual(f.audit.value["setup_tasks"]["google_assistant"]["status"], "verified")
        self.assertFalse(any("160" in str(command) for command in f.adb.commands))

    def test_live_android_auto_refuses_before_backup_or_install(self):
        f = self.fixture
        f.display = 'DisplayDeviceInfo{"GhFacetBar": owner ' + wizard.AA + ' (uid 99)}'
        with f.patches(), self.assertRaises(wizard.UnsafePrecondition):
            f.run()
        self.assertFalse(f.actions)
        self.assertIsNone(f.audit.value["backup_path"])

    def test_unreadable_or_truncated_display_never_means_disconnected(self):
        for text in ("", "Permission Denial", "DisplayInfo only", 'DisplayDeviceInfo{"Built-in": bad'):
            with self.subTest(text=text):
                self.fixture.display = text
                with self.assertRaises(wizard.UnsafePrecondition):
                    wizard.require_disconnected(self.fixture.adb)

    def test_quoted_and_nested_braces_are_handled_conservatively(self):
        self.fixture.display = 'DisplayDeviceInfo{"Name }": shape {a=1}, state ON}'
        self.assertEqual(wizard.require_disconnected(self.fixture.adb)["native_entries"], 1)
        self.fixture.display = 'DisplayDeviceInfo{"' + wizard.AA + '": state OFF}'
        with self.assertRaises(wizard.UnsafePrecondition):
            wizard.require_disconnected(self.fixture.adb)

    def test_existing_service_blocks_backup_even_with_off_screen(self):
        f = self.fixture
        f.preexisting = f.service_running = True
        with f.patches(), self.assertRaises(wizard.UnsafePrecondition):
            f.run()
        self.assertNotIn("backup-read", [name for name, value in f.actions])

    def test_user_done_does_not_bypass_unrestored_existing_helper(self):
        f = self.fixture
        f.preexisting = True
        f.screen_text = "Needs attention\nAutomatic scaling: off\nPaired-car automatic: off"
        f.args.non_interactive = False
        with f.patches(), self.assertRaises(wizard.UnsafePrecondition):
            f.run(prompt=lambda message: "done")
        self.assertNotIn("backup-read", [name for name, value in f.actions])

    def test_restored_screen_and_service_absence_allow_existing_phone_backup(self):
        f = self.fixture
        f.preexisting = True
        with f.patches():
            f.run()
        self.assertEqual(f.audit.value["setup_tasks"]["existing_helper"]["status"], "verified")

    def test_wrong_apk_refuses_without_phone_operations(self):
        f = self.fixture
        with f.patches(), mock.patch.object(wizard, "EXPECTED_APK_SHA256", "wrong"), self.assertRaises(wizard.shared.Refusal):
            f.run()
        self.assertFalse(f.adb.commands)

    def test_unknown_settings_ui_stays_pending_and_other_stages_continue(self):
        f = self.fixture
        f.fail_ui = "car"
        with f.patches():
            result = f.run()
        tasks = f.audit.value["setup_tasks"]
        self.assertEqual(tasks["android_auto_preferences"]["status"], "pending")
        self.assertEqual(tasks["phone_maps_buildings"]["status"], "verified")
        self.assertEqual(tasks["google_assistant"]["status"], "verified")
        self.assertIn("android_auto_preferences", result["pending_tasks"])

    def test_missing_requested_launcher_label_is_not_blanket_success(self):
        f = self.fixture
        f.missing_labels = ["Heritage"]
        with f.patches():
            result = f.run()
        self.assertIn("android_auto_preferences", result["pending_tasks"])

    def test_keep_list_override_is_exact_and_default_preserves_requested_apps(self):
        f = self.fixture
        f.args.keep_app = [" Maps ", "Messages", "Maps"]
        with f.patches():
            f.run()
        self.assertEqual(next(value[0] for name, value in f.actions if name == "car"), {"Maps", "Messages"})
        self.assertEqual(set(wizard.DEFAULT_KEEP), {"Maps", "Messages", "Reminder", "Heritage", "NewPipe"})

    def test_identity_drift_during_snapshot_halts_before_install(self):
        f = self.fixture
        snapshot = f.snapshot
        def drift(*args):
            result = snapshot(*args)
            f.identity["hardware_serial"] = "DIFFERENT-PHONE"
            return result
        f.snapshot = drift
        with f.patches(), self.assertRaises(wizard.UnsafePrecondition):
            f.run()
        self.assertNotIn("install", [name for name, value in f.actions])

    def test_human_completion_is_labeled_user_confirmed_not_verified(self):
        f = self.fixture
        f.args.non_interactive = False
        f.args.check_car_now = True
        f.ui.configure_vendor_lock = lambda *a, **k: {"status": "verified"}
        f.ui.configure_selected_car = lambda *a, **k: {"status": "verified"}
        with f.patches():
            result = f.run(prompt=lambda message: "done")
        self.assertEqual(result["status"], "setup-guided-user-confirmed")
        self.assertEqual(f.audit.value["setup_tasks"]["physical_car_acceptance"]["status"], "user-confirmed")
        self.assertIn("not independently verified", f.audit.value["setup_tasks"]["physical_car_acceptance"]["verification"])

    def test_helper_ui_recovery_and_automatic_modes_must_both_be_off(self):
        for bad in [OFF_TEXT.replace("Paired-car automatic: off", "Paired-car automatic: Elantra"),
                    OFF_TEXT.replace("Paired-car automatic: off", "Paired-car automatic: offroad car"),
                    OFF_TEXT + "\nFinishing or recovering", OFF_TEXT + "\nNeeds attention",
                    OFF_TEXT.replace("Automatic scaling: off", "Automatic scaling: enabled")]:
            with self.subTest(text=bad):
                self.assertFalse(wizard.helper_screen_is_restored(SimpleNamespace(nodes=[{"package": wizard.installer.APP, "text": bad}])))

    def test_closed_input_leaves_human_steps_pending(self):
        f = self.fixture
        f.args.non_interactive = False
        f.args.check_car_now = True
        def closed(message):
            raise EOFError()
        with f.patches():
            result = f.run(prompt=closed)
        self.assertEqual(result["status"], "setup-needs-follow-up")
        self.assertIn("physical_car_acceptance", result["pending_tasks"])

    def test_initial_unused_helper_off_screen_is_supported(self):
        text = OFF_TEXT.replace("Automatic scaling is off. Owned phone preferences restored.", "Automatic scaling is off.")
        self.assertTrue(wizard.helper_screen_is_restored(SimpleNamespace(nodes=[{"package": wizard.installer.APP, "text": text}])))

    def test_secondary_android_user_refuses_before_backup_or_install(self):
        f = self.fixture
        f.current_user = 10
        with f.patches(), self.assertRaises(wizard.UnsafePrecondition):
            f.run()
        self.assertFalse(f.actions)

    def test_user_switch_between_installer_intents_stops_following_mutation(self):
        f = self.fixture
        def changed(args, audit):
            audit.event("install-intent")
            f.current_user = 10
            audit.event("permission-grant-intent")
            raise AssertionError("The later grant must not run for a different Android user")
        f.install = changed
        with f.patches(), self.assertRaises(wizard.UnsafePrecondition):
            f.run()
        self.assertTrue(Path(f.audit.value["backup_path"]).is_file())
        self.assertFalse(any(event["kind"] == "permission-grant-intent" for event in f.audit.value["events"]))

    def test_helper_enable_is_verified_before_notification_setup(self):
        f = self.fixture
        with f.patches():
            f.run()
        names = [name for name, value in f.actions]
        self.assertLess(names.index("enable"), names.index("notification"))
        self.assertEqual(f.audit.value["setup_tasks"]["helper_enable"]["status"], "verified")

    def test_main_returns_follow_up_code_and_durable_concrete_report(self):
        f = self.fixture
        with f.patches(), mock.patch.dict(sys.modules, {"setup_ui": f.ui, "setup_assistant": f.assistant}):
            code = wizard.main(["--serial", "USB", "--apk", str(f.apk), "--state-dir", str(f.root), "--non-interactive", "--wait-seconds", "0"])
        self.assertEqual(code, 2)
        report_path = next(f.root.glob("*-setup-*-report.json"))
        report = json.loads(report_path.read_text())
        self.assertEqual(report["status"], "setup-needs-follow-up")
        self.assertEqual(report["setup_tasks"]["original_phone_backup"]["status"], "verified")
        self.assertEqual(report["setup_tasks"]["physical_car_acceptance"]["status"], "pending")


if __name__ == "__main__":
    unittest.main()
