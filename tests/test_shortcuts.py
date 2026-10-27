from pathlib import Path
import sys,unittest
from unittest.mock import Mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from control_core import Observation,Profile
from shortcuts import FingerShortcuts
import runtime

class FingerActions(unittest.TestCase):
    def setUp(self):self.s=FingerShortcuts();self.t=100
    def feed(self,mask=3,x=.5,y=.5,**kw):
        self.t+=1/30
        return self.s.feed(Observation(self.t,x,y,.8,60,finger_mask=mask),**kw)
    def arm(self,mask=3):
        for _ in range(10):self.feed(mask)
    def flick(self,mask=3,dx=0,dy=.012):
        actions=[]
        for i in range(14):
            a=self.feed(mask,x=.5+i*dx,y=.5+i*dy)
            if a:actions.append(a)
        return actions
    def test_two_finger_curl_and_release_double_clicks_once(self):
        self.arm()
        for _ in range(3):self.assertIsNone(self.feed(0))
        self.assertEqual(self.feed(),dict(kind='double_click'))
        self.assertFalse(any(self.feed() for _ in range(15)))
    def test_resting_two_fingers_does_not_click(self):
        self.arm();self.assertFalse(any(self.feed() for _ in range(40)))
    def test_long_curl_is_rest_not_tap(self):
        self.arm()
        for _ in range(20):self.feed(0)
        self.assertIsNone(self.feed())
    def test_tap_bounce_does_not_click(self):
        self.arm();self.feed(0)
        self.assertIsNone(self.feed())
    def test_two_finger_scroll_down_and_up(self):
        self.arm();a=self.flick();self.assertEqual(len(a),1);self.assertLess(a[0]['dy'],0)
        self.setUp();self.arm();a=self.flick(dy=-.012);self.assertEqual(len(a),1);self.assertGreater(a[0]['dy'],0)
    def test_two_finger_flick_can_start_without_stationary_hold(self):
        a=self.flick()
        self.assertEqual(len(a),1)
        self.assertEqual(a[0]['kind'],'scroll')
    def test_three_finger_swipe_can_start_without_stationary_hold(self):
        self.assertEqual(self.flick(7,dx=.02,dy=0),[dict(kind='desktop',direction='right')])
    def test_open_palm_is_reserved_for_pointing_and_tilt(self):
        self.assertEqual(self.flick(15,dx=.02,dy=0),[])
    def test_flick_return_does_not_reverse_scroll(self):
        self.arm();self.flick()
        self.assertFalse(any(self.feed(y=.656-i*.012) for i in range(14)))
    def test_three_finger_swipes(self):
        for mask in (7,11,13,14):
            self.setUp();self.arm(mask);a=self.flick(mask,dx=.02,dy=0)
            self.assertEqual(a,[dict(kind='desktop',direction='right')])
    def test_three_finger_swipe_left(self):
        self.arm(7);self.assertEqual(self.flick(7,dx=-.02,dy=0),[dict(kind='desktop',direction='left')])
    def test_three_finger_vertical_does_not_scroll(self):
        self.arm(7);self.assertEqual(self.flick(7),[])
    def test_two_finger_horizontal_does_not_change_desktop(self):
        self.arm();self.assertEqual(self.flick(dx=.02,dy=0),[])
    def test_one_finger_pointing_cannot_trigger_shortcuts(self):
        self.arm(1);self.assertEqual(self.flick(1,dx=.02),[])
    def test_disabled_desktops_leave_open_hand_for_pointer(self):
        for _ in range(20):self.assertIsNone(self.feed(15,allow_desktop=False))
        self.assertFalse(self.s.reserved)
    def test_no_action_across_tracking_loss(self):
        self.arm();self.feed(0);self.s.feed(None)
        self.assertIsNone(self.feed())
    def test_disabled_no_action(self):
        self.arm();self.assertIsNone(self.feed(y=.7,allowed=False))
        self.assertFalse(self.s.reserved)
    def test_hand_switch_does_not_complete_tap(self):
        self.arm();self.feed(0)
        self.t+=1/30
        self.assertIsNone(self.s.feed(Observation(self.t,.5,.5,.8,60,hand='Left',finger_mask=3)))

class RuntimeGestures(unittest.TestCase):
    def setUp(self):
        self.r=runtime.Runtime((0,0,1920,1080),True)
        self.r.handle_shortcut=Mock();self.t=100
    def tearDown(self):self.r.close()
    def sequence(self):
        for mask in [3]*10+[0]*3+[3]:
            self.t+=1/30
            self.r.process_shortcuts(Observation(self.t,.5,.5,.8,60,finger_mask=mask),self.t)
    def test_paused_does_not_recognize_actions(self):
        self.sequence();self.r.handle_shortcut.assert_not_called()
    def test_swipe_only_state_does_not_allow_double_click(self):
        self.r.desktop_swipes=True
        self.sequence();self.r.handle_shortcut.assert_not_called()
    def test_desktop_shortcut_works_with_pointer_paused(self):
        self.r.desktop_swipes=True
        for i in range(24):
            self.t+=1/30
            x=.5 if i<10 else .5+(i-10)*.02
            self.r.process_shortcuts(Observation(self.t,x,.5,.8,60,finger_mask=7),self.t)
        self.r.handle_shortcut.assert_called_once_with(dict(kind='desktop',direction='right'))
    def test_held_drag_is_never_stolen_by_shortcut(self):
        self.r.core.paused=False;self.r.core.finger_down=True;self.r.core.state='drag'
        self.sequence();self.r.handle_shortcut.assert_not_called()
        self.assertTrue(self.r.core.finger_down)
    def test_enabled_shortcut_recognizes_double_click(self):
        self.r.core.paused=False;self.sequence()
        self.r.handle_shortcut.assert_called_once_with(dict(kind='double_click'))
    def test_scroll_momentum_stops_when_paused(self):
        self.r.scroll_remaining=500;self.r.pump_scroll(self.r.scroll_time+.02)
        self.assertEqual(self.r.scroll_remaining,0)

    def test_fluid_chord_candidates_never_reserve_or_disarm_pointer(self):
        self.r.core.profile=Profile(motion_scheme='fluid',shortcuts=True)
        self.r.core.pause(False)
        for i in range(30):
            self.t+=1/30
            o=Observation(self.t,.5+i*.0005,.5,.8,60,finger_mask=3)
            self.assertFalse(self.r.process_shortcuts(o,self.t))
            self.r.core.feed(o)
        self.assertTrue(self.r.core.rearmed)
        self.assertGreater(self.r.core.x,960)
        self.assertFalse(self.r.shortcut_reserved)

    def test_fluid_scroll_and_desktop_still_reach_runtime(self):
        self.r.core.profile=Profile(motion_scheme='fluid',shortcuts=True)
        self.r.core.paused=False;self.r.desktop_swipes=True
        for mask,axis,kind in ((3,'y','scroll'),(7,'x','desktop')):
            self.r.shortcuts.clear();self.r.handle_shortcut.reset_mock();self.t+=1
            for i in range(20):
                self.t+=1/30
                xy=dict(x=.5,y=.5);xy[axis]+=.01*i
                self.r.process_shortcuts(Observation(self.t,contact=.8,palm_px=60,finger_mask=mask,**xy),self.t)
            self.assertEqual(self.r.handle_shortcut.call_count,1)
            self.assertEqual(self.r.handle_shortcut.call_args.args[0]['kind'],kind)

    def test_fluid_two_finger_curl_does_not_double_click(self):
        self.r.core.profile=Profile(motion_scheme='fluid',shortcuts=True)
        self.r.core.paused=False;self.sequence()
        self.r.handle_shortcut.assert_not_called()

    def test_partial_unused_pinky_does_not_block_three_finger_desktop(self):
        s=FingerShortcuts();actions=[]
        for i in range(20):
            a=s.feed(Observation(100+i/30,.5+i*.01,.5,.8,60,finger_mask=7,
                                 in_frame=False,palm_in_frame=True,visible_fingers=7))
            if a:actions.append(a)
        self.assertEqual(actions,[dict(kind='desktop',direction='right')])

    def test_hidden_active_finger_cannot_switch_desktop(self):
        s=FingerShortcuts();actions=[]
        for i in range(20):
            a=s.feed(Observation(100+i/30,.5+i*.01,.5,.8,60,finger_mask=7,
                                 in_frame=False,palm_in_frame=True,visible_fingers=3))
            if a:actions.append(a)
        self.assertEqual(actions,[])

if __name__=='__main__':unittest.main()
