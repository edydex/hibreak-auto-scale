"""Scoped Android 14 assistant setup for the adjacent HiBreak setup wizard.

Only the Assistant role and RECORD_AUDIO are written. No settings keys, wake-word
preferences, application data, or other explicit permission grants are changed.
An Assistant role change can itself grant Android-managed role privileges; those
permission deltas are reported. Configuration readback is not an audio test.
"""
from __future__ import annotations

import re
import time

import hibreak_aa as shared

GOOGLE = "com.google.android.googlequicksearchbox"
AA = "com.google.android.projection.gearhead"
MIC = "android.permission.RECORD_AUDIO"
ROLE = "android.app.role.ASSISTANT"
GOOGLE_SERVICE = GOOGLE + "/com.google.android.voiceinteraction.GsaVoiceInteractionService"
_PACKAGE = re.compile(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z0-9_]+)+")
_MODES = {"allow", "ignore", "deny", "default", "foreground"}


def _output(adb, *args):
    result = adb.shell(*args)
    text = result.stdout.strip()
    if re.search(r"(?im)^\s*(?:error:|exception|securityexception|unknown command|unknown option)",
                 text + "\n" + result.stderr):
        raise shared.Refusal("Android rejected assistant command: " + " ".join(args[:3]))
    return text


def _user(adb):
    text = _output(adb, "am", "get-current-user")
    if not re.fullmatch(r"\d+", text):
        raise shared.Refusal("Could not identify the current Android user")
    return int(text)


def _role(adb, user):
    text = _output(adb, "cmd", "role", "get-role-holders", "--user", str(user), ROLE)
    holders = text.splitlines() if text else []
    if len(holders) > 1 or any(not _PACKAGE.fullmatch(item) for item in holders):
        raise shared.Refusal("Assistant role output was unrecognized or nonexclusive")
    return holders


def _component(text):
    if text in {"", "null"}:
        return None
    if not re.fullmatch(r"[A-Za-z0-9_.]+/[A-Za-z0-9_.$]+", text):
        raise shared.Refusal("Android returned an unrecognized assistant component")
    package, name = text.split("/", 1)
    return package + "/" + (package + name if name.startswith(".") else name)


def _role_state(adb, user):
    holders = _role(adb, user)
    settings = {key: _component(_output(adb, "settings", "--user", str(user), "get", "secure", key))
                for key in ("assistant", "voice_interaction_service")}
    dump = _output(adb, "dumpsys", "voiceinteraction")
    if "VOICE INTERACTION MANAGER" not in dump or "Permission Denial" in dump:
        raise shared.Refusal("Voice-interaction service state could not be read")
    components = re.findall(r"(?m)^\s*mComponent=(\S+)\s*$", dump)
    current_users = re.findall(r"(?m)^\s*mCurUser:\s*(\d+)\s*$", dump)
    bound = (len(components) == 1 and _component(components[0]) == GOOGLE_SERVICE
             and bool(re.search(r"(?m)^\s*mBound=true\b", dump))
             and current_users == [str(user)]
             and "mTemporarilyDisabled: true" not in dump
             and "mEnableService: false" not in dump)
    return {"holders": holders, **settings, "google_service_bound": bound,
            "voiceinteraction_raw": dump}


def _dump_section(text, heading):
    found = re.search(r"(?ms)^" + re.escape(heading) + r":\n(.*?)(?=^\S|\Z)", text)
    if found is None:
        raise shared.Refusal("Required package dump section missing: " + heading)
    return found.group(1)


def _dump_record(text, kind, name):
    starts = list(re.finditer(r"(?m)^  " + re.escape(kind) + r" \[([^\]]+)\][^\n]*\n", text))
    selected = [(i, match) for i, match in enumerate(starts) if match.group(1) == name]
    if len(selected) != 1:
        raise shared.Refusal("Required package dump record missing or ambiguous: " + name)
    index, match = selected[0]
    return text[match.end():starts[index + 1].start() if index + 1 < len(starts) else len(text)]


def _user_body(text, user):
    sections = list(re.finditer(r"(?m)^ {4}User (\d+):([^\n]*)", text))
    selected = [(i, match) for i, match in enumerate(sections) if int(match.group(1)) == user]
    if len(selected) != 1:
        raise shared.Refusal("Selected-user package state missing or ambiguous")
    index, match = selected[0]
    end = sections[index + 1].start() if index + 1 < len(sections) else len(text)
    return match.group(2), text[match.end():end]


def parse_package(text, package, user):
    """Read active package grants, excluding hidden stubs and other users.

    AA uses a shared-user setting even when it is the only package with that
    UID. Android dumps its runtime grants under Shared users, so associate that
    exact record through the active Package's sharedUser field.
    """
    active = _dump_record(_dump_section(text, "Packages"), "Package", package)
    state, body = _user_body(active, user)
    if not re.search(r"\binstalled=true\b", state) or re.search(r"\b(?:hidden|suspended)=true\b", state):
        raise shared.Refusal("Required assistant package is unavailable for this user: " + package)
    enabled = re.search(r"\benabled=(\d+)\b", state)
    if enabled is None or enabled.group(1) not in {"0", "1"}:
        raise shared.Refusal("Required assistant package is disabled: " + package)
    runtime = re.search(r"(?m)^\s+runtime permissions:\s*$", body)
    if runtime is None:
        shared_user = re.search(r"(?m)^    sharedUser=SharedUserSetting\{\S+ ([^/\s]+)/\d+\}\s*$", active)
        if shared_user:
            record = _dump_record(_dump_section(text, "Shared users"), "SharedUser", shared_user.group(1))
            _, body = _user_body(record, user)
            runtime = re.search(r"(?m)^\s+runtime permissions:\s*$", body)
    if runtime is None:
        raise shared.Refusal("Runtime permission section missing for " + package)
    grants = {}
    for line in body[runtime.end():].splitlines():
        grant = re.fullmatch(r"\s+([A-Za-z0-9_.]+): granted=(true|false)(?:, flags=\[([^\]]*)\])?\s*", line)
        if grant:
            grants[grant.group(1)] = {"granted": grant.group(2) == "true", "flags": grant.group(3) or ""}
        elif line.strip() and not line.startswith(" " * 8):
            break
    if MIC not in grants:
        raise shared.Refusal("RECORD_AUDIO runtime state missing for " + package)
    return grants


def parse_appops(text, uid_only=False):
    """AppOps 'get PACKAGE' prints UID override and package state separately."""
    if re.search(r"(?im)(?:error:|unknown package|permission denial|exception)", text):
        raise shared.Refusal("Microphone AppOps readback failed")
    uid = re.findall(r"(?m)^Uid mode:\s*RECORD_AUDIO:\s*(\w+)\b", text)
    modes = re.findall(r"(?m)^\s*RECORD_AUDIO:\s*(\w+)\b", text)
    if len(uid) > 1 or len(modes) > 1 or any(mode not in _MODES for mode in uid + modes):
        raise shared.Refusal("Unrecognized microphone AppOps output")
    if not uid and not modes and not re.search(r"\bNo (?:operations|ops)(?:\.|\s|$)", text):
        raise shared.Refusal("Empty or unrecognized microphone AppOps output")
    if uid_only:
        # Numeric UID lookup returns an ordinary RECORD_AUDIO line, without a
        # package, or 'No operations.' when there is no explicit UID override.
        if uid and modes and uid[0] != modes[0]:
            raise shared.Refusal("Conflicting UID microphone AppOps output")
        return (uid or modes or ["default"])[0]
    return {"uid_mode": uid[0] if uid else "default",
            "package_mode": modes[0] if modes else "default"}


def _microphone(adb, package, user):
    listing = _output(adb, "pm", "list", "packages", "--user", str(user), "-U", package)
    matches = re.findall(r"(?m)^package:" + re.escape(package) + r" uid:(\d+)\s*$", listing)
    if len(matches) != 1:
        raise shared.Refusal("Could not identify the installed UID for " + package)
    uid = int(matches[0])
    if uid // 100000 != user:
        raise shared.Refusal("Package UID belongs to another Android user")
    dump = _output(adb, "dumpsys", "package", package)
    grants = parse_package(dump, package, user)
    package_raw = _output(adb, "cmd", "appops", "get", "--user", str(user), package, "RECORD_AUDIO")
    modes = parse_appops(package_raw)
    # Numeric UID lookup is supported by Android's AppOps shell and excludes
    # package-level entries. This independently verifies the UID override.
    uid_raw = _output(adb, "cmd", "appops", "get", str(uid), "RECORD_AUDIO")
    uid_mode = parse_appops(uid_raw, uid_only=True)
    if uid_mode != modes["uid_mode"]:
        raise shared.Refusal("Package and UID microphone AppOps disagree for " + package)
    return {"uid": uid, "runtime_permissions": grants,
            "runtime_granted": grants[MIC]["granted"],
            "one_time_grant": bool(re.search(r"\bONE_TIME\b", grants[MIC]["flags"])), **modes,
            "package_appops_raw": package_raw, "uid_appops_raw": uid_raw}


def _usable(mic):
    return mic["runtime_granted"] and not mic["one_time_grant"] and all(mic[key] not in {"ignore", "deny"}
                                           for key in ("uid_mode", "package_mode"))


def _guard(adb, identity, user):
    shared.guard_identity(identity, adb.identity(adb.serial))
    if _user(adb) != user:
        raise shared.Refusal("Android user changed during assistant setup")


def _private_uid(adb, package, mic, user):
    text = _output(adb, "pm", "list", "packages", "--user", str(user), "--uid", str(mic["uid"]))
    packages = re.findall(r"(?m)^package:([A-Za-z0-9_.]+)(?:\s+uid:\d+)?\s*$", text)
    if packages != [package]:
        raise shared.Refusal("Refusing a UID microphone change shared with another application: " + package)


def _permission_delta(before, after):
    return {name: {"before": before.get(name), "after": after.get(name)}
            for name in sorted(before.keys() | after.keys())
            if before.get(name) != after.get(name) and name != MIC}


def configure_assistant(adb, audit, identity, prompt=input):
    """Configure scoped prerequisites; return a report, or raise shared.Refusal.

    A pending report is incomplete, not success. prompt=None never replaces a
    different assistant. Existing working AA mic/AppOps are preserved. Every
    mutation has a durable intent before execution and a fresh readback after.
    No automatic rollback is attempted after a partial operation: the audit
    preserves precise previous modes/grants and the platform-owned role state.
    """
    report = {"status": "preparing", "before": None, "after": None, "changes": [],
              "verified": {}, "head_unit_audio_tested": False,
              "wakeword_preferences_written": False,
              "wakeword_private_preferences_readable": False,
              "notes": ["No wake-word preference is changed; existing Voice Match selection is preserved.",
                        "Configuration readback does not verify car microphone, recognition, internet, or response audio.",
                        "Android may grant role-managed permissions when its default Assistant changes."]}

    def save():
        audit.update(assistant_setup=report)

    def mutate(kind, command, package=None):
        _guard(adb, identity, user)
        if kind == "select-google-role" and _role(adb, user):
            raise shared.Refusal("Assistant choice changed; rerun setup to review it")
        # None means outcome not yet known. If the transport times out after
        # Android accepted a write, the journal must not claim it did not apply.
        event = {"kind": kind, "command": list(command), "package": package, "applied": None, "verified": False}
        report["changes"].append(event)
        save()
        audit.event("assistant-write-intent", operation=kind, command=list(command), package=package)
        _output(adb, *command)
        event["applied"] = True
        save()
        return event

    def snapshot():
        return {"user": user, "role": _role_state(adb, user),
                "microphones": {package: _microphone(adb, package, user) for package in (GOOGLE, AA)}}

    try:
        shared.guard_identity(identity, adb.identity(adb.serial))
        if str(identity.get("sdk")) != "34":
            raise shared.Refusal("Assistant automation supports the verified Android 14 interface only")
        user = _user(adb)
        before = snapshot()
        report["before"] = before
        save()
        role = before["role"]
        foreign = role["holders"] not in ([], [GOOGLE]) or any(
            component and not component.startswith(GOOGLE + "/")
            for component in (role["assistant"], role["voice_interaction_service"]))
        if foreign:
            report["status"] = "pending-user-choice"
            report["notes"].append("A different assistant is selected; it has not been replaced.")
            save()
            answer = prompt("A different assistant is selected. Open the phone's assistant chooser to select Google? [y/N] ") if prompt else ""
            if answer.strip().lower() not in {"y", "yes"}:
                return report
            _guard(adb, identity, user)
            audit.event("assistant-role-chooser-open-intent", user=user)
            _output(adb, "am", "start", "--user", str(user), "-a", "android.settings.VOICE_INPUT_SETTINGS")
            prompt("On the phone, choose Google as the default digital assistant, then press Enter here. ")
            _guard(adb, identity, user)
            role = _role_state(adb, user)
            if role["holders"] != [GOOGLE]:
                report["after"] = snapshot()
                report["notes"].append("Google selection was not verified. Continue in the phone's Default apps > Digital assistant settings.")
                save()
                return report
            report["changes"].append({"kind": "user-selected-assistant", "applied": True, "verified": True})
            save()
        if not role["holders"]:
            # Re-read immediately before changing a formerly empty role, so a
            # choice made during preflight is never silently overwritten.
            _guard(adb, identity, user)
            if _role(adb, user):
                raise shared.Refusal("Assistant choice changed; rerun setup to review it")
            event = mutate("select-google-role", ("cmd", "role", "add-role-holder", "--user", str(user), ROLE, GOOGLE, "0"), GOOGLE)
            role = _role_state(adb, user)
            event["verified"] = role["holders"] == [GOOGLE]
            save()
            if not event["verified"]:
                raise shared.Refusal("Android did not verify Google as the default assistant")

        for package in (GOOGLE, AA):
            mic = _microphone(adb, package, user)
            if mic["uid"] != before["microphones"][package]["uid"]:
                raise shared.Refusal("Application UID changed during assistant setup: " + package)
            # A working AA grant is never tightened just to match Google.
            if package == AA and _usable(mic):
                continue
            if not mic["runtime_granted"] or mic["uid_mode"] != "foreground" or mic["package_mode"] != "allow":
                _private_uid(adb, package, mic, user)
            if not mic["runtime_granted"]:
                event = mutate("grant-microphone", ("pm", "grant", "--user", str(user), package, MIC), package)
                mic = _microphone(adb, package, user)
                event["verified"] = mic["runtime_granted"]
                event["readback"] = mic
                save()
                if not event["verified"]:
                    raise shared.Refusal("Microphone runtime grant was not verified for " + package)
            if mic["uid_mode"] != "foreground":
                event = mutate("microphone-while-using", ("cmd", "appops", "set", "--user", str(user), "--uid", package, "RECORD_AUDIO", "foreground"), package)
                mic = _microphone(adb, package, user)
                event["verified"] = mic["uid_mode"] == "foreground"
                event["readback"] = mic
                save()
                if not event["verified"]:
                    raise shared.Refusal("While-using UID microphone mode was not verified for " + package)
            if mic["package_mode"] != "allow":
                event = mutate("microphone-package-allow", ("cmd", "appops", "set", "--user", str(user), package, "RECORD_AUDIO", "allow"), package)
                mic = _microphone(adb, package, user)
                event["verified"] = mic["package_mode"] == "allow"
                event["readback"] = mic
                save()
                if not event["verified"]:
                    raise shared.Refusal("Package microphone AppOps was not verified for " + package)

        # Binding can follow the asynchronous role change. Three bounded reads
        # allow that transition; failure remains pending, never a speech claim.
        for attempt in range(3):
            _guard(adb, identity, user)
            after = snapshot()
            report["after"] = after
            google = after["microphones"][GOOGLE]
            role = after["role"]
            report["verified"] = {
                "google_role": role["holders"] == [GOOGLE],
                "google_assistant_setting": bool(role["assistant"] and role["assistant"].startswith(GOOGLE + "/")),
                "google_voice_service_setting": role["voice_interaction_service"] == GOOGLE_SERVICE,
                "google_voice_service_bound": role["google_service_bound"],
                "google_runtime_microphone": google["runtime_granted"],
                "google_microphone_not_one_time": not google["one_time_grant"],
                "google_uid_microphone_foreground": google["uid_mode"] == "foreground",
                "google_package_microphone_allow": google["package_mode"] == "allow",
                "android_auto_microphone_usable": _usable(after["microphones"][AA])}
            report["permission_deltas_except_microphone"] = {
                package: _permission_delta(before["microphones"][package]["runtime_permissions"],
                                           after["microphones"][package]["runtime_permissions"])
                for package in (GOOGLE, AA)}
            if all(report["verified"].values()):
                report["status"] = "configured"
                save()
                return report
            if attempt < 2:
                time.sleep(0.5)
        report["status"] = "pending-verification"
        report["notes"].append("Complete Google assistant onboarding/default selection on the phone, then rerun. Do not assume voice audio works yet.")
        for package, mic in after["microphones"].items():
            if mic["one_time_grant"]:
                report["notes"].append("Choose 'Allow only while using the app' for microphone in App permissions for " + package + "; its current microphone grant is one-time.")
        save()
        return report
    except BaseException as error:
        report["status"] = "partial-failure" if report["changes"] else "refused"
        report["error"] = type(error).__name__ + ": " + str(error)
        save()
        raise
