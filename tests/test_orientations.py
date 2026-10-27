from pathlib import Path
from types import SimpleNamespace as N
from dataclasses import asdict
import math,sys,unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from hand_geometry import hand_points,extensions
from runtime import extract
from control_core import Controller,Observation,Profile
from tracking import restore


def hand(closed=False):
    p=np.zeros((21,3))
    p[1:5]=[[-.025,.015,0],[-.04,.03,0],[-.055,.045,0],[-.075,.055,0]]
    for start,x,y in ((5,-.025,.05),(9,0,.055),(13,.025,.05),(17,.045,.04)):
        p[start:start+4]=[[x,y,0],[x,y+.03,0],[x,y+.05,0],[x,y+.07,0]]
    if closed:p[4]=p[8]
    return p


def result(points,world=True):
    lm=[N(x=.5+p[0],y=.7-p[1]*1920/1080,z=p[2]) for p in points]
    return N(hand_landmarks=[lm],hand_world_landmarks=[[N(x=p[0],y=p[1],z=p[2]) for p in points]] if world else [],handedness=[[N(category_name='Right')]])


class Orientations(unittest.TestCase):
    def rotations(self):
        for pitch in (-80,-40,0,40,80,140,180):
            for roll in (0,45,90,180,270):
                a,b=math.radians(pitch),math.radians(roll)
                rx=np.array([[1,0,0],[0,math.cos(a),-math.sin(a)],[0,math.sin(a),math.cos(a)]])
                rz=np.array([[math.cos(b),-math.sin(b),0],[math.sin(b),math.cos(b),0],[0,0,1]])
                yield rz@rx

    def test_open_hand_shape_survives_35_rotations(self):
        for r in self.rotations():
            p=hand()@r.T
            o=extract(result(p),(1080,1920,3),100,'pinch')
            self.assertEqual(o.figure,'open_hand')
            self.assertTrue(o.open_palm)
            self.assertGreater(o.contact,.46)

    def test_contact_survives_35_rotations(self):
        for r in self.rotations():
            o=extract(result(hand(True)@r.T),(1080,1920,3),100,'pinch')
            self.assertLess(o.contact,.28)

    def test_depth_fallback_keeps_rotated_finger_shape(self):
        for r in self.rotations():
            p,_=hand_points(result(hand()@r.T,False),1920,1080)
            self.assertEqual(extensions(p),[True]*4)

    def test_crop_does_not_discard_world_geometry(self):
        original=result(hand())
        cropped=restore(original,(100,200,400,400),(1080,1920,3))
        self.assertIs(cropped.hand_world_landmarks,original.hand_world_landmarks)


class FluidPointer(unittest.TestCase):
    def test_partial_pinky_does_not_block_visible_palm_or_pinch(self):
        r=result(hand());r.hand_landmarks[0][20].x=1.01
        o=extract(r,(1080,1920,3),100,'pinch')
        self.assertFalse(o.in_frame)
        self.assertTrue(o.pointer_usable())
        self.assertTrue(o.pinch_visible)
        self.assertEqual(o.visible_fingers,7)

    def test_hidden_thumb_disables_contact_but_not_palm_tracking(self):
        r=result(hand());r.hand_landmarks[0][4].x=1.01
        o=extract(r,(1080,1920,3),100,'pinch')
        self.assertTrue(o.pointer_usable())
        self.assertFalse(o.pinch_visible)

    def test_visible_palm_moves_immediately_before_click_rearm(self):
        c=Controller(profile=Profile(motion_scheme='fluid'));c.pause(False)
        for i in range(6):c.feed(Observation(100+i/30,.5+i*.005,.5,.1,60))
        self.assertGreater(c.x,960)
        self.assertFalse(c.rearmed)
        self.assertTrue(all(e['kind']=='move' for e in c.drain()))

    def test_fist_classification_does_not_clutch_fluid_motion(self):
        c=Controller(profile=Profile(motion_scheme='fluid'));c.pause(False)
        for i in range(15):c.feed(Observation(100+i/30,.5,.5,.8,60))
        before=c.x
        for i in range(10):c.feed(Observation(100.5+i/30,.5+i*.005,.5,.8,60,posture='fist'))
        self.assertGreater(c.x,before)

    def test_hidden_pinch_releases_drag_and_keeps_moving_without_click(self):
        c=Controller(profile=Profile(motion_scheme='fluid'));c.pause(False)
        for i in range(15):c.feed(Observation(100+i/30,.5,.5,.8,60))
        c.finger_down=True;c.state='drag';c.drain()
        before=c.x
        for i in range(10):
            c.feed(Observation(100.5+i/30,.5+i*.005,.5,.1,60,in_frame=False,palm_in_frame=True,pinch_visible=False))
        events=c.drain()
        self.assertEqual(sum(e['kind']=='up' for e in events),1)
        self.assertFalse(any(e['kind'] in ('click','down') for e in events))
        self.assertGreater(c.x,before)

    def test_palm_loss_still_releases_and_blocks_output(self):
        c=Controller(profile=Profile(motion_scheme='fluid'));c.pause(False)
        c.finger_down=True;c.state='drag'
        c.feed(Observation(100,.6,.5,.8,60,in_frame=False,palm_in_frame=False))
        self.assertEqual([e['kind'] for e in c.drain()],['up'])

    def test_fluid_scheme_survives_save(self):
        self.assertEqual(Profile.from_dict(asdict(Profile(motion_scheme='fluid'))).motion_scheme,'fluid')

    def test_thumb_shape_does_not_stop_fluid_pointing(self):
        c=Controller(profile=Profile(motion_scheme='fluid'));c.pause(False)
        t=100
        for i in range(15):
            t+=1/30;c.feed(Observation(t,.5,.5,.8,60))
        c.drain()
        for i in range(20):
            t+=1/30;c.feed(Observation(t,.6,.5,.8,60,posture='scroll_up'))
        events=c.drain()
        self.assertFalse(any(e['kind']=='scroll' for e in events))
        self.assertTrue(any(e['kind']=='move' for e in events))
        self.assertGreater(c.x,960)

if __name__=='__main__':unittest.main()
