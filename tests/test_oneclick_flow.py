import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import setup_on_mac as wizard
import setup_ui as ui


class PhoneWait(unittest.TestCase):
    def test_waits_through_authorization_without_restarting_or_writing(self):
        results=iter(['List of devices attached\n','List of devices attached\nPHONE unauthorized\n',
                      'List of devices attached\nPHONE device product:HiBreak\n'])
        calls=[]
        adb=SimpleNamespace(run=lambda *a,**k:(calls.append((a,k)) or SimpleNamespace(stdout=next(results))))
        messages=[]
        with patch.object(wizard.shared,'select_device',return_value={'verified':'phone'}) as select, patch.object(wizard.time,'sleep'):
            result=wizard.wait_for_phone(adb,None,120,messages.append)
        self.assertEqual(result,{'verified':'phone'})
        self.assertEqual(len(messages),2)
        self.assertEqual(len(calls),3)
        select.assert_called_once_with(adb,None)

    def test_unauthorized_second_phone_is_not_ignored_for_another_online_phone(self):
        output='List of devices attached\nFIRST device\nSECOND unauthorized\n'
        adb=SimpleNamespace(run=lambda *a,**k:SimpleNamespace(stdout=output))
        with patch.object(wizard.time,'monotonic',side_effect=[0,5]), patch.object(wizard.shared,'select_device') as select:
            with self.assertRaises(wizard.shared.Refusal):wizard.wait_for_phone(adb,None,5,lambda m:None)
        select.assert_not_called()

    def test_explicit_transport_does_not_wait_for_an_unrelated_unauthorized_phone(self):
        adb=SimpleNamespace(run=lambda *a,**k:SimpleNamespace(stdout='FIRST device\nSECOND unauthorized\n'))
        with patch.object(wizard.shared,'select_device',return_value={'phone':'FIRST'}) as select:
            wizard.wait_for_phone(adb,'FIRST',5,lambda m:None)
        select.assert_called_once_with(adb,'FIRST')


class HumanActions(unittest.TestCase):
    def test_vendor_lock_matches_exact_app_and_primary_user_only(self):
        self.assertFalse(ui.vendor_lock_present('platform white list:\norg.hibreak.autoscale:0\napp white list:\nother.app:0\n\napp clone info:\n'))
        self.assertFalse(ui.vendor_lock_present('app white list:\norg.hibreak.autoscale:10\n\napp clone info:\n'))
        self.assertTrue(ui.vendor_lock_present('app white list:\n  org.hibreak.autoscale:0\n\napp clone info:\n'))
        with self.assertRaises(ui.UiUnavailable):ui.vendor_lock_present('unrecognized vendor output')

    def test_existing_lock_needs_no_navigation_or_person(self):
        helper=SimpleNamespace(adb=SimpleNamespace(shell=lambda *a:SimpleNamespace(stdout='app white list:\norg.hibreak.autoscale:0\n')))
        report=ui.configure_vendor_lock(helper,interactive=True)
        self.assertEqual(report['status'],'verified')
        self.assertFalse(report['changed_by_script'])

    def test_existing_car_is_preserved_without_permissions_or_picker(self):
        text='Automatic scaling: enabled\nPaired-car automatic: Synthetic Car'
        screen=SimpleNamespace(nodes=[{'package':'org.hibreak.autoscale','text':text}])
        adb=SimpleNamespace(shell=lambda *a:SimpleNamespace(stdout='android.permission.BLUETOOTH_CONNECT: granted=true'))
        helper=SimpleNamespace(launch=lambda *a:None,screen=lambda:screen,adb=adb)
        report=ui.configure_selected_car(helper,None,{'sdk':'34'},interactive=True)
        self.assertTrue(report['selection_preserved'])
        self.assertEqual(report['selected_label'],'Synthetic Car')

    def test_existing_car_missing_permission_is_repaired_without_reselection(self):
        commands=[];events=[];state={'granted':False}
        def shell(*a):
            commands.append(a)
            if a[:2]==('pm','grant'):state['granted']=True
            return SimpleNamespace(stdout='android.permission.BLUETOOTH_CONNECT: granted='+str(state['granted']).lower())
        text='Automatic scaling: enabled\nPaired-car automatic: Synthetic Car\nNearby devices access is missing.'
        helper=SimpleNamespace(launch=lambda *a:None,screen=lambda:SimpleNamespace(nodes=[{'package':'org.hibreak.autoscale','text':text}]),
            adb=SimpleNamespace(shell=shell),before_mutation=lambda:None,record=lambda **k:events.append(k))
        audit=SimpleNamespace(event=lambda *a,**k:events.append((a,k)))
        report=ui.configure_selected_car(helper,audit,{'sdk':'34'},interactive=False)
        self.assertEqual(report['status'],'verified')
        self.assertTrue(report['selection_preserved'])
        self.assertEqual(sum(c[:2]==('pm','grant') for c in commands),1)

    def test_noninteractive_car_stage_never_grants_or_guesses_a_car(self):
        screen=SimpleNamespace(nodes=[{'package':'org.hibreak.autoscale','text':'Automatic scaling: enabled\nPaired-car automatic: off'}])
        helper=SimpleNamespace(launch=lambda *a:None,screen=lambda:screen)
        report=ui.configure_selected_car(helper,None,{'sdk':'34'},interactive=False)
        self.assertEqual(report['status'],'pending-person')


class WindowsPersistence(unittest.TestCase):
    def test_atomic_file_flush_does_not_try_opening_a_windows_directory(self):
        import hibreak_aa as h
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'private.json'
            real_open=h.os.open
            def guarded_open(target,*a,**k):
                if Path(target)==path.parent:raise AssertionError('Windows cannot os.open directories')
                return real_open(target,*a,**k)
            with patch.object(h.os,'name','nt'),patch.object(h.os,'open',side_effect=guarded_open):
                h.atomic_json(path,{'own-phone':True},new=True)
            self.assertEqual(json.loads(path.read_text()),{'own-phone':True})


if __name__=='__main__':unittest.main()
