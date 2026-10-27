"""Deliberate open-palm desktop swipes; independent of pointer motion."""
from collections import deque
import math


class DesktopSwipes:
    def __init__(self):
        self.last_fire = -100.0
        self.need_release = False
        self.reset()

    def reset(self):
        self.rest = None
        self.anchor = None
        self.previous = None
        self.moving_at = None
        self.samples = deque(maxlen=30)

    def feed(self, o, allowed=True):
        if not allowed or o is None or not o.usable():
            if o is None:
                self.need_release=False
            self.reset()
            return None
        if self.previous and (o.t <= self.previous.t or o.t-self.previous.t>.15 or o.hand!=self.previous.hand):
            self.reset()
        self.previous=o
        if not o.open_palm:
            self.need_release=False
            self.reset()
            return None
        if self.need_release or o.t-self.last_fire<1.2:
            return None
        if self.anchor is None:
            if self.rest is None or math.hypot(o.x-self.rest.x,o.y-self.rest.y)>.018:
                self.rest=o
            if o.t-self.rest.t>=.25:
                self.anchor=o
            return None
        dx,dy=o.x-self.anchor.x,o.y-self.anchor.y
        travel=max(.055,min(.18,o.palm_fraction*2.5))
        if self.moving_at is None and abs(dx)>.02:
            self.moving_at=o.t
        self.samples.append(o)
        if self.moving_at is None:
            return None
        duration=o.t-self.moving_at
        if abs(dy)>.13 or duration>.7:
            self.reset()
            return None
        if (abs(dx)>=travel and len(self.samples)>=4 and .10<=duration<=.7
                and abs(dx)>abs(dy)*2.8 and abs(dx)/max(.1,duration)>.35):
            direction='right' if dx>0 else 'left'
            self.last_fire=o.t
            self.need_release=True
            self.reset()
            return direction
        return None
