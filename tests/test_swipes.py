from pathlib import Path
import sys
import unittest
from dataclasses import replace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from control_core import Observation
from swipes import DesktopSwipes


class Swipes(unittest.TestCase):
    def setUp(self):
        self.s=DesktopSwipes(); self.t=100

    def feed(self,x=.5,y=.5,open=True,allowed=True,hand='Right'):
        self.t+=1/30
        return self.s.feed(Observation(self.t,x,y,.8,70,hand=hand,open_palm=open),allowed)

    def arm(self):
        for _ in range(12): self.feed()

    def sweep(self,direction=1,open=True,y=.5):
        results=[]
        for i in range(13):
            r=self.feed(.5+direction*.02*i,y,open)
            if r: results.append(r)
        return results

    def test_left_and_right(self):
        self.arm(); self.assertEqual(self.sweep(-1),['left'])
        self.setUp(); self.arm(); self.assertEqual(self.sweep(1),['right'])

    def test_pointing_is_not_swipe(self):
        self.arm(); self.assertEqual(self.sweep(open=False),[])

    def test_no_hold_no_switch(self):
        self.assertEqual(self.sweep(),[])

    def test_disabled_no_switch(self):
        self.arm()
        self.assertIsNone(self.feed(.8,allowed=False))

    def test_vertical_motion_no_switch(self):
        self.arm()
        results=[self.feed(.5+i*.015,.5+i*.025) for i in range(13)]
        self.assertFalse(any(results))

    def test_return_motion_does_not_switch_back(self):
        self.arm(); self.sweep()
        self.assertFalse(any(self.feed(.74-i*.02) for i in range(13)))

    def test_lost_hand_clears_motion(self):
        self.arm(); self.s.feed(None)
        self.assertEqual(self.sweep(),[])

    def test_hand_switch_requires_rearm(self):
        self.arm()
        self.assertIsNone(self.feed(.8,hand='Left'))

    def test_cooldown_and_release(self):
        self.arm(); self.sweep()
        for _ in range(45): self.feed(open=False)
        self.arm(); self.assertEqual(self.sweep(-1),['left'])


if __name__=='__main__': unittest.main()
