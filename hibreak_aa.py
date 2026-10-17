#!/usr/bin/env python3
"""Back up and adjust three Android Auto app display policies on Bigme HiBreak.

Python standard library only. Requires ADB and the bundled display-policy bridge.
This CLI changes app policies only after saving a device-specific atomic backup.
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
import shutil
import subprocess
import sys
import tempfile
import uuid

ROOT = Path(__file__).resolve().parent
PACKAGES = (
    "com.google.android.projection.gearhead",
    "com.google.android.apps.maps",
    "com.google.android.googlequicksearchbox",
)
SERVICE = "xrz_display_policy_service"
INTERFACE = "xrz.framework.manager.IDisplayPolicyManager"
POLICY_CLASS = "xrz.framework.manager.DisplayPolicy"
OWNED_FIELDS = ("appDpi", "isDpiSetting", "appTextEnhance")
SETTERS = {
    "appDpi": ("set-dpi", "setDpiForPackage"),
    "isDpiSetting": ("set-dpi-enabled", "setIsDpiSettingForPackage"),
    "appTextEnhance": ("set-text-enhance", "setTextEnhanceForPackage"),
}
PROPERTIES = {
    "manufacturer": "ro.product.manufacturer", "model": "ro.product.model",
    "hardware_serial": "ro.serialno", "fingerprint": "ro.build.fingerprint",
    "sdk": "ro.build.version.sdk", "initial_dpi": "ro.sf.lcd_density",
}
FORMAT = "hibreak-aa-backup-v1"


class Refusal(RuntimeError):
    """A precondition failed, or a write could not be fully verified."""


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def json_bytes(value) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")


def atomic_json(path: Path, value, *, new=False):
    """Durable replacement within one directory, with private local permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if new and path.exists():
        raise Refusal(f"Refusing to overwrite existing file: {path}")
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(json_bytes(value))
            stream.flush()
            os.fsync(stream.fileno())
        if new:
            # Hard-link insertion refuses an existing destination without a race.
            os.link(temporary, path)
            os.unlink(temporary)
        else:
            os.replace(temporary, path)
        # POSIX supports syncing a directory after an atomic rename. Windows
        # cannot open a directory through os.open; the file was already flushed
        # above and os.replace/os.link still provide the naming boundary.
        if os.name != "nt":
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class Audit:
    def __init__(self, path: Path, action: str):
        self.path = path
        self.value = {"tool_version": 1, "action": action, "started_utc": now(),
                      "status": "preparing", "events": [], "backup_path": None}
        atomic_json(path, self.value, new=True)

    def event(self, kind: str, **details):
        self.value["events"].append({"utc": now(), "kind": kind, **details})
        atomic_json(self.path, self.value)

    def update(self, **details):
        self.value.update(details)
        atomic_json(self.path, self.value)


class ADB:
    def __init__(self, executable: str, audit: Audit, timeout=30):
        self.executable = executable
        self.audit = audit
        self.timeout = timeout
        self.serial = None

    def run(self, *arguments: str, selected=True, check=True):
        if selected and not self.serial:
            raise Refusal("No ADB transport has been selected")
        command = [self.executable]
        if selected:
            command.extend(["-s", self.serial])
        command.extend(str(item) for item in arguments)
        try:
            result = subprocess.run(command, capture_output=True, text=True,
                                    encoding="utf-8", errors="strict", timeout=self.timeout)
        except subprocess.TimeoutExpired as error:
            self.audit.event("adb-timeout", command=command, timeout_seconds=self.timeout)
            raise Refusal(f"ADB command timed out after {self.timeout} seconds") from error
        self.audit.event("adb", command=command, returncode=result.returncode,
                         stdout=result.stdout, stderr=result.stderr)
        if check and result.returncode:
            raise Refusal(f"ADB command failed ({result.returncode}): {result.stderr.strip() or result.stdout.strip()}")
        return result

    def shell(self, *arguments: str, check=True):
        return self.run("shell", shlex.join([str(value) for value in arguments]), check=check)

    def identity(self, serial: str):
        original = self.serial
        self.serial = serial
        try:
            identity = {name: self.shell("getprop", prop).stdout.strip() for name, prop in PROPERTIES.items()}
            identity["adb_serial"] = serial
            return identity
        finally:
            self.serial = original


def validate_identity(identity: dict):
    if not isinstance(identity, dict):
        raise Refusal("Device identity record is missing or malformed")
    if identity.get("manufacturer", "").casefold() != "bigme":
        raise Refusal("Selected phone does not identify its manufacturer as Bigme")
    if not identity.get("model", "").casefold().startswith("hibreak"):
        raise Refusal("Selected Bigme phone does not identify its model as HiBreak")
    for name in ("hardware_serial", "fingerprint"):
        value = identity.get(name, "")
        if not value or value.casefold() in {"unknown", "null", "none"}:
            raise Refusal(f"Phone does not expose a usable {name}; refusing identity-unsafe operation")
    if not str(identity.get("initial_dpi", "")).isdigit() or not 1 <= int(identity["initial_dpi"]) <= 1000:
        raise Refusal("ro.sf.lcd_density is unavailable or invalid; flag persistence workaround cannot be selected safely")


def guard_identity(expected: dict, actual: dict):
    validate_identity(actual)
    for key in ("hardware_serial", "fingerprint", "manufacturer", "model", "sdk", "initial_dpi"):
        if expected.get(key) != actual.get(key):
            raise Refusal(f"Device identity/build changed: {key}")


def select_device(adb: ADB, requested: str | None) -> dict:
    listing = adb.run("devices", "-l", selected=False).stdout
    authorized = []
    for line in listing.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            authorized.append(parts[0])
    if requested:
        if requested not in authorized:
            raise Refusal("Requested --serial is not an authorized online ADB device")
        identity = adb.identity(requested)
    else:
        if not authorized:
            raise Refusal("No authorized online phone. Enable USB debugging and accept this Mac on the phone")
        identities = [adb.identity(serial) for serial in authorized]
        hardware_ids = {item.get("hardware_serial") for item in identities}
        if any(not item or item.casefold() in {"unknown", "null", "none"} for item in hardware_ids):
            raise Refusal("A connected transport has no stable hardware ID; choose the intended --serial explicitly")
        if len(hardware_ids) != 1:
            raise Refusal("Multiple authorized physical devices are connected; choose --serial explicitly")
        identity = next((item for item in identities if ":" not in item["adb_serial"]), identities[0])
        for alternate in identities:
            guard_identity(identity, alternate)
    validate_identity(identity)
    adb.serial = identity["adb_serial"]
    adb.audit.update(identity=identity, status="device-verified")
    return identity


def parse_json_output(text: str) -> dict:
    matches = []
    for line in text.splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and "bridgeVersion" in value:
            matches.append(value)
    if len(matches) != 1:
        raise Refusal("Bridge did not emit exactly one identifiable JSON object")
    return matches[0]


def schema_of(inspect: dict, fingerprint: str) -> dict:
    if inspect.get("ok") is not True or inspect.get("command") != "inspect":
        raise Refusal("Runtime bridge inspection failed")
    if inspect.get("buildFingerprint") != fingerprint:
        raise Refusal("Bridge fingerprint does not match the selected phone")
    if inspect.get("serviceName") != SERVICE or inspect.get("interfaceName") != INTERFACE:
        raise Refusal("Unexpected vendor display-policy interface")
    binder = inspect.get("binder", {})
    if any(binder.get(key) is not True for key in ("found", "alive", "ping")) or binder.get("descriptor") != INTERFACE:
        raise Refusal("The expected vendor display-policy Binder is not available/alive")
    methods = inspect.get("interface", {}).get("declaredMethods", [])
    required = {"getPolicyByPackage": (["java.lang.String"], POLICY_CLASS)}
    required.update({method: (["java.lang.String", "int"], "boolean") for _, method in SETTERS.values()})
    for name, (parameters, returns) in required.items():
        candidates = [method for method in methods if method.get("name") == name
                      and method.get("parameterTypes") == parameters
                      and method.get("returnType") == returns
                      and "static" not in method.get("modifiers", "").split()]
        if len(candidates) != 1:
            raise Refusal(f"Runtime method/schema mismatch: {name}")
    getters = [item for item in inspect.get("allowlistedPackageGetters", [])
               if item.get("name") == "getPolicyByPackage" and item.get("returnType") == POLICY_CLASS]
    if len(getters) != 1:
        raise Refusal("Runtime policy getter schema is missing or ambiguous")
    fields = getters[0].get("returnSchema", {}).get("fields", [])
    instance_fields = {field["name"]: field.get("type") for field in fields
                       if "static" not in field.get("modifiers", "").split()}
    if any(instance_fields.get(name) != "int" for name in OWNED_FIELDS):
        raise Refusal("Expected writable instance-int readback fields are not present")
    canonical = {"interface": INTERFACE, "policy_class": POLICY_CLASS,
                 "methods": sorted([{"name": method.get("name"),
                                     "parameters": method.get("parameterTypes"),
                                     "returns": method.get("returnType"),
                                     "static": "static" in method.get("modifiers", "").split()}
                                    for method in methods], key=lambda value: json.dumps(value, sort_keys=True)),
                 "instance_fields": instance_fields}
    canonical["sha256"] = hashlib.sha256(json_bytes(canonical)).hexdigest()
    return canonical


def policy_fields(result: dict, key="value") -> dict:
    policy = result.get(key)
    if not isinstance(policy, dict) or policy.get("class") != POLICY_CLASS or not isinstance(policy.get("fields"), dict):
        raise Refusal(f"Bridge {key} is not the expected complete policy object")
    fields = policy["fields"]
    if any(type(fields.get(name)) is not int for name in OWNED_FIELDS):
        raise Refusal("Policy readback fields are missing or not integers")
    if any(isinstance(value, (dict, list)) for value in fields.values()):
        raise Refusal("Policy fields contain an unsupported/truncated reflection value")
    return fields.copy()


def parse_policy_rows(text: str) -> dict:
    if "Policy list:" not in text or "Permission Denial" in text:
        raise Refusal("Vendor service dump did not expose a readable Policy list")
    rows = {}
    for match in re.finditer(r"DisplayPolicy\{([^{}]*)\}", text.split("Policy list:", 1)[1]):
        fields = {}
        for item in match.group(1).split(","):
            if "=" not in item:
                raise Refusal("Unknown vendor policy dump format")
            key, value = (part.strip() for part in item.split("=", 1))
            if value.startswith("'") and value.endswith("'"):
                parsed = value[1:-1]
            elif re.fullmatch(r"-?\d+", value):
                parsed = int(value)
            elif re.fullmatch(r"-?\d+\.\d+", value):
                parsed = float(value)
            else:
                raise Refusal(f"Unsupported policy dump field value: {key}")
            if key in fields:
                raise Refusal("Duplicate field in vendor policy dump")
            fields[key] = parsed
        package = fields.get("packageName")
        if not isinstance(package, str) or package in rows:
            raise Refusal("Missing/duplicate package in vendor policy dump")
        rows[package] = fields
    if not rows:
        raise Refusal("Vendor Policy list was empty/unparseable; refusing to infer missing rows")
    return rows


class Bridge:
    def __init__(self, adb: ADB, jar: Path, identity: dict):
        self.adb = adb
        self.identity = identity
        digest = hashlib.sha256(jar.read_bytes()).hexdigest()
        self.remote = f"/data/local/tmp/hibreak-aa-bridge-{digest[:20]}.jar"
        self.jar_digest = digest
        adb.run("push", str(jar), self.remote)
        self.inspect = self.call("inspect")
        self.schema = schema_of(self.inspect, identity["fingerprint"])
        if type(self.inspect.get("bridgeVersion")) is not int or self.inspect["bridgeVersion"] < 2:
            raise Refusal("Bridge is too old for verified setters; bundle bridge version 2 or newer")

    def call(self, *arguments: str, allow_failure=False) -> dict:
        command = f"CLASSPATH={shlex.quote(self.remote)} " + shlex.join(
            ["app_process", "/system/bin", "DisplayPolicyBridge", *map(str, arguments)])
        process = self.adb.run("shell", command, check=False)
        result = parse_json_output(process.stdout)
        if result.get("buildFingerprint") != self.identity["fingerprint"]:
            raise Refusal("Bridge returned a different device build fingerprint")
        if not allow_failure and (process.returncode != 0 or result.get("ok") is not True):
            raise Refusal(f"Bridge command failed: {result.get('error', process.stderr.strip())}")
        return result

    def get(self, package: str) -> dict:
        result = self.call("get", package)
        if result.get("package") != package or result.get("getter", {}).get("name") != "getPolicyByPackage":
            raise Refusal("Bridge package/getter readback mismatch")
        fields = policy_fields(result)
        if fields.get("packageName") != package or set(fields) != set(self.schema["instance_fields"]):
            raise Refusal("Policy package or complete field schema does not match runtime inspection")
        return fields


def installed_version(adb: ADB, package: str) -> dict | None:
    paths = adb.shell("pm", "path", package, check=False)
    package_paths = [line[8:].strip() for line in paths.stdout.splitlines() if line.startswith("package:")]
    if not package_paths:
        return None
    dump = adb.shell("dumpsys", "package", package).stdout
    code = re.search(r"\bversionCode=(\d+)", dump)
    name = re.search(r"\bversionName=([^\r\n]+)", dump)
    if not code:
        raise Refusal(f"Could not establish installed versionCode for {package}")
    return {"version_code": int(code.group(1)), "version_name": name.group(1).strip() if name else None,
            "apk_paths": package_paths}


def choose_packages(requested, adb: ADB):
    selected = list(dict.fromkeys(requested or PACKAGES))
    if any(package not in PACKAGES for package in selected):
        raise Refusal("--package accepts only Android Auto, Google Maps, or the Google app")
    versions = {}
    skipped = []
    for package in selected:
        version = installed_version(adb, package)
        if version is None:
            if requested:
                raise Refusal(f"Requested package is not installed: {package}")
            skipped.append(package)
        else:
            versions[package] = version
    if not versions:
        raise Refusal("None of the three supported apps is installed")
    return versions, skipped


def snapshot(adb: ADB, bridge: Bridge, identity: dict, versions: dict, skipped: list) -> dict:
    guard_identity(identity, adb.identity(adb.serial))
    dump = adb.shell("dumpsys", SERVICE).stdout
    rows = parse_policy_rows(dump)
    packages = {}
    for package, version in versions.items():
        fields = bridge.get(package)
        # The service dump exposes raw DB values. Its getter clones/resolves
        # color-mode defaults, so several unrelated effective fields can differ
        # legitimately. The three owned values must not be globally overridden.
        if package in rows and any(rows[package].get(name) != fields[name] for name in OWNED_FIELDS):
            raise Refusal(f"Raw and effective owned policy values disagree for {package}; diagnose global overrides before writing")
        packages[package] = {"fields": fields, "row_present": package in rows,
                             "dump_row": rows.get(package), "app_version": version}
    second_dump = adb.shell("dumpsys", SERVICE).stdout
    if rows != parse_policy_rows(second_dump):
        raise Refusal("Service policy rows changed during backup; retry before writing")
    guard_identity(identity, adb.identity(adb.serial))
    return {"format": FORMAT, "created_utc": now(), "identity": identity,
            "schema": bridge.schema, "bridge_sha256": bridge.jar_digest,
            "runtime_inspection": bridge.inspect, "packages": packages,
            "skipped_not_installed": skipped, "service_dump": dump,
            "all_policy_rows": rows, "tool_owned_fields": list(OWNED_FIELDS)}


def validate_backup(value: dict):
    if not isinstance(value, dict) or value.get("format") != FORMAT or not isinstance(value.get("packages"), dict) or not value["packages"]:
        raise Refusal("File is not a nonempty HiBreak AA backup")
    validate_identity(value.get("identity", {}))
    for package, saved in value["packages"].items():
        if package not in PACKAGES or type(saved.get("row_present")) is not bool:
            raise Refusal("Backup contains unsupported package or missing original row-presence evidence")
        fields = saved.get("fields", {})
        if fields.get("packageName") != package:
            raise Refusal("Backup package/fields mismatch")
        if any(type(fields.get(key)) is not int for key in OWNED_FIELDS):
            raise Refusal("Backup does not contain exact original DPI/flag/text values")
        if not 0 <= fields["appDpi"] <= 1000 or fields["isDpiSetting"] not in (0, 1) or not 0 <= fields["appTextEnhance"] <= 100:
            raise Refusal("Backup original value is outside the verified bridge restore bounds")
    # Validate row evidence instead of trusting a manually changed row_present flag.
    rows = parse_policy_rows(value.get("service_dump", ""))
    for package, saved in value["packages"].items():
        if saved["row_present"] != (package in rows) or saved.get("dump_row") != rows.get(package):
            raise Refusal("Backup row-presence evidence is inconsistent")


class Mutator:
    def __init__(self, adb: ADB, bridge: Bridge, identity: dict, audit: Audit):
        self.adb, self.bridge, self.identity, self.audit = adb, bridge, identity, audit
        self.writes = 0
        self.modified_packages = set()

    def set_field(self, package: str, field: str, value: int, expected: dict) -> dict:
        if expected[field] == value:
            self.audit.event("unchanged", package=package, field=field, value=value)
            return expected
        guard_identity(self.identity, self.adb.identity(self.adb.serial))
        current = self.bridge.get(package)
        if current != expected:
            raise Refusal(f"Policy changed concurrently before write: {package}")
        self.audit.event("mutation-intent", package=package, field=field, value=value, before=expected)
        self.writes += 1
        self.modified_packages.add(package)
        result = self.bridge.call(SETTERS[field][0], package, str(value), allow_failure=True)
        self.audit.event("bridge-write-result", package=package, field=field, result=result)
        after = self.bridge.get(package)
        desired = {**expected, field: value}
        if policy_fields(result, "beforePolicy") != expected:
            raise Refusal(f"Bridge before-policy changed concurrently during write: {package}")
        if policy_fields(result, "afterPolicy") != desired or after != desired:
            raise Refusal(f"Write readback mismatch or unexpected field change: {package} {field}")
        # Real no-ops were skipped above. False for an actual change can mean
        # a failed DB insert despite a matching temporary in-memory readback.
        if result.get("setterResult") is not True or result.get("ok") is not True:
            raise Refusal(f"Vendor setter did not confirm persistence for changed value: {package} {field}")
        self.audit.event("mutation-verified", package=package, field=field, value=value,
                         setter_result=result.get("setterResult"), bridge_ok=result.get("ok"),
                         accepted_by_exact_readback=True)
        return after

    def configure(self, package: str, desired: dict, current: dict) -> dict:
        initial_dpi = int(self.identity["initial_dpi"])
        if current["isDpiSetting"] != desired["isDpiSetting"]:
            if current["appDpi"] == initial_dpi:
                # Verified vendor-source quirk: flag change at INIT_DPI skips DB
                # persistence/notification even though its live getter changes.
                temporary = next(number for number in (160, 161, 240) if number != initial_dpi)
                self.audit.event("stage-dpi-for-flag-persistence", package=package,
                                 initial_dpi=initial_dpi, temporary_dpi=temporary)
                current = self.set_field(package, "appDpi", temporary, current)
            current = self.set_field(package, "isDpiSetting", desired["isDpiSetting"], current)
        current = self.set_field(package, "appDpi", desired["appDpi"], current)
        current = self.set_field(package, "appTextEnhance", desired["appTextEnhance"], current)
        return current


def locate_adb(explicit):
    executable = "adb.exe" if os.name == "nt" else "adb"
    candidates = [explicit] if explicit else [
        str(ROOT / "platform-tools" / executable), str(ROOT.parent / "platform-tools" / executable),
        str(ROOT.parent / "android-sdk/platform-tools" / executable), shutil.which(executable),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return str(Path(candidate).expanduser().resolve())
    raise Refusal("ADB not found. Pass --adb /absolute/path/to/adb or place platform-tools beside this script")


def locate_jar(explicit):
    candidates = [Path(explicit).expanduser()] if explicit else [
        ROOT / "display-policy-bridge.jar", ROOT.parent / "bridge/build/display-policy-bridge.jar"]
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    raise Refusal("Bridge JAR not found. Bundle display-policy-bridge.jar beside this script or pass --bridge")


def parser_for_cli():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serial", help="explicit ADB transport serial (recommended)")
    parser.add_argument("--adb", help="ADB executable")
    parser.add_argument("--bridge", help="bridge JAR, otherwise bundled sibling file")
    parser.add_argument("--state-dir", default=str(ROOT / "records"), help="local backups and audit JSON")
    sub = parser.add_subparsers(dest="action", required=True)
    status = sub.add_parser("status", help="inspect identity, installed apps, and live per-app policies")
    backup = sub.add_parser("backup", help="save exact per-app policy and original row presence")
    apply = sub.add_parser("apply", help="back up, then apply an explicit selected DPI")
    restore = sub.add_parser("restore", help="restore the backup's three supported original fields")
    for command in (status, backup, apply):
        command.add_argument("--package", choices=PACKAGES, action="append", help="repeat to choose supported installed apps")
    backup.add_argument("--output", help="new backup JSON path; existing files are never overwritten")
    apply.add_argument("--dpi", type=int, required=True, help="explicit requested app DPI, 72..640")
    apply.add_argument("--text-enhance", type=int, help="optional explicit value, 0..100; otherwise unchanged")
    restore.add_argument("backup", help="exact original backup JSON (same phone/build/schema)")
    return parser


def execute(args, audit: Audit, state: Path):
    if args.action == "apply":
        if not 72 <= args.dpi <= 640:
            raise Refusal("--dpi must be an explicit integer between 72 and 640")
        if args.text_enhance is not None and not 0 <= args.text_enhance <= 100:
            raise Refusal("--text-enhance must be 0..100")
    original = None
    if args.action == "restore":
        original = json.loads(Path(args.backup).expanduser().read_text(encoding="utf-8"))
        validate_backup(original)
        audit.update(restore_source=str(Path(args.backup).expanduser().resolve()))
    adb = ADB(locate_adb(args.adb), audit)
    identity = select_device(adb, args.serial)
    if original:
        guard_identity(original["identity"], identity)
    bridge = Bridge(adb, locate_jar(args.bridge), identity)
    if original and bridge.schema != original.get("schema"):
        raise Refusal("Runtime schema differs from the backup; restoration requires a reviewed adapter")
    versions, skipped = choose_packages(list(original["packages"]) if original else args.package, adb)
    before = snapshot(adb, bridge, identity, versions, skipped)
    if args.action == "apply":
        invalid_scale = [package for package, saved in before["packages"].items()
                         if saved["fields"].get("appDpiScale") != 1]
        if invalid_scale:
            raise Refusal("apply requires appDpiScale == 1; vendor resources/display services otherwise disagree: "
                          + ", ".join(invalid_scale))
    summary = {"identity": identity, "schema_sha256": bridge.schema["sha256"],
               "packages": {package: {"fields": saved["fields"], "row_present": saved["row_present"],
                                      "app_version": saved["app_version"]}
                            for package, saved in before["packages"].items()},
               "skipped_not_installed": skipped}
    if args.action == "status":
        return {"status": "inspected", **summary}, 0
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    backup_path = (Path(args.output).expanduser().resolve()
                   if args.action == "backup" and args.output else state / f"{stamp}-before-{args.action}.json")
    atomic_json(backup_path, before, new=True)
    # Persist the rollback location before any settings mutation is attempted.
    audit.update(backup_path=str(backup_path), status="backup-saved")
    if args.action == "backup":
        return {"status": "backed-up", "backup_path": str(backup_path), **summary}, 0
    mutator = Mutator(adb, bridge, identity, audit)
    expected = {package: saved["fields"].copy() for package, saved in before["packages"].items()}
    desired = {}
    for package, current in expected.items():
        if original:
            desired[package] = {name: original["packages"][package]["fields"][name] for name in OWNED_FIELDS}
        else:
            desired[package] = {"appDpi": args.dpi, "isDpiSetting": 1,
                                "appTextEnhance": current["appTextEnhance"]
                                if args.text_enhance is None else args.text_enhance}
    audit.update(status="applying", requested_fields=desired)
    for package in expected:
        expected[package] = mutator.configure(package, desired[package], expected[package])
    guard_identity(identity, adb.identity(adb.serial))
    # dumpsys reloads the persisted policy list on this vendor service. A getter
    # before that reload can see a failed insert's transient in-memory mutation.
    rows = parse_policy_rows(adb.shell("dumpsys", SERVICE).stdout)
    after = {package: bridge.get(package) for package in expected}
    if after != expected:
        raise Refusal("Persisted final policy readback after service reload differs from the verified settings")
    before_rows = before["all_policy_rows"]
    outside_targets = set(before_rows).union(rows) - set(expected)
    if any(before_rows.get(package) != rows.get(package) for package in outside_targets):
        raise Refusal("An unrelated package policy changed during the operation; inspect audit before continuing")
    for package, fields in after.items():
        if package in mutator.modified_packages and package not in rows:
            raise Refusal(f"Changed package has no persisted policy row after service reload: {package}")
        if package in rows and any(rows[package].get(name) != fields[name] for name in OWNED_FIELDS):
            raise Refusal(f"Persisted owned fields disagree with effective policy readback: {package}")
        if package in before_rows and package in rows:
            unrelated_before = {name: value for name, value in before_rows[package].items() if name not in OWNED_FIELDS}
            unrelated_after = {name: value for name, value in rows[package].items() if name not in OWNED_FIELDS}
            if unrelated_before != unrelated_after:
                raise Refusal(f"Unrelated raw policy fields changed in an existing target row: {package}")
    presence_differences = []
    if original:
        presence_differences = [package for package, saved in original["packages"].items()
                                if saved["row_present"] != (package in rows)]
    status = ("restored-values-row-presence-differs" if presence_differences else
              "restored-fields" if original else "applied-fields")
    audit.update(status=status, verified_final_fields=after, row_presence_differences=presence_differences,
                 writes_attempted=mutator.writes)
    return {"status": status, "backup_path": str(backup_path), "packages": after,
            "row_presence_differences": presence_differences,
            "note": "Settings readback is verified. Reconnect Android Auto and test layout/persistence separately."
                    + (" Original absent policy rows remain materialized; no row deletion API was used."
                       if presence_differences else "")}, 3 if presence_differences else 0


def main(argv=None):
    parser = parser_for_cli()
    args = parser.parse_args(argv)
    state = Path(args.state_dir).expanduser().resolve()
    audit_path = state / f"{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S.%fZ')}-{args.action}-{uuid.uuid4().hex[:8]}-audit.json"
    audit = None
    try:
        audit = Audit(audit_path, args.action)
        result, code = execute(args, audit, state)
        audit.update(status=result["status"], ended_utc=now(), result=result)
        result["audit_path"] = str(audit_path)
        print(json.dumps(result, indent=2, sort_keys=True))
        return code
    except (Refusal, OSError, ValueError, subprocess.SubprocessError, KeyboardInterrupt) as error:
        backup_path = audit.value.get("backup_path") if audit else None
        attempted = bool(audit and any(event["kind"] == "mutation-intent" for event in audit.value["events"]))
        result = {"status": "partial-failure" if attempted else "refused-before-settings-write",
                  "error": f"{type(error).__name__}: {error}", "backup_path": backup_path,
                  "audit_path": str(audit_path) if audit else None,
                  "note": "No automatic rollback was attempted. Preserve this backup and audit."
                          if attempted else "No app policy setter was attempted."}
        if audit:
            try:
                audit.update(status=result["status"], ended_utc=now(), result=result)
            except OSError:
                result["audit_save_error"] = "Could not update audit after failure"
        print(json.dumps(result, indent=2, sort_keys=True))
        return 130 if isinstance(error, KeyboardInterrupt) else 1


if __name__ == "__main__":
    raise SystemExit(main())
