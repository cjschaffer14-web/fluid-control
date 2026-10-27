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
