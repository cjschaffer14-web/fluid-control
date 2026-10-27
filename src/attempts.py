"""Short, explicit user trials. Records derived signals and outcomes, never raw media."""
from dataclasses import asdict, replace
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import math
import time
import uuid

ROOT = Path(__file__).resolve().parent
ROOT = ROOT.parents[2] if ROOT.name=='Resources' else ROOT.parent


def attempt_directory():
    if (ROOT/'src/app.py').exists():
        return ROOT/'attempts'
    return Path.home()/'Library/Application Support/Control/attempts'


class Attempt:
    def __init__(self, task, profile, directory=None):
        self.task, self.profile = task, replace(profile)
        self.started = time.monotonic()
        self.last_sample = -1
        self.last_tracking=-1
        self.tracking_frames=0;self.usable_frames=0
        self.distance_trial=False
        self.samples = []
        self.finished = False
        self.grabs = self.releases = 0
        self.best_delta = 0.0
        self.hits = self.misses = 0
        self.released_delta = None
        folder = Path(directory) if directory else attempt_directory()
        folder.mkdir(parents=True,exist_ok=True)
        self.id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:6]
        self.path = folder/(self.id+'.jsonl')
        fingerprint = hashlib.sha256()
        for source in sorted(Path(__file__).parent.glob('*.py')):
            fingerprint.update(source.name.encode())
            fingerprint.update(source.read_bytes())
        self.write('start', task=task, profile=asdict(profile), design=fingerprint.hexdigest()[:12],
                   raw_video=False, raw_audio=False)

    def write(self, kind, **values):
        data = dict(kind=kind, elapsed_s=round(time.monotonic()-self.started,3), **values)
        with self.path.open('a') as f:
            f.write(json.dumps(data,allow_nan=False)+'\n')

    def sample(self, obs, state):
        age = time.monotonic()-self.started
        if self.finished or age-self.last_sample < .1:
            return
        self.last_sample = age
        row = dict(phase='rest' if age<3 else 'action', contact=obs.contact,
                   pinch=obs.pinch, side=obs.side, curled=obs.curled,
                   palm_px=obs.palm_px, state=state, x=obs.x,y=obs.y,figure=obs.figure,geometry=obs.geometry,
                   finger_mask=obs.finger_mask,extension_scores=list(obs.extension_scores),
                   curls=obs.hand_map.get('curls') if obs.hand_map else None,
                   gesture_x=obs.gesture_x,gesture_y=obs.gesture_y)
        if not all(math.isfinite(v) for v in (obs.contact,obs.palm_px)):
            return
        self.samples.append(row)
        self.write('sample',**row)

    def tracking(self,obs,now,metrics,precision):
        if self.finished:return
        self.tracking_frames+=1
        usable=bool(obs and obs.usable() and metrics.get('age_ms',1000)<=150)
        self.usable_frames+=usable
        if now-self.last_tracking<.2:return
        self.last_tracking=now
        self.write('tracking',detected=obs is not None,usable=usable,palm_px=metrics.get('palm_px',0),
                   age_ms=metrics.get('age_ms'),precision=precision,in_frame=bool(obs and obs.in_frame))

    def event(self, event):
        if self.finished:
            return
        if event['kind']=='down': self.grabs+=1
        if event['kind']=='up': self.releases+=1
        self.write('input',event=event)

    def frame(self, rect, delta, released=False):
        self.best_delta = max(self.best_delta,delta)
        if released:
            self.released_delta = delta
        self.write('window',rect=rect,delta_px=round(delta,1),released=released)

    def finish(self, reason='completed'):
        if self.finished:
            return
        self.finished=True
        self.success = bool(reason=='completed' and self.releases>0 and self.released_delta is not None
                            and self.released_delta>=120)
        if self.task in ('pointer','shortcuts'):
            self.success=bool(reason=='completed' and self.hits>=5)
        self.write('outcome',success=self.success,reason=reason,grabs=self.grabs,releases=self.releases,
                   best_delta_px=round(self.best_delta,1),released_delta_px=self.released_delta,tracking_frames=self.tracking_frames,usable_frames=self.usable_frames,hits=self.hits,misses=self.misses)

    def target(self, hit, figure, requested_angle=None):
        if self.finished: return
        if hit: self.hits+=1
        else: self.misses+=1
        self.write('target',hit=hit,hits=self.hits,misses=self.misses,figure=figure,requested_angle=requested_angle)

    def feedback(self, answers, current):
        p=replace(current)
        if answers['feel']=='Too slow': p.sensitivity=min(2.5,p.sensitivity*1.15)
        if answers['feel']=='Too fast': p.sensitivity=max(.4,p.sensitivity/1.15)
        if answers['feel']=='Jittery': p.cutoff=max(.8,p.cutoff*.8)
        if self.task=='pointer' and current.motion_scheme=='figures' and answers['gesture'] in ('One finger','Open hand') and answers['feel'] in ('Too slow','Too fast'):
            p.sensitivity=current.sensitivity
            field='finger_speed' if answers['gesture']=='One finger' else 'palm_speed'
            factor=1.15 if answers['feel']=='Too slow' else 1/1.15
            lo,hi=(.6,2) if field=='finger_speed' else (.3,1.2)
            setattr(p,field,max(lo,min(hi,getattr(p,field)*factor)))
        gesture={'Fingertip pinch':'pinch','Thumb side tap':'side','Whole-hand grab':'grab'}.get(answers['gesture'])
        note='Movement tuning updated from your feedback.'
        if self.distance_trial and answers['feel'] in ('Too slow','Too fast'):
            p.sensitivity=current.sensitivity
            p.tilt_gain=max(.3,min(2,current.tilt_gain*(1.15 if answers['feel']=='Too slow' else 1/1.15)))
            note='Tilt precision gain updated. Retest from the same distance.'
        if self.task=='shortcuts':
            p.sensitivity=current.sensitivity
            if answers['feel'] in ('Gesture was missed','Needed too much movement'):
                p.shortcut_scale=max(.7,p.shortcut_scale*.9)
            elif answers['feel']=='Triggered too easily':
                p.shortcut_scale=min(1.4,p.shortcut_scale*1.1)
            note='Finger shortcut travel tuned. The next round will test it.'
        if gesture=='grab':
            p.gesture='grab'; p.contact_on=.28; p.contact_off=.46; p.calibrated=True
            note='Whole-hand grab selected from your response. The next trial will test it.'
        elif gesture:
            field='pinch' if gesture=='pinch' else 'side'
            resting=sorted(s[field] for s in self.samples if s['phase']=='rest' and s[field] is not None)
            acting=sorted(s[field] for s in self.samples if s['phase']=='action' and s[field] is not None)
            if len(resting)>=8 and len(acting)>=12:
                op=resting[int(.15*(len(resting)-1))]
                contact=acting[int(.15*(len(acting)-1))]
                gap=op-contact
                on,off=contact+.25*gap,contact+.65*gap
                if gap>=.16 and .03<=on<off<=2 and off-on>=.06:
                    p.gesture=gesture; p.contact_on=on; p.contact_off=off; p.calibrated=True
                    note='Contact thresholds fitted to this attempt. The next trial will verify them.'
                else:
                    note='Your contact signal was unclear; existing gesture thresholds retained.'
            else:
                note='Not enough visible hand samples; existing gesture thresholds retained.'
        self.write('feedback',answers=answers,next_profile=asdict(p),note=note)
        return p,note
