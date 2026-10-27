"""Exclusive finger chords. No output, timer threads, or guessing across lost frames."""
import math


class FingerShortcuts:
    def __init__(self):
        self.last_fire=-100.0
        self.blocked=None
        self.previous=None
        self.reset()

    def reset(self):
        self.group=None
        self.rest=None
        self.anchor=None
        self.moving_at=None
        self.tap_at=None
        self.reserved=False

    def clear(self):
        self.previous=None
        self.blocked=None
        self.reset()

    def hint(self):
        if self.blocked:return 'Relax your fingers for the next gesture'
        if self.tap_at is not None:return 'Tap: reopen index + middle fingers'
        if self.group=='two':return 'Two fingers ready: tap or flick' if self.anchor else 'Raise index + middle together'
        if self.group=='three':return 'Swipe left or right' if self.anchor or (self.previous and self.previous.finger_mask.bit_count()==3) else 'Open palm: hold, then swipe'
        return 'One finger: point · two: tap/flick · three: swipe'

    @staticmethod
    def group_for(mask):
        if mask==3:return 'two'
        if mask.bit_count()>=3:return 'three'
        return None

    def fire(self,o,action,group):
        self.last_fire=o.t;self.blocked=group
        self.reset();self.reserved=True
        return action

    def feed(self,o,allowed=True,scale=1,allow_desktop=True,allow_two=True):
        self.reserved=False
        if not allowed or o is None or not o.usable():
            self.reset();self.previous=None
            if o is None:self.blocked=None
            return None
        if self.previous and (o.t<=self.previous.t or o.t-self.previous.t>.15 or o.hand!=self.previous.hand):
            self.reset();self.blocked=None
        self.previous=o
        group=self.group_for(o.finger_mask)
        if group=='three' and not allow_desktop:group=None
        if group=='two' and not allow_two:
            self.reset();return None
        if self.blocked:
            if group!=self.blocked:self.blocked=None
            else:
                self.reserved=True
                return None
        if o.t-self.last_fire<.6:
            self.reset()
            self.reserved=group=='two'
            return None
        # A two-finger air tap is curl -> reopen, with the palm almost stationary.
        if self.group=='two' and self.anchor and group is None and o.finger_mask in (0,1,2):
            self.reserved=True
            if self.tap_at is None:self.tap_at=o.t
            if o.t-self.tap_at>.45 or math.hypot(o.x-self.anchor.x,o.y-self.anchor.y)>.045:
                self.reset()
            return None
        if self.tap_at is not None:
            duration=o.t-self.tap_at
            if group=='two' and .06<=duration<=.45 and math.hypot(o.x-self.anchor.x,o.y-self.anchor.y)<.045:
                return self.fire(o,dict(kind='double_click'),'two')
            self.reset()
        if group is None:
            self.reset();return None
        if group!=self.group:
            self.reset();self.group=group
        self.reserved=group=='two'
        if self.anchor is None:
            if group=='two' or o.finger_mask.bit_count()==3:
                if self.rest is None:self.rest=o
                if o.t-self.rest.t<.075:return None
                self.anchor=self.rest
            else:
                if self.rest is None or math.hypot(o.x-self.rest.x,o.y-self.rest.y)>.018:
                    self.rest=o
                if o.t-self.rest.t>=.16:self.anchor=o
                return None
        dx,dy=o.x-self.anchor.x,o.y-self.anchor.y
        distance=abs(dy) if group=='two' else abs(dx)
        if self.moving_at is None and distance>.012:self.moving_at=o.t
        if self.moving_at is None:return None
        self.reserved=group=='two'
        duration=o.t-self.moving_at
        if duration>.65:
            self.reset();return None
        if group=='two':
            travel=max(.035,min(.10,o.palm_fraction*1.5))*scale
            if .07<=duration<=.50 and abs(dy)>=travel and abs(dy)>abs(dx)*2.4 and abs(dy)/max(.1,duration)>.26:
                amount=max(180,min(600,abs(dy)/max(.1,duration)*650))
                return self.fire(o,dict(kind='scroll',dy=-math.copysign(amount,dy)),'two')
        else:
            travel=max(.055,min(.18,o.palm_fraction*2.3))*scale
            if .09<=duration<=.65 and abs(dx)>=travel and abs(dx)>abs(dy)*2.8 and abs(dx)/max(.1,duration)>.32:
                return self.fire(o,dict(kind='desktop',direction='right' if dx>0 else 'left'),'three')
        return None
