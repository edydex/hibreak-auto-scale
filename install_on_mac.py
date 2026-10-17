#!/usr/bin/env python3
"""Install/update the HiBreak companion and prepare its explicitly scoped grants.

Does not enable automatic scaling, uninstall the app, or clear application data.
Uses Python's standard library and the adjacent hibreak_aa.py device/audit helpers.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import sys
import uuid
import zipfile

import hibreak_aa as shared

ROOT = Path(__file__).resolve().parent
APP = "org.hibreak.autoscale"
ACTIVITY = APP + "/.MainActivity"
DUMP = "android.permission.DUMP"
NOTIFICATIONS = "android.permission.POST_NOTIFICATIONS"


def locate_adb(explicit=None):
    try:
        return shared.locate_adb(explicit)
    except shared.Refusal:
        if explicit:
            raise
        homebrew = Path("/opt/homebrew/bin/adb")
        if homebrew.is_file():
            return str(homebrew.resolve())
        raise shared.Refusal(
            "ADB was not found. Install Google's SDK Platform-Tools for Mac: "
            "https://developer.android.com/tools/releases/platform-tools "
            "or supply --adb /absolute/path/to/adb. No download or install was attempted.")


def package_state(adb):
    result = adb.shell("pm", "path", APP, check=False)
    paths = [line[8:].strip() for line in result.stdout.splitlines() if line.startswith("package:")]
    if result.returncode and not re.search(r"unknown package|not found|could not find", result.stdout + result.stderr, re.I):
        raise shared.Refusal("Could not check the companion's installed state: "
                             + (result.stderr.strip() or result.stdout.strip()))
    if not paths:
        return {"installed": False, "apk_paths": [], "permissions": {DUMP: False, NOTIFICATIONS: False}}
    dump = adb.shell("dumpsys", "package", APP).stdout
    permissions = {}
    for permission in (DUMP, NOTIFICATIONS):
        grants = re.findall(re.escape(permission) + r"\s*:\s*granted=(true|false)\b", dump)
        permissions[permission] = "true" in grants
    version = re.search(r"\bversionName=([^\r\n]+)", dump)
    return {"installed": True, "apk_paths": paths, "permissions": permissions,
            "version_name": version.group(1).strip() if version else None}


def whitelist_state(adb):
    result = adb.shell("dumpsys", "deviceidle", "whitelist")
    # AOSP output is category,package,uid; match the entire package field.
    entries = []
    for line in result.stdout.splitlines():
        columns = [column.strip() for column in line.split(",")]
        if len(columns) >= 2 and columns[1] == APP:
            entries.append({"category": columns[0], "line": line})
    if not result.stdout.strip():
        raise shared.Refusal("Device-idle whitelist output was empty; refusing to guess its prior state")
    return {"present": bool(entries), "entries": entries, "raw": result.stdout}


def aa_display_present(adb):
    dump = adb.shell("dumpsys", "display").stdout
    # This is an advisory, never the app's enable/restore decision. The companion
    # uses its strict native-display parser for those decisions.
    return any("DisplayDeviceInfo{" in line and re.search(
        r"\bowner\s+com\.google\.android\.projection\.gearhead\s+\(uid\s+\d+\)", line)
               for line in dump.splitlines())


def undo_advisory(adb_executable, serial, before, idle_before, added_whitelist):
    prefix = [adb_executable, "-s", serial, "shell"]
    argv = []
    for permission in (DUMP, NOTIFICATIONS):
        if not before["permissions"].get(permission):
            argv.append(prefix + [shlex.join(["pm", "revoke", APP, permission])])
    if added_whitelist and not idle_before["present"]:
        argv.append(prefix + [shlex.join(["dumpsys", "deviceidle", "whitelist", "-" + APP])])
    commands = [shlex.join(command) for command in argv]
    powershell = ["& " + " ".join("'" + part.replace("'", "''") + "'" for part in command)
                  for command in argv]
    return {"first": "Open HiBreak Auto Scale, press Stop and Restore, and wait for its successful restore status.",
            "then": "Only after that restoration, revoke grants added here and remove the idle exception only if added here.",
            "commands_for_this_install": commands,
            "commands_for_this_install_shell": "POSIX sh/bash; do not paste these in PowerShell or cmd.exe",
            "powershell_commands_for_this_install": powershell,
            "argv_for_this_install": argv,
            "preserve_existing_whitelist": idle_before["present"],
            "app_removal": "This installer does not uninstall the app. Keep it until its saved preferences are restored."}


def install(args, audit):
    apk = Path(args.apk).expanduser().resolve()
    if not apk.is_file():
        raise shared.Refusal("HiBreak-Auto-Scale.apk is missing beside this installer")
    try:
        with zipfile.ZipFile(apk) as package:
            if "AndroidManifest.xml" not in package.namelist() or "classes.dex" not in package.namelist():
                raise shared.Refusal("The companion APK is not a complete Android package")
    except zipfile.BadZipFile as error:
        raise shared.Refusal("The companion APK is not a readable Android package") from error
    apk_info = {"path": str(apk), "bytes": apk.stat().st_size,
                "sha256": hashlib.sha256(apk.read_bytes()).hexdigest()}
    audit.update(apk=apk_info)
    adb = shared.ADB(locate_adb(args.adb), audit, timeout=120)
    identity = shared.select_device(adb, args.serial)
    before = package_state(adb)
    idle_before = whitelist_state(adb)
    aa_present = aa_display_present(adb)
    audit.update(status="installation-prepared", app_before=before,
                 idle_whitelist_before=idle_before, android_auto_displays_before=aa_present,
                 automatic_scaling_enabled_by_installer=False,
                 undo_advisory=undo_advisory(adb.executable, adb.serial, before, idle_before, False))
    shared.guard_identity(identity, adb.identity(adb.serial))
    # -r preserves the installed app's data and signing compatibility. A signer
    # mismatch must fail here; there is deliberately no uninstall/clear fallback.
    audit.event("install-intent", replace_existing=True, preserve_app_data=True)
    result = adb.run("install", "-r", str(apk))
    if not re.search(r"(?m)^Success\s*$", result.stdout):
        raise shared.Refusal("ADB did not confirm successful APK installation")
    audit.update(status="apk-installed")
    if not package_state(adb)["installed"]:
        raise shared.Refusal("The expected companion package was not present after APK installation")
    permissions = [DUMP]
    if int(identity["sdk"]) >= 33:
        permissions.append(NOTIFICATIONS)
    for permission in permissions:
        shared.guard_identity(identity, adb.identity(adb.serial))
        audit.event("permission-grant-intent", package=APP, permission=permission,
                    previously_granted=before["permissions"].get(permission, False))
        adb.shell("pm", "grant", APP, permission)
        granted = package_state(adb)["permissions"].get(permission)
        if granted is not True:
            raise shared.Refusal("The companion permission grant was not verified: " + permission)
    added_whitelist = False
    if not idle_before["present"]:
        shared.guard_identity(identity, adb.identity(adb.serial))
        audit.event("idle-whitelist-add-intent", package=APP)
        adb.shell("dumpsys", "deviceidle", "whitelist", "+" + APP)
        added_whitelist = True
        # Save the precise undo state immediately, even if subsequent checks fail.
        audit.update(added_idle_whitelist=True,
                     undo_advisory=undo_advisory(adb.executable, adb.serial, before, idle_before, True))
    idle_after = whitelist_state(adb)
    if not idle_after["present"]:
        raise shared.Refusal("The companion's exact device-idle exception was not verified")
    after = package_state(adb)
    audit.update(permissions_after=after["permissions"], idle_whitelist_after=idle_after,
                 added_idle_whitelist=added_whitelist,
                 undo_advisory=undo_advisory(adb.executable, adb.serial, before, idle_before, added_whitelist))
    shared.guard_identity(identity, adb.identity(adb.serial))
    launch = adb.shell("am", "start", "-n", ACTIVITY)
    if re.search(r"(?im)^\s*(?:error:|exception|securityexception)", launch.stdout + launch.stderr):
        raise shared.Refusal("Android reported an error opening the companion")
    return {"status": "installed-and-opened", "identity": identity, "apk_sha256": apk_info["sha256"],
            "added_idle_whitelist": added_whitelist,
            "android_auto_displays_detected": aa_present,
            "automatic_scaling_enabled_by_installer": False,
            "next_step": "Disconnect Android Auto and enable the helper to capture normal preferences. Lock its card in Recents > Process manage. Follow docs/setup.md to learn host DPI, then choose Automatic for paired car and grant Nearby devices in the app.",
            "note": "Existing app data was preserved. The installer did not enable or prepare scaling, grant Bluetooth access, select a car, set the vendor padlock, or change app display preferences."}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", default=os.environ.get("ADB_SERIAL"), help="ADB serial; defaults to ADB_SERIAL if set")
    parser.add_argument("--adb", help="ADB executable; also searches PATH, bundled tools, and /opt/homebrew/bin/adb")
    parser.add_argument("--apk", default=str(ROOT / "HiBreak-Auto-Scale.apk"), help="companion APK beside the installer")
    parser.add_argument("--state-dir", default=str(ROOT / "records"), help="local installation audit directory")
    args = parser.parse_args(argv)
    audit = None
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    path = Path(args.state_dir).expanduser().resolve() / f"{stamp}-install-{uuid.uuid4().hex[:8]}-audit.json"
    try:
        audit = shared.Audit(path, "install-companion")
        result = install(args, audit)
        result["install_log_path"] = str(path)
        audit.update(status=result["status"], ended_utc=shared.now(), result=result)
        print(json.dumps(result, indent=2, sort_keys=True))
        print("\nDisconnect Android Auto for initial Enable. Lock the helper in Recents > Process manage. See docs/setup.md to learn host DPI, then choose Automatic for paired car and grant Nearby devices in the app.")
        return 0
    except (shared.Refusal, OSError, ValueError, KeyboardInterrupt) as error:
        events = audit.value["events"] if audit else []
        changed = any(event["kind"] in {"install-intent", "permission-grant-intent", "idle-whitelist-add-intent"}
                      for event in events)
        result = {"status": "installation-partial-failure" if changed else "installation-refused",
                  "error": f"{type(error).__name__}: {error}",
                  "install_log_path": str(path) if audit else None,
                  "note": "No uninstall, data clear, or automatic enabling was attempted. See the log for completed steps and undo advice."}
        if audit:
            try:
                audit.update(status=result["status"], ended_utc=shared.now(), result=result)
            except OSError:
                result["audit_save_error"] = "Could not update installation log after failure"
        print(json.dumps(result, indent=2, sort_keys=True))
        return 130 if isinstance(error, KeyboardInterrupt) else 1


if __name__ == "__main__":
    raise SystemExit(main())
