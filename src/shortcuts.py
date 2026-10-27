"""Finger chords with fingertip scroll travel and brief classification tolerance."""
import math


class FingerShortcuts:
    def __init__(self):
        self.last_fire=-100.0;self.blocked=None;self.previous=None
        self.candidate=None;self.candidate_at=None;self.release_since=None
        self.reset()

    def reset(self):
        self.group=None;self.rest=None;self.anchor=None
        self.moving_at=None;self.tap_at=None;self.reserved=False;self.progress=0.

    def clear(self):
        self.previous=None;self.blocked=None;self.candidate=None;self.candidate_at=None;self.release_since=None;self.reset()

    def hint(self):
        if self.blocked:return 'Relax your fingers for the next gesture'
        if self.tap_at is not None:return 'Tap: reopen index + middle fingers'
        if self.group=='two':return 'Two fingers: move or flick UP / DOWN'
        if self.group=='three':return 'Sweep LEFT / RIGHT · '+str(round(self.progress*100))+'%'
        return 'Two fingers: scroll · three: desktops · open-hand wave: recall position'

    @staticmethod
    def group_for(mask):
        if mask==3:return 'two'
        if mask.bit_count()==3:return 'three'
        return None

    @staticmethod
    def position(o,group):
        if group=='two' and o.gesture_x is not None and o.gesture_y is not None:
            return o.gesture_x,o.gesture_y
        return o.x,o.y

    def fire(self,o,action,group):
        self.last_fire=o.t;self.blocked=group
        self.reset();self.reserved=True
        return action

    def feed(self,o,allowed=True,scale=1,allow_desktop=True,allow_two=True,allow_tap=True):
        self.reserved=False
        if not allowed or o is None or not o.pointer_usable():
            self.reset();self.previous=None
            if o is None:self.blocked=None
            return None
        if self.previous and (o.t<=self.previous.t or o.t-self.previous.t>.15 or o.hand!=self.previous.hand):
            self.clear()
        self.previous=o
        raw=self.group_for(o.finger_mask)
        if raw and (o.visible_fingers & o.finger_mask)!=o.finger_mask:
            self.reset();return None
        if raw=='three' and not allow_desktop:raw=None
        if raw=='two' and not allow_two:self.reset();return None
        # A transient ring-finger estimate must not erase a two-finger stroke.
        group=raw
        if self.group and raw!=self.group and not (self.group=='two' and o.finger_mask in (0,1,2)):
            if raw!=self.candidate or self.candidate_at is None:self.candidate,self.candidate_at=raw,o.t
            if o.t-self.candidate_at<.09:group=self.group
        else:self.candidate=None;self.candidate_at=None
        if self.blocked:
            if raw!=self.blocked:
                if self.release_since is None:self.release_since=o.t
                if o.t-self.release_since>=.09:self.blocked=None;self.release_since=None
            else:
                self.release_since=None
            if self.blocked:
                self.reserved=raw=='two';return None
        if o.t-self.last_fire<.50:
            self.reset();self.reserved=group=='two';return None
        if self.group=='two' and self.anchor and raw is None and o.finger_mask in (0,1,2):
            if not allow_tap:self.reset();return None
            self.reserved=True
            if self.tap_at is None:self.tap_at=o.t
            if o.t-self.tap_at>.45 or math.hypot(o.x-self.anchor.x,o.y-self.anchor.y)>.045:self.reset()
            return None
        if self.tap_at is not None:
            duration=o.t-self.tap_at
            if raw=='two' and .06<=duration<=.45 and math.hypot(o.x-self.anchor.x,o.y-self.anchor.y)<.045:
                return self.fire(o,dict(kind='double_click'),'two')
            self.reset()
        if group is None:self.reset();return None
        if group!=self.group:self.reset();self.group=group
        self.reserved=group=='two'
        if self.anchor is None:
            self.anchor=o;return None
        x,y=self.position(o,group);ax,ay=self.position(self.anchor,group)
        dx,dy=x-ax,y-ay
        vertical=o.palm_height_fraction or o.palm_fraction
        travel=(max(.009,min(.065,vertical*.42)) if group=='two' else max(.020,min(.13,o.palm_fraction*1.5)))*scale
        distance=abs(dy) if group=='two' else abs(dx)
        self.progress=min(1.,distance/max(travel,1e-6))
        elapsed=o.t-self.anchor.t
        if elapsed>1.0:
            self.anchor=o;self.progress=0.;return None
        if group=='two':
            if .10<=elapsed<=.85 and abs(dy)>=travel and abs(dy)>abs(dx)*1.5 and abs(dy)/max(.1,elapsed)>max(.03,min(.075,vertical*1.3)):
                amount=max(120,min(650,abs(dy)/max(.1,elapsed)*900))
                return self.fire(o,dict(kind='scroll',dy=-math.copysign(amount,dy)),'two')
        else:
            if raw!='three':return None
            self.reserved=abs(dx)>travel*.45 and abs(dx)>abs(dy)*1.65
            minimum=.12 if o.finger_mask.bit_count()>3 else .075
            if minimum<=elapsed<=.85 and abs(dx)>=travel and abs(dx)>abs(dy)*1.65 and abs(dx)/max(.1,elapsed)>max(.04,min(.15,o.palm_fraction*1.8)):
                return self.fire(o,dict(kind='desktop',direction='right' if dx>0 else 'left'),'three')
        return None
