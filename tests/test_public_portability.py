"""Real host filesystem and encoding contracts; no phone or network access."""
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import hibreak_aa as core
import install_on_mac as installer
import setup_ui


class NativePersistence(unittest.TestCase):
    def test_real_create_replace_and_refused_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'state.json'
            core.atomic_json(path, {'phase': 'before', 'label': 'Мой автомобиль 🚗'}, new=True)
            self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['phase'], 'before')
            core.atomic_json(path, {'phase': 'after', 'label': 'Мой автомобиль 🚗'})
            self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['phase'], 'after')
            with self.assertRaises(core.Refusal):
                core.atomic_json(path, {'phase': 'wrong'}, new=True)
            self.assertEqual(json.loads(path.read_text(encoding='utf-8'))['phase'], 'after')
            self.assertEqual([p.name for p in Path(folder).iterdir()], ['state.json'])

    def test_non_ascii_capture_uses_explicit_utf8_under_legacy_locale(self):
        xml = '<hierarchy><node text="Мой автомобиль 🚗" package="synthetic.app" bounds="[0,0][400,100]" /></hierarchy>'
        class Adb:
            def shell(self, *args, **kwargs):
                return SimpleNamespace(stdout='UI hierarchy dumped to: /data/local/tmp/synthetic.xml', stderr='')
            def run(self, *args, **kwargs):
                return SimpleNamespace(stdout=xml, stderr='')
        real_fdopen = os.fdopen
        def legacy_fdopen(fd, mode='r', **kwargs):
            kwargs.setdefault('encoding', 'cp1252')
            return real_fdopen(fd, mode, **kwargs)
        with tempfile.TemporaryDirectory() as folder, patch.object(setup_ui.os, 'fdopen', side_effect=legacy_fdopen):
            capture = setup_ui.Ui(Adb(), folder)
            self.assertTrue(capture.screen().has('Мой автомобиль 🚗', 'synthetic.app'))
            saved = next((Path(folder) / 'private-ui').glob('*.xml'))
            self.assertEqual(saved.read_text(encoding='utf-8'), xml)


class UndoPresentation(unittest.TestCase):
    def test_windows_path_and_quote_have_powershell_and_structured_forms(self):
        path = "C:\\Users\\O'Connor\\Android Tools\\adb.exe"
        before = {'permissions': {installer.DUMP: False, installer.NOTIFICATIONS: True}}
        report = installer.undo_advisory(path, 'SYNTHETIC-USB', before, {'present': False}, True)
        self.assertEqual(len(report['argv_for_this_install']), 2)
        self.assertTrue(report['powershell_commands_for_this_install'][0].startswith("& 'C:\\Users\\O''Connor"))
        self.assertEqual(report['argv_for_this_install'][0][0], path)
        self.assertIn('POSIX', report['commands_for_this_install_shell'])
        self.assertFalse(any(installer.NOTIFICATIONS in str(item) for item in report['argv_for_this_install']))


if __name__ == '__main__':
    unittest.main()
