"""Real OS event round-trip check, confined to an owned, foreground test window."""
import json,time,os
from pathlib import Path
import AppKit as A
import Foundation as F
import Quartz as Q
from native import Output, is_own_event, EVENT_TAG


class ClickProbe(A.NSView):
    def acceptsFirstMouse_(self,event): return True
    def mouseDown_(self,event): self.owner.record('left_down',event)
    def mouseUp_(self,event): self.owner.record('left_up',event)
    def rightMouseDown_(self,event): self.owner.record('right_down',event)
    def rightMouseUp_(self,event): self.owner.record('right_up',event)
    def mouseDragged_(self,event): self.owner.record('drag',event)
    def scrollWheel_(self,event):
        self.owner.events.append(dict(kind='scroll',dy=event.scrollingDeltaY(),timestamp=event.timestamp()))


class ClickClock(A.NSObject):
    def tick_(self,timer): self.owner.tick()


class ClickCheck:
    def __init__(self,bounds,data):
        self.finished=False;self.events=[];self.started=time.monotonic();self.step=0
        self.polled_left=self.polled_right=0
        self.data=Path(data);self.out=Output(bounds);self.out.enabled=True
        self.window=A.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            ((200,200),(520,350)),A.NSWindowStyleMaskTitled|A.NSWindowStyleMaskClosable,A.NSBackingStoreBuffered,False)
        self.window.setTitle_('Control · Native click check')
        self.window.setReleasedWhenClosed_(False);self.window.center()
        self.view=ClickProbe.alloc().initWithFrame_(((0,0),(520,350)))
        self.view.owner=self;self.window.setContentView_(self.view)
        self.label=A.NSTextField.labelWithString_('Checking single, double, right click, drag and release…')
        self.label.setFrame_(((24,265),(472,60)));self.label.setMaximumNumberOfLines_(3)
        self.label.setFont_(A.NSFont.systemFontOfSize_(18));self.view.addSubview_(self.label)
        self.note=A.NSTextField.labelWithString_('Clicks stay inside this window. Switching apps cancels the check.')
        self.note.setFrame_(((24,20),(472,44)));self.note.setMaximumNumberOfLines_(2);self.view.addSubview_(self.note)
        self.window.makeKeyAndOrderFront_(None);A.NSApp.activateIgnoringOtherApps_(True)
        point=self.window.convertPointToScreen_((220,160))
        self.x,self.y=point.x,Q.CGDisplayBounds(Q.CGMainDisplayID()).size.height-point.y
        self.actions=[(.5,'single'),(1.2,'double'),(2.0,'right'),(2.8,'down'),(3.1,'move'),(3.4,'up'),(4.0,'down'),(4.3,'cancel'),(4.7,'scroll')]
        self.clock=ClickClock.alloc().init();self.clock.owner=self
        self.timer=F.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(1/120,self.clock,'tick:',None,True)

    def record(self,kind,event):
        p=event.locationInWindow()
        source=Q.CGEventGetIntegerValueField(event.CGEvent(),Q.kCGEventSourceUnixProcessID)
        tagged=Q.CGEventGetIntegerValueField(event.CGEvent(),Q.kCGEventSourceUserData)==EVENT_TAG
        self.events.append(dict(kind=kind,count=event.clickCount(),timestamp=event.timestamp(),x=p.x,y=p.y,source_pid=source,tagged=tagged))
        if not is_own_event(event.CGEvent()) and not self.finished:
            self.finish(cancelled=True)

    def finish(self,cancelled=False,error=None):
        self.finished=True;self.timer.invalidate();self.out.release()
        downs=[e for e in self.events if e['kind']=='left_down']
        ups=[e for e in self.events if e['kind']=='left_up']
        right_down=[e for e in self.events if e['kind']=='right_down']
        right_up=[e for e in self.events if e['kind']=='right_up']
        durations=[u['timestamp']-d['timestamp'] for d,u in zip(downs,ups)]
        checks=dict(left_pairs=len(downs)==5 and len(ups)==5,
                    double_click=[e['count'] for e in downs[:3]]==[1,1,2],
                    right_click=len(right_down)==1 and len(right_up)==1,
                    drag=any(e['kind']=='drag' for e in self.events),
                    visible_press=len(durations)>=3 and min(durations[:3])>=.045,
                    polled_left_press=self.polled_left>=2,polled_right_press=self.polled_right>=2,
                    scroll=any(e['kind']=='scroll' and e['dy']!=0 for e in self.events),
                    ownership_tag=bool(downs) and all(e['tagged'] for e in downs+ups+right_down+right_up),
                    release_not_stuck=not self.out.down)
        self.passed=not cancelled and not error and all(checks.values())
        report=dict(kind='native_click_check',passed=self.passed,cancelled=cancelled,error=error,
                    checks=checks,press_seconds=durations,events=self.events,time=time.time(),
                    polled_left_samples=self.polled_left,polled_right_samples=self.polled_right)
        folder=self.data/'attempts';folder.mkdir(parents=True,exist_ok=True)
        (folder/'native-click-check.json').write_text(json.dumps(report,indent=2))
        self.label.setStringValue_('Check passed: single, double, right click, drag, scroll and release.' if self.passed else ('Check cancelled. Your clicks have been released.' if cancelled else 'Click check needs attention. Results were saved locally.'))
        self.note.setStringValue_('This verifies real macOS event delivery. The Steam popup still needs its own trial.')

    def tick(self):
        try:
            if not self.window.isVisible() or not A.NSApp.isActive() or not self.window.isKeyWindow():
                self.finish(cancelled=True);return
            p=self.window.convertPointToScreen_((220,160))
            if abs(p.x-self.x)>1 or abs(Q.CGDisplayBounds(Q.CGMainDisplayID()).size.height-p.y-self.y)>1:
                self.finish(cancelled=True);return
            now=time.monotonic();elapsed=now-self.started
            if Q.CGEventSourceButtonState(Q.kCGEventSourceStateCombinedSessionState,Q.kCGMouseButtonLeft):
                self.polled_left+=1
            if Q.CGEventSourceButtonState(Q.kCGEventSourceStateCombinedSessionState,Q.kCGMouseButtonRight):
                self.polled_right+=1
            if self.step<len(self.actions) and elapsed>=self.actions[self.step][0]:
                action=self.actions[self.step][1];self.step+=1
                event=dict(kind='click',x=self.x,y=self.y)
                if action=='double':
                    self.out.handle(event);self.out.handle(dict(event,count=2))
                elif action in ('single','right'):
                    self.out.handle(dict(event,right=action=='right'))
                elif action=='cancel': self.out.release()
                elif action=='scroll':self.out.handle(dict(kind='scroll',x=self.x,y=self.y,dy=240))
                else:
                    self.out.handle(dict(kind=action,x=self.x+(70 if action in ('move','up') else 0),y=self.y,mode='pointer'))
            self.out.pump(now)
            if elapsed>=5.3:self.finish()
        except Exception as e:
            self.finish(error=str(e))
