#!/usr/bin/env python3
"""Verified, English-label UI steps for the optional HiBreak setup wizard.

Uses fresh Android accessibility dumps, never guessed screen coordinates. An
unrecognized screen stops the affected step; its setting is not assumed applied.
UI captures and the change journal contain private data and belong in records/.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
import time
import uuid
import xml.etree.ElementTree as ET

import hibreak_aa as shared

AA = 'com.google.android.projection.gearhead'
MAPS = 'com.google.android.apps.maps'


class UiUnavailable(shared.Refusal):
    pass


def bounds(node):
    match = re.fullmatch(r'\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]', node.get('bounds', ''))
    values = list(map(int, match.groups())) if match else []
    if (len(values) != 4 or min(values) < 0
            or values[2] <= values[0] or values[3] <= values[1]):
        raise UiUnavailable('Control has no usable visible bounds')
    return values


def checked(node):
    if node.get('checkable') != 'true' or node.get('checked') not in {'true', 'false'}:
        raise UiUnavailable('Android did not expose a definite checkbox state')
    return node.get('checked') == 'true'


class Screen:
    def __init__(self, data):
        self.root = ET.fromstring(data)
        self.nodes = list(self.root.iter('node'))
        self.parents = {c: p for p in self.root.iter() for c in p}

    def label(self, label, package=None):
        nodes = [n for n in self.nodes if not package or n.get('package') == package]
        # An icon and its caption can have the same label. Prefer the caption.
        found = [n for n in nodes if n.get('text') == label]
        if not found:
            found = [n for n in nodes if n.get('content-desc') == label]
        if len(found) != 1:
            raise UiUnavailable('Expected one visible control: ' + label)
        bounds(found[0])
        return found[0]

    def has(self, label, package=None):
        try:
            self.label(label, package)
            return True
        except UiUnavailable:
            return False

    def switch(self, label, package):
        node = self.label(label, package)
        while node is not None:
            kind = node.get('class', '')
            if node.get('scrollable') == 'true' or 'RecyclerView' in kind or kind.endswith('ScrollView'):
                break
            is_row = (kind == 'android.widget.LinearLayout' and node.get('clickable') == 'true')
            is_row = is_row or node.get('resource-id') == 'com.android.settings:id/main_switch_bar'
            if is_row:
                checks = [n for n in node.iter('node')
                          if n.get('checkable') == 'true' and n.get('package') == package]
                if len(checks) == 1:
                    bounds(checks[0])
                    return checks[0]
                break
            node = self.parents.get(node)
        raise UiUnavailable('Cannot identify the single switch for ' + label)

    def launcher_rows(self):
        rows = []
        for node in self.nodes:
            if node.get('package') != AA:
                continue
            labels = [c for c in node if c.get('resource-id') == AA + ':id/app_name']
            if len(labels) != 1:
                continue
            checks = [c for c in node if c.get('resource-id') == AA + ':id/enable_disable_app']
            rows.append((labels[0].get('text'), checks[0] if len(checks) == 1 else None))
        return rows


class Ui:
    def __init__(self, adb, records_dir, before_mutation=None):
        self.adb = adb
        self.folder = Path(records_dir) / 'private-ui'
        self.folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.folder, 0o700)
        self.before_mutation = before_mutation or (lambda: None)
        self.sequence = 0
        self.journal = []
        self.expected_package = None

    def screen(self):
        for attempt in range(3):
            remote = '/data/local/tmp/hbaa-' + uuid.uuid4().hex + '.xml'
            try:
                result = self.adb.shell('uiautomator', 'dump', remote, check=False)
                if 'dumped to:' not in result.stdout:
                    if attempt < 2:
                        time.sleep(0.5)
                        continue
                    raise UiUnavailable('Android did not expose a usable screen; unlock the phone')
                data = self.adb.run('exec-out', 'cat', remote).stdout
            finally:
                self.adb.shell('rm', '-f', remote, check=False)
            self.sequence += 1
            path = self.folder / ('screen-%04d.xml' % self.sequence)
            # Fresh random name per run avoids overwriting another setup's captures.
            if path.exists():
                path = self.folder / ('screen-' + uuid.uuid4().hex + '.xml')
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(data)
            try:
                return Screen(data)
            except ET.ParseError as error:
                raise UiUnavailable('Android returned an invalid accessibility screen') from error
        raise UiUnavailable('No usable Android screen')

    def tap_node(self, node):
        if node.get('enabled') != 'true':
            raise UiUnavailable('The requested control is disabled')
        x1, y1, x2, y2 = bounds(node)
        self.before_mutation()
        fresh = self.screen()
        keys = ('text', 'content-desc', 'resource-id', 'package', 'bounds', 'checked', 'checkable')
        candidates = [n for n in fresh.nodes if all(n.get(k) == node.get(k) for k in keys)]
        if len(candidates) != 1 or candidates[0].get('enabled') != 'true':
            raise UiUnavailable('The screen changed before the requested action; inspect it and rerun')
        self.adb.shell('input', 'tap', str((x1 + x2) // 2), str((y1 + y2) // 2))
        time.sleep(0.35)

    def tap(self, label, package=None):
        self.tap_node(self.screen().label(label, package))

    def launch(self, *args):
        self.before_mutation()
        result = self.adb.shell('am', 'start', *args)
        if re.search(r'(?im)^\s*(?:error:|exception|securityexception)', result.stdout + result.stderr):
            raise UiUnavailable('Android could not open the requested settings screen')
        time.sleep(0.5)

    def swipe(self, direction='down'):
        self.before_mutation()
        screen = self.screen()
        areas = [n for n in screen.nodes if n.get('scrollable') == 'true'
                 and (not self.expected_package or n.get('package') == self.expected_package)]
        if not areas:
            raise UiUnavailable('This screen exposes no scrollable settings list')
        area = max(areas, key=lambda n: (bounds(n)[2] - bounds(n)[0]) * (bounds(n)[3] - bounds(n)[1]))
        x1, y1, x2, y2 = bounds(area)
        x = (x1 + x2) // 2
        high, low = int(y1 + .22 * (y2 - y1)), int(y1 + .82 * (y2 - y1))
        start, end = (low, high) if direction == 'down' else (high, low)
        self.adb.shell('input', 'swipe', str(x), str(start), str(x), str(end), '400')
        time.sleep(0.25)

    def find(self, label, package, limit=7):
        self.expected_package = package
        last = None
        for attempt in range(limit + 1):
            screen = self.screen()
            if screen.has(label, package):
                return screen
            fingerprint = ET.tostring(screen.root)
            if fingerprint == last or attempt == limit:
                break
            last = fingerprint
            self.swipe()
        raise UiUnavailable('Setting is not visible in this version/language: ' + label)

    def record(self, **entry):
        self.journal.append({'utc': shared.now(), **entry})
        shared.atomic_json(self.folder / 'changes.json', self.journal)

    def set_switch(self, label, wanted, package):
        screen = self.find(label, package)
        control = screen.switch(label, package)
        before = checked(control)
        if before == wanted:
            self.record(setting=label, before=before, requested=wanted, status='already-verified')
            return {'status': 'verified', 'before': before, 'after': before}
        self.record(setting=label, before=before, requested=wanted, status='write-intent')
        self.tap_node(control)
        after = checked(self.screen().switch(label, package))
        self.record(setting=label, before=before, requested=wanted, after=after,
                    status='verified' if after == wanted else 'unverified')
        if after != wanted:
            raise UiUnavailable('Switch did not read back as requested: ' + label)
        return {'status': 'verified', 'before': before, 'after': after}


def configure_car_preferences(ui, keep_apps):
    """Turn auto-media off and verify every encountered optional launcher row."""
    ui.launch('--activity-clear-top', '-n', AA + '/.companion.settings.DefaultSettingsActivity')
    if not ui.screen().has('Android Auto', AA):
        raise UiUnavailable('Return to the main Android Auto settings page, then rerun this step')
    music = ui.set_switch('Start music automatically', False, AA)
    ui.find('Customize launcher', AA)
    ui.tap('Customize launcher', AA)
    ui.find('Launcher sorting', AA)
    observed, protected, unresolved = {}, set(), {}
    last_screen = None
    for attempt in range(80):
        screen = ui.screen()
        if not screen.has('Customize launcher', AA):
            raise UiUnavailable('The Android Auto launcher editor is no longer open')
        rows = screen.launcher_rows()
        if not rows:
            raise UiUnavailable('No recognizable Android Auto launcher rows')
        changed = False
        for name, check in rows:
            if check is None:
                if name in {'Maps', 'Exit', 'Phone', 'Settings'}:
                    protected.add(name)
                else:
                    unresolved[name] = 'no recognized checkbox'
                continue
            x1, y1, x2, y2 = bounds(check)
            # Do not tap a partly clipped checkbox at a viewport edge.
            if y2 - y1 < 24:
                unresolved[name] = 'clipped checkbox'
                continue
            wanted, before = name in keep_apps, checked(check)
            observed[name] = before
            unresolved.pop(name, None)
            if before != wanted:
                if check.get('enabled') != 'true':
                    unresolved[name] = 'disabled checkbox differs from requested choice'
                    continue
                ui.record(setting='launcher/' + name, before=before, requested=wanted, status='write-intent')
                ui.tap_node(check)
                # Hiding moves the row into Hidden Apps. Locate it again in a full
                # verification pass rather than interpreting a stale node.
                changed = True
                last_screen = None
                break
        if changed:
            # Return to the top with bounded semantic scrolling after reordering.
            top_confirmed = False
            for _ in range(7):
                s = ui.screen()
                if s.has('Launcher sorting', AA):
                    top_confirmed = True
                    break
                ui.swipe('up')
            if not top_confirmed:
                raise UiUnavailable('Could not verify the top of the launcher list after it reordered')
            observed, unresolved = {}, {}
            continue
        fingerprint = ET.tostring(screen.root)
        if fingerprint == last_screen:
            break
        last_screen = fingerprint
        ui.swipe()
    else:
        raise UiUnavailable('Launcher verification did not settle; inspect it on the phone')
    mismatch = {n: v for n, v in observed.items() if v != (n in keep_apps)}
    if mismatch or unresolved:
        raise UiUnavailable('Launcher choices did not independently verify')
    ui.record(setting='launcher', status='verified', optional=observed, protected=sorted(protected))
    return {'status': 'verified', 'music_autostart': music, 'optional_apps': observed,
            'protected_apps': sorted(protected),
            'requested_but_not_observed': sorted(set(keep_apps) - set(observed) - protected),
            'note': 'Launcher hiding does not disable apps or establish CPU savings. Reconnect Android Auto to refresh.'}


def configure_phone_maps(ui):
    """Set only phone Navigation's building preference; projection is separate."""
    ui.launch('-a', 'android.intent.action.MAIN', '-c', 'android.intent.category.LAUNCHER', '-p', MAPS)
    for _ in range(4):
        screen = ui.screen()
        if screen.has('Show raised buildings', MAPS):
            break
        if screen.has('Navigation', MAPS):
            if screen.has('Settings', MAPS):
                ui.tap('Navigation', MAPS)
            break
        if screen.has('Account and settings.', MAPS):
            ui.tap('Account and settings.', MAPS)
            ui.find('Settings', MAPS)
            ui.tap('Settings', MAPS)
            ui.find('Navigation', MAPS)
            ui.tap('Navigation', MAPS)
            break
        raise UiUnavailable('Complete Maps first-run prompts and return to its main map, then resume setup')
    result = ui.set_switch('Show raised buildings', False, MAPS)
    return {'status': 'verified', 'phone_navigation_raised_buildings': result,
            'projected_raised_buildings': 'pending-real-head-unit-check',
            'note': 'Android Auto Maps has a separate Raised Buildings switch. This phone setting does not prove it is off.'}


def configure_notification(ui):
    """Hide only the companion's channel after it has been created by the app."""
    ui.launch('-a', 'android.settings.CHANNEL_NOTIFICATION_SETTINGS',
              '--es', 'android.provider.extra.APP_PACKAGE', 'org.hibreak.autoscale',
              '--es', 'android.provider.extra.CHANNEL_ID', 'automatic-scaling')
    screen = ui.screen()
    headers = [n for n in screen.nodes
               if n.get('resource-id') == 'com.android.settings:id/entity_header_title'
               and n.get('text') == 'Automatic Android Auto scaling']
    if len(headers) != 1 or not screen.has('HiBreak Auto Scale', 'com.android.settings'):
        raise UiUnavailable('The helper notification channel is not available; enable the helper first')
    result = ui.set_switch('Show notifications', False, 'com.android.settings')
    listing = ui.adb.shell('pm', 'list', 'packages', '--user', '0', '-U', 'org.hibreak.autoscale').stdout
    uids = re.findall(r'(?m)^package:org\.hibreak\.autoscale uid:(\d+)\s*$', listing)
    if len(uids) != 1:
        raise UiUnavailable('Could not identify the helper notification owner')
    notification = ui.adb.shell('dumpsys', 'notification').stdout
    if not notification_is_hidden(notification, int(uids[0])):
        raise UiUnavailable('The hidden notification channel did not independently read back')
    return {'status': 'verified', 'channel': 'automatic-scaling', 'visible': False,
            'switch': result,
            'note': 'Overall notification permission is preserved. Android can still show Active apps.'}


def notification_is_hidden(dump, uid):
    """Read the channel only from this exact app/user's preferences block."""
    owner = re.search(r'(?m)^( +)AppSettings: org\.hibreak\.autoscale \(' + str(uid) + r'\)[^\n]*\n', dump)
    if owner is None:
        return False
    indent = len(owner.group(1))
    record = []
    for line in dump[owner.end():].splitlines():
        if line.strip() and len(line) - len(line.lstrip()) <= indent:
            break
        record.append(line)
    return bool(re.search(r"mId='automatic-scaling'[^\n]*mImportance=0", '\n'.join(record)))


def enable_helper(ui):
    """Use the app's normal guarded Enable; never fabricate its private state."""
    app = 'org.hibreak.autoscale'
    ui.launch('-n', app + '/.MainActivity')
    for attempt in range(8):
        screen = ui.screen()
        text = '\n'.join(n.get('text', '') for n in screen.nodes if n.get('package') == app)
        if ('Automatic scaling: enabled' in text and 'Waiting for Android Auto.' in text
                and 'Finishing or recovering' not in text and 'Needs attention' not in text):
            service = ui.adb.shell('dumpsys', 'activity', 'services', app).stdout
            if 'isForeground=true' in service:
                return {'status': 'verified', 'monitoring_enabled': True,
                        'backup': 'App enable completed its guarded own-phone backup path',
                        'car_selection': 'separate-user-choice', 'head_unit_dpi': 'not-inferred'}
        if 'Needs attention' in text or 'Finishing or recovering' in text:
            raise UiUnavailable('Finish the helper recovery shown on the phone before continuing')
        if attempt == 0:
            ui.tap('ENABLE DETECTION / LEARN CAR', app)
        time.sleep(0.5)
    raise UiUnavailable('Helper enabling did not verify; inspect its visible status on the phone')


def vendor_lock_present(dump):
    match = re.search(r'(?mi)^app white list:[ \t]*\r?\n(.*?)(?=^\S[^\n]*:[ \t]*(?:\r?\n|\Z)|\Z)', dump, re.S)
    if match is None:
        raise UiUnavailable('This firmware does not expose a recognized Bigme background-lock list')
    return 'org.hibreak.autoscale:0' in {line.strip() for line in match.group(1).splitlines()}


def configure_vendor_lock(ui, interactive=True, seconds=90, announce=print):
    def present():
        return vendor_lock_present(ui.adb.shell('dumpsys', 'xrz_system_proxy_service').stdout)
    if present():
        return {'status': 'verified', 'locked': True, 'changed_by_script': False}
    if not interactive:
        return {'status': 'pending-person', 'locked': False}
    announce('On the phone: Recents > Process manage > lock the HiBreak Auto Scale card. '
             'Setup will notice the padlock automatically; no typing is needed.')
    ui.before_mutation()
    ui.adb.shell('input', 'keyevent', '187')
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if present():
            return {'status': 'verified', 'locked': True, 'changed_by_script': False,
                    'note': 'The person set the lock; its vendor readback was independently verified.'}
        time.sleep(2)
    return {'status': 'pending-person', 'locked': False,
            'note': 'Keep the helper locked in Bigme Recents before relying on unattended scaling.'}


def selected_car(screen):
    app = 'org.hibreak.autoscale'
    labels = []
    for node in screen.nodes:
        if node.get('package') != app:
            continue
        text = node.get('text', '')
        if 'Automatic scaling: enabled' not in text or 'Finishing or recovering' in text or 'Needs attention' in text:
            continue
        labels.extend(re.findall(r'(?m)^Paired-car automatic: (.+)$', text))
    return labels[0] if len(labels) == 1 and labels[0] != 'off' else None


def configure_selected_car(ui, audit, identity, interactive=True, seconds=90, announce=print):
    """Open the existing picker; only the person can identify the correct car."""
    app, permission = 'org.hibreak.autoscale', 'android.permission.BLUETOOTH_CONNECT'
    ui.launch('-n', app + '/.MainActivity')
    chosen = selected_car(ui.screen())
    if not interactive and not chosen:
        return {'status': 'pending-person', 'note': 'Choose your own already-paired car on the phone.'}
    if int(identity['sdk']) >= 31:
        before = ui.adb.shell('dumpsys', 'package', app).stdout
        grants = re.findall(re.escape(permission) + r': granted=(true|false)\b', before)
        if len(grants) != 1:
            raise UiUnavailable('Could not identify the helper Nearby devices permission unambiguously')
        if grants[0] != 'true':
            ui.record(setting=permission, before=False, requested=True, status='write-intent')
            audit.event('nearby-devices-grant-intent', package=app, permission=permission, previously_granted=False)
            ui.before_mutation()
            ui.adb.shell('pm', 'grant', '--user', '0', app, permission)
            after = ui.adb.shell('dumpsys', 'package', app).stdout
            if re.findall(re.escape(permission) + r': granted=(true|false)\b', after) != ['true']:
                raise UiUnavailable('Nearby devices permission did not verify')
            ui.record(setting=permission, before=False, after=True, status='verified',
                      undo='After Stop and restore, revoke this helper permission only if you no longer want automatic car detection.')
    if chosen:
        return {'status': 'verified', 'selected_label': chosen, 'selection_preserved': True,
                'nearby_devices_permission': 'verified'}
    announce('Choose your own car from the list on the phone. Setup will notice your selection automatically. '
             'If it is not paired yet, finish normal Bluetooth pairing and choose it later.')
    ui.tap('AUTOMATIC FOR PAIRED CAR', app)
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        screen = ui.screen()
        if screen.has('Pair the car first', app) or screen.has('Could not choose car', app):
            return {'status': 'pending-person', 'note': 'Pair your actual car in Bluetooth settings, then choose it in the helper.'}
        chosen = selected_car(screen)
        if chosen:
            return {'status': 'verified', 'selected_label': chosen, 'selection_preserved': False,
                    'note': 'The person selected this device in the normal paired-car picker; no car was guessed.'}
        time.sleep(1)
    return {'status': 'pending-person', 'note': 'Open Automatic for paired car after pairing your actual car.'}
