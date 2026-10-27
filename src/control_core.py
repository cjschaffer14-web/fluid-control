"""Deterministic interaction engine. No camera, UI or operating-system side effects."""
from dataclasses import dataclass
from collections import deque
import math
import statistics
from precision import TiltPrecision


def clamp(x, lo, hi):
    return min(hi, max(lo, x))


class OneEuro:
    """Derivative is computed from raw samples, not last filtered output."""
    def __init__(self, cutoff=1.8, beta=12.0):
        self.cutoff, self.beta = cutoff, beta
        self.reset()

    def reset(self):
        self.raw = self.value = self.t = None
        self.derivative = 0.0

    @staticmethod
    def alpha(cutoff, dt):
        return 1 / (1 + 1 / (2 * math.pi * cutoff * dt))

    def __call__(self, x, t):
        if self.t is None:
            self.raw = self.value = x
            self.t = t
            return x
        dt = clamp(t - self.t, .001, .15)
        a = self.alpha(1.0, dt)
        self.derivative += a * ((x - self.raw) / dt - self.derivative)
        a = self.alpha(self.cutoff + self.beta * abs(self.derivative), dt)
        self.value += a * (x - self.value)
        self.raw, self.t = x, t
        return self.value


@dataclass(frozen=True)
class Observation:
    t: float
    x: float
    y: float
    contact: float
    palm_px: float
    posture: str = "point"  # point / fist / scroll_up / scroll_down
    hand: str = "Right"
    pinch: float | None = None
    side: float | None = None
    curled: bool | None = None
    open_palm: bool = False
    palm_fraction: float = .08
    figure: str = 'neutral'
    geometry: str = 'depth'
    finger_mask: int = 0

    gesture_x: float | None = None
    gesture_y: float | None = None
    palm_height_fraction: float = 0.0
    extension_scores: tuple = ()
    hand_map: dict | None = None
    palm_basis: tuple = ()
    in_frame: bool = True

    def usable(self):
        return (all(math.isfinite(v) for v in (self.t, self.x, self.y, self.contact, self.palm_px))
                and -.1 <= self.x <= 1.1 and -.1 <= self.y <= 1.1
                and 0 <= self.contact <= 8 and self.palm_px >= 22 and self.in_frame)


@dataclass
class Profile:
    contact_on: float = .28
    contact_off: float = .46
    sensitivity: float = 1.0
    cutoff: float = 1.8
    calibrated: bool = False
    gesture: str = "pinch"
    motion_scheme: str = 'figures'
    finger_speed: float = 1.35
    palm_speed: float = .60
    shortcuts: bool = True
    shortcut_scale: float = 1.0
    tilt_precision: bool = True
    tilt_gain: float = 1.0

    @classmethod
    def from_dict(cls, data):
        p = cls()
        try:
            a, b = float(data['contact_on']), float(data['contact_off'])
            s, c = float(data['sensitivity']), float(data['cutoff'])
            if not all(math.isfinite(v) for v in (a, b, s, c)):
                return p
            if not (.03 <= a < b <= 2.0 and b - a >= .06):
                return p
            f, h, g = float(data.get('finger_speed',1.35)), float(data.get('palm_speed',.60)),float(data.get('shortcut_scale',1))
            tilt_gain=float(data.get('tilt_gain',1))
            if not all(math.isfinite(v) for v in (f,h,g,tilt_gain)):
                return p
            return cls(a, b, clamp(s, .4, 2.5), clamp(c, .8, 4),
                       bool(data.get('calibrated')), data.get('gesture') if data.get('gesture') in ('side','grab') else 'pinch',
                       data.get('motion_scheme') if data.get('motion_scheme') in ('classic','fluid') else 'figures',
                       clamp(f,.6,2.0),clamp(h,.3,1.2),bool(data.get('shortcuts',True)),clamp(g,.7,1.4),
                       bool(data.get('tilt_precision',True)),clamp(tilt_gain,.3,2))
        except (KeyError, ValueError, TypeError):
            return p


class Calibration:
    """Three paired open/contact trials. New profiles are explicit, never self-labelled."""
    phases = [("Hold your hand still, thumb away", 2.5, False),
              ("Touch thumb to finger and hold", 2.0, True),
              ("Release; hold your thumb away", 2.0, False),
              ("Touch again and hold", 2.0, True),
              ("Release; hold your thumb away", 2.0, False),
              ("Touch once more and hold", 2.0, True),
              ("Release your thumb", 1.8, False)]

    def __init__(self, now):
        self.phase = 0
        self.elapsed = 0.0
        self.last_t = now
        self.open = []
        self.closed = []
        self.phase_counts = [0] * len(self.phases)
        self.hold = []
        self.done = False
        self.error = ''

    @property
    def prompt(self):
        if self.done:
            return self.error or 'Calibration complete'
        text, seconds, _ = self.phases[self.phase]
        return f'{text} · {max(0, seconds - self.elapsed):.0f}s'

    def add(self, obs):
        dt = clamp(obs.t - self.last_t, 0, .12)
        self.last_t = obs.t
        if self.done or not obs.usable():
            return
        self.elapsed += dt
        _, duration, contact = self.phases[self.phase]
        # Ignore the beginning of each transition rather than learning it as contact.
        if self.elapsed > .8:
            (self.closed if contact else self.open).append(obs.contact)
            self.phase_counts[self.phase] += 1
            if self.phase == 0:
                self.hold.append((obs.x, obs.y))
        if self.elapsed >= duration:
            self.phase += 1
            self.elapsed = 0.0
            self.done = self.phase == len(self.phases)

    def finish(self, old):
        if not self.done or min(self.phase_counts) < 6:
            self.error = 'Not enough clear samples. Keep your hand visible and try again.'
            return None
        op = sorted(self.open)
        cl = sorted(self.closed)
        low_open = op[int(.1 * (len(op) - 1))]
        high_closed = cl[int(.9 * (len(cl) - 1))]
        gap = low_open - high_closed
        if gap < .14:
            self.error = 'Contact is not distinct enough at this distance. Try a larger pinch or move closer.'
            return None
        on, off = high_closed + gap * .25, high_closed + gap * .65
        if not (.03 <= on < off <= 2 and off - on >= .06):
            self.error = 'Gesture range is unsuitable. Try a more visible gesture.'
            return None
        # Tune noise suppression from a deliberately stationary labelled sample.
        jitter = max(statistics.pstdev(p[i] for p in self.hold) for i in (0, 1))
        cutoff = clamp(2.4 - jitter * 100, .9, 2.4)
        from dataclasses import replace
        return replace(old,contact_on=on,contact_off=off,cutoff=cutoff,calibrated=True)


class Controller:
    """One owner for the pointer and button state. All calls made under runtime lock."""
    def __init__(self, bounds=(0, 0, 1920, 1080), profile=None):
        self.bounds = bounds
        self.profile = profile or Profile()
        self.x = bounds[0] + bounds[2] / 2
        self.y = bounds[1] + bounds[3] / 2
        self.paused = True
        self.mode = 'pointer'
        self.state = 'idle'
        self.status = 'Paused'
        self.last_obs = None
        self.last_t = None
        self.last_input_t = -100.0
        self.finger_down = False
        self.rearmed = False
        self.open_since = None
        self.close_since = None
        self.release_since = None
        self.pose_since = None
        self.pose = None
        self.scroll_y = None
        self.press_t = None
        self.anchor = None
        self.previous = None
        self.start_hand = None
        self.last_click = (-100.0, 0, 0, 0)
        self.fx, self.fy = OneEuro(), OneEuro()
        self.history = deque(maxlen=40)
        self.events = []
        self.tilt=TiltPrecision()
        self.figure = self.figure_candidate = 'neutral'
        self.figure_since = None

    def emit(self, kind, **data):
        self.events.append(dict(kind=kind, x=self.x, y=self.y, **data))

    def drain(self):
        e, self.events = self.events, []
        return e

    def cancel(self, reason='Paused'):
        if self.finger_down:
            self.emit('up', cancelled=True)
        self.finger_down = False
        self.state = 'idle'
        self.tilt.reset()
        self.rearmed = False
        self.open_since = self.close_since = self.release_since = None
        self.last_obs = self.previous = self.pose = self.pose_since = self.scroll_y = None
        self.anchor = self.press_t = self.start_hand = None
        self.fx.reset()
        self.fy.reset()
        self.history.clear()
        self.figure = self.figure_candidate = 'neutral'
        self.figure_since = None
        self.status = reason

    def pause(self, value=True):
        self.cancel('Paused' if value else 'Show an open hand to start')
        self.paused = value

    def set_mode(self, mode):
        if mode not in ('pointer', 'move', 'resize', 'scroll'):
            raise ValueError(mode)
        self.cancel('Show an open hand to start')
        self.mode = mode

    def tick(self, now):
        if self.last_obs is not None and now - self.last_obs.t > .15:
            self.cancel('Hand lost · release and show your hand again')

    def feed(self, o):
        if self.paused:
            return
        if self.last_t is not None and o.t <= self.last_t:
            return
        self.last_t = o.t
        if not o.usable():
            self.cancel('Hand detail uncertain · waiting for a clear view')
            return
        if self.last_obs and (o.t - self.last_obs.t > .15 or o.hand != self.last_obs.hand):
            self.cancel('Tracking changed · release to continue')
        if self.last_obs and math.hypot(o.x-self.last_obs.x, o.y-self.last_obs.y) > .22:
            self.cancel('Tracking jump · release to continue')
        frame_dt = clamp(o.t-self.last_obs.t, .008, .1) if self.last_obs else 1/30
        self.last_obs = o
        if not self.rearmed:
            if o.contact > self.profile.contact_off and o.posture == 'point':
                if self.open_since is None:
                    self.open_since = o.t
                if o.t - self.open_since >= .24:
                    self.rearmed = True
                    self.state = 'ready'
                    self.previous = (o.x, o.y, o.t)
                    self.fx(o.x, o.t)
                    self.fy(o.y, o.t)
            else:
                self.open_since = None
            self.status = 'Show an open hand to start'
            return
        # Preserve a held interaction regardless of finger posture changing during pinch.
        if self.state not in ('contact', 'drag'):
            if o.posture != self.pose:
                self.pose, self.pose_since = o.posture, o.t
            if o.posture == 'fist' or (self.profile.motion_scheme=='fluid' and o.posture in ('scroll_up','scroll_down')):
                if self.profile.motion_scheme=='fluid' and o.t-self.pose_since<.16:
                    self.status='Hand shape changing · holding pointer'
                    return
                self.previous = None
                self.scroll_y = None
                self.fx.reset(); self.fy.reset()
                self.tilt.reset()
                self.status = 'Clutched · relax and reposition'
                self.close_since = None
                return
            if o.posture in ('scroll_up', 'scroll_down') and self.profile.motion_scheme!='fluid':
                self.previous = None
                self.scroll_y = None
                self.fx.reset(); self.fy.reset()
                self.close_since = None
                self.status = 'Hold thumb direction to scroll'
                if o.t - self.pose_since >= .32:
                    self.emit('scroll', dy=(660 if o.posture == 'scroll_up' else -660)*frame_dt)
                    self.status = 'Scrolling'
                return
        if self.mode == 'scroll':
            if self.scroll_y is not None:
                dy = (o.y - self.scroll_y) * 2400
                if abs(dy) > 1:
                    self.emit('scroll', dy=-dy)
            self.scroll_y = o.y
            self.status = 'Scroll mode · move hand up or down'
            return
        # Change feel only after a stable figure; pinching retains its prior feel.
        if self.profile.motion_scheme=='figures' and self.state=='ready' and o.contact>=self.profile.contact_off:
            if o.figure!=self.figure_candidate:
                self.figure_candidate,self.figure_since=o.figure,o.t
            if self.figure_since is not None and o.t-self.figure_since>=.12 and o.figure in ('one_finger','open_hand'):
                self.figure=o.figure
        factor=1.0
        if self.profile.motion_scheme=='fluid':
            self.fx.cutoff=self.fy.cutoff=self.profile.cutoff*.65
            self.fx.beta=self.fy.beta=22
        elif self.profile.motion_scheme=='figures' and self.figure!='neutral':
            factor=self.profile.finger_speed if self.figure=='one_finger' else self.profile.palm_speed
            # Strong still-hand smoothing, with less lag as deliberate speed rises.
            self.fx.cutoff=self.fy.cutoff=self.profile.cutoff*(.9 if self.figure=='one_finger' else .7)
            self.fx.beta=self.fy.beta=28 if self.figure=='one_finger' else 10
        else:
            self.fx.cutoff=self.fy.cutoff=self.profile.cutoff
            self.fx.beta=self.fy.beta=12
        fx, fy = self.fx(o.x, o.t), self.fy(o.y, o.t)
        if self.previous is None:
            self.previous = (fx, fy, o.t)
        px, py, pt = self.previous
        dt = max(.001, o.t - pt)
        speed = math.hypot(fx - px, fy - py) / dt
        # Relative control avoids distance-dependent absolute screen warping.
        if self.profile.motion_scheme=='fluid':
            # Small movements stay precise; large sweeps cover the screen with less effort.
            curve=.55+5.0*clamp(speed/.40,0,1)**1.5
        else:
            curve=(.85 + 3.55*clamp(speed/.45,0,1)) if self.figure!='neutral' and self.profile.motion_scheme=='figures' else (1.8+2.6*clamp(speed/.6,0,1))
        distance_gain=max(1,min(2.2,.04/max(.015,o.palm_fraction))) if self.profile.motion_scheme=='fluid' else 1
        gain = self.profile.sensitivity * factor * curve * distance_gain
        dx, dy = (fx - px) * self.bounds[2] * gain, (fy - py) * self.bounds[3] * gain
        self.previous = (fx, fy, o.t)
        tilt=self.tilt.feed(o,enabled=self.profile.tilt_precision and self.mode=='pointer' and o.posture=='point')
        if tilt is not None:
            pixels=min(self.bounds[2:])*.65*self.profile.tilt_gain
            dx,dy=tilt[0]*pixels,tilt[1]*pixels
        if self.state == 'ready' and o.contact < self.profile.contact_on:
            if self.close_since is None:
                self.close_since = o.t
                # Stabilize from onset. No unconditional time rewind or cursor teleport.
                self.anchor = (self.x, self.y)
                self.start_hand = (fx, fy)
            if o.t - self.close_since >= .055:
                self.state = 'contact'
                self.press_t = self.close_since
            self.status = 'Contact'
            return
        if self.state == 'ready':
            self.close_since = None
        if self.state in ('contact', 'drag'):
            if o.contact >= self.profile.contact_off:
                if self.release_since is None:
                    self.release_since = o.t
                if o.t - self.release_since >= .055:
                    if self.finger_down:
                        self.emit('up', cancelled=False)
                        self.finger_down = False
                    elif self.mode == 'pointer':
                        self.x, self.y = self.anchor
                        when, x, y, count = self.last_click
                        count = count + 1 if o.t - when < .42 and math.hypot(self.x-x,self.y-y) < 24 else 1
                        # A double-click is two down/up pairs total, carrying click count metadata.
                        self.emit('click', count=count)
                        self.last_click = (o.t, self.x, self.y, count)
                    self.state = 'ready'
                    self.close_since = self.release_since = None
                    self.status = 'Ready'
                return
            self.release_since = None
            if self.state == 'contact':
                moved = math.hypot(fx-self.start_hand[0], fy-self.start_hand[1])
                if o.t - self.press_t >= .22 or moved > .018:
                    self.x, self.y = self.anchor
                    self.emit('down', mode=self.mode)
                    self.finger_down = True
                    self.state = 'drag'
                else:
                    return
        # Window modes only move while held; pointer mode follows open hand too.
        if self.mode == 'pointer' or self.state == 'drag':
            bx, by, w, h = self.bounds
            self.x = clamp(self.x + dx, bx, bx+w-1)
            self.y = clamp(self.y + dy, by, by+h-1)
            self.emit('move', dragging=self.finger_down, dt=dt)
        self.status = ('Tilt precision · pinch to click' if self.tilt.active and not self.finger_down else 'Ready · '+self.mode)
        if self.finger_down:self.status = ('Dragging' if self.mode == 'pointer' else f'{self.mode.title()} window') if self.finger_down else f'Ready · {self.mode}'


COMMANDS = {
    'click': 'click', 'select': 'click', 'double click': 'double_click',
    'right click': 'right_click', 'drag': 'drag', 'drop': 'drop', 'release': 'drop',
    'move window': 'move', 'resize window': 'resize', 'pointer': 'pointer',
    'scroll mode': 'scroll', 'scroll up': 'scroll_up', 'scroll down': 'scroll_down',
    'pause control': 'pause', 'stop control': 'pause', 'resume control': 'resume',
    'faster': 'faster', 'slower': 'slower', 'play pause': 'media',
    'volume up': 'volume_up', 'volume down': 'volume_down', 'go back': 'back',
    'go forward': 'forward', 'cancel': 'cancel',
    'desktop left': 'desktop_left', 'desktop right': 'desktop_right',
    'previous desktop': 'desktop_left', 'next desktop': 'desktop_right',
    'calibrate here': 'position_save', 'remember this position': 'position_save',
    'control': 'position_recall', 'come here': 'position_recall',
}


def parse_command(text):
    # Exact bounded vocabulary: ordinary conversation must not become a command.
    return COMMANDS.get(' '.join(text.lower().strip().rstrip('.!?').split()))
