"""Non-interactive tracking halo following the current front window, including fullscreen."""
import AppKit as A
import Foundation as F
import Quartz as Q

COLORS={'white':(1,1,1),'green':(.2,1,.5),'red':(1,.2,.22),'amber':(1,.7,.15),'gray':(.5,.5,.5)}


class HaloPanel(A.NSPanel):
    def canBecomeKeyWindow(self):return False
    def canBecomeMainWindow(self):return False


class HaloView(A.NSView):
    state={'color':'white','label':'Hand tracking'}

    def drawRect_(self,rect):
        rgb=COLORS[self.state['color']]
        bounds=self.bounds();w,h=bounds.size.width,bounds.size.height
        for width,alpha in ((18,.12),(11,.24),(5,.95)):
            A.NSColor.colorWithCalibratedRed_green_blue_alpha_(*rgb,alpha).setStroke()
            path=A.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(A.NSInsetRect(bounds,10,10),18,18)
            path.setLineWidth_(width);path.stroke()
        label=self.state['label']
        attrs={A.NSFontAttributeName:A.NSFont.boldSystemFontOfSize_(19),
               A.NSForegroundColorAttributeName:A.NSColor.colorWithCalibratedRed_green_blue_alpha_(*rgb,1)}
        text=F.NSString.stringWithString_(label);size=text.sizeWithAttributes_(attrs)
        x=max(12,(w-size.width-32)/2);y=max(12,h-55)
        A.NSColor.colorWithWhite_alpha_(.04,.88).setFill()
        A.NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(((x,y),(size.width+32,34)),10,10).fill()
        text.drawAtPoint_withAttributes_((x+16,y+5),attrs)


class TrackingHalo:
    def __init__(self):
        self.enabled=True
        self.panel=HaloPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            ((0,0),(600,400)),A.NSWindowStyleMaskBorderless|A.NSWindowStyleMaskNonactivatingPanel,
            A.NSBackingStoreBuffered,False)
        self.panel.setTitle_('Control tracking halo')
        self.panel.setOpaque_(False);self.panel.setBackgroundColor_(A.NSColor.clearColor())
        self.panel.setHasShadow_(False);self.panel.setIgnoresMouseEvents_(True)
        self.panel.setHidesOnDeactivate_(False);self.panel.setExcludedFromWindowsMenu_(True)
        self.panel.setLevel_(A.NSStatusWindowLevel)
        self.panel.setCollectionBehavior_(A.NSWindowCollectionBehaviorCanJoinAllSpaces|A.NSWindowCollectionBehaviorFullScreenAuxiliary|A.NSWindowCollectionBehaviorIgnoresCycle)
        self.view=HaloView.alloc().initWithFrame_(((0,0),(600,400)))
        self.panel.setContentView_(self.view)

    def update(self,state,camera_on):
        if not self.enabled or not camera_on:
            self.panel.orderOut_(None);return
        front=A.NSWorkspace.sharedWorkspace().frontmostApplication()
        pid=front.processIdentifier() if front else None
        windows=Q.CGWindowListCopyWindowInfo(Q.kCGWindowListOptionOnScreenOnly|Q.kCGWindowListExcludeDesktopElements,Q.kCGNullWindowID) or []
        bounds=None
        for item in windows:
            b=item.get(Q.kCGWindowBounds,{})
            if item.get(Q.kCGWindowOwnerPID)==pid and item.get(Q.kCGWindowLayer)==0 and b.get('Width',0)>180 and b.get('Height',0)>100:
                bounds=b;break
        top=A.NSScreen.screens()[0].frame().size.height
        if bounds:
            frame=((bounds['X'],top-bounds['Y']-bounds['Height']),(bounds['Width'],bounds['Height']))
        else:
            frame=A.NSScreen.mainScreen().frame()
        self.panel.setFrame_display_(frame,False)
        self.view.state=state;self.view.setNeedsDisplay_(True)
        self.panel.orderFrontRegardless()

    def close(self):self.panel.orderOut_(None)
