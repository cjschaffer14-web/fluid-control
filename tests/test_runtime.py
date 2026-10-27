from pathlib import Path
import sys
import time
import unittest
from unittest.mock import patch

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
