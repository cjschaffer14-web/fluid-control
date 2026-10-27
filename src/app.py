#!/usr/bin/env python3
"""Control — native Mac app. Starts paused; never records camera or microphone media."""
import argparse
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import queue
import signal
import subprocess
import sys
import time
import AppKit as A
import Foundation as F
import Quartz as Q
import objc
import ctypes
import json
from native import trusted
from runtime import Runtime, DATA
from runtime import profile_save
from attempts import Attempt
from version import VERSION, UPDATED
from awareness import tracking_state
from halo import TrackingHalo

try:
    PERMISSIONS = ctypes.CDLL(None)
    PERMISSIONS.control_camera_status.restype = ctypes.c_int
    PERMISSIONS.control_microphone_status.restype = ctypes.c_int
except AttributeError:
    PERMISSIONS = None  # Source-only launch: packaged native app supplies permission hooks.


class FlippedView(A.NSView):
    def isFlipped(self):
        return True


class RoomMapView(A.NSView):
    snapshot={}

    def drawRect_(self, rect):
        A.NSColor.colorWithWhite_alpha_(.08,1).setFill();A.NSRectFill(self.bounds())
        attrs={A.NSFontAttributeName:A.NSFont.systemFontOfSize_(14),A.NSForegroundColorAttributeName:A.NSColor.whiteColor()}
        def text(s,x,y):F.NSString.stringWithString_(s).drawAtPoint_withAttributes_((x,y),attrs)
        text('Saved camera positions · size of dot shows relative hand size',18,356)
        text('Save at your desk, sofa, or standing. Keep the camera fixed.',18,329)
        text('Open-hand wave: recall. Three fingers: switch desktop.',18,24)
        if not self.snapshot.get('anchors'):text('No positions yet. Choose Control → Save position here.',20,190)
        for a in self.snapshot.get('anchors',[]):
            x=35+a['x']*470;y=70+(1-a['y'])*220
            size=max(12,min(42,a['size']*240))
            (A.NSColor.systemGreenColor() if a['name']==self.snapshot.get('active') else A.NSColor.systemBlueColor()).setFill()
            A.NSBezierPath.bezierPathWithOvalInRect_(((x-size/2,y-size/2),(size,size))).fill()
            text(a['name'],x-35,y+size/2+4)


class AppDelegate(A.NSObject):
    def applicationDidFinishLaunching_(self, notification):
        DATA.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(DATA/'control.log', maxBytes=400000, backupCount=2)
        logging.basicConfig(level=logging.INFO, handlers=[handler], format='%(asctime)s %(levelname)s %(message)s')
        b = Q.CGDisplayBounds(Q.CGMainDisplayID())
        self.rt = Runtime((b.origin.x,b.origin.y,b.size.width,b.size.height), '--dry-run' in sys.argv)
        from feedback_audio import ClickAudio
        self.click_audio=ClickAudio()
        try:
            prefs=json.loads((DATA/'feedback-preferences.json').read_text())
            self.click_audio.enabled=bool(prefs.get('click_audio',True))
        except (OSError,ValueError,TypeError):pass
        self.rt.output.click_feedback=lambda: self.performSelectorOnMainThread_withObject_waitUntilDone_('clickTap:',None,False)
        self.halo=TrackingHalo()
        self.halo_state={}
        self.last_image = None
        self.last_metrics = 0
        self.camera_pending = False
        self.voice_pending = False
        self.wake_pending = False
        self.demo = None
        self.demo_active = False
        self.demo_grab = None
        self.restore_on_launch='--restore-pointer' in sys.argv
        if self.restore_on_launch:
            self.rt.restore_pointer()
        self.auto_swipes='--desktop-swipes' in sys.argv
        self.next_status=0
        self.pending_desktop=None
        self.auto_fluid=(self.restore_on_launch or self.auto_swipes and self.rt.core.profile.motion_scheme=='fluid') and '--live-demo' not in sys.argv
        self.last_takeover_queued=0
        self.click_check=None
        self.hotkeys = PERMISSIONS.control_register_hotkeys() if PERMISSIONS else 0
        if PERMISSIONS and self.hotkeys != 31:
            logging.warning('Some shortcuts are already in use; installed hotkey mask=%s',self.hotkeys)
        self.monitors = []
        self.buildWindow()
        self.buildMenu()
        icon=F.NSBundle.mainBundle().pathForResource_ofType_('Control-v02','icns')
        if icon:
            A.NSApp.setApplicationIconImage_(A.NSImage.alloc().initWithContentsOfFile_(icon))
        self.timer = F.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(.1,self,'tick:',None,True)
        mask = A.NSEventMaskKeyDown | A.NSEventMaskMouseMoved | A.NSEventMaskLeftMouseDown | A.NSEventMaskRightMouseDown
        global_monitor = A.NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(mask, self.globalEvent)
        if global_monitor:
            self.monitors.append(global_monitor)
        local_monitor = A.NSEvent.addLocalMonitorForEventsMatchingMask_handler_(A.NSEventMaskKeyDown,self.localEvent)
        if local_monitor:
            self.monitors.append(local_monitor)
        self.window.makeKeyAndOrderFront_(None)
        A.NSApp.activateIgnoringOtherApps_(True)
        signal.signal(signal.SIGTERM, lambda *_: self.rt.ui_actions.put(('quit',None)))
        signal.signal(signal.SIGINT, lambda *_: self.rt.ui_actions.put(('quit',None)))
        if '--live-demo' in sys.argv:
            self.demo_(None)
        elif self.auto_swipes or self.restore_on_launch:
            self.camera_(None)
        if '--smoke-ui' in sys.argv:
            self.smoke_end = time.monotonic()+5
        if '--smoke-camera' in sys.argv:
            self.rt.start_camera()
            self.smoke_end = time.monotonic()+12

    @objc.python_method
    def label(self, text, rect, size=13, color=None):
        v = A.NSTextField.labelWithString_(text)
        v.setFrame_(rect)
        v.setFont_(A.NSFont.systemFontOfSize_(size))
        v.setTextColor_(color or A.NSColor.labelColor())
        self.content.addSubview_(v)
        return v

    @objc.python_method
    def button(self, title, rect, action):
        b = A.NSButton.alloc().initWithFrame_(rect)
        b.setTitle_(title)
        b.setBezelStyle_(A.NSBezelStyleRounded)
        b.setTarget_(self); b.setAction_(action)
        self.content.addSubview_(b)
        return b

    @objc.python_method
    def buildWindow(self):
        self.window = A.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            ((0,0),(700,772)), A.NSWindowStyleMaskTitled | A.NSWindowStyleMaskClosable | A.NSWindowStyleMaskMiniaturizable,
            A.NSBackingStoreBuffered, False)
        self.window.setTitle_('Control '+VERSION+' · Updated')
        self.window.setReleasedWhenClosed_(False)
        self.window.center()
        self.content = FlippedView.alloc().initWithFrame_(((0,0),(700,772)))
        self.window.setContentView_(self.content)
        self.label('Control', ((24,16),(350,36)), 28)
        self.fluid_button=self.button('Fluid pointer',((276,22),(155,30)),'fluid:')
        self.label('UPDATED · v'+VERSION,((446,26),(225,26)),14,A.NSColor.systemBlueColor())
        self.label('Your hand moves. Your computer follows.', ((24,57),(400,25)), 14, A.NSColor.secondaryLabelColor())
        self.tilt_button=self.button('Tilt mode',((440,55),(110,28)),'tilt:')
        self.button('Room map',((560,55),(110,28)),'roomMap:')
        self.cam_button = self.button('Start camera', ((20,94),(145,34)), 'camera:')
        self.start_button = self.button('Start control', ((175,94),(155,34)), 'toggle:')
        self.voice_button = self.button('Voice · 12 sec', ((340,94),(155,34)), 'voice:')
        self.button('Permissions…', ((505,94),(170,34)), 'permissions:')
        self.modes = A.NSSegmentedControl.alloc().initWithFrame_(((24,142),(650,32)))
        self.modes.setSegmentCount_(4)
        for i, name in enumerate(('Pointer  ⌥1','Move window  ⌥2','Resize window  ⌥3','Scroll  ⌥4')):
            self.modes.setLabel_forSegment_(name,i)
            self.modes.setWidth_forSegment_(162,i)
        self.modes.setSelectedSegment_(0)
        self.modes.setTarget_(self); self.modes.setAction_('mode:')
        self.content.addSubview_(self.modes)
        self.image = A.NSImageView.alloc().initWithFrame_(((24,188),(650,366)))
        self.image.setImageScaling_(A.NSImageScaleProportionallyUpOrDown)
        self.image.setWantsLayer_(True)
        self.image.layer().setBackgroundColor_(A.NSColor.colorWithWhite_alpha_(.08,1).CGColor())
        self.image.layer().setCornerRadius_(12)
        self.content.addSubview_(self.image)
        self.finger_label=self.label('Show your hand to see recognized fingers',((36,513),(624,30)),13,A.NSColor.whiteColor())
        self.finger_label.setWantsLayer_(True)
        self.finger_label.layer().setBackgroundColor_(A.NSColor.colorWithWhite_alpha_(.05,.85).CGColor())
        self.finger_label.layer().setCornerRadius_(6)
        self.placeholder = self.label('Camera off · video stays on this Mac', ((100,354),(520,30)), 17, A.NSColor.secondaryLabelColor())
        self.metrics = self.label('Ready when you are', ((24,564),(650,24)), 12, A.NSColor.secondaryLabelColor())
        self.status = self.label('Start the camera to check your setup', ((24,593),(650,46)), 15)
        self.status.setMaximumNumberOfLines_(2)
        self.help = self.label('One finger: quick. Open hand: precise. Pinch: click. Fist: rest. Esc: pause.', ((24,640),(650,24)), 12)
        self.voice_label = self.label('Voice off · ⌥Space to speak one command', ((24,666),(650,24)), 12, A.NSColor.secondaryLabelColor())
        self.button('5–10 ft trial', ((20,704),(110,32)), 'distanceDemo:')
        self.button('Slower', ((135,704),(90,32)), 'slower:')
        self.button('Faster', ((228,704),(90,32)), 'faster:')
        self.button('Undo tuning', ((325,704),(120,32)), 'undo:')
        self.gesture = A.NSPopUpButton.alloc().initWithFrame_pullsDown_(((455,704),(215,32)),False)
        self.gesture.addItemsWithTitles_(['Fingertip pinch','Side tap · calibrate first','Whole-hand grab'])
        self.gesture.selectItemAtIndex_(1 if self.rt.core.profile.gesture=='side' else 0)
        self.gesture.setTarget_(self); self.gesture.setAction_('gesture:')
        self.content.addSubview_(self.gesture)
        self.label('Window modes: place the pointer inside a window, select mode, then pinch and move.', ((24,747),(650,20)), 11, A.NSColor.secondaryLabelColor())

    @objc.python_method
    def item(self, menu, title, action, tag=0):
        i = A.NSMenuItem.alloc().initWithTitle_action_keyEquivalent_(title, action, '')
        i.setTarget_(self); i.setTag_(tag)
        menu.addItem_(i)
        return i

    @objc.python_method
    def buildMenu(self):
        main=A.NSMenu.alloc().init()
        app_item=A.NSMenuItem.alloc().init()
        main.addItem_(app_item)
        app_menu=A.NSMenu.alloc().init()
        self.item(app_menu,'About Control '+VERSION,'about:')
        self.item(app_menu,'Open live demo','demo:')
        self.item(app_menu,'5–10 ft tilt trial','distanceDemo:')
        self.item(app_menu,'Tracking halo on / off','halo:')
        self.item(app_menu,'Tilt precision on / off','tilt:')
        self.item(app_menu,'Play button challenge','aim:')
        self.item(app_menu,'Try finger shortcuts','shortcutDemo:')
        self.item(app_menu,'Finger shortcuts on / off','shortcuts:')
        self.item(app_menu,'Save position here · hold hand still','savePosition:')
        self.item(app_menu,'Recall position · or wave open hand','recallPosition:')
        self.item(app_menu,'Show saved room positions','roomMap:')
        self.item(app_menu,'Click sound on / off','clickSound:')
        self.item(app_menu,'Listen for “Control” on / off','wake:')
        self.item(app_menu,'Fluid pointer · aim + pinch click','fluid:')
        self.item(app_menu,'Run native click check','clickCheck:')
        self.item(app_menu,'Hand figures · quick finger / slow palm','figures:')
        self.item(app_menu,'Classic motion','classic:')
        self.item(app_menu,'Show recorded attempts','attempts:')
        self.item(app_menu,'Desktop left','desktopLeft:')
        self.item(app_menu,'Desktop right','desktopRight:')
        app_menu.addItem_(A.NSMenuItem.separatorItem())
        self.item(app_menu,'Quit Control','quit:').setKeyEquivalent_('q')
        app_item.setSubmenu_(app_menu)
        A.NSApp.setMainMenu_(main)
        self.bar = A.NSStatusBar.systemStatusBar().statusItemWithLength_(A.NSVariableStatusItemLength)
        self.bar.button().setTitle_('Control ◌')
        menu = A.NSMenu.alloc().init()
        self.item(menu,'Control '+VERSION+' · Updated','about:')
        self.item(menu,'Show Control','show:')
        self.item(menu,'Live move / resize demo','demo:')
        self.item(menu,'5–10 ft tilt trial','distanceDemo:')
        self.item(menu,'Tracking halo on / off','halo:')
        self.item(menu,'Tilt precision on / off','tilt:')
        self.item(menu,'Play button challenge','aim:')
        self.item(menu,'Start / Pause','toggle:')
        self.item(menu,'Speak one command  ⌥Space','voice:')
        self.item(menu,'Desktop swipes on / off','swipes:')
        self.item(menu,'Save position here · hold hand still','savePosition:')
        self.item(menu,'Recall position · or wave open hand','recallPosition:')
        self.item(menu,'Show saved room positions','roomMap:')
        self.item(menu,'Click sound on / off','clickSound:')
        self.item(menu,'Listen for “Control” on / off','wake:')
        self.item(menu,'Desktop left','desktopLeft:')
        self.item(menu,'Desktop right','desktopRight:')
        menu.addItem_(A.NSMenuItem.separatorItem())
        for i,name in enumerate(('Pointer','Move window','Resize window','Scroll')):
            self.item(menu,name,'menuMode:',i)
        menu.addItem_(A.NSMenuItem.separatorItem())
        self.item(menu,'Calibrate gesture','calibrate:')
        self.item(menu,'Reset settings','reset:')
        preview = self.item(menu,'Hide / Show camera preview','preview:')
        submenu = A.NSMenu.alloc().init()
        for i in range(3):
            self.item(submenu,f'Camera {i+1}','selectCamera:',i)
        camera = self.item(menu,'Choose camera','show:')
        camera.setSubmenu_(submenu)
        self.item(menu,'Help','help:')
        self.item(menu,'Quit Control','quit:')
        self.bar.setMenu_(menu)

    def about_(self, sender):
        alert=A.NSAlert.alloc().init()
        alert.setMessageText_('Control '+VERSION+' · Updated')
        alert.setInformativeText_('Updated '+UPDATED+'\n\nLive move and resize demos\nFive questions after each attempt\nFeedback-driven recalibration\nRecorded interaction attempts\n\nBuilt for this Mac using its existing Python environment.')
        alert.setIcon_(A.NSApp.applicationIconImage())
        alert.addButtonWithTitle_('OK')
        alert.runModal()

    def attempts_(self, sender):
        from attempts import attempt_directory
        folder=attempt_directory()
        folder.mkdir(parents=True,exist_ok=True)
        subprocess.Popen(['open',str(folder)])

    @objc.python_method
    def globalEvent(self, event):
        if event.type() == A.NSEventTypeKeyDown:
            self.keyboard(event)
        elif not self.rt.core.paused:
            cg = event.CGEvent()
            source = Q.CGEventGetIntegerValueField(cg, Q.kCGEventSourceUnixProcessID) if cg else 0
            from native import is_own_event
            if not is_own_event(cg):
                now=time.monotonic()
                if now-self.last_takeover_queued>.08:
                    self.last_takeover_queued=now
                    app=A.NSRunningApplication.runningApplicationWithProcessIdentifier_(source) if source else None
                    self.rt.ui_actions.put(('takeover',dict(source_pid=source,source_app=str(app.localizedName()) if app else 'Mouse or trackpad')))

    @objc.python_method
    def localEvent(self, event):
        self.keyboard(event)
        return event

    @objc.python_method
    def keyboard(self, event):
        option = bool(event.modifierFlags() & A.NSEventModifierFlagOption)
        if event.keyCode() == 53:
            self.rt.ui_actions.put(('pause',None))
        elif not PERMISSIONS and option and event.keyCode() == 49:
            self.rt.ui_actions.put(('listen',None))
        elif not PERMISSIONS and option and event.charactersIgnoringModifiers() in ('1','2','3','4'):
            self.rt.ui_actions.put(('mode',int(event.charactersIgnoringModifiers())-1))

    def show_(self, sender):
        self.window.makeKeyAndOrderFront_(None)
        A.NSApp.activateIgnoringOtherApps_(True)

    def camera_(self, sender):
        if self.rt.capture_stop.is_set():
            if PERMISSIONS:
                status = PERMISSIONS.control_camera_status()
                if status == 0:
                    self.camera_pending = True
                    PERMISSIONS.control_request_camera()
                    self.rt.message = 'Allow camera access in the macOS prompt to continue'
                    return
                if status != 3:
                    self.rt.message = 'Camera access is off · open Permissions → Camera to enable Control'
                    return
            self.rt.start_camera(self.rt.camera_index)
        else:
            self.rt.stop_camera()

    def selectCamera_(self, sender):
        self.rt.stop_camera()
        self.rt.camera_index = sender.tag()
        self.camera_(None)

    def toggle_(self, sender):
        if self.rt.core.paused and not trusted() and PERMISSIONS and not self.rt.dry_run:
            PERMISSIONS.control_request_accessibility()
        self.rt.pause(not self.rt.core.paused)

    def mode_(self, sender):
        self.rt.set_mode(('pointer','move','resize','scroll')[self.modes.selectedSegment()])

    def menuMode_(self, sender):
        self.rt.set_mode(('pointer','move','resize','scroll')[sender.tag()])

    def voice_(self, sender):
        if PERMISSIONS and not self.rt.voice_until > time.monotonic():
            status = PERMISSIONS.control_microphone_status()
            if status == 0:
                self.voice_pending = True
                PERMISSIONS.control_request_microphone()
                self.rt.voice_message = 'Allow microphone access in the macOS prompt'
                return
            if status != 3:
                self.rt.voice_message = 'Microphone access is off · open Permissions → Microphone'
                return
        self.rt.listen()

    def wake_(self, sender):
        if not self.rt.voice_wake and PERMISSIONS:
            status=PERMISSIONS.control_microphone_status()
            if status==0:
                self.wake_pending=True;PERMISSIONS.control_request_microphone();return
            if status!=3:
                self.rt.voice_message='Enable Microphone access to use optional wake listening';return
        self.rt.set_wake(not self.rt.voice_wake)

    def clickTap_(self, sender):
        self.click_audio.play()

    def clickSound_(self, sender):
        self.click_audio.enabled=not self.click_audio.enabled
        (DATA/'feedback-preferences.json').write_text(json.dumps(dict(click_audio=self.click_audio.enabled)))
        if self.click_audio.enabled:self.click_audio.play()
        self.rt.message='Click sound '+('on' if self.click_audio.enabled else 'off')

    def savePosition_(self, sender):
        self.rt.save_position()

    def recallPosition_(self, sender):
        with self.rt.lock:self.rt.recall_position()

    def roomMap_(self, sender):
        if not hasattr(self,'room_window'):
            self.room_window=A.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                ((0,0),(540,390)),A.NSWindowStyleMaskTitled|A.NSWindowStyleMaskClosable,A.NSBackingStoreBuffered,False)
            self.room_window.setTitle_('Room positions · camera map')
            self.room_window.setReleasedWhenClosed_(False)
            self.room_window.center()
            self.room_view=RoomMapView.alloc().initWithFrame_(((0,0),(540,390)))
            self.room_window.setContentView_(self.room_view)
        self.room_view.snapshot=self.rt.room.snapshot()
        self.room_view.setNeedsDisplay_(True)
        self.room_window.makeKeyAndOrderFront_(None)

    def halo_(self,sender):
        self.halo.enabled=not self.halo.enabled
        if not self.halo.enabled:self.halo.close()

    def tilt_(self,sender):
        with self.rt.lock:
            enabled=not self.rt.core.profile.tilt_precision
            self.rt.restore_pointer(shortcuts=False)
            self.rt.core.profile.tilt_precision=enabled
            profile_save(self.rt.core.profile)
            self.rt.message='Tilt enabled · settle hand, then make small wrist tilts' if enabled else 'Tilt off · move hand to point'
        self.auto_fluid=True
        if self.rt.capture_stop.is_set():self.camera_(None)

    def distanceDemo_(self,sender):
        self.demo_(None)
        self.demo_task.selectItemAtIndex_(2)
        self.prepareAim()
        self.distance_trial=True
        self.demo_prompt.setStringValue_('Stand or sit 5–10 feet away. Move to travel; settle your hand, then tilt to fine-tune.')
        self.demo_signal.setStringValue_('Green: ready. White: tracked. Amber: unclear. Red: hand lost. Pinch to hit five targets.')
        self.demo_goal.setStringValue_('Test from your actual seat. Afterward, report distance and tilt feel in five questions.')

    def swipes_(self, sender):
        if self.rt.capture_stop.is_set():
            self.auto_swipes=True
            self.camera_(None)
        else:
            self.rt.enable_swipes(not self.rt.desktop_swipes)

    def desktopLeft_(self, sender):
        self.pending_desktop=('left',time.monotonic()+1)

    def desktopRight_(self, sender):
        self.pending_desktop=('right',time.monotonic()+1)

    def calibrate_(self, sender):
        self.rt.calibrate()

    def slower_(self, sender):
        self.rt.adjust(1/1.15)

    def faster_(self, sender):
        self.rt.adjust(1.15)

    def figures_(self, sender):
        self.setScheme('figures')

    def classic_(self, sender):
        self.setScheme('classic')

    def fluid_(self, sender):
        self.rt.restore_pointer()
        self.auto_swipes=False
        self.auto_fluid=True
        if self.rt.capture_stop.is_set():
            self.camera_(None)

    def shortcuts_(self, sender):
        with self.rt.lock:
            self.rt.core.profile.shortcuts=not self.rt.core.profile.shortcuts
            self.rt.shortcuts.clear()
            self.rt.shortcut_reserved=False
            self.rt.core.cancel('Finger shortcuts changed · open your hand to resume')
            self.rt._dispatch();self.rt.output.release()
            self.rt.desktop_swipes=self.rt.core.profile.shortcuts and not self.rt.core.paused
            profile_save(self.rt.core.profile)

    def shortcutDemo_(self, sender):
        self.demo_(None)
        self.demo_task.selectItemAtIndex_(3)
        self.prepareShortcuts()

    @objc.python_method
    def prepareShortcuts(self):
        self.shortcut_steps=[('scroll_down','Raise index + middle fingers. Move the fingertips DOWN; a small flick is enough.'),
                             ('scroll_up','Relax your fingers, then raise index + middle and move UP.'),
                             ('desktop_left','Raise three fingers and swipe LEFT.'),
                             ('desktop_right','Relax, raise three fingers and sweep RIGHT.'),
                             ('double_click','Raise index + middle fingers, briefly curl both and reopen.')]
        self.demo_prompt.setStringValue_('Five gestures. Try them naturally. Desktop actions stay inside this demo.')
        self.demo_goal.setStringValue_('Scroll down → scroll up → desktop left → desktop right → double click')
        self.demo_goal.setMaximumNumberOfLines_(2)
        if not hasattr(self,'shortcut_preview') or self.shortcut_preview.superview()!=self.demo.contentView():
            self.shortcut_preview=A.NSSegmentedControl.alloc().initWithFrame_(((80,324),(460,28)))
            self.shortcut_preview.setSegmentCount_(3)
            for i in range(3):
                self.shortcut_preview.setLabel_forSegment_('Desktop '+str(i+1),i)
                self.shortcut_preview.setWidth_forSegment_(150,i)
            self.shortcut_preview.setSelectedSegment_(1)
            self.shortcut_preview.setEnabled_(False)
            self.demo.contentView().addSubview_(self.shortcut_preview)
        self.shortcut_preview.setSelectedSegment_(1)
        self.shortcut_scroll=0

    @objc.python_method
    def practiceShortcut(self, action):
        if not self.demo_active or self.rt.attempt.task!='shortcuts':return
        name=action['kind']
        if name=='double_click':
            self.click_audio.play()
            self.performSelector_withObject_afterDelay_('clickTap:',None,.11)
        if name=='scroll':name='scroll_up' if action['dy']>0 else 'scroll_down'
        elif name=='desktop':name='desktop_'+action['direction']
        if name.startswith('desktop_'):
            i=self.shortcut_preview.selectedSegment()+(-1 if name=='desktop_left' else 1)
            self.shortcut_preview.setSelectedSegment_(max(0,min(2,i)))
        elif name.startswith('scroll_'):
            self.shortcut_scroll+=-1 if name=='scroll_up' else 1
        self.demo_goal.setStringValue_(f"Preview · scroll position {self.shortcut_scroll} · last action: {name.replace('_',' ')}")
        expected=self.shortcut_steps[self.rt.attempt.hits][0]
        self.rt.attempt.target(name==expected,self.rt.metrics.get('figure','neutral'),requested_angle=expected)
        self.rt.attempt.write('shortcut_result',recognized=name,expected=expected)
        if self.rt.attempt.hits>=5:self.endAttempt('completed')

    def clickCheck_(self, sender):
        if self.click_check and not self.click_check.finished:
            return
        from click_check import ClickCheck
        self.rt.pause(True)
        self.click_check=ClickCheck(self.rt.output.bounds,DATA)
        self.click_check.out.click_feedback=self.rt.output.click_feedback

    @objc.python_method
    def setScheme(self, scheme):
        from dataclasses import replace
        with self.rt.lock:
            self.rt.previous_profile=replace(self.rt.core.profile)
            self.rt.core.cancel('Motion scheme changed · open your hand to resume')
            self.rt._dispatch()
            self.rt.output.release()
            self.rt.core.profile.motion_scheme=scheme
            profile_save(self.rt.core.profile)
            self.rt.message={'figures':'Hand figures · one finger quick, open hand precise',
                             'classic':'Classic motion restored',
                             'fluid':'Fluid pointer · gentle aiming, pinch to click, fist to rest'}[scheme]
            if scheme=='fluid':
                self.rt.desktop_swipes=self.rt.core.profile.shortcuts and not self.rt.core.paused

    def aim_(self, sender):
        self.demo_(None)
        self.demo_task.selectItemAtIndex_(2)
        self.prepareAim()

    @objc.python_method
    def prepareAim(self):
        self.demo_prompt.setStringValue_('Five angles, five stars. Point, pinch, release. Keep your arm comfortable.')
        self.demo_signal.setStringValue_('The small blue dot is your practice cursor. Rest your arm whenever you need.')
        self.demo_goal.setHidden_(True)
        self.demo_signal.setFrame_(((24,238),(565,36)))
        self.aim_positions=[(280,320,64),(90,300,48),(455,340,48),(185,355,32),(370,300,32)]
        self.aim_angles=['Your comfortable palm-down angle','Palm facing the camera','Back of hand toward the camera','A gentle sideways tilt','Your preferred relaxed angle']
        self.aim_target=self.button('★',((280,320),(64,64)),None)
        self.aim_target.setFont_(A.NSFont.systemFontOfSize_(26))
        self.aim_target.setBezelColor_(A.NSColor.systemYellowColor())
        self.demo.contentView().addSubview_(self.aim_target)
        self.aim_dot=A.NSView.alloc().initWithFrame_(((300,290),(12,12)))
        self.aim_dot.setWantsLayer_(True)
        self.aim_dot.layer().setBackgroundColor_(A.NSColor.systemBlueColor().CGColor())
        self.aim_dot.layer().setCornerRadius_(6)
        self.demo.contentView().addSubview_(self.aim_dot)

    @objc.python_method
    def aimPoint(self, x, y):
        screen_max=Q.CGDisplayBounds(Q.CGMainDisplayID()).size.height
        p=self.demo.convertPointFromScreen_((x,screen_max-y))
        return self.demo.contentView().convertPoint_fromView_(p,None)

    def undo_(self, sender):
        self.rt.reset_profile(True)

    def reset_(self, sender):
        self.rt.reset_profile(False)

    def gesture_(self, sender):
        # Changing contact geometry requires new labelled samples; no reused thresholds.
        self.rt.calibrate(('pinch','side','grab')[sender.indexOfSelectedItem()])

    def demo_(self, sender):
        self.distance_trial=False
        self.rt.pause(True)
        self.aim_target=None
        if self.demo:
            self.demo.orderOut_(None)
        self.demo = A.NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            ((200,300),(620,540)),A.NSWindowStyleMaskTitled|A.NSWindowStyleMaskClosable|A.NSWindowStyleMaskResizable,
            A.NSBackingStoreBuffered,False)
        self.demo.setTitle_('Control '+VERSION+' · Live demo')
        self.demo.setReleasedWhenClosed_(False)
        self.demo.center()
        view=FlippedView.alloc().initWithFrame_(((0,0),(620,540)))
        self.demo.setContentView_(view)
        saved=self.content; self.content=view
        self.label('Try it your way · v'+VERSION,((24,20),(560,34)),25)
        self.label('This real practice window responds without Accessibility permission.',((24,62),(575,40)),13)
        self.demo_task=A.NSPopUpButton.alloc().initWithFrame_pullsDown_(((24,108),(270,32)),False)
        self.demo_task.addItemsWithTitles_(['Move this window right','Make this window wider','Play five-star button challenge','Try finger shortcuts'])
        view.addSubview_(self.demo_task)
        self.button('Start attempt',((315,108),(170,32)),'startAttempt:')
        self.button('Stop',((495,108),(100,32)),'stopAttempt:')
        self.demo_prompt=self.label('First relax your hand. Then grab however feels natural.',((24,162),(565,90)),20)
        self.demo_prompt.setMaximumNumberOfLines_(3)
        self.demo_signal=self.label('The app records gesture signals, timing, and results during the trial.',((24,260),(565,60)),13)
        self.demo_signal.setMaximumNumberOfLines_(3)
        self.demo_goal=self.label('Goal: move right or grow wider by 120 points, then release.',((24,350),(570,42)),14)
        self.label('Afterward: five questions → recalibrate → repeat.',((24,410),(570,32)),15)
        self.label('Desktop control stays off during this practice trial.',((24,458),(570,28)),12,A.NSColor.secondaryLabelColor())
        self.content=saved
        self.demo.makeKeyAndOrderFront_(None)
        A.NSApp.activateIgnoringOtherApps_(True)
        if self.rt.capture_stop.is_set():
            self.camera_(None)

    def startAttempt_(self, sender):
        if self.rt.capture_stop.is_set() or not self.rt.metrics['tracked']:
            self.demo_prompt.setStringValue_('Show your hand to the camera, then press Start attempt.')
            return
        if self.demo_active:
            self.stopAttempt_(None)
            return
        with self.rt.lock:
            self.rt.pause(True)
            self.rt.practice=True
            task=('move','resize','pointer','shortcuts')[self.demo_task.indexOfSelectedItem()]
            if task=='pointer' and self.aim_target is None:
                self.prepareAim()
            if task=='shortcuts':self.prepareShortcuts()
            self.rt.core.set_mode('pointer' if task=='shortcuts' else task)
            self.rt.attempt=Attempt(task,self.rt.core.profile)
            self.rt.attempt.distance_trial=self.distance_trial
            self.rt.attempt.write('setup',target_distance_ft=[5,10] if self.distance_trial else None,
                                  camera_width=self.rt.metrics.get('camera_width'),camera_height=self.rt.metrics.get('camera_height'))
            self.demo_origin=self.demo.frame()
            self.demo_grab=None
            self.demo_active=True
            self.demo_started_input=False
            self.demo_prompt.setStringValue_('Relax your hand for 3 seconds. Do not grab yet.')
        subprocess.Popen(['say','Relax your hand. Then follow the gesture on the screen.' if task=='shortcuts' else 'Relax your hand. Then grab this window however feels natural.'],
                         stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)

    def stopAttempt_(self, sender):
        if self.demo_active:
            self.endAttempt('stopped')

    @objc.python_method
    def practiceEvent(self, event):
        if not self.demo_active:
            return
        kind=event['kind']
        if self.rt.attempt.task=='shortcuts':return
        if kind=='click':self.click_audio.play()
        if self.rt.attempt.task=='pointer':
            p=self.aimPoint(event['x'],event['y'])
            if kind=='move':
                self.aim_dot.setFrameOrigin_((p.x-6,p.y-6))
            if kind=='click':
                hit=bool(A.NSPointInRect(p,self.aim_target.frame()))
                self.rt.attempt.target(hit,self.rt.metrics.get('figure','neutral'),self.aim_angles[self.rt.attempt.hits])
                if hit:
                    n=self.rt.attempt.hits
                    if n>=5:
                        self.endAttempt('completed')
                    else:
                        x,y,size=self.aim_positions[n]
                        self.aim_target.setFrame_(((x,y),(size,size)))
                        self.aim_target.setTitle_('★' if size>=48 else '•')
                        self.aim_target.setBezelColor_(A.NSColor.systemGreenColor() if n%2 else A.NSColor.systemYellowColor())
            return
        if kind=='down':
            f=self.demo.frame()
            self.demo_grab=(event['x'],event['y'],f.origin.x,f.origin.y,f.size.width,f.size.height)
        elif kind=='move' and self.demo_grab:
            x,y,wx,wy,w,h=self.demo_grab
            dx,dy=event['x']-x,event['y']-y
            screen=self.demo.screen().visibleFrame()
            if self.rt.attempt.task=='move':
                nx=max(screen.origin.x,min(screen.origin.x+screen.size.width-160,wx+dx))
                ny=max(screen.origin.y,min(screen.origin.y+screen.size.height-80,wy-dy))
                self.demo.setFrameOrigin_((nx,ny))
            else:
                nw=max(480,min(screen.size.width,w+dx))
                nh=max(400,min(screen.size.height,h+dy))
                self.demo.setFrame_display_(((wx,wy+h-nh),(nw,nh)),True)
            self.measurePractice(False)
        elif kind=='up':
            self.demo_grab=None
            self.measurePractice(not event.get('cancelled',False))
            if self.rt.attempt.released_delta is not None and self.rt.attempt.released_delta>=120:
                self.endAttempt('completed')

    @objc.python_method
    def measurePractice(self, released):
        f=self.demo.frame(); initial=self.demo_origin
        delta=f.origin.x-initial.origin.x if self.rt.attempt.task=='move' else f.size.width-initial.size.width
        self.rt.attempt.frame([round(f.origin.x),round(f.origin.y),round(f.size.width),round(f.size.height)],delta,released)

    @objc.python_method
    def endAttempt(self, reason):
        self.demo_active=False
        with self.rt.lock:
            self.rt.pause(True)
            self.rt.attempt.finish(reason)
            self.rt.practice=False
        self.demo_grab=None
        self.showFeedback()

    @objc.python_method
    def showFeedback(self):
        self.demo.setFrame_display_(((self.demo.frame().origin.x,self.demo.frame().origin.y),(620,570)),True)
        view=FlippedView.alloc().initWithFrame_(((0,0),(620,570)))
        self.demo.setContentView_(view)
        saved=self.content; self.content=view
        if self.rt.attempt.task in ('pointer','shortcuts'):
            result=f"{self.rt.attempt.hits}/5 {'gestures' if self.rt.attempt.task=='shortcuts' else 'stars'} · {self.rt.attempt.misses} mismatches · tell us how it felt."
        else:
            result='Worked: window changed by 120+ points and you released.' if self.rt.attempt.success else 'Not proven yet: the target action was not completed.'
        self.label(result,((24,20),(575,50)),17).setMaximumNumberOfLines_(2)
        self.feedback_controls={}
        questions=[('intent','1. What did you intend?',['Move window','Resize window']),
                   ('response','2. Did it respond as intended?',['No','Partly','Yes']),
                   ('gesture','3. How did you naturally grab?',['Fingertip pinch','Thumb side tap','Whole-hand grab','Something else']),
                   ('feel','4. What most needs changing?',['Gesture was missed','Too slow','Too fast','Jittery','Nothing']),
                   ('comfort','5. How comfortable was it?',['0','1','2','3','4','5','6','7','8','9','10'])]
        if self.rt.attempt.task=='pointer':
            questions[0]=('intent','1. Which angle felt hardest?',['Palm down','Palm toward camera','Back toward camera','Sideways tilt','None felt difficult'])
            questions[2]=('gesture','3. Which hand shape did you use?',['One finger','Open hand','Mixed'])
        elif self.rt.attempt.task=='shortcuts':
            questions[0]=('intent','1. Which gesture needs the most work?',['Double click','Scroll down','Scroll up','Desktop left','Desktop right','None'])
            questions[2]=('gesture','3. Which hand angle felt best?',['Palm down','Palm toward camera','Back toward camera','Sideways tilt'])
            questions[3]=('feel','4. What needs changing?',['Gesture was missed','Triggered too easily','Needed too much movement','Nothing'])
        if self.rt.attempt.distance_trial:
            questions[0]=('intent','1. How far from the camera?',['5 feet','7–8 feet','10 feet','Other / not measured'])
            questions[2]=('gesture','3. How did tilt control behave?',['Fine adjustment worked','Did not enter tilt mode','Moved the wrong way','Needed arm movement','Too unstable'])
        for i,(key,prompt,choices) in enumerate(questions):
            yy=90+i*70
            self.label(prompt,((24,yy),(320,26)),14)
            field=A.NSPopUpButton.alloc().initWithFrame_pullsDown_(((345,yy-4),(245,32)),False)
            field.addItemsWithTitles_(choices)
            field.selectItemAtIndex_(-1)  # An unanswered question is never silently treated as feedback.
            view.addSubview_(field)
            self.feedback_controls[key]=field
        self.feedback_note=self.label('Answer all five. Your responses will tune the next attempt.',((24,452),(575,46)),13)
        self.feedback_note.setMaximumNumberOfLines_(2)
        self.button('Recalibrate + next attempt',((150,510),(320,36)),'saveFeedback:')
        self.content=saved

    def saveFeedback_(self, sender):
        if any(field.indexOfSelectedItem()<0 for field in self.feedback_controls.values()):
            self.feedback_note.setStringValue_('Choose an answer to each of the five questions first.')
            return
        answers={key:str(field.titleOfSelectedItem()) for key,field in self.feedback_controls.items()}
        with self.rt.lock:
            candidate,note=self.rt.attempt.feedback(answers,self.rt.core.profile)
            self.rt.previous_profile=self.rt.core.profile
            self.rt.core.profile=candidate
            self.rt.core.fx.cutoff=self.rt.core.fy.cutoff=candidate.cutoff
            profile_save(candidate)
        task={'pointer':'Aim at buttons','shortcuts':'Finger shortcuts'}.get(self.rt.attempt.task,answers['intent'])
        distance_trial=self.rt.attempt.distance_trial
        self.demo_(None)
        self.demo_task.selectItemAtIndex_(3 if task=='Finger shortcuts' else (2 if task=='Aim at buttons' else (1 if task=='Resize window' else 0)))
        if task=='Aim at buttons':
            if distance_trial:self.distanceDemo_(None)
            else:self.prepareAim()
        elif task=='Finger shortcuts':self.prepareShortcuts()
        self.demo_prompt.setStringValue_(note+' Press Start attempt to test the change.')

    def preview_(self, sender):
        self.rt.preview = not self.rt.preview
        self.image.setHidden_(not self.rt.preview)
        if not self.rt.preview:
            self.rt.jpeg = None
            self.image.setImage_(None)
            self.last_image = None

    def permissions_(self, sender):
        self.rt.pause(True)
        menu = A.NSMenu.alloc().init()
        for tag,name in enumerate(('Accessibility · desktop control','Camera · hand tracking','Microphone · voice')):
            self.item(menu,name,'permissionPage:',tag)
        menu.popUpMenuPositioningItem_atLocation_inView_(None,(0,34),sender)

    def permissionPage_(self, sender):
        page = ('Accessibility','Camera','Microphone')[sender.tag()]
        subprocess.Popen(['open','x-apple.systempreferences:com.apple.preference.security?Privacy_'+page])
        self.rt.message = 'Enable Control in '+page+', then return here'

    def help_(self, sender):
        path = Path(__file__).resolve().parent/'README.md'
        if not path.exists():
            path = Path(__file__).resolve().parent.parent/'README.md'
        subprocess.Popen(['open',str(path)])

    def quit_(self, sender):
        A.NSApp.terminate_(None)

    @objc.python_method
    def systemCommand(self, command):
        if self.rt.core.paused:
            return
        if command in ('back','forward'):
            code = 33 if command=='back' else 30
            for down in (True,False):
                event = Q.CGEventCreateKeyboardEvent(None, code, down)
                Q.CGEventSetFlags(event,Q.kCGEventFlagMaskCommand)
                self.rt.output.post(event)
        elif command in ('volume_up','volume_down'):
            script = 'set volume output volume ((output volume of (get volume settings)) '+('+' if command=='volume_up' else '-')+' 8)'
            subprocess.Popen(['osascript','-e',script], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif command == 'media':
            for down in (True,False):
                e = A.NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
                    14,(0,0),0xa00 if down else 0xb00,0,0,None,8,(16<<16)|((0xa if down else 0xb)<<8),-1)
                self.rt.output.post(e.CGEvent())

    def tick_(self, timer):
        try:
            if self.pending_desktop and time.monotonic()>=self.pending_desktop[1]:
                direction=self.pending_desktop[0]
                self.pending_desktop=None
                with self.rt.lock:
                    self.rt.switch_desktop(direction)
            if PERMISSIONS:
                shortcut = PERMISSIONS.control_poll_hotkey()
                if shortcut in (1,2,3,4):
                    self.rt.ui_actions.put(('mode',shortcut-1))
                elif shortcut == 5:
                    self.rt.ui_actions.put(('listen',None))
            if PERMISSIONS and self.camera_pending:
                status = PERMISSIONS.control_camera_status()
                if status != 0:
                    self.camera_pending = False
                    self.camera_(None)
            if PERMISSIONS and self.wake_pending:
                status=PERMISSIONS.control_microphone_status()
                if status!=0:self.wake_pending=False;self.wake_(None)
            if PERMISSIONS and self.voice_pending:
                status = PERMISSIONS.control_microphone_status()
                if status != 0:
                    self.voice_pending = False
                    self.voice_(None)
            while True:
                try:
                    kind,value = self.rt.ui_actions.get_nowait()
                except queue.Empty:
                    break
                if kind=='pause':
                    self.auto_fluid=False;self.auto_swipes=False
                    self.rt.pause(True)
                elif kind=='takeover':
                    self.rt.takeover(value)
                elif kind=='listen': self.voice_(None)
                elif kind=='mode': self.rt.set_mode(('pointer','move','resize','scroll')[value])
                elif kind=='voice': self.rt.command(value)
                elif kind=='system': self.systemCommand(value)
                elif kind=='quit': self.quit_(None)
                elif kind=='practice': self.practiceEvent(value)
                elif kind=='practice_shortcut':self.practiceShortcut(value)
                elif kind=='position_feedback':self.rt.message=value;self.rt.core.status=value
            if self.demo_active:
                elapsed=time.monotonic()-self.rt.attempt.started
                if not self.demo.isVisible():
                    self.endAttempt('window_closed')
                elif elapsed>=(65 if self.rt.attempt.task=='shortcuts' else (40 if self.rt.attempt.task=='pointer' else 20)):
                    self.endAttempt('completed')
                elif elapsed>=3:
                    if not self.demo_started_input:
                        self.rt.pause(False)
                        self.demo_started_input=True
                    if self.rt.attempt.task=='shortcuts':
                        i=min(4,self.rt.attempt.hits)
                        self.demo_prompt.setStringValue_(f'{i+1}/5 · '+self.shortcut_steps[i][1])
                        names=' + '.join(name for i,name in enumerate(('index','middle','ring','pinky')) if self.rt.metrics.get('finger_mask',0)&(1<<i)) or 'no clear fingers'
                        self.demo_signal.setStringValue_(f"{self.rt.attempt.hits}/5 gestures · {self.rt.attempt.misses} mismatches · {65-elapsed:.0f}s\nSeeing: {names}. {self.rt.shortcuts.hint()}")
                    elif self.rt.attempt.task=='pointer':
                        if not hasattr(self,'aim_cursor_started') or self.aim_cursor_started!=self.rt.attempt.id:
                            p=self.demo.convertPointToScreen_((310,240))
                            with self.rt.lock:
                                self.rt.core.x,self.rt.core.y=p.x,Q.CGDisplayBounds(Q.CGMainDisplayID()).size.height-p.y
                            self.aim_cursor_started=self.rt.attempt.id
                        self.demo_prompt.setStringValue_(self.aim_angles[min(4,self.rt.attempt.hits)]+'. Point, pinch and release.')
                        self.demo_signal.setStringValue_(f"{self.rt.attempt.hits}/5 stars · {self.rt.attempt.misses} misses · {40-elapsed:.0f}s · {self.rt.metrics.get('figure','neutral').replace('_',' ')}")
                    else:
                        action='move it to the RIGHT' if self.rt.attempt.task=='move' else 'make it WIDER'
                        self.demo_prompt.setStringValue_('Grab however feels natural and '+action+'. Then release.')
                        self.demo_signal.setStringValue_(f"{20-elapsed:.0f}s left · {self.rt.core.status} · {self.rt.metrics['palm_px']}px palm · {self.rt.attempt.best_delta:.0f}/120 points")
            with self.rt.lock:
                if self.auto_fluid and not self.rt.capture_stop.is_set() and self.rt.metrics['fps']>0:
                    self.auto_fluid=False
                    self.rt.pause(False)
                if self.auto_swipes and not self.rt.capture_stop.is_set() and self.rt.metrics['fps']>0:
                    self.auto_swipes=False
                    self.rt.enable_swipes(True)
                active = not self.rt.core.paused
                self.bar.button().setTitle_('Control ●' if active else ('Control ↔' if self.rt.desktop_swipes else 'Control ◌'))
                self.start_button.setTitle_('Pause control' if active else 'Start control')
                self.fluid_button.setTitle_('Fluid ●' if active and self.rt.core.profile.motion_scheme=='fluid' else 'Fluid pointer')
                self.tilt_button.setTitle_('Tilt ON' if self.rt.core.profile.tilt_precision else 'Tilt OFF')
                fluid=self.rt.core.profile.motion_scheme=='fluid'
                self.help.setStringValue_(('Pinch: click / hold to drag. Two fingers: flick to scroll. Three: swipe desktops. Esc: pause.' if self.rt.core.profile.shortcuts else 'Move hand to point. Pinch: click / hold to drag. Esc: pause.') if fluid else ('2-finger tap: double click. 2-finger flick: scroll. 3 fingers: desktops.' if self.rt.core.profile.shortcuts else 'One finger: quick. Open hand: precise. Pinch: click. Fist: rest. Esc: pause.'))
                self.cam_button.setTitle_('Start camera' if self.rt.capture_stop.is_set() else 'Stop camera')
                listening = self.rt.voice_until > time.monotonic()
                self.voice_button.setTitle_('Stop listening' if listening else 'Voice · 12 sec')
                self.voice_label.setStringValue_(('MIC ON · ' if self.rt.voice_wake else '')+self.rt.voice_message)
                mode = self.rt.core.mode
                self.modes.setSelectedSegment_(('pointer','move','resize','scroll').index(mode))
                self.gesture.selectItemAtIndex_({'pinch':0,'side':1,'grab':2}[self.rt.core.profile.gesture])
                status = self.rt.message if not active or self.rt.calibration else self.rt.core.status
                if self.rt.dry_run:
                    status = 'PREVIEW ONLY · ' + status
                self.status.setStringValue_(status)
                m = dict(self.rt.metrics)
                self.halo_state=tracking_state(m,time.monotonic(),camera_on=not self.rt.capture_stop.is_set(),
                    paused=self.rt.core.paused,ready=self.rt.core.rearmed,handoff=bool(self.rt.takeover_until),
                    precision=self.rt.core.tilt.active,access=bool(trusted()) or self.rt.practice,
                    resting=self.rt.core.status.startswith('Clutched'),tilt_enabled=self.rt.core.profile.tilt_precision,
                    free_pointer=fluid and self.rt.core.mode=='pointer' and not self.rt.core.profile.tilt_precision)
                self.halo.update(self.halo_state,not self.rt.capture_stop.is_set())
                if hasattr(self,'room_window') and self.room_window.isVisible():
                    self.room_view.snapshot=self.rt.room.snapshot();self.room_view.setNeedsDisplay_(True)
                names=' + '.join(name for i,name in enumerate(('index','middle','ring','pinky')) if m.get('finger_mask',0)&(1<<i)) or 'no clear fingers'
                hint='Paused · Start control' if self.rt.core.paused else ('Mouse in use · resuming shortly' if self.rt.takeover_until else self.rt.shortcuts.hint())
                if active and fluid and self.rt.core.profile.shortcuts and not self.rt.takeover_until and not self.rt.shortcuts.group:
                    hint='Two fingers: flick to scroll · three: swipe desktops'
                if not self.rt.core.paused and not self.rt.takeover_until and self.rt.last_shortcut and time.time()-self.rt.last_shortcut['time']<1.3:
                    action=self.rt.last_shortcut
                    name=action['kind'].replace('_',' ')
                    if action['kind']=='desktop':name+=' '+action['direction']
                    hint='Recognized: '+name
                if active and not self.rt.takeover_until and not self.rt.core.profile.shortcuts:
                    hint=self.rt.core.tilt.reason if self.rt.core.profile.tilt_precision else 'Move hand to point · pinch to click'
                self.finger_label.setStringValue_('Seeing: '+names+' · '+hint)
                self.finger_label.setHidden_(self.rt.capture_stop.is_set())
                access = 'Accessibility ready' if trusted() else 'Accessibility required for desktop control'
                swipe=(' · '+self.rt.core.figure.replace('_',' ') if active else '')+(' · Swipes ON' if self.rt.desktop_swipes else '')+(' · '+self.rt.room.active if self.rt.room.active else '')
                self.metrics.setStringValue_(f"{m['fps']} fps · palm {m['palm_px']}px · {m.get('geometry','none')} 3D · {m['age_ms']}ms · {access}{swipe}")
                if time.monotonic()>=self.next_status:
                    self.next_status=time.monotonic()+.5
                    report=dict(time=time.time(),version=VERSION,camera_on=not self.rt.capture_stop.is_set(),
                                pointer_paused=self.rt.core.paused,desktop_swipes=self.rt.desktop_swipes,
                                state=self.rt.core.state,status=self.rt.core.status,accessibility=bool(trusted()),
                                metrics=m,last_desktop=self.rt.last_desktop,post_access=bool(Q.CGPreflightPostEventAccess()),
                                motion_scheme=self.rt.core.profile.motion_scheme,clicks=dict(self.rt.output.click_stats))
                    report.update(finger_shortcuts=self.rt.core.profile.shortcuts,last_shortcut=self.rt.last_shortcut,
                                  mouse_handoff=bool(self.rt.takeover_until),last_takeover_source=self.rt.last_takeover_source,
                                  shortcut_hint=self.rt.shortcuts.hint(),shortcut_progress=self.rt.shortcuts.progress,
                                  shortcut_diagnostics=self.rt.shortcut_diagnostics,
                                  room=self.rt.room.snapshot(),click_audio=self.click_audio.enabled,voice_wake=self.rt.voice_wake,
                                  halo=self.halo_state,tilt_precision=self.rt.core.tilt.active,
                                  tilt_enabled=self.rt.core.profile.tilt_precision,tilt_reason=self.rt.core.tilt.reason,
                                  tilt_progress=self.rt.core.tilt.progress,output_enabled=self.rt.output.enabled,
                                  events=dict(self.rt.events_count))
                    temp=DATA/'status.tmp'
                    temp.write_text(json.dumps(report))
                    temp.replace(DATA/'status.json')
                self.placeholder.setHidden_(bool(self.rt.jpeg) and self.rt.preview)
                if self.rt.jpeg and self.rt.preview and self.last_image is not self.rt.jpeg:
                    self.last_image = self.rt.jpeg
                    data = F.NSData.dataWithBytes_length_(self.last_image,len(self.last_image))
                    self.image.setImage_(A.NSImage.alloc().initWithData_(data))
                if self.rt.capture_stop.is_set():
                    self.image.setImage_(None)
                    self.last_image = None
            if hasattr(self,'smoke_end') and time.monotonic() > self.smoke_end:
                logging.info('Smoke completed: %s', self.rt.metrics)
                self.quit_(None)
        except Exception:
            logging.exception('UI update failed')
            self.rt.pause(True)

    def applicationWillTerminate_(self, notification):
        self.timer.invalidate()
        self.halo.close()
        for monitor in self.monitors:
            A.NSEvent.removeMonitor_(monitor)
        self.rt.close()

    def applicationShouldTerminateAfterLastWindowClosed_(self, app):
        return False

    def applicationShouldHandleReopen_hasVisibleWindows_(self, app, visible):
        self.show_(None)
        return True


def main():
    app = A.NSApplication.sharedApplication()
    app.setActivationPolicy_(A.NSApplicationActivationPolicyRegular)
    delegate = AppDelegate.alloc().init()
    app.setDelegate_(delegate)
    app.run()


if __name__=='__main__':
    main()
