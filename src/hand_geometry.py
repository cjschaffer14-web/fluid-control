"""Hand-shape measurements in 3D, independent of rotation in the camera image."""
import numpy as np


def hand_points(result, width, height):
    world=getattr(result,'hand_world_landmarks',None)
    if world and len(world[0])==21:
        points=np.asarray([(p.x,p.y,p.z) for p in world[0]],dtype=float)
        if np.isfinite(points).all() and np.linalg.norm(points[0]-points[9])>1e-5:
            return points,'world'
    lm=result.hand_landmarks[0]
    points=np.asarray([(p.x*width,p.y*height,getattr(p,'z',0)*width) for p in lm],dtype=float)
    return points,'depth'


def extended(points, mcp, pip, dip, tip):
    def cosine(a,b,c):
        u,v=points[a]-points[b],points[c]-points[b]
        return float(np.dot(u,v)/max(1e-10,np.linalg.norm(u)*np.linalg.norm(v)))
    chain=sum(np.linalg.norm(points[a]-points[b]) for a,b in ((mcp,pip),(pip,dip),(dip,tip)))
    straight=np.linalg.norm(points[tip]-points[mcp])/max(1e-8,chain)
    return bool(cosine(mcp,pip,dip)<-.65 and cosine(pip,dip,tip)<-.55 and straight>.75)


def extensions(points):
    return [extended(points,*finger) for finger in ((5,6,7,8),(9,10,11,12),(13,14,15,16),(17,18,19,20))]


# All 21 joints, including the thumb, are retained for the live hand map.
BONES = ((0,1),(1,2),(2,3),(3,4),(0,5),(5,6),(6,7),(7,8),
         (5,9),(9,10),(10,11),(11,12),(9,13),(13,14),(14,15),(15,16),
         (13,17),(17,18),(18,19),(19,20),(17,0))
FINGERS = ((1,2,3,4),(5,6,7,8),(9,10,11,12),(13,14,15,16),(17,18,19,20))


def extension_scores(points):
    """Continuous joint straightness; thresholds can have temporal hysteresis."""
    scores=[]
    for a,b,c,d in FINGERS:
        u,v=points[b]-points[a],points[c]-points[b]
        w=points[d]-points[c]
        def alignment(x,y):
            return float(np.dot(x,y)/max(1e-10,np.linalg.norm(x)*np.linalg.norm(y)))
        chain=np.linalg.norm(u)+np.linalg.norm(v)+np.linalg.norm(w)
        reach=np.linalg.norm(points[d]-points[a])/max(chain,1e-8)
        # Modestly bent fingers remain recognizable; a folded PIP does not.
        score=min((alignment(u,v)+.15)/.95,(alignment(v,w)+.3)/1.0,(reach-.42)/.48)
        scores.append(float(np.clip(score,0,1)))
    return scores


def map_hand(points, source):
    center=np.mean(points[[0,5,9,13,17]],axis=0)
    scale=max(np.linalg.norm(points[0]-points[9]),np.linalg.norm(points[5]-points[17]),1e-8)
    across=points[5]-points[17]
    across=across/max(np.linalg.norm(across),1e-8)
    along=points[9]-points[0]
    normal=np.cross(across,along)
    normal=normal/max(np.linalg.norm(normal),1e-8)
    along=np.cross(normal,across)
    basis=np.stack([across,along,normal],axis=1)
    return dict(source=source,basis=basis.reshape(-1).tolist(),joints=((points-center)/scale).round(4).tolist(),
                local_joints=(((points-center)@basis)/scale).round(4).tolist(),
                palm_normal=normal.round(4).tolist(),
                curls=[round(1-s,3) for s in extension_scores(points)],estimated_depth=True)


class HandPoseFilter:
    """Hysteresis for finger shape only; pointer position is never delayed here."""
    def __init__(self):
        self.clear()

    def clear(self):
        self.last=None; self.hand=None; self.scores=None; self.mask=0

    def feed(self, observation):
        from dataclasses import replace
        o=observation
        if o is None:
            self.clear();return None
        if not o.extension_scores:
            return o
        scores=np.asarray(o.extension_scores,dtype=float)
        fresh=self.last is None or o.t-self.last>.15 or o.t<=self.last or o.hand!=self.hand
        if fresh:
            self.scores=scores.copy();self.mask=o.finger_mask
        else:
            self.scores=.65*scores+.35*self.scores
            for i,s in enumerate(self.scores):
                if s>.60:self.mask|=1<<i
                elif s<.36:self.mask&=~(1<<i)
        self.last,self.hand=o.t,o.hand
        ext=[bool(self.mask&(1<<i)) for i in range(4)]
        figure='one_finger' if ext[0] and not any(ext[1:]) else ('open_hand' if sum(ext)>=3 else 'neutral')
        return replace(o,finger_mask=self.mask,figure=figure,open_palm=all(ext) and o.contact>.55)
