#!/usr/bin/env python3
"""Shared HiBreak setup: own-phone backup, companion, settings and car checklist.

The Mac/Linux/Windows launchers prepare private Python/ADB tools when needed.
Only the standard library is used. The person identifies the actual car and sets
the Bigme padlock; supported readbacks notice those actions automatically.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import sys
import time
from types import SimpleNamespace
import uuid

import hibreak_aa as shared
import install_on_mac as installer

ROOT = Path(__file__).resolve().parent
AA = shared.PACKAGES[0]
DEFAULT_KEEP = ("Maps", "Messages", "Reminder", "Heritage", "NewPipe")
RELEASE = json.loads((ROOT / "release.json").read_text(encoding="utf-8"))
if (RELEASE.get("format") != "hibreak-auto-scale-release-v1"
        or RELEASE.get("package") != installer.APP
        or not re.fullmatch(r"[a-f0-9]{64}", str(RELEASE.get("apk_sha256", "")))
        or type(RELEASE.get("version_code")) is not int
        or not isinstance(RELEASE.get("version_name"), str)):
    raise shared.Refusal("The release metadata is missing or invalid; use the complete kit")
EXPECTED_APK_SHA256 = RELEASE["apk_sha256"]
EXPECTED_VERSION = (RELEASE["version_code"], RELEASE["version_name"])


class UnsafePrecondition(shared.Refusal):
    """Stop all setup writes when identity or disconnected state is uncertain."""


class MutationAudit:
    """Add user/identity checks to existing durable intents without changing tools."""
    INTENTS = {"install-intent", "permission-grant-intent", "idle-whitelist-add-intent",
               "assistant-write-intent", "assistant-role-chooser-open-intent",
               "nearby-devices-grant-intent"}

    def __init__(self, audit, before_mutation):
        self.audit, self.before_mutation = audit, before_mutation

    def __getattr__(self, name):
        return getattr(self.audit, name)

    def event(self, kind, **details):
        if kind in self.INTENTS:
            self.before_mutation()
        self.audit.event(kind, **details)


def require_disconnected(adb):
    """Conservative presence check; never choose a target DPI or use old logs."""
    text = adb.shell("dumpsys", "display").stdout
    if not text.strip() or "Permission Denial" in text:
        raise UnsafePrecondition("Cannot confirm disconnected Android Auto from display diagnostics")
    offset = count = 0
    marker = "DisplayDeviceInfo{"
    while True:
        start = text.find(marker, offset)
        if start < 0:
            break
        depth, quoted, escaped = 1, False, False
        end = start + len(marker)
        while end < len(text) and depth:
            char = text[end]
            if quoted:
                if escaped:
                    escaped = False
                elif char == "\\":
                    escaped = True
                elif char == '"':
                    quoted = False
            elif char == '"':
                quoted = True
            elif char == "{":
                depth += 1
            elif char == "}":
                depth -= 1
            end += 1
        if depth or quoted:
            raise UnsafePrecondition("Display information is incomplete; disconnect Android Auto and retry")
        if AA in text[start:end]:
            raise UnsafePrecondition("Disconnect Android Auto before backing up or changing phone preferences")
        offset, count = end, count + 1
    if not count:
        raise UnsafePrecondition("No readable native display entries; refusing to assume Android Auto is disconnected")
    return {"status": "verified", "android_auto_display_present": False, "native_entries": count}


def wait_for_phone(adb, requested, seconds, announce=print):
    """Wait for the physical authorization step without restarting setup."""
    if seconds <= 0:
        return shared.select_device(adb, requested)
    deadline, last = time.monotonic() + seconds, None
    while True:
        lines = adb.run("devices", "-l", selected=False).stdout.splitlines()
        devices = [line.split()[:2] for line in lines if len(line.split()) >= 2
                   and line.split()[1] in {"device", "unauthorized", "offline", "no"}]
        relevant = [pair for pair in devices if not requested or pair[0] == requested]
        unauthorized = [pair for pair in relevant if pair[1] == "unauthorized"]
        online = [pair for pair in relevant if pair[1] == "device"]
        if online and not unauthorized:
            return shared.select_device(adb, requested)
        status = "authorization" if unauthorized else "connection"
        if status != last:
            announce("On the phone, accept Allow USB debugging (and Allow accessory on the computer if shown)."
                     if unauthorized else
                     "Waiting for your HiBreak. Plug it in, unlock it and enable USB debugging. "
                     "Linux may need USB access rules; Windows may need its Android USB driver.")
            last = status
        if time.monotonic() >= deadline:
            raise shared.Refusal("The phone is not authorized yet. Complete the phone/USB prompt, then run setup again.")
        time.sleep(min(2, max(0, deadline - time.monotonic())))


def helper_service_absent(adb):
    text = adb.shell("dumpsys", "activity", "services", installer.APP).stdout
    if "ACTIVITY MANAGER SERVICES" not in text and "(nothing)" not in text:
        raise UnsafePrecondition("Cannot verify whether an existing helper service is stopped")
    return not re.search(r"ServiceRecord\{[^\n]*\b" + re.escape(installer.APP) + r"/", text)


def helper_screen_is_restored(screen):
    texts = [node.get("text", "") for node in screen.nodes
             if node.get("package") == installer.APP]
    for text in texts:
        first = text.split("\n", 1)[0]
        lines = text.splitlines()
        known_off = (first == "Automatic scaling is off."
                     or first.startswith("Automatic scaling is off. Owned phone preferences restored."))
        if (known_off and "Automatic scaling: off" in lines and "Paired-car automatic: off" in lines
                and "Finishing or recovering" not in text and "Needs attention" not in text):
            return True
    return False


def task(audit, name, status, **details):
    stages = dict(audit.value.get("setup_tasks", {}))
    stages[name] = {"status": status, "utc": shared.now(), **details}
    audit.update(setup_tasks=stages, status="setup-in-progress")


def human_step(audit, name, instructions, prompt, non_interactive):
    print("\n" + instructions)
    task(audit, name, "pending", instructions=instructions,
         verification="Requires a person; no machine verification is claimed")
    if non_interactive:
        return False
    try:
        answer = prompt("Type done after this step, or press Return to leave it pending: ").strip().casefold()
    except EOFError:
        return False
    if answer in {"quit", "exit", "stop"}:
        raise KeyboardInterrupt()
    if answer != "done":
        return False
    task(audit, name, "user-confirmed", instructions=instructions,
         verification="Confirmed by the person, not independently verified by this script")
    return True


def ensure_existing_helper_restored(adb, ui, audit, prompt, non_interactive):
    if not installer.package_state(adb)["installed"]:
        task(audit, "existing_helper", "not-applicable", note="No previous companion is installed")
        return
    ui.launch("-n", installer.ACTIVITY)
    if helper_screen_is_restored(ui.screen()) and helper_service_absent(adb):
        task(audit, "existing_helper", "verified", note="Known off/restored screen and no helper service")
        return
    completed = human_step(audit, "existing_helper",
        "An existing helper may hold car settings. On the phone press Stop and restore. "
        "Wait for its successful off/restored status before continuing. Do not clear its storage.",
        prompt, non_interactive)
    if not completed:
        raise UnsafePrecondition("Original-phone backup is blocked until the existing helper is verifiably stopped/restored")
    for attempt in range(5):
        if helper_screen_is_restored(ui.screen()) and helper_service_absent(adb):
            task(audit, "existing_helper", "verified", note="Off/restored UI independently checked; helper service absent")
            return
        if attempt < 4:
            time.sleep(0.5)
    raise UnsafePrecondition("The existing helper did not verify off/restored; no new baseline was captured")


def preference_step(audit, name, action, instructions):
    task(audit, name, "pending", instructions=instructions)
    try:
        report = action()
    except UnsafePrecondition:
        raise
    except (shared.Refusal, OSError, ValueError, EOFError) as error:
        task(audit, name, "pending", instructions=instructions, reason=str(error))
        print("This setting needs a phone check: " + instructions)
        return
    status = "verified" if report.get("status") in {"verified", "configured"} else "pending"
    if report.get("requested_but_not_observed"):
        status = "pending"
    task(audit, name, status, result=report, instructions=instructions)


def run_setup(args, audit, ui_module, assistant_module, prompt=input):
    apk = Path(args.apk).expanduser().resolve()
    if not apk.is_file() or hashlib.sha256(apk.read_bytes()).hexdigest() != EXPECTED_APK_SHA256:
        raise shared.Refusal("Use this kit's unmodified HiBreak-Auto-Scale.apk (1.1.1); its release hash did not match")
    keep = tuple(dict.fromkeys(label.strip() for label in (args.keep_app or DEFAULT_KEEP)))
    if any(not label.strip() or len(label) > 100 for label in keep):
        raise shared.Refusal("Each --keep-app must be a nonempty launcher label of at most 100 characters")
    adb = shared.ADB(installer.locate_adb(args.adb), audit, timeout=120)
    identity = wait_for_phone(adb, args.serial, args.wait_seconds)
    audit.update(identity=identity, launcher_keep=list(keep),
                 note="Private phone-specific report. Never copy its backup to another phone.")

    def guard():
        if adb.shell("am", "get-current-user").stdout.strip() != "0":
            raise UnsafePrecondition("This setup supports only Android's primary user (user 0); switch back before continuing")
        try:
            shared.guard_identity(identity, adb.identity(adb.serial))
        except shared.Refusal as error:
            raise UnsafePrecondition("Phone identity/build changed; setup stopped") from error
        require_disconnected(adb)

    guard()
    guarded_audit = MutationAudit(audit, guard)
    folder = audit.path.parent / (audit.path.stem + "-files")
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(folder, 0o700)
    ui = ui_module.Ui(adb, folder, before_mutation=guard)
    ensure_existing_helper_restored(adb, ui, audit, prompt, args.non_interactive)
    print("Saving this phone's own original app display settings…")
    guard()
    bridge = shared.Bridge(adb, shared.locate_jar(args.bridge), identity)
    versions, skipped = shared.choose_packages(None, adb)
    if AA not in versions:
        raise shared.Refusal("Install Android Auto on this phone before running this setup")
    baseline = shared.snapshot(adb, bridge, identity, versions, skipped)
    guard()
    if not helper_service_absent(adb):
        raise UnsafePrecondition("The companion started during backup; stop/restore it and retry")
    backup = folder / "original-phone-policy.json"
    shared.atomic_json(backup, baseline, new=True)
    audit.update(backup_path=str(backup))
    task(audit, "original_phone_backup", "verified", path=str(backup),
         note="Captured from this disconnected phone; no donor backup or guessed DPI")

    guard()
    print("Installing the companion and its scoped permissions…")
    installed = installer.install(SimpleNamespace(apk=str(apk), adb=adb.executable, serial=adb.serial), guarded_audit)
    shared.guard_identity(identity, installed["identity"])
    version = shared.installed_version(adb, installer.APP)
    if not version or (version["version_code"], version["version_name"]) != EXPECTED_VERSION:
        raise UnsafePrecondition("The expected companion version did not verify after installation")
    task(audit, "companion_install", "verified", result=installed, installed_version=version)

    guard()
    preference_step(audit, "android_auto_preferences",
        lambda: ui_module.configure_car_preferences(ui, set(keep)),
        "Android Auto settings > Customize launcher: keep the requested apps; leave protected entries. "
        "Turn Start music automatically off. Missing requested labels need an individual phone check.")
    guard()
    preference_step(audit, "phone_maps_buildings", lambda: ui_module.configure_phone_maps(ui),
        "Phone Maps settings > Navigation > Show raised buildings: off. The projected Maps switch is separate.")
    guard()
    preference_step(audit, "google_assistant",
        lambda: assistant_module.configure_assistant(adb, guarded_audit, identity,
            prompt=prompt if not args.non_interactive else lambda message: ""),
        "Choose Google as the digital assistant if wanted, with Google microphone access only while in use. "
        "Do not replace a different chosen assistant without making that choice on the phone.")

    guard()
    preference_step(audit, "helper_enable", lambda: ui_module.enable_helper(ui),
        "With Android Auto disconnected, tap Enable detection / learn car in HiBreak Auto Scale. "
        "Wait for its waiting-for-Android-Auto status so its own private backup is saved too.")
    preference_step(audit, "vendor_background_lock",
        lambda: ui_module.configure_vendor_lock(ui, interactive=not args.non_interactive),
        "Open Bigme Recents > Process manage and lock only HiBreak Auto Scale with its padlock. "
        "Keep this lock; swiping the individual card away removes it.")
    guard()
    preference_step(audit, "quiet_notification", lambda: ui_module.configure_notification(ui),
        "After enabling the helper, App info > Notifications > Automatic Android Auto scaling > off. "
        "Keep the overall permission, service, Nearby devices access and Bigme padlock. "
        "To unhide later, enable that category and open the helper or tap Refresh status.")
    guard()
    preference_step(audit, "paired_car_selection",
        lambda: ui_module.configure_selected_car(ui, guarded_audit, identity, interactive=not args.non_interactive),
        "Choose your actual already-paired car in HiBreak Auto Scale > Automatic for paired car. "
        "If the car is not paired yet, pair it normally and choose it afterward.")
    # Physical-car checks are a take-away checklist unless requested now. A
    # wired-only receiver cannot be connected to the computer at the same time.
    car_later = args.non_interactive or not args.check_car_now
    human_step(audit, "real_host_learning",
        "Connect the intended real head unit once and let the helper learn its native DPI. "
        "If the first screen stays oversized, wait for adjustment and reconnect within ten seconds. "
        "No fixed 160-DPI value was applied by this script.", prompt, car_later)
    human_step(audit, "projected_maps_buildings",
        "On the connected Android Auto Maps screen, open Settings and turn Raised Buildings off. "
        "Check the projected map is flat. The phone's Navigation switch alone does not establish this.",
        prompt, car_later)
    human_step(audit, "physical_car_acceptance",
        "While parked, check a normal fresh automatic connection, the map and a screen/steering-wheel voice "
        "request with an audible response. After both car and Android Auto disconnect, check phone preferences restore.",
        prompt, car_later)
    tasks = audit.value["setup_tasks"]
    pending = [name for name, report in tasks.items() if report["status"] == "pending"]
    confirmed = [name for name, report in tasks.items() if report["status"] == "user-confirmed"]
    return {"status": "setup-needs-follow-up" if pending else "setup-guided-user-confirmed",
            "pending_tasks": pending, "user_confirmed_tasks": confirmed,
            "backup_path": str(backup), "report_path": str(audit.path),
            "note": "Verified settings and human confirmations are separate. The script does not claim unattended car setup.",
            "debugging": "No sleep/debugging setting was changed. When finished, you may turn off USB/wireless debugging yourself."}


def parser():
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--serial", default=os.environ.get("ADB_SERIAL"))
    value.add_argument("--adb", help="ADB path; otherwise searches existing Platform-Tools/Homebrew")
    value.add_argument("--apk", default=str(ROOT / "HiBreak-Auto-Scale.apk"))
    value.add_argument("--bridge", help="Bridge JAR; otherwise the existing CLI's sibling lookup")
    value.add_argument("--state-dir", default=str(ROOT / "records"), help="private local backup/report folder")
    value.add_argument("--keep-app", action="append", help="repeat desired launcher labels; replaces the default keep list")
    value.add_argument("--non-interactive", action="store_true", help="run supported verified steps and leave human tasks pending")
    value.add_argument("--wait-seconds", type=int, default=120,
                       help="wait for the phone and USB authorization; 0 checks immediately")
    value.add_argument("--check-car-now", action="store_true",
                       help="ask about physical car checks now; otherwise leave a take-away checklist")
    return value


def main(argv=None, prompt=input):
    args = parser().parse_args(argv)
    if not args.non_interactive and not sys.stdin.isatty():
        args.non_interactive = True
        print("No interactive terminal: supported settings will run, and human steps will remain pending.")
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    path = Path(args.state_dir).expanduser().resolve() / (stamp + "-setup-" + uuid.uuid4().hex[:8] + "-report.json")
    audit = None
    try:
        ui_module = importlib.import_module("setup_ui")
        assistant_module = importlib.import_module("setup_assistant")
        audit = shared.Audit(path, "guided-phone-setup")
        result = run_setup(args, audit, ui_module, assistant_module, prompt)
        audit.update(status=result["status"], ended_utc=shared.now(), result=result)
        print("\nSetup report: " + str(path))
        for name, report in audit.value["setup_tasks"].items():
            print("  " + report["status"] + ": " + name.replace("_", " "))
        print("Original phone backup: " + result["backup_path"])
        print(result["note"] + "\n" + result["debugging"])
        return 2 if result["pending_tasks"] else 0
    except (shared.Refusal, OSError, ValueError, ImportError, KeyboardInterrupt) as error:
        if audit:
            try:
                audit.update(status="setup-stopped" if isinstance(error, KeyboardInterrupt) else "setup-blocked",
                             ended_utc=shared.now(), error=type(error).__name__ + ": " + str(error))
            except OSError:
                print("The final report could not be saved; preserve any backup already written.", file=sys.stderr)
        print("\nSetup stopped: " + str(error), file=sys.stderr)
        if audit:
            print("Keep the private report and any saved backup: " + str(path), file=sys.stderr)
        print("No automatic rollback, uninstall or data clearing was attempted.", file=sys.stderr)
        return 130 if isinstance(error, KeyboardInterrupt) else 1


if __name__ == "__main__":
    raise SystemExit(main())
