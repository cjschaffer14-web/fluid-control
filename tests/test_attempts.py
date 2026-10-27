from pathlib import Path
import json
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from attempts import Attempt
from control_core import Profile


class LiveTrials(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.a=Attempt('move',Profile(),self.temp.name)

    def tearDown(self):
        self.temp.cleanup()

    def test_motion_without_release_does_not_pass(self):
        self.a.frame([100,100,600,500],150)
        self.a.finish()
        self.assertFalse(self.a.success)

    def test_real_release_after_target_passes(self):
        self.a.event({'kind':'down','x':0,'y':0})
        self.a.event({'kind':'up','x':150,'y':0,'cancelled':False})
        self.a.frame([250,100,600,500],150,True)
        self.a.finish()
        self.assertTrue(self.a.success)

    def test_stopping_is_not_success(self):
        self.a.event({'kind':'up'})
        self.a.frame([250,100,600,500],150,True)
        self.a.finish('stopped')
        self.assertFalse(self.a.success)

    def test_five_answers_recorded_and_grab_adapts(self):
        answers=dict(intent='Move window',response='No',gesture='Whole-hand grab',feel='Too slow',comfort='3')
        p,note=self.a.feedback(answers,Profile())
        self.assertEqual(p.gesture,'grab')
        self.assertAlmostEqual(p.sensitivity,1.15)
        records=[json.loads(s) for s in self.a.path.read_text().splitlines()]
        self.assertEqual(records[-1]['answers'],answers)
        self.assertFalse(records[0]['raw_video'])

    def test_unresolved_contact_preserves_thresholds(self):
        self.a.samples=[dict(phase=phase,pinch=.4,side=.4) for phase in ['rest']*20+['action']*20]
        answers=dict(intent='Move window',response='No',gesture='Thumb side tap',feel='Gesture was missed',comfort='4')
        p,note=self.a.feedback(answers,Profile())
        self.assertEqual(p.gesture,'pinch')
        self.assertEqual(p.contact_on,Profile().contact_on)

    def test_button_round_needs_five_hits(self):
        self.a.task='pointer'
        for _ in range(4): self.a.target(True,'open_hand')
        self.a.target(False,'open_hand')
        self.a.finish()
        self.assertFalse(self.a.success)
        self.assertEqual((self.a.hits,self.a.misses),(4,1))

    def test_five_button_hits_complete_round(self):
        self.a.task='pointer'
        for _ in range(5): self.a.target(True,'one_finger')
        self.a.finish()
        self.assertTrue(self.a.success)

    def test_palm_feedback_keeps_finger_and_global_speed(self):
        self.a.task='pointer'
        old=Profile(sensitivity=1.3)
        answers=dict(intent='Aim at buttons',response='Partly',gesture='Open hand',feel='Too fast',comfort='6')
        p,_=self.a.feedback(answers,old)
        self.assertLess(p.palm_speed,old.palm_speed)
        self.assertEqual(p.finger_speed,old.finger_speed)
        self.assertEqual(p.sensitivity,old.sensitivity)

    def test_fluid_feedback_tunes_fluid_sensitivity(self):
        self.a.task='pointer'
        old=Profile(motion_scheme='fluid')
        answers=dict(intent='Sideways tilt',response='Partly',gesture='Open hand',feel='Too fast',comfort='6')
        p,_=self.a.feedback(answers,old)
        self.assertLess(p.sensitivity,old.sensitivity)
        self.assertEqual(p.finger_speed,old.finger_speed)
        self.assertEqual(p.palm_speed,old.palm_speed)


if __name__=='__main__': unittest.main()
