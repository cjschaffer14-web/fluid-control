from pathlib import Path
from dataclasses import asdict,replace
import math,sys,unittest
from types import SimpleNamespace as N
from tempfile import TemporaryDirectory
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from precision import TiltPrecision
from awareness import tracking_state
from control_core import Observation,Controller,Profile
from tracking import hand_region,search_region
from shortcuts import FingerShortcuts
from attempts import Attempt


def basis(yaw=0,pitch=0):
    a,b=math.radians(yaw),math.radians(pitch)
    return (math.cos(a),math.sin(a)*math.sin(b),math.sin(a)*math.cos(b),
            0,math.cos(b),-math.sin(b),-math.sin(a),math.cos(a)*math.sin(b),math.cos(a)*math.cos(b))


def observation(t,yaw=0,pitch=0,x=.5,y=.5,palm=26):
    return Observation(t,x,y,.8,palm,geometry='world',palm_fraction=palm/1920,palm_basis=basis(yaw,pitch))


class WristPrecision(unittest.TestCase):
    def controller(self,palm=26):
        c=Controller(profile=Profile(motion_scheme='fluid',tilt_precision=True));c.pause(False)
        for i in range(30):c.feed(observation(1+i/30,palm=palm))
        self.assertTrue(c.tilt.active)
        c.drain();return c

    def test_tilt_moves_pointer_without_palm_translation(self):
        c=self.controller();before=c.x
        for i in range(1,16):c.feed(observation(2+i/30,yaw=i*.25))
        self.assertGreater(abs(c.x-before),20)
        self.assertLess(abs(c.x-before),100)

    def test_tilt_gain_is_independent_of_apparent_distance(self):
        amounts=[]
        for palm in (22,40,80):
            c=self.controller(palm);before=c.x
            for i in range(1,16):c.feed(observation(2+i/30,yaw=i*.25,palm=palm))
            amounts.append(c.x-before)
        self.assertAlmostEqual(amounts[0],amounts[1]);self.assertAlmostEqual(amounts[1],amounts[2])

    def test_steady_hand_does_not_drift(self):
        c=self.controller()
        for i in range(1,60):c.feed(observation(2+i/30,yaw=4))
        x=c.x
        for i in range(60,100):c.feed(observation(2+i/30,yaw=4))
        self.assertLess(abs(c.x-x),.01)

    def test_small_position_jitter_is_ignored_during_tilt(self):
        c=self.controller();before=c.x
        for i in range(1,50):c.feed(observation(2+i/30,x=.5+(.002 if i%2 else -.002)))
        self.assertAlmostEqual(c.x,before)

    def test_near_hand_can_settle_despite_small_palm_anchor_shift(self):
        p=TiltPrecision()
        for i in range(18):p.feed(observation(1+i/30,x=.5+i*.001,palm=260))
        self.assertTrue(p.active)

    def test_arm_movement_returns_to_travel(self):
        c=self.controller();before=c.x
        c.feed(observation(2.033,x=.54))
        self.assertFalse(c.tilt.active);self.assertNotEqual(c.x,before)

    def test_loss_resets_orientation_baseline(self):
        c=self.controller();c.tick(3)
        self.assertFalse(c.tilt.active)
        c.feed(observation(3.033,yaw=30))
        self.assertFalse(c.tilt.active)

    def test_bad_basis_cannot_move_pointer(self):
        precision=TiltPrecision()
        for i in range(15):self.assertIsNone(precision.feed(replace(observation(1+i/30),palm_basis=(float('nan'),)*9)))
        self.assertFalse(precision.active)

    def test_explicit_tilt_survives_but_legacy_profile_does_not_enable_it(self):
        p=Profile(tilt_gain=.7,tilt_precision=True)
        self.assertEqual(Profile.from_dict(asdict(p)),p)
        d=asdict(p);d.pop('tilt_gain');d.pop('tilt_precision')
        self.assertFalse(Profile.from_dict(d).tilt_precision)

    def test_default_pointer_keeps_translation_after_settling(self):
        c=Controller(profile=Profile(motion_scheme='fluid'));c.pause(False)
        for i in range(30):c.feed(observation(1+i/30,palm=260))
        self.assertFalse(c.tilt.active)
        before=c.x
        for i in range(1,8):c.feed(observation(2+i/30,x=.5+i*.001,palm=260))
        self.assertGreater(c.x-before,5)

    def test_translation_gain_does_not_change_with_apparent_palm_size(self):
        amounts=[]
        for palm in (22,40,260):
            c=Controller(profile=Profile(motion_scheme='fluid'));c.pause(False)
            for i in range(30):c.feed(observation(1+i/30,palm=palm))
            before=c.x
            for i in range(1,12):c.feed(observation(2+i/30,x=.5+i*.002,palm=palm))
            amounts.append(c.x-before)
        self.assertGreater(amounts[0],5)
        self.assertAlmostEqual(amounts[0],amounts[1]);self.assertAlmostEqual(amounts[1],amounts[2])


class DistanceDetection(unittest.TestCase):
    def test_far_hand_gets_tighter_native_pixel_crop(self):
        lm=[N(x=.49+(i%3)*.005,y=.48+(i%7)*.006) for i in range(21)]
        x,y,w,h=hand_region(N(hand_landmarks=[lm]),(1080,1920,3))
        self.assertEqual(w,160);self.assertEqual(h,160)
        self.assertTrue(all(x<=p.x*1920<=x+w and y<=p.y*1080<=y+h for p in lm))

    def test_search_includes_low_resting_hand(self):
        boxes=[search_region((1080,1920,3),i) for i in range(7)]
        self.assertTrue(any(y+h>1000 for x,y,w,h in boxes))
        self.assertTrue(any(y<100 for x,y,w,h in boxes))

    def test_far_short_scroll_and_swipe_need_less_arm_travel(self):
        for mask,axis,kind in ((3,'y','scroll'),(7,'x','desktop')):
            s=FingerShortcuts();actions=[]
            for i in range(20):
                o=replace(observation(1+i/30),finger_mask=mask,palm_height_fraction=26/1080)
                o=replace(o,**{axis:.5+i*.002})
                action=s.feed(o)
                if action:actions.append(action)
            self.assertEqual(len(actions),1);self.assertEqual(actions[0]['kind'],kind)


class HaloStates(unittest.TestCase):
    def metrics(self,**kw):return dict(tracked=True,palm_px=30,observed_at=10,age_ms=25,in_frame=True,**kw)
    def test_detected_and_paused_is_white(self):
        self.assertEqual(tracking_state(self.metrics(),10,paused=True)['color'],'white')
    def test_ready_and_precision_is_green(self):
        s=tracking_state(self.metrics(),10,ready=True,precision=True)
        self.assertEqual(s['color'],'green');self.assertIn('Tilt',s['label'])
    def test_lost_is_red(self):
        m=self.metrics();m['tracked']=False
        self.assertEqual(tracking_state(m,10)['color'],'red')
    def test_stale_last_observation_cannot_stay_green(self):
        self.assertEqual(tracking_state(self.metrics(),11,ready=True)['color'],'red')
    def test_partial_or_tiny_hand_is_amber(self):
        for change in ({'in_frame':False},{'palm_px':18},{'age_ms':170}):
            m=self.metrics();m.update(change)
            self.assertEqual(tracking_state(m,10,ready=True)['color'],'amber')
    def test_camera_off_is_distinct(self):
        self.assertEqual(tracking_state(self.metrics(),10,camera_on=False)['color'],'gray')

    def test_plain_pointer_label_does_not_instruct_tilt(self):
        self.assertNotIn('tilt',tracking_state(self.metrics(),10,ready=True)['label'])
        self.assertIn('tilt',tracking_state(self.metrics(),10,ready=True,tilt_enabled=True)['label'])


class RangeTrial(unittest.TestCase):
    def test_lost_frames_are_recorded_with_successful_frames(self):
        with TemporaryDirectory() as d:
            a=Attempt('pointer',Profile(),d)
            a.tracking(None,10,dict(age_ms=20,palm_px=0),False)
            a.tracking(observation(10.3),10.3,dict(age_ms=20,palm_px=26),True)
            self.assertEqual((a.tracking_frames,a.usable_frames),(2,1))
            self.assertIn('"detected": false',a.path.read_text())

    def test_distance_feedback_tunes_tilt_without_changing_travel(self):
        with TemporaryDirectory() as d:
            a=Attempt('pointer',Profile(),d);a.distance_trial=True
            p,_=a.feedback(dict(intent='10 feet',response='Partly',gesture='Fine adjustment worked',feel='Too slow',comfort='5'),Profile())
            self.assertEqual(p.sensitivity,1);self.assertGreater(p.tilt_gain,1)

if __name__=='__main__':unittest.main()
