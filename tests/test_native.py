from pathlib import Path
import sys
import unittest
from unittest.mock import patch, Mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import native


class NativeOutput(unittest.TestCase):
    def setUp(self):
        self.out=native.Output((0,0,1920,1080))
        self.out.enabled=True
        self.out.mouse=Mock()

    @patch.object(native.Q,'CGEventPost')
    def test_tag_identifies_own_event_even_when_source_pid_is_zero(self,post):
        e=native.Q.CGEventCreate(None)
        self.out.post(e)
        native.Q.CGEventSetIntegerValueField(e,native.Q.kCGEventSourceUnixProcessID,0)
        self.assertTrue(native.is_own_event(e))
        post.assert_called_once()

    def test_untagged_pid_zero_event_still_yields_to_physical_input(self):
        e=native.Q.CGEventCreate(None)
        native.Q.CGEventSetIntegerValueField(e,native.Q.kCGEventSourceUnixProcessID,0)
        native.Q.CGEventSetIntegerValueField(e,native.Q.kCGEventSourceUserData,0)
        self.assertFalse(native.is_own_event(e))
        self.assertFalse(native.is_own_event(None))

    @patch.object(native.time,'sleep')
    def test_desktop_arrow_has_mac_navigation_flags(self,sleep):
        events=[]
        self.out.post=events.append
        self.out.switch_desktop('left')
        arrow=events[1]
        flags=native.Q.CGEventGetFlags(arrow)
        self.assertEqual(native.Q.CGEventGetIntegerValueField(arrow,native.Q.kCGKeyboardEventKeycode),123)
        required=native.Q.kCGEventFlagMaskControl | native.Q.kCGEventFlagMaskSecondaryFn | native.Q.kCGEventFlagMaskNumericPad | 1
        self.assertEqual(flags & required,required)
        self.assertEqual(native.Q.CGEventGetFlags(events[-1]),0)

    @patch.object(native.time,'sleep')
    def test_desktop_failure_releases_control_key(self,sleep):
        self.out.post=Mock(side_effect=[None,RuntimeError('post failed'),None])
        with self.assertRaises(RuntimeError):
            self.out.switch_desktop('right')
        last=self.out.post.call_args.args[0]
        self.assertEqual(native.Q.CGEventGetIntegerValueField(last,native.Q.kCGKeyboardEventKeycode),59)
        self.assertEqual(native.Q.CGEventGetFlags(last),0)

    def test_double_click_emits_four_events(self):
        for count in (1,2):
            self.out.handle(dict(kind='click',x=100,y=100,count=count))
        for i in range(50): self.out.pump(100+i*.01)
        pairs=[c for c in self.out.mouse.call_args_list if c.args[0] in (native.Q.kCGEventLeftMouseDown,native.Q.kCGEventLeftMouseUp)]
        self.assertEqual(len(pairs),4)
        self.assertEqual([c.args[3] for c in pairs],[1,1,2,2])

    def test_disabled_no_events(self):
        self.out.enabled=False
        self.out.handle(dict(kind='click',x=100,y=100))
        self.out.mouse.assert_not_called()

    def test_release_is_idempotent(self):
        self.out.handle(dict(kind='down',x=100,y=100,mode='pointer'))
        self.out.release(); self.out.release()
        self.assertEqual(self.out.mouse.call_count,2)

    def test_stale_target_no_motion(self):
        self.out.handle(dict(kind='move',x=100,y=100,dt=.03))
        self.out.pump(self.out.observed+.2)
        self.out.mouse.assert_not_called()

    def test_window_grab_does_not_send_mouse_down(self):
        self.out.window.begin=Mock()
        self.out.handle(dict(kind='down',x=100,y=100,mode='move'))
        self.out.window.begin.assert_called_once_with(100,100,'move')
        self.out.mouse.assert_not_called()

    def test_click_press_is_visible_to_frame_polling(self):
        self.out.handle(dict(kind='click',x=100,y=100))
        self.out.pump(100);self.out.pump(100.02)
        self.assertTrue(self.out.down)
        self.out.pump(100.06)
        self.assertTrue(self.out.down)
        self.out.pump(100.09)
        self.assertFalse(self.out.down)
        self.assertEqual(self.out.click_stats['completed'],1)

    def test_pause_cancels_click_waiting_for_down(self):
        self.out.handle(dict(kind='click',x=100,y=100))
        self.out.pump(100);self.out.release();self.out.pump(100.1)
        kinds=[c.args[0] for c in self.out.mouse.call_args_list]
        self.assertNotIn(native.Q.kCGEventLeftMouseDown,kinds)

    def test_click_stays_at_anchor_during_press(self):
        self.out.handle(dict(kind='click',x=100,y=100))
        self.out.pump(100);self.out.pump(100.02)
        self.out.handle(dict(kind='move',x=500,y=500))
        self.out.pump(100.09)
        last=self.out.mouse.call_args.args
        self.assertEqual(last[:3],(native.Q.kCGEventLeftMouseUp,100,100))

    def test_right_click_release_on_error(self):
        self.out.mouse.side_effect=[None,None,RuntimeError('failed up'),None]
        self.out.handle(dict(kind='click',x=100,y=100,right=True))
        self.out.pump(100);self.out.pump(100.02)
        with self.assertRaises(RuntimeError): self.out.pump(100.09)
        self.assertTrue(self.out.down)
        self.out.release()
        self.assertFalse(self.out.down)
        self.assertEqual(self.out.mouse.call_args.args[0],native.Q.kCGEventRightMouseUp)


class WindowFrames(unittest.TestCase):
    def setUp(self):
        self.win=native.WindowGrab()
        self.win.element=123
        self.win.start=(100,100,200,200,800,500)

    @patch.object(native,'set_value')
    def test_move_keeps_original_size(self,write):
        self.win.mode='move'; self.win.update(150,180,(0,0,1920,1080),True)
        _,key,kind,p=write.call_args.args
        self.assertEqual((key,kind,p.x,p.y),('AXPosition',1,250,280))

    @patch.object(native,'set_value')
    def test_resize_keeps_origin(self,write):
        self.win.mode='resize'; self.win.update(250,200,(0,0,1920,1080),True)
        _,key,kind,s=write.call_args.args
        self.assertEqual((key,kind,s.width,s.height),('AXSize',2,950,600))

    @patch.object(native,'set_value')
    def test_resize_minimum(self,write):
        self.win.mode='resize'; self.win.update(-2000,-2000,(0,0,1920,1080),True)
        size=write.call_args.args[3]
        self.assertEqual((size.width,size.height),(240,160))

    @patch.object(native,'set_value')
    def test_window_move_remains_reachable(self,write):
        self.win.mode='move'; self.win.update(5000,5000,(0,0,1920,1080),True)
        p=write.call_args.args[3]
        self.assertLessEqual(p.x,1820); self.assertLessEqual(p.y,1020)


if __name__=='__main__': unittest.main()
