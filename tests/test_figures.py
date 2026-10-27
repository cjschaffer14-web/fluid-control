from pathlib import Path
import sys,unittest
from dataclasses import asdict
from types import SimpleNamespace as N
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from control_core import Controller,Observation,Profile
from tracking import restore,hand_region,search_region

class HandFigures(unittest.TestCase):
    def travel(self,figure,scheme='figures'):
        c=Controller(profile=Profile(motion_scheme=scheme));c.pause(False)
        t=100
        for i in range(25):
            t+=1/30;c.feed(Observation(t,.5,.5,.8,50,figure=figure))
        for i in range(12):
            t+=1/30;c.feed(Observation(t,.5+(i+1)*.003,.5,.8,50,figure=figure))
        return c.x-960,c

    def test_one_finger_faster_than_palm(self):
        finger,c=self.travel('one_finger');palm,_=self.travel('open_hand')
        self.assertGreater(finger,palm*1.8)
        self.assertEqual(c.figure,'one_finger')

    def test_classic_ignores_figure(self):
        a,_=self.travel('one_finger','classic');b,_=self.travel('open_hand','classic')
        self.assertAlmostEqual(a,b)

    def test_shape_changes_without_motion_cannot_jump(self):
        _,c=self.travel('one_finger')
        t=c.last_t
        for i in range(60):
            t+=1/30;c.feed(Observation(t,.536,.5,.8,50,figure='one_finger'))
        before=c.x
        for i in range(20):
            t+=1/30;c.feed(Observation(t,.536,.5,.8,50,figure='open_hand'))
        # Only the existing smoothing tail can settle; switching gains cannot warp the cursor.
        self.assertLess(abs(c.x-before),.1)
        self.assertEqual(c.figure,'open_hand')

    def test_profile_keeps_independent_speeds(self):
        p=Profile(finger_speed=1.6,palm_speed=.45)
        self.assertEqual(Profile.from_dict(asdict(p)),p)

class DistanceCrops(unittest.TestCase):
    def test_crop_restores_full_frame_position_and_scale(self):
        result=N(hand_landmarks=[[N(x=.5,y=.25,z=.1)]],handedness=[])
        p=restore(result,(800,200,400,400),(1080,1920,3)).hand_landmarks[0][0]
        self.assertAlmostEqual(p.x,1000/1920);self.assertAlmostEqual(p.y,300/1080)
        self.assertAlmostEqual(p.z,40/1920)

    def test_search_covers_left_center_right_and_stays_in_frame(self):
        boxes=[search_region((1080,1920,3),i) for i in range(3)]
        self.assertLess(boxes[0][0],boxes[1][0]);self.assertLess(boxes[1][0],boxes[2][0])
        for x,y,w,h in boxes:
            self.assertGreaterEqual(x,0);self.assertGreaterEqual(y,0)
            self.assertLessEqual(x+w,1920);self.assertLessEqual(y+h,1080)

    def test_missing_hand_has_no_stale_crop(self):
        self.assertIsNone(hand_region(N(hand_landmarks=[]),(1080,1920,3)))

if __name__=='__main__':unittest.main()
