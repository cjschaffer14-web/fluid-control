"""Native-pixel search crops. Results are always restored to full-camera coordinates."""
from types import SimpleNamespace


def hand_region(result, shape):
    if not result.hand_landmarks:
        return None
    h,w=shape[:2]
    lm=result.hand_landmarks[0]
    xs,ys=[p.x*w for p in lm],[p.y*h for p in lm]
    side=min(h,w,max(320,(max(xs)-min(xs))*3,(max(ys)-min(ys))*3))
    # Large hands already occupy enough of the full detector image.
    if side>=min(h,w)*.85:
        return None
    x=max(0,min(w-side,(min(xs)+max(xs)-side)/2))
    y=max(0,min(h-side,(min(ys)+max(ys)-side)/2))
    return (int(x),int(y),int(side),int(side))


def search_region(shape, step):
    h,w=shape[:2]
    side=int(min(h,w)*.70)
    cx=(.25,.5,.75)[step%3]*w
    return (int(max(0,min(w-side,cx-side/2))),int((h-side)/2),side,side)


def restore(result, region, shape):
    x,y,cw,ch=region; h,w=shape[:2]
    hands=[[SimpleNamespace(x=(x+p.x*cw)/w,y=(y+p.y*ch)/h,z=p.z*cw/w) for p in hand]
           for hand in result.hand_landmarks]
    return SimpleNamespace(hand_landmarks=hands,handedness=result.handedness,
                           hand_world_landmarks=getattr(result,'hand_world_landmarks',[]))
