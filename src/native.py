"""macOS input and window manipulation. Accessibility calls use the system C API."""
import ctypes as C
import os
import time
import math
import secrets
from collections import deque
import Quartz as Q

# Process-local ownership survives event routes that report source PID zero.
EVENT_TAG = secrets.randbits(56) or 1


def is_own_event(event):
    return event is not None and (
        Q.CGEventGetIntegerValueField(event, Q.kCGEventSourceUserData) == EVENT_TAG or
        Q.CGEventGetIntegerValueField(event, Q.kCGEventSourceUnixProcessID) == os.getpid())


class Point(C.Structure):
    _fields_ = [('x', C.c_double), ('y', C.c_double)]


class Size(C.Structure):
    _fields_ = [('width', C.c_double), ('height', C.c_double)]


CF = C.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
AX = C.CDLL('/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices')


def bind(lib, name, result, args):
    fn = getattr(lib, name)
    fn.restype = result
    fn.argtypes = args
    return fn


release = bind(CF, 'CFRelease', None, [C.c_void_p])
string = bind(CF, 'CFStringCreateWithCString', C.c_void_p, [C.c_void_p, C.c_char_p, C.c_uint32])
cf_bool = bind(CF, 'CFBooleanGetValue', C.c_bool, [C.c_void_p])
trusted = bind(AX, 'AXIsProcessTrusted', C.c_bool, [])
system_wide = bind(AX, 'AXUIElementCreateSystemWide', C.c_void_p, [])
element_at = bind(AX, 'AXUIElementCopyElementAtPosition', C.c_int,
                  [C.c_void_p, C.c_float, C.c_float, C.POINTER(C.c_void_p)])
copy_attr = bind(AX, 'AXUIElementCopyAttributeValue', C.c_int,
                 [C.c_void_p, C.c_void_p, C.POINTER(C.c_void_p)])
set_attr = bind(AX, 'AXUIElementSetAttributeValue', C.c_int, [C.c_void_p, C.c_void_p, C.c_void_p])
settable = bind(AX, 'AXUIElementIsAttributeSettable', C.c_int,
                [C.c_void_p, C.c_void_p, C.POINTER(C.c_bool)])
value_create = bind(AX, 'AXValueCreate', C.c_void_p, [C.c_int, C.c_void_p])
value_get = bind(AX, 'AXValueGetValue', C.c_bool, [C.c_void_p, C.c_int, C.c_void_p])
timeout = bind(AX, 'AXUIElementSetMessagingTimeout', C.c_int, [C.c_void_p, C.c_float])
cf_equal = bind(CF, 'CFEqual', C.c_bool, [C.c_void_p, C.c_void_p])
type_id = bind(CF, 'CFGetTypeID', C.c_ulong, [C.c_void_p])
bool_type = bind(CF, 'CFBooleanGetTypeID', C.c_ulong, [])


def attr(element, name):
    key = string(None, name.encode(), 0x08000100)
    out = C.c_void_p()
    try:
        err = copy_attr(element, key, C.byref(out))
        return out.value if err == 0 else None
    finally:
        release(key)


def can_set(element, name):
    key = string(None, name.encode(), 0x08000100)
    out = C.c_bool()
    try:
        return settable(element, key, C.byref(out)) == 0 and out.value
    finally:
        release(key)


def set_value(element, name, kind, value):
    key = string(None, name.encode(), 0x08000100)
    val = value_create(kind, C.byref(value))
    try:
        if not val or set_attr(element, key, val):
            raise RuntimeError('This window refused the change')
    finally:
        if val:
            release(val)
        release(key)


class WindowGrab:
    def __init__(self):
        self.element = None
        self.mode = None
        self.last_update = 0

    def end(self):
        if self.element:
            release(self.element)
        self.element = None

    def begin(self, x, y, mode):
        self.end()
        root, hit = system_wide(), C.c_void_p()
        try:
            timeout(root, .08)
            if element_at(root, x, y, C.byref(hit)) or not hit.value:
                raise RuntimeError('Point inside a window first')
        finally:
            release(root)
        current = hit.value
        try:
            win = attr(current, 'AXWindow')
            if win:
                release(current)
                current = win
            else:
                # A hit can itself be a window. Ascend only through actual parents.
                for _ in range(12):
                    role = attr(current, 'AXRole')
                    expected = string(None, b'AXWindow', 0x08000100)
                    match = bool(role and cf_equal(role, expected))
                    if role:
                        release(role)
                    release(expected)
                    if match:
                        break
                    parent = attr(current, 'AXParent')
                    if not parent:
                        raise RuntimeError('Point inside a normal application window')
                    release(current)
                    current = parent
                else:
                    raise RuntimeError('No movable window at the pointer')
            timeout(current, .08)
            fs = attr(current, 'AXFullScreen')
            try:
                if fs and type_id(fs) == bool_type() and cf_bool(fs):
                    raise RuntimeError('Exit full screen before moving or resizing')
            finally:
                if fs:
                    release(fs)
            key = 'AXPosition' if mode == 'move' else 'AXSize'
            if not can_set(current, key):
                raise RuntimeError('This window does not support ' + ('moving' if mode == 'move' else 'resizing'))
            pos, size = attr(current, 'AXPosition'), attr(current, 'AXSize')
            p, s = Point(), Size()
            try:
                if not pos or not size or not value_get(pos, 1, C.byref(p)) or not value_get(size, 2, C.byref(s)):
                    raise RuntimeError('Cannot read this window frame')
            finally:
                if pos:
                    release(pos)
                if size:
                    release(size)
            self.start = (x, y, p.x, p.y, s.width, s.height)
            self.mode, self.element = mode, current
            self.last_update = 0
            current = None
        finally:
            if current:
                release(current)

    def update(self, x, y, bounds, force=False):
        if not self.element:
            return
        now = time.monotonic()
        if not force and now - self.last_update < 1/30:
            return
        self.last_update = now
        sx, sy, wx, wy, ww, wh = self.start
        bx, by, bw, bh = bounds
        if self.mode == 'move':
            # Keep enough title area reachable to recover the window.
            p = Point(max(bx-ww+100, min(bx+bw-100, wx+x-sx)), max(by, min(by+bh-60, wy+y-sy)))
            set_value(self.element, 'AXPosition', 1, p)
        else:
            s = Size(max(240, min(bw*1.5, ww+x-sx)), max(160, min(bh*1.5, wh+y-sy)))
            set_value(self.element, 'AXSize', 2, s)


class Output:
    def __init__(self, bounds):
        self.bounds = bounds
        self.window = WindowGrab()
        self.mode = 'pointer'
        self.down = False
        self.target = None
        self.current = self.position()
        self.velocity = (0, 0)
        self.observed = 0
        self.enabled = False
        self.last_count = 1
        self.right_down = False
        self.scroll_acc = 0.0
        self.click_queue = deque()
        self.click_active = None
        self.next_click = 0.0
        self.click_stats = dict(requested=0,completed=0,cancelled=0)
        self.click_feedback=None

    @staticmethod
    def position():
        p = Q.CGEventGetLocation(Q.CGEventCreate(None))
        return float(p.x), float(p.y)

    @staticmethod
    def post(event):
        if event is None:
            raise RuntimeError('macOS could not create an input event')
        Q.CGEventSetIntegerValueField(event, Q.kCGEventSourceUnixProcessID, os.getpid())
        Q.CGEventSetIntegerValueField(event, Q.kCGEventSourceUserData, EVENT_TAG)
        Q.CGEventPost(Q.kCGHIDEventTap, event)

    def mouse(self, kind, x, y, count=1, right=False):
        e = Q.CGEventCreateMouseEvent(None, kind, (x, y), Q.kCGMouseButtonRight if right else Q.kCGMouseButtonLeft)
        Q.CGEventSetIntegerValueField(e, Q.kCGMouseEventClickState, count)
        self.post(e)

    def feedback(self):
        if self.click_feedback:
            try:self.click_feedback()
            except Exception:pass  # Sound feedback must never affect event delivery.

    def release(self):
        if self.click_active or self.click_queue:
            self.click_stats['cancelled']+=len(self.click_queue)+bool(self.click_active)
        self.click_queue.clear()
        self.click_active=None
        try:
            if self.window.element and self.target:
                self.window.update(*self.target, self.bounds, force=True)
        finally:
            self.window.end()
            try:
                if self.down:
                    self.mouse(Q.kCGEventRightMouseUp if self.right_down else Q.kCGEventLeftMouseUp,
                               *self.current, self.last_count, self.right_down)
            finally:
                self.down = False
                self.right_down = False
                self.target = None
                self.velocity = (0, 0)

    def handle(self, event):
        kind, x, y = event['kind'], event['x'], event['y']
        if kind == 'up':
            self.release()
            return
        if not self.enabled:
            return
        if kind == 'scroll':
            self.scroll_acc += event['dy']
            dy = int(self.scroll_acc)
            if dy:
                self.post(Q.CGEventCreateScrollWheelEvent(None, Q.kCGScrollEventUnitPixel, 1, dy))
                self.scroll_acc -= dy
        elif kind == 'move':
            old = self.target or (x, y)
            dt = max(.008, event.get('dt', .033))
            self.velocity = ((x-old[0])/dt, (y-old[1])/dt)
            self.target, self.observed = (x, y), time.monotonic()
            if self.window.element:
                self.window.update(x, y, self.bounds)
        elif kind == 'down':
            self.release()
            self.mode = event.get('mode', 'pointer')
            if self.mode in ('move', 'resize'):
                self.window.begin(x, y, self.mode)
            else:
                self.current = (x, y)
                self.last_count,self.right_down=1,False
                self.mouse(Q.kCGEventLeftMouseDown, x, y)
                self.down = True
                self.feedback()
        elif kind == 'click':
            if not self.click_active and not self.click_queue:
                self.release()
            # Bound command backlog. Each accepted contact is one down/up pair.
            if len(self.click_queue)<4:
                self.click_queue.append((x,y,event.get('count',1),event.get('right',False)))
                self.click_stats['requested']+=1

    def pump(self, now):
        if not self.enabled:
            return
        if self.click_active:
            x,y,count,right,stage,due=self.click_active
            if now<due:
                return
            if stage=='hover':
                self.mouse(Q.kCGEventRightMouseDown if right else Q.kCGEventLeftMouseDown,x,y,count,right)
                self.down,self.right_down,self.last_count=True,right,count
                self.feedback()
                self.click_active=(x,y,count,right,'press',now+.060)
            else:
                self.mouse(Q.kCGEventRightMouseUp if right else Q.kCGEventLeftMouseUp,x,y,count,right)
                self.down,self.right_down=False,False
                self.click_active=None
                self.next_click=now+.040
                self.click_stats['completed']+=1
            return
        if self.click_queue:
            if now>=self.next_click:
                x,y,count,right=self.click_queue.popleft()
                self.current=(x,y)
                self.mouse(Q.kCGEventMouseMoved,x,y,0)
                self.click_active=(x,y,count,right,'hover',now+.016)
            return
        if not self.enabled or not self.target or self.window.element:
            return
        age = now - self.observed
        if age > .10:
            return
        # Small bounded interpolation horizon; never continue on stale camera data.
        horizon = min(age, .012)
        bx, by, w, h = self.bounds
        x = max(bx, min(bx+w-1, self.target[0]+self.velocity[0]*horizon*.3))
        y = max(by, min(by+h-1, self.target[1]+self.velocity[1]*horizon*.3))
        if math.hypot(x-self.current[0], y-self.current[1]) < .2:
            return
        self.current = (x, y)
        self.mouse(Q.kCGEventLeftMouseDragged if self.down else Q.kCGEventMouseMoved, x, y)

    def switch_desktop(self, direction):
        if direction not in ('left','right'):
            raise ValueError(direction)
        code=123 if direction=='left' else 124
        try:
            for key,down in ((59,True),(code,True),(code,False)):
                event=Q.CGEventCreateKeyboardEvent(None,key,down)
                flags=Q.kCGEventFlagMaskControl | 1
                if key==code:
                    flags |= Q.kCGEventFlagMaskSecondaryFn | Q.kCGEventFlagMaskNumericPad
                Q.CGEventSetFlags(event,flags)
                self.post(event)
                time.sleep(.06)
        finally:
            event=Q.CGEventCreateKeyboardEvent(None,59,False)
            Q.CGEventSetFlags(event,0)
            self.post(event)
