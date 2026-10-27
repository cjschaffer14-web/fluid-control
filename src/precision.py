"""Relative hand-rotation precision, entered after a stationary palm settles."""
from collections import deque
import math


def valid_basis(basis):
    if len(basis)!=9 or not all(math.isfinite(v) for v in basis):return False
    rows=[basis[i:i+3] for i in (0,3,6)]
    return all(abs(sum(v*v for v in row)-1)<.08 for row in rows) and all(
        abs(sum(a*b for a,b in zip(rows[i],rows[j])))<.08 for i,j in ((0,1),(0,2),(1,2)))


def rotation_xy(current,reference):
    # Rotation in camera axes, using the whole palm frame rather than Euler angles.
    r=[[sum(current[i*3+k]*reference[j*3+k] for k in range(3)) for j in range(3)] for i in range(3)]
    return (r[0][2]-r[2][0])*.5,(r[2][1]-r[1][2])*.5


class TiltPrecision:
    def __init__(self):self.reset()

    def reset(self):
        self.samples=deque(maxlen=30);self.active=False;self.center=None
        self.reference=None;self.last_t=None;self.hand=None
        self.filtered=(0.,0.);self.last=(0.,0.);self.reason='Hold hand still to enable tilt';self.progress=0.

    def feed(self,o,enabled=True):
        if not enabled:
            self.reset();self.reason='Tilt off · move hand to point';return None
        if o is None or o.geometry!='world' or not valid_basis(o.palm_basis):
            self.reset();self.reason='Waiting for clear 3D hand geometry';return None
        if self.last_t is not None and (o.t<=self.last_t or o.t-self.last_t>.15 or o.hand!=self.hand):self.reset()
        dt=min(.1,max(.001,o.t-self.last_t)) if self.last_t is not None else 1/30
        self.last_t,self.hand=o.t,o.hand
        if self.active:
            if math.hypot(o.x-self.center[0],o.y-self.center[1])>max(.025,min(.06,o.palm_fraction*.6)):
                self.reset();return None
            rx,ry=rotation_xy(o.palm_basis,self.reference)
            # Reject a pose flip; do not convert it into a cursor jump.
            if max(abs(rx),abs(ry))>.40:
                self.reset();return (0.,0.)
            alpha=1-math.exp(-dt/.065)
            self.filtered=tuple(a+alpha*(b-a) for a,b in zip(self.filtered,(rx,ry)))
            def deadzone(v):return math.copysign(max(0,abs(v)-math.radians(.35)),v)
            current=tuple(deadzone(v) for v in self.filtered)
            delta=tuple(a-b for a,b in zip(current,self.last));self.last=current
            self.reason='Tilt precision active';self.progress=1.
            return delta
        if self.samples and math.hypot(o.x-self.samples[0].x,o.y-self.samples[0].y)>max(.008,min(.035,o.palm_fraction*.30)):self.samples.clear()
        self.samples.append(o)
        self.progress=min(1.,(o.t-self.samples[0].t)/.32)
        self.reason=f'Settle hand · {round(self.progress*100)}% to tilt'
        if len(self.samples)>=8 and o.t-self.samples[0].t>=.32:
            self.active=True;self.center=(o.x,o.y)
            self.reference=o.palm_basis
            self.filtered=self.last=(0.,0.)
            self.reason='Tilt precision active';self.progress=1.
            return (0.,0.)
        return None
