import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import setup_ui as m


def node(text='', *, check=None, desc='', rid='', children='', package=m.AA, bounds='[0,0][500,100]'):
    return ('<node text="%s" content-desc="%s" package="%s" enabled="true" '
            'class="%s" clickable="%s" bounds="%s" resource-id="%s" checkable="%s" checked="%s">%s</node>') % (
                text, desc, package, 'android.widget.LinearLayout' if children else 'android.widget.TextView',
                'true' if children else 'false', bounds, rid, str(check is not None).lower(),
                str(bool(check)).lower(), children)


def screen(children):
    return m.Screen('<hierarchy>' + children + '</hierarchy>')


def setting(checked):
    return screen(node(children=node('Start music automatically') + node(check=checked)))


class Controls(unittest.TestCase):
    def test_guard_refusal_blocks_swipe(self):
        ui=m.Ui.__new__(m.Ui)
        def refuse():raise m.shared.Refusal('identity changed')
        ui.before_mutation=refuse
        ui.screen=lambda:self.fail('No screen action is permitted after refusal')
        with self.assertRaises(m.shared.Refusal):ui.swipe()

    def test_unknown_maps_dialog_is_left_for_the_person(self):
        class Fake:
            def launch(self,*a):pass
            def screen(self):return screen(node('Review your choices',package=m.MAPS))
        with self.assertRaises(m.UiUnavailable):m.configure_phone_maps(Fake())

    def test_negative_bounds_do_not_become_positive_coordinates(self):
        with self.assertRaises(m.UiUnavailable):
            m.bounds(screen(node('Maps',bounds='[0,-20][100,100]')).nodes[0])

    def test_notification_readback_cannot_match_another_package_or_user(self):
        other="      AppSettings: other.package (10199)\n        NotificationChannel{mId='automatic-scaling', mImportance=0}\n"
        own="      AppSettings: org.hibreak.autoscale (10199)\n        NotificationChannel{mId='automatic-scaling', mImportance=0}\n"
        self.assertFalse(m.notification_is_hidden(other,10199))
        self.assertFalse(m.notification_is_hidden(own,110199))
        self.assertTrue(m.notification_is_hidden(own,10199))

    def test_missing_checked_is_never_interpreted_as_off(self):
        for value in [None, '', 'unknown', 'False']:
            control=setting(False).switch('Start music automatically',m.AA)
            if value is None: control.attrib.pop('checked')
            else: control.set('checked',value)
            with self.assertRaises(m.UiUnavailable): m.checked(control)

    def test_icon_and_caption_choose_caption_but_two_captions_refuse(self):
        s = screen(node(desc='Maps') + node('Maps'))
        self.assertEqual(s.label('Maps').get('text'), 'Maps')
        with self.assertRaises(m.UiUnavailable):
            screen(node('Maps') + node('Maps')).label('Maps')

    def test_switch_cannot_guess_between_two_controls(self):
        with self.assertRaises(m.UiUnavailable):
            screen(node(children=node('Start music automatically') + node(check=True) + node(check=False))).switch(
                'Start music automatically', m.AA)

    def test_switch_does_not_climb_out_of_its_row(self):
        unrelated = node(children=node('Other setting') + node(check=True))
        missing = node(children=node('Start music automatically'))
        with self.assertRaises(m.UiUnavailable):
            screen(node(children=missing + unrelated)).switch('Start music automatically', m.AA)

    def test_foreign_overlay_label_is_not_a_setting(self):
        s = screen(node('Start music automatically', package='unrelated.overlay') + node(check=True))
        with self.assertRaises(m.UiUnavailable):
            s.switch('Start music automatically', m.AA)

    def test_idempotent_switch_and_failed_independent_readback(self):
        class Fake:
            def __init__(self, before, after): self.before=before; self.after=after; self.taps=0; self.log=[]
            def find(self, *a): return setting(self.before)
            def screen(self): return setting(self.after)
            def tap_node(self, n): self.taps += 1
            def record(self, **entry): self.log.append(entry)
        f = Fake(False, False)
        result = m.Ui.set_switch(f, 'Start music automatically', False, m.AA)
        self.assertEqual(f.taps, 0)
        self.assertEqual(result['status'], 'verified')
        f = Fake(True, True)
        with self.assertRaises(m.UiUnavailable):
            m.Ui.set_switch(f, 'Start music automatically', False, m.AA)
        self.assertEqual(f.taps, 1)
        self.assertEqual(f.log[0]['status'], 'write-intent')
        self.assertEqual(f.log[-1]['status'], 'unverified')

    def test_dump_failure_removes_temporary_file_and_never_taps(self):
        class Adb:
            def __init__(self): self.calls=[]
            def shell(self, *a, **kw):
                self.calls.append(a)
                return SimpleNamespace(stdout='ERROR: null root node returned', stderr='', returncode=0)
        adb=Adb()
        with tempfile.TemporaryDirectory() as folder, patch.object(m.time, 'sleep'):
            with self.assertRaises(m.UiUnavailable): m.Ui(adb, folder).screen()
        self.assertEqual(sum(c[:2] == ('rm','-f') for c in adb.calls), 3)
        self.assertFalse(any(c[:2] == ('input','tap') for c in adb.calls))

    def test_changed_screen_refuses_stale_tap(self):
        calls=[]
        ui=m.Ui.__new__(m.Ui)
        ui.before_mutation=lambda:None
        ui.adb=SimpleNamespace(shell=lambda *a:calls.append(a))
        ui.screen=lambda:screen(node('Other page'))
        with self.assertRaises(m.UiUnavailable):ui.tap_node(screen(node('Maps')).label('Maps'))
        self.assertEqual(calls,[])


class LauncherContract(unittest.TestCase):
    def test_incomplete_rewind_cannot_verify_a_suffix_only(self):
        class Fake:
            lost=False
            def launch(self,*a):pass
            def set_switch(self,*a):return {'status':'verified'}
            def find(self,*a):return self.screen()
            def tap(self,*a):pass
            def swipe(self,*a):pass
            def record(self,**entry):pass
            def tap_node(self,*a):self.lost=True
            def screen(self):
                rows=node(children=node('News',rid=m.AA+':id/app_name')+node(check=not self.lost,rid=m.AA+':id/enable_disable_app'))
                return screen(node('Android Auto')+node('Customize launcher')+('' if self.lost else node('Launcher sorting'))+rows)
        with self.assertRaises(m.UiUnavailable):m.configure_car_preferences(Fake(),{'Maps'})

    def test_reordered_rows_rechecked_and_required_entries_preserved(self):
        class FakeUi:
            def __init__(self):
                self.apps={'News':True,'Messages':True,'Heritage':False,'NewPipe':True}
                self.taps=[];self.log=[]
            def launch(self,*a):pass
            def set_switch(self,*a):return {'status':'verified','before':True,'after':False}
            def find(self,*a):return self.screen()
            def tap(self,*a):pass
            def swipe(self,*a):pass
            def record(self,**entry):self.log.append(entry)
            def tap_node(self,c):
                name=c.get('content-desc');self.taps.append(name);self.apps[name]=not self.apps[name]
            def screen(self):
                rows=[]
                for name in ['Exit','Maps','Phone','Settings'] + sorted(self.apps,key=lambda n: (not self.apps[n],n)):
                    label=node(name,rid=m.AA+':id/app_name')
                    check='' if name not in self.apps else node(check=self.apps[name],desc=name,rid=m.AA+':id/enable_disable_app')
                    rows.append(node(children=label+check))
                return screen(node('Android Auto')+node('Customize launcher')+node('Launcher sorting')+''.join(rows))
        ui=FakeUi()
        result=m.configure_car_preferences(ui,{'Maps','Messages','Heritage','NewPipe'})
        self.assertEqual(result['optional_apps'],{'Heritage':True,'Messages':True,'NewPipe':True,'News':False})
        self.assertEqual(set(result['protected_apps']),{'Maps','Exit','Phone','Settings'})
        self.assertEqual(set(ui.taps),{'News','Heritage'})
        self.assertEqual(result['requested_but_not_observed'],[])


if __name__ == '__main__': unittest.main()
