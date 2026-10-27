from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch
from tempfile import TemporaryDirectory

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import runtime
from control_core import Observation, Profile


class RuntimeSafety(unittest.TestCase):
    def setUp(self):
        self.save=patch.object(runtime,'profile_save')
        self.save.start()
        self.r=runtime.Runtime((0,0,1920,1080),True)
        self.r.capture_stop.clear()  # Synthetic camera; no real capture is opened.

    def tearDown(self):
        self.r.close(); self.save.stop()

    def test_voice_commands_do_nothing_while_paused(self):
        self.r.command('click')
        self.assertEqual(self.r.events_count,{})

    def test_voice_drag_has_watchdog(self):
        self.r.pause(False)
        self.r.core.last_obs=Observation(time.monotonic(),.5,.5,.8,60)
        self.r.command('drag')
        self.assertTrue(self.r.core.finger_down)
        self.r.core.tick(time.monotonic()+.3)
        self.assertFalse(self.r.core.finger_down)

    def test_voice_double_click_is_two_clicks(self):
        self.r.pause(False); self.r.command('double_click')
        self.assertEqual(self.r.events_count.get('click'),2)

    def test_uncalibrated_side_tap_cannot_start(self):
        self.r.core.profile=Profile(gesture='side')
        self.assertFalse(self.r.pause(False))

    def test_failed_calibration_keeps_old_profile(self):
        old=self.r.core.profile
        self.r.calibrate('side')
        self.r.calibration.done=True
        self.r._finish_calibration()
        self.assertIs(self.r.core.profile,old)

    def test_no_camera_cannot_start(self):
        self.r.capture_stop.set()
        self.assertFalse(self.r.pause(False))

    def test_fluid_pointer_does_not_enable_desktop_swipes(self):
        self.r.core.profile.motion_scheme='fluid'
        self.r.core.profile.shortcuts=False
        self.assertTrue(self.r.pause(False))
        self.assertFalse(self.r.desktop_swipes)
        self.r.enable_swipes(True)
        self.assertFalse(self.r.desktop_swipes)

    def test_restore_pointer_releases_drag_and_preserves_calibration(self):
        with TemporaryDirectory() as folder,patch.object(runtime,'DATA',Path(folder)):
            self.r.core.profile=Profile(contact_on=.2,contact_off=.5,sensitivity=1.32,
                                        calibrated=True,tilt_precision=True,shortcuts=True)
            self.r.core.finger_down=True
            self.r.core.state='drag'
            self.r.desktop_swipes=True
            self.r.shortcut_reserved=True
            self.r.scroll_remaining=200
            self.r.restore_pointer()
            self.assertFalse(self.r.core.finger_down)
            self.assertEqual(self.r.events_count.get('up'),1)
            self.assertEqual(self.r.core.profile.sensitivity,1.32)
            self.assertEqual(self.r.core.profile.contact_on,.2)
            self.assertTrue(self.r.core.profile.calibrated)
            self.assertTrue(self.r.previous_profile.tilt_precision)
            self.assertFalse(self.r.core.profile.tilt_precision)
            self.assertFalse(self.r.core.profile.shortcuts)
            self.assertFalse(self.r.desktop_swipes)
            self.assertFalse(self.r.shortcut_reserved)
            self.assertEqual(self.r.scroll_remaining,0)
            self.r.pause(False)
            t=time.monotonic()
            for i in range(20):
                self.r.process_shortcuts(Observation(t+i/30,.5,.5,.8,60,finger_mask=3),t+i/30)
            self.assertFalse(self.r.shortcut_reserved)

    def test_recovery_keeps_first_local_profile_backup(self):
        with TemporaryDirectory() as folder,patch.object(runtime,'DATA',Path(folder)):
            saved=Path(folder)/'profile.json';saved.write_text('original profile')
            self.r.restore_pointer()
            saved.write_text('later profile')
            self.r.restore_pointer()
            self.assertEqual((Path(folder)/'profile-before-0.8.1.json').read_text(),'original profile')

    def test_camera_stop_clears_stale_telemetry(self):
        self.r.metrics.update(fps=30,palm_px=100,camera_width=1920,observed_at=100,tracked=True)
        self.r.stop_camera()
        self.assertTrue(self.r.core.paused)
        self.assertEqual(self.r.metrics['fps'],0)
        self.assertEqual(self.r.metrics['camera_width'],0)
        self.assertFalse(self.r.metrics['tracked'])

    def test_mouse_handoff_resumes_without_manual_start(self):
        with self.r.lock:
            self.r.core.paused=False
            now=time.monotonic()+100
            self.r.takeover(dict(source_pid=0),now)
            self.assertFalse(self.r.core.paused)
            self.assertGreater(self.r.takeover_until,now)
            self.r.resume_takeover(now+.81)
            self.assertEqual(self.r.takeover_until,0)
            self.assertFalse(self.r.core.paused)

    def test_explicit_pause_does_not_auto_resume(self):
        with self.r.lock:
            self.r.core.paused=False
            now=time.monotonic()+100
            self.r.takeover(None,now)
            self.r.pause(True)
            self.r.resume_takeover(now+10)
            self.assertTrue(self.r.core.paused)
            self.assertFalse(self.r.output.enabled)

    def test_mouse_handoff_releases_drag(self):
        with self.r.lock:
            self.r.core.paused=False
            self.r.core.finger_down=True
            self.r.core.state='drag'
            self.r.takeover(None,time.monotonic()+100)
            self.assertFalse(self.r.core.finger_down)
            self.assertEqual(self.r.events_count.get('up'),1)

    def test_two_finger_tap_works_after_mouse_handoff(self):
        from unittest.mock import Mock
        with self.r.lock:
            self.r.core.paused=False
            now=time.monotonic()+100
            self.r.takeover(None,now)
            self.r.resume_takeover(now+.81)
            self.r.handle_shortcut=Mock()
            t=now+.9
            for mask in [3]*10+[0]*3+[3]:
                t+=1/30
                self.r.process_shortcuts(Observation(t,.5,.5,.8,60,finger_mask=mask),t)
            self.r.handle_shortcut.assert_called_once_with(dict(kind='double_click'))


if __name__=='__main__': unittest.main()
