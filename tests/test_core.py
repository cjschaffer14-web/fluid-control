from pathlib import Path
import dataclasses
import sys
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from control_core import Controller, Observation, Profile, Calibration, OneEuro, parse_command


class Interactions(unittest.TestCase):
    def setUp(self):
        self.c, self.t = Controller(), 100.0

    def feed(self, contact=.8, x=.5, y=.5, pose='point', hand='Right', palm=60, n=1):
        for _ in range(n):
            self.t+=1/30
            self.c.feed(Observation(self.t,x,y,contact,palm,pose,hand))

    def arm(self):
        self.c.pause(False); self.feed(n=10); self.c.drain()
        self.assertTrue(self.c.rearmed)

    def tap(self):
        self.feed(contact=.1,n=3); self.feed(n=3)

    def hold(self):
        self.feed(contact=.1,n=15)
        self.assertTrue(self.c.finger_down)

    def kinds(self):
        return [e['kind'] for e in self.c.drain()]

    def test_paused_no_actions(self):
        self.feed(n=20); self.tap(); self.assertEqual(self.kinds(),[])

    def test_start_closed_requires_release(self):
        self.c.pause(False); self.feed(contact=.1,n=30)
        self.assertFalse(self.c.rearmed); self.assertEqual(self.kinds(),[])

    def test_single_click(self):
        self.arm(); self.tap(); kinds=self.kinds()
        self.assertEqual(kinds.count('click'),1); self.assertNotIn('down',kinds)

    def test_double_click_is_two_contacts(self):
        self.arm(); self.tap(); self.tap()
        self.assertEqual([e['count'] for e in self.c.drain() if e['kind']=='click'],[1,2])

    def test_contact_bounce(self):
        self.arm(); self.feed(contact=.1); self.feed(n=8)
        self.assertNotIn('click',self.kinds())

    def test_release_bounce_keeps_drag(self):
        self.arm(); self.hold(); self.c.drain()
        self.feed(); self.feed(contact=.1,n=4)
        self.assertTrue(self.c.finger_down); self.assertNotIn('up',self.kinds())

    def test_drag_lifecycle(self):
        self.arm(); self.hold(); self.feed(contact=.1,x=.54,n=5); self.feed(x=.54,n=4)
        kinds=self.kinds()
        self.assertEqual((kinds.count('down'),kinds.count('up')),(1,1))
        self.assertNotIn('click',kinds); self.assertGreater(self.c.x,960)

    def test_loss_releases_once(self):
        self.arm(); self.hold(); self.c.drain()
        self.c.tick(self.t+.16); self.c.tick(self.t+.5)
        self.assertEqual(self.kinds(),['up']); self.assertFalse(self.c.rearmed)

    def test_closed_reentry_cannot_click(self):
        self.arm(); self.hold(); self.c.tick(self.t+.2); self.t+=.3; self.c.drain()
        self.feed(contact=.1,n=15); self.assertEqual(self.kinds(),[])

    def test_gap_cancels_before_feed(self):
        self.arm(); self.hold(); self.c.drain(); self.t+=.3; self.feed(contact=.1)
        self.assertEqual(self.kinds(),['up'])

    def test_switch_hand_cancels(self):
        self.arm(); self.hold(); self.c.drain(); self.feed(contact=.1,hand='Left')
        self.assertEqual(self.kinds(),['up'])

    def test_small_hand_disarms(self):
        self.arm(); self.feed(palm=12,x=.55,n=6)
        self.assertEqual(self.kinds(),[]); self.assertFalse(self.c.rearmed)

    def test_pause_releases(self):
        self.arm(); self.hold(); self.c.drain(); self.c.pause(True)
        self.assertEqual(self.kinds(),['up'])

    def test_fist_clutches(self):
        self.arm(); old=(self.c.x,self.c.y); self.feed(x=.55,pose='fist',n=10)
        self.assertEqual((self.c.x,self.c.y),old)

    def test_window_motion_requires_hold(self):
        self.c.set_mode('move'); self.arm(); self.feed(x=.55,n=6)
        self.assertEqual(self.kinds(),[])

    def test_resize_separate_from_click(self):
        self.c.set_mode('resize'); self.arm(); self.hold()
        self.feed(contact=.1,x=.55,n=6); self.feed(x=.55,n=4)
        events=self.c.drain()
        self.assertEqual([e['mode'] for e in events if e['kind']=='down'],['resize'])
        self.assertFalse(any(e['kind']=='click' for e in events))

    def test_mode_switch_releases(self):
        self.arm(); self.hold(); self.c.drain(); self.c.set_mode('move')
        self.assertEqual(self.kinds(),['up'])

    def test_scroll_dwell(self):
        self.arm(); self.feed(pose='scroll_down',n=4)
        self.assertNotIn('scroll',self.kinds())
        self.feed(pose='scroll_down',n=12); self.assertIn('scroll',self.kinds())

    def test_jump_disarms(self):
        self.arm(); self.feed(x=.9); self.assertFalse(self.c.rearmed)

    def test_nonfinite_disarms(self):
        self.arm(); self.feed(x=float('nan')); self.assertFalse(self.c.rearmed)

    def test_stale_timestamp_ignored(self):
        self.arm(); self.c.feed(Observation(1,.8,.8,.1,60)); self.assertEqual(self.kinds(),[])

    def test_scroll_clutch_does_not_jump(self):
        self.c.set_mode('scroll'); self.arm(); self.feed(y=.55,n=2)
        self.feed(y=.6,pose='fist',n=4); self.c.drain(); self.feed(y=.62)
        self.assertNotIn('scroll',self.kinds())


class Learning(unittest.TestCase):
    def calibration(self,opened,closed):
        c=Calibration(0); c.done=True; c.phase_counts=[10]*7
        c.open=[opened]*50; c.closed=[closed]*50; c.hold=[(.5,.5)]*10
        return c

    def test_invalid_profile_rejected(self):
        d=dataclasses.asdict(Profile()); d['contact_on']=float('nan')
        self.assertEqual(Profile.from_dict(d),Profile())

    def test_overlapping_calibration_rejected(self):
        self.assertIsNone(self.calibration(.4,.35).finish(Profile()))

    def test_good_calibration_bounded(self):
        p=self.calibration(.8,.1).finish(Profile())
        self.assertTrue(p.calibrated); self.assertLess(.1,p.contact_on); self.assertLess(p.contact_off,.8)

    def test_missing_phase_rejected(self):
        c=self.calibration(.8,.1); c.phase_counts[3]=0
        self.assertIsNone(c.finish(Profile()))

    def test_invalid_sample_no_learning(self):
        c=Calibration(0); c.add(Observation(.1,.5,.5,.1,3)); self.assertEqual(c.elapsed,0)

    def test_filter_raw_derivative(self):
        f=OneEuro(); f(0,1); f(.1,1.03); before=f.derivative; f(.1,1.06)
        self.assertLess(f.derivative,before)

    def test_voice_exact_vocabulary(self):
        self.assertEqual(parse_command('Resize window!'),'resize')
        self.assertIsNone(parse_command('I might resize window later'))
        self.assertIsNone(parse_command('please click an advertisement'))


if __name__=='__main__': unittest.main()
