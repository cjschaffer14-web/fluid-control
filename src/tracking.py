"""Native-pixel search crops. Results are always restored to full-camera coordinates."""
from types import SimpleNamespace


def hand_region(result, shape):
    if not result.hand_landmarks:
        return None
    h,w=shape[:2]
    lm=result.hand_landmarks[0]
    xs,ys=[p.x*w for p in lm],[p.y*h for p in lm]
    side=min(h,w,max(160,(max(xs)-min(xs))*2.2,(max(ys)-min(ys))*2.2))
    # Large hands already occupy enough of the full detector image.
    if side>=min(h,w)*.85:
        return None
    x=max(0,min(w-side,(min(xs)+max(xs)-side)/2))
    y=max(0,min(h-side,(min(ys)+max(ys)-side)/2))
    return (int(x),int(y),int(side),int(side))


def search_region(shape, step):
    h,w=shape[:2]
    # Alternate a broad central pass with six smaller tiles, including a resting hand low in frame.
    if step%7==6:
        side=int(min(h,w)*.85);cx,cy=w/2,h/2
    else:
        side=int(min(h,w)*.48);cx=(.2,.5,.8)[step%3]*w
        cy=(.28,.73)[(step//3)%2]*h
    return (int(max(0,min(w-side,cx-side/2))),int(max(0,min(h-side,cy-side/2))),side,side)


def restore(result, region, shape):
    x,y,cw,ch=region; h,w=shape[:2]
    hands=[[SimpleNamespace(x=(x+p.x*cw)/w,y=(y+p.y*ch)/h,z=p.z*cw/w) for p in hand]
           for hand in result.hand_landmarks]
    return SimpleNamespace(hand_landmarks=hands,handedness=result.handedness,
                           hand_world_landmarks=getattr(result,'hand_world_landmarks',[]))
