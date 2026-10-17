"""Synthetic Android shell fixtures only: these tests never contact a phone."""
import copy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import setup_assistant as setup


def identity():
    return {"adb_serial": "SYNTHETIC", "hardware_serial": "SYNTHETIC-PHONE",
            "manufacturer": "Bigme", "model": "HiBreak", "sdk": "34",
            "fingerprint": "SYNTHETIC/Android14", "initial_dpi": "276"}


class Audit:
    def __init__(self):
        self.value, self.events, self.saved = {}, [], []

    def update(self, **values):
        self.value.update(copy.deepcopy(values))
        self.saved.append(copy.deepcopy(self.value))

    def event(self, kind, **values):
        self.events.append({"kind": kind, **copy.deepcopy(values)})


class Android14:
    def __init__(self, audit, holders=None, google_mic=False, aa_mic=True, bound=True):
        self.audit, self.serial = audit, "SYNTHETIC"
        self.holders = [setup.GOOGLE] if holders is None else holders
        self.bound = bound
        self.commands = []
        self.user = 0
        self.writes = []
        self.shared_uid = False
        self.fail_grant = False
        self.ignore_uid_write = False
        self.identity_changed = False
        self.role_grants_sms = False
        self.user_choice_google = False
        self.one_time_google = False
        self.microphones = {
            setup.GOOGLE: {"uid": 10198, "granted": google_mic,
                           "uid_mode": "foreground" if google_mic else "ignore", "package_mode": "allow"},
            setup.AA: {"uid": 10098, "granted": aa_mic,
                       "uid_mode": "foreground" if aa_mic else "ignore", "package_mode": "foreground"}}
        self.sms = False

    def identity(self, serial):
        result = identity()
        if self.identity_changed:
            result["hardware_serial"] = "OTHER-SYNTHETIC-PHONE"
        return result

    def package_dump(self, package):
        mic = self.microphones[package]
        return ("Packages:\n  Package [" + package + "] (synthetic):\n"
                "    User 0: installed=true hidden=false suspended=false enabled=0\n"
                "      runtime permissions:\n"
                f"        {setup.MIC}: granted={str(mic['granted']).lower()}, flags=[ {'ONE_TIME' if package == setup.GOOGLE and self.one_time_google else 'USER_SENSITIVE_WHEN_GRANTED'} ]\n"
                f"        android.permission.READ_SMS: granted={str(self.sms).lower()}, flags=[]\n"
                "    User 10: installed=true hidden=false suspended=false enabled=0\n"
                f"      runtime permissions:\n        {setup.MIC}: granted=true, flags=[ USER_SET ]\n"
                "Queries:\n")

    def voice_dump(self):
        component = setup.GOOGLE_SERVICE if self.holders == [setup.GOOGLE] else "other.assistant/other.assistant.Service"
        return ("VOICE INTERACTION MANAGER (dumpsys voiceinteraction)\n"
                f"  mCurUser: {self.user}\n  mEnableService: true\n  mTemporarilyDisabled: false\n"
                f"  mComponent={component}\n  mBound={str(self.bound).lower()} mService=SYNTHETIC\n")

    def shell(self, *args, check=True):
        self.commands.append(args)
        output = ""
        if args == ("am", "get-current-user"):
            output = str(self.user)
        elif args[:3] == ("cmd", "role", "get-role-holders"):
            output = "\n".join(self.holders)
        elif args[:1] == ("settings",):
            self.assert_read_only_settings(args)
            if not self.holders:
                output = "null"
            elif self.holders == [setup.GOOGLE]:
                output = setup.GOOGLE_SERVICE
            else:
                output = self.holders[0] + "/.Service"
        elif args == ("dumpsys", "voiceinteraction"):
            output = self.voice_dump()
        elif args[:3] == ("pm", "list", "packages"):
            if "--uid" in args:
                uid = int(args[args.index("--uid") + 1])
                package = next(package for package, value in self.microphones.items() if value["uid"] == uid)
                output = "package:" + package
                if self.shared_uid:
                    output += "\npackage:unrelated.shared"
            else:
                package = args[-1]
                output = f"package:{package} uid:{self.microphones[package]['uid']}"
        elif args[:2] == ("dumpsys", "package"):
            output = self.package_dump(args[2])
        elif args[:3] == ("cmd", "appops", "get"):
            target = args[-2]
            if target.isdigit():
                mic = next(value for value in self.microphones.values() if value["uid"] == int(target))
                output = "No operations." if mic["uid_mode"] == "default" else "RECORD_AUDIO: " + mic["uid_mode"]
            else:
                mic = self.microphones[target]
                prefix = "" if mic["uid_mode"] == "default" else "Uid mode: RECORD_AUDIO: " + mic["uid_mode"] + "\n"
                output = prefix + "RECORD_AUDIO: " + mic["package_mode"] + "; time=+5s48ms ago; duration=+2s20ms"
        elif args[:3] == ("cmd", "role", "add-role-holder"):
            self.record_write(args)
            self.holders = [args[-2]]
            if self.role_grants_sms:
                self.sms = True
        elif args[:2] == ("pm", "grant"):
            self.record_write(args)
            self.assertEqual(args[-1], setup.MIC)
            if self.fail_grant:
                raise setup.shared.Refusal("SYNTHETIC grant failure")
            self.microphones[args[-2]]["granted"] = True
        elif args[:3] == ("cmd", "appops", "set"):
            self.record_write(args)
            mic = self.microphones[args[-3]]
            if "--uid" in args:
                if not self.ignore_uid_write:
                    mic["uid_mode"] = args[-1]
            else:
                mic["package_mode"] = args[-1]
        elif args[:2] == ("am", "start"):
            self.assertEqual(args[-1], "android.settings.VOICE_INPUT_SETTINGS")
            if self.user_choice_google:
                self.holders = [setup.GOOGLE]
            output = "Starting: Intent { act=android.settings.VOICE_INPUT_SETTINGS }"
        else:
            raise AssertionError(args)
        return SimpleNamespace(stdout=output, stderr="", returncode=0)

    def record_write(self, args):
        # Every command that can change configuration must have a durable intent.
        report = self.audit.value["assistant_setup"]
        assert report["before"] is not None
        assert report["changes"][-1]["command"] == list(args)
        assert not report["changes"][-1]["applied"]
        assert self.audit.events[-1]["kind"] == "assistant-write-intent"
        self.writes.append(args)

    @staticmethod
    def assertEqual(a, b):
        assert a == b, (a, b)

    @staticmethod
    def assert_read_only_settings(args):
        assert args[3] == "get" and args[-1] in {"assistant", "voice_interaction_service"}, args


class SetupAssistantTests(unittest.TestCase):
    def setUp(self):
        self.audit = Audit()
        self.adb = Android14(self.audit)
        self.sleep = mock.patch.object(setup.time, "sleep", return_value=None)
        self.sleep.start()
        self.addCleanup(self.sleep.stop)

    def configure(self, prompt=None):
        return setup.configure_assistant(self.adb, self.audit, identity(), prompt=prompt)

    def test_repair_google_mic_preserves_working_android_auto_modes(self):
        result = self.configure()
        self.assertEqual(result["status"], "configured")
        self.assertTrue(all(result["verified"].values()))
        self.assertFalse(result["head_unit_audio_tested"])
        self.assertFalse(result["wakeword_preferences_written"])
        self.assertEqual(self.adb.microphones[setup.AA]["package_mode"], "foreground")
        self.assertTrue(all(setup.AA not in command for command in self.adb.writes))
        self.assertEqual(self.adb.microphones[setup.GOOGLE]["uid_mode"], "foreground")
        self.assertEqual(result["before"]["microphones"][setup.GOOGLE]["uid_mode"], "ignore")
        self.assertTrue(all(change["applied"] and change["verified"] for change in result["changes"]))

    def test_idempotent_when_already_configured(self):
        self.adb.microphones[setup.GOOGLE].update(granted=True, uid_mode="foreground")
        result = self.configure()
        self.assertEqual(result["status"], "configured")
        self.assertEqual(self.adb.writes, [])

    def test_empty_role_selected_and_android_managed_permissions_reported(self):
        self.adb.holders = []
        self.adb.role_grants_sms = True
        result = self.configure()
        self.assertEqual(result["status"], "configured")
        self.assertIn("android.permission.READ_SMS", result["permission_deltas_except_microphone"][setup.GOOGLE])
        explicit = [command for command in self.adb.writes if command[:2] == ("pm", "grant")]
        self.assertTrue(all(command[-1] == setup.MIC for command in explicit))

    def test_other_assistant_without_prompt_preserved_without_writes(self):
        self.adb.holders = ["other.assistant"]
        result = self.configure()
        self.assertEqual(result["status"], "pending-user-choice")
        self.assertEqual(self.adb.holders, ["other.assistant"])
        self.assertEqual(self.adb.writes, [])

    def test_other_assistant_explicit_decline_never_opens_or_replaces(self):
        self.adb.holders = ["other.assistant"]
        result = self.configure(prompt=lambda message: "no")
        self.assertEqual(result["status"], "pending-user-choice")
        self.assertFalse(any(command[:2] == ("am", "start") for command in self.adb.commands))
        self.assertEqual(self.adb.writes, [])

    def test_other_assistant_guided_choice_verified_before_mic(self):
        self.adb.holders = ["other.assistant"]
        self.adb.user_choice_google = True
        choices = iter(["yes", ""])
        result = self.configure(prompt=lambda message: next(choices))
        self.assertEqual(result["status"], "configured")
        self.assertFalse(any(command[:3] == ("cmd", "role", "add-role-holder") for command in self.adb.writes))
        self.assertEqual(result["changes"][0]["kind"], "user-selected-assistant")

    def test_guided_choice_not_completed_stays_pending_and_no_mic_changes(self):
        self.adb.holders = ["other.assistant"]
        choices = iter(["yes", ""])
        result = self.configure(prompt=lambda message: next(choices))
        self.assertEqual(result["status"], "pending-user-choice")
        self.assertEqual(self.adb.writes, [])

    def test_role_alone_does_not_prove_voice_service_bound(self):
        self.adb.bound = False
        result = self.configure()
        self.assertEqual(result["status"], "pending-verification")
        self.assertFalse(result["verified"]["google_voice_service_bound"])
        self.assertFalse(result["head_unit_audio_tested"])

    def test_runtime_grant_alone_does_not_prove_ignored_uid_repaired(self):
        self.adb.ignore_uid_write = True
        with self.assertRaisesRegex(setup.shared.Refusal, "While-using UID"):
            self.configure()
        result = self.audit.value["assistant_setup"]
        self.assertEqual(result["status"], "partial-failure")
        self.assertTrue(result["changes"][-1]["applied"])
        self.assertFalse(result["changes"][-1]["verified"])
        self.assertEqual(result["changes"][-1]["readback"]["uid_mode"], "ignore")

    def test_shared_uid_refused_before_any_mic_grant(self):
        self.adb.shared_uid = True
        with self.assertRaisesRegex(setup.shared.Refusal, "shared"):
            self.configure()
        self.assertEqual(self.adb.writes, [])

    def test_blocked_android_auto_is_repaired(self):
        self.adb.microphones[setup.AA].update(granted=False, uid_mode="ignore", package_mode="ignore")
        result = self.configure()
        self.assertEqual(result["status"], "configured")
        self.assertEqual(self.adb.microphones[setup.AA]["uid_mode"], "foreground")
        self.assertEqual(self.adb.microphones[setup.AA]["package_mode"], "allow")

    def test_partial_command_failure_keeps_prior_state_and_unverified_intent(self):
        self.adb.fail_grant = True
        with self.assertRaisesRegex(setup.shared.Refusal, "grant failure"):
            self.configure()
        result = self.audit.value["assistant_setup"]
        self.assertFalse(result["before"]["microphones"][setup.GOOGLE]["runtime_granted"])
        self.assertFalse(result["changes"][-1]["applied"])
        self.assertFalse(result["changes"][-1]["verified"])

    def test_identity_change_rejected_before_writes(self):
        self.adb.identity_changed = True
        with self.assertRaisesRegex(setup.shared.Refusal, "identity/build changed"):
            self.configure()
        self.assertEqual(self.adb.writes, [])

    def test_parse_does_not_borrow_grant_from_second_user(self):
        parsed = setup.parse_package(self.adb.package_dump(setup.GOOGLE), setup.GOOGLE, 0)
        self.assertFalse(parsed[setup.MIC]["granted"])
        self.assertTrue(setup.parse_package(self.adb.package_dump(setup.GOOGLE), setup.GOOGLE, 10)[setup.MIC]["granted"])

    def test_saved_live_format_separates_uid_from_package_mode(self):
        parsed = setup.parse_appops("Uid mode: RECORD_AUDIO: foreground\nRECORD_AUDIO: allow; time=+5s48ms ago; duration=+2s20ms")
        self.assertEqual(parsed, {"uid_mode": "foreground", "package_mode": "allow"})
        self.assertEqual(setup.parse_appops("No operations.", uid_only=True), "default")
        with self.assertRaises(setup.shared.Refusal):
            setup.parse_appops("")
        with self.assertRaises(setup.shared.Refusal):
            setup.parse_appops("RECORD_AUDIO: madeup")

    def test_shared_user_runtime_grants_ignore_hidden_stub_and_query_user(self):
        text = f"""Packages:
  Package [{setup.AA}] (active):
    sharedUser=SharedUserSetting{{abcd {setup.AA}/10098}}
    User 0: installed=true hidden=false suspended=false enabled=0
Hidden system packages:
  Package [{setup.AA}] (stub):
    User 0: installed=true hidden=false suspended=false enabled=0
      runtime permissions:
        {setup.MIC}: granted=false, flags=[]
Queries:
    User 0:
Shared users:
  SharedUser [{setup.AA}] (abcd):
    appId=10098
    User 0:
      runtime permissions:
        {setup.MIC}: granted=true, flags=[ GRANTED_BY_ROLE]
Dexopt state:
"""
        self.assertEqual(setup.parse_package(text, setup.AA, 0)[setup.MIC],
                         {"granted": True, "flags": " GRANTED_BY_ROLE"})

    def test_one_time_google_grant_never_claims_durable_setup(self):
        self.adb.microphones[setup.GOOGLE].update(granted=True, uid_mode="foreground")
        self.adb.one_time_google = True
        result = self.configure()
        self.assertEqual(result["status"], "pending-verification")
        self.assertFalse(result["verified"]["google_microphone_not_one_time"])


if __name__ == "__main__":
    unittest.main()
