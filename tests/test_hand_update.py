from pathlib import Path
from dataclasses import replace
from tempfile import TemporaryDirectory
import sys,time,unittest,io,wave
from unittest.mock import Mock,patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from control_core import Observation,Profile,parse_command
from shortcuts import FingerShortcuts
from positions import RoomPositions,WaveRecall
from hand_geometry import map_hand,extension_scores,HandPoseFilter
from feedback_audio import tap_wav
import test_orientations as fixtures
import runtime,native


def obs(t,x=.5,y=.5,mask=15,size=.08,**kw):
    return Observation(t,x,y,.8,80,finger_mask=mask,palm_fraction=size,**kw)


class HandMapping(unittest.TestCase):
    def test_full_map_retains_thumb_and_all_21_joints(self):
        m=map_hand(fixtures.hand(),'world')
        self.assertEqual(len(m['joints']),21);self.assertEqual(len(m['curls']),5)
        self.assertAlmostEqual(np.linalg.norm(m['palm_normal']),1,places=3)

    def test_local_map_and_curls_survive_rotation(self):
        reference=map_hand(fixtures.hand(),'world')
        for rotation in fixtures.Orientations().rotations():
            m=map_hand(fixtures.hand()@rotation.T,'world')
            np.testing.assert_allclose(m['local_joints'],reference['local_joints'],atol=.001)
            np.testing.assert_allclose(m['curls'],reference['curls'],atol=.001)

    def test_shape_filter_bridges_single_marginal_estimate(self):
        f=HandPoseFilter()
        f.feed(obs(1,mask=3,extension_scores=(1,1,.1,.1)))
        out=f.feed(obs(1.033,mask=7,extension_scores=(1,1,.55,.1)))
        self.assertEqual(out.finger_mask,3)
        self.assertEqual(out.x,.5)

    def test_new_hand_does_not_inherit_filtered_fingers(self):
        f=HandPoseFilter();f.feed(obs(1,mask=3,extension_scores=(1,1,0,0)))
        out=f.feed(obs(1.033,mask=15,hand='Left',extension_scores=(1,1,1,1)))
        self.assertEqual(out.finger_mask,15)


class EasierShortcuts(unittest.TestCase):
    def test_finger_only_scroll_with_stationary_palm(self):
        s=FingerShortcuts();actions=[]
        for i in range(16):
            a=s.feed(obs(1+i/30,mask=3,gesture_x=.5,gesture_y=.4+i*.004,palm_height_fraction=.1))
            if a:actions.append(a)
        self.assertEqual(len(actions),1);self.assertLess(actions[0]['dy'],0)

    def test_single_ring_finger_misclassification_does_not_erase_scroll(self):
        s=FingerShortcuts();actions=[]
        for i in range(14):
            a=s.feed(obs(1+i/30,y=.5+i*.007,mask=7 if i==4 else 3))
            if a:actions.append(a)
        self.assertEqual(len(actions),1);self.assertEqual(actions[0]['kind'],'scroll')

    def test_diagonal_three_finger_swipe_is_allowed(self):
        s=FingerShortcuts();actions=[]
        for i in range(15):
            a=s.feed(obs(1+i/30,x=.5+i*.014,y=.5+i*.005,mask=7))
            if a:actions.append(a)
        self.assertEqual(actions,[dict(kind='desktop',direction='right')])

    def test_swipe_pose_to_no_fingers_does_not_crash(self):
        s=FingerShortcuts()
        for i,mask in enumerate([7]*4+[0]*8+[7]*4+[1]*8):
            self.assertIsNone(s.feed(obs(1+i/30,mask=mask)))

    def test_all_finger_mask_transitions_are_safe(self):
        for first in range(16):
            for second in range(16):
                s=FingerShortcuts()
                for i,mask in enumerate([first]*4+[second]*5):
                    s.feed(obs(1+i/30,mask=mask))

    def test_full_landmark_pipeline_scrolls_without_palm_travel(self):
        s=FingerShortcuts();f=HandPoseFilter();actions=[];palms=[]
        for i in range(16):
            points=fixtures.hand()
            for m in (13,17):
                points[m+1:m+4]=points[m]+np.array([[0,.02,.01],[0,.015,.03],[0,-.01,.025]])
            angle=i/15*np.pi/3
            rot=np.array([[1,0,0],[0,np.cos(angle),-np.sin(angle)],[0,np.sin(angle),np.cos(angle)]])
            for m in (5,9):points[m+1:m+4]=(points[m+1:m+4]-points[m])@rot.T+points[m]
            o=f.feed(runtime.extract(fixtures.result(points),(1080,1920,3),1+i/30,'pinch'))
            palms.append(o.y)
            a=s.feed(o)
            if a:actions.append(a)
        self.assertAlmostEqual(max(palms),min(palms))
        self.assertEqual(len(actions),1);self.assertEqual(actions[0]['kind'],'scroll')

    def test_resting_jitter_does_not_scroll(self):
        s=FingerShortcuts()
        for i in range(100):self.assertIsNone(s.feed(obs(1+i/30,y=.5+(i%3-1)*.003,mask=3)))

    def test_relax_rearms_second_flick(self):
        s=FingerShortcuts();actions=[]
        for i in range(90):
            mask=0 if 20<=i<45 else 3
            y=.5+min(i,15)*.007 if i<20 else (.5+(i-45)*.007 if i>=45 else .5)
            a=s.feed(obs(1+i/30,y=y,mask=mask))
            if a:actions.append(a)
        self.assertEqual([a['kind'] for a in actions],['scroll','scroll'])


class PositionMapping(unittest.TestCase):
    def test_one_swipe_is_not_a_wave(self):
        wave=WaveRecall()
        self.assertFalse(any(wave.feed(obs(1+i/30,x=.3+i*.01)) for i in range(25)))

    def test_back_and_forth_wave_recalls_once(self):
        wave=WaveRecall();events=[]
        xs=list(np.linspace(.45,.55,8))+list(np.linspace(.55,.45,8))+list(np.linspace(.45,.55,8))+list(np.linspace(.55,.45,8))
        for i,x in enumerate(xs):
            if wave.feed(obs(1+i/30,x=float(x))):events.append(i)
        self.assertEqual(len(events),1)

    def test_tracking_loss_breaks_wave(self):
        wave=WaveRecall()
        for i,x in enumerate(np.linspace(.4,.6,10)):wave.feed(obs(1+i/30,x=float(x)))
        wave.feed(None)
        self.assertFalse(any(wave.feed(obs(2+i/30,x=.6-i*.01)) for i in range(15)))

    def test_save_and_recall_relative_distance_profiles(self):
        with TemporaryDirectory() as d:
            room=RoomPositions(Path(d)/'positions.json')
            for start,size,sensitivity in ((1,.12,.8),(4,.035,1.5)):
                room.begin(start)
                for i in range(30):room.observe(obs(start+i/30,size=size),Profile(sensitivity=sensitivity))
            self.assertEqual(len(room.anchors),2)
            loaded=RoomPositions(room.path)
            a=loaded.recall(obs(10,size=.035))
            self.assertEqual(a['profile']['sensitivity'],1.5)
            self.assertIsNone(loaded.recall(obs(10,x=.01,size=.005)))

    def test_ambiguous_positions_do_not_guess(self):
        with TemporaryDirectory() as d:
            room=RoomPositions(Path(d)/'positions.json')
            room.anchors=[dict(x=.4,y=.5,size=.08,hand='Right'),dict(x=.6,y=.5,size=.08,hand='Right')]
            self.assertIsNone(room.recall(obs(1)))

    def test_moving_hand_is_not_saved(self):
        with TemporaryDirectory() as d:
            room=RoomPositions(Path(d)/'positions.json');room.begin(1)
            for i in range(30):room.observe(obs(1+i/30,x=.2+i*.02),Profile())
            self.assertEqual(room.anchors,[])

    def test_voice_position_commands_are_exact(self):
        self.assertEqual(parse_command('Calibrate here.'),'position_save')
        self.assertEqual(parse_command('Control'),'position_recall')
        self.assertIsNone(parse_command('Can you control the video'))


class Feedback(unittest.TestCase):
    def test_tap_is_short_valid_pcm(self):
        with wave.open(io.BytesIO(tap_wav()),'rb') as audio:
            self.assertEqual(audio.getnchannels(),1);self.assertEqual(audio.getsampwidth(),2)
            self.assertLess(audio.getnframes()/audio.getframerate(),.04)

    def test_sound_only_on_actual_mouse_down(self):
        out=native.Output((0,0,1920,1080));out.enabled=True;out.mouse=Mock();out.click_feedback=Mock()
        out.handle(dict(kind='click',x=1,y=1))
        out.click_feedback.assert_not_called()
        out.pump(10);out.pump(10.02);out.pump(10.1)
        out.click_feedback.assert_called_once()

    def test_cancelled_click_is_silent(self):
        out=native.Output((0,0,1920,1080));out.enabled=True;out.mouse=Mock();out.click_feedback=Mock()
        out.handle(dict(kind='click',x=1,y=1));out.release();out.pump(10)
        out.click_feedback.assert_not_called()

    def test_audio_failure_does_not_cancel_click(self):
        out=native.Output((0,0,1920,1080));out.enabled=True;out.mouse=Mock();out.click_feedback=Mock(side_effect=RuntimeError())
        out.handle(dict(kind='click',x=1,y=1));out.pump(10);out.pump(10.02);out.pump(10.1)
        self.assertEqual(out.click_stats['completed'],1)


class RuntimePositionGates(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.r=runtime.Runtime((0,0,1920,1080),True)
        self.r.room=RoomPositions(Path(self.tmp.name)/'positions.json')
        self.r.capture_stop.clear()
        self.r.handle_shortcut=Mock()

    def tearDown(self):self.r.close();self.tmp.cleanup()

    def test_saved_positions_reserve_four_finger_wave_from_desktops(self):
        self.r.room.anchors=[dict(name='Desk')];self.r.desktop_swipes=True
        for i in range(20):self.r.process_shortcuts(obs(1+i/30,x=.4+i*.02),1+i/30)
        self.r.handle_shortcut.assert_not_called()

    def test_three_finger_desktop_still_works_with_positions(self):
        self.r.room.anchors=[dict(name='Desk')];self.r.desktop_swipes=True
        for i in range(20):self.r.process_shortcuts(obs(1+i/30,x=.4+i*.02,mask=7),1+i/30)
        self.r.handle_shortcut.assert_called_once_with(dict(kind='desktop',direction='right'))

    def test_drag_cannot_be_stolen_by_wave_or_position_save(self):
        self.r.room.begin(1);self.r.core.finger_down=True;self.r.core.state='drag'
        self.assertFalse(self.r.process_position(obs(1),1))
        self.assertEqual(self.r.room.samples,[])

    def test_stale_hand_cannot_recall_profile(self):
        self.r.latest_obs=obs(time.monotonic()-1)
        self.r.core.profile.sensitivity=1.2
        self.r.recall_position()
        self.assertIn('Show your hand',self.r.message)
        self.assertEqual(self.r.core.profile.sensitivity,1.2)

if __name__=='__main__':unittest.main()
