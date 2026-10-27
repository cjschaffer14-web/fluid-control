"""Local camera-position anchors, not a metric room scan or biometric identity."""
from dataclasses import asdict
from collections import deque
import json
import math


class WaveRecall:
    """Three clear horizontal direction changes distinguish a wave from a swipe."""
    def __init__(self):
        self.samples=deque();self.last_fire=-100.;self.last_hand=None

    def clear(self):
        self.samples.clear();self.last_hand=None

    def feed(self,o):
        if o is None or not o.usable() or o.finger_mask.bit_count()<3:
            self.clear();return False
        if self.samples and (o.t<=self.samples[-1].t or o.t-self.samples[-1].t>.15 or o.hand!=self.last_hand):
            self.clear()
        self.last_hand=o.hand
        self.samples.append(o)
        while self.samples and o.t-self.samples[0].t>1.6:self.samples.popleft()
        if o.t-self.last_fire<3 or len(self.samples)<9:return False
        points=list(self.samples)
        travel=max(.025,min(.07,o.palm_fraction*.65))
        pivot=points[0].x;direction=0;turns=0
        for p in points[1:]:
            delta=p.x-pivot
            if not direction:
                if abs(delta)>=travel:direction=1 if delta>0 else -1;pivot=p.x
            elif direction*(p.x-pivot)>=0:pivot=p.x
            elif abs(delta)>=travel:
                turns+=1;direction=-direction;pivot=p.x
        if turns>=3 and max(p.y for p in points)-min(p.y for p in points)<.18:
            self.last_fire=o.t;self.clear();return True
        return False


class RoomPositions:
    def __init__(self,path):
        self.path=path;self.anchors=[];self.active=None;self.collecting=None;self.samples=[]
        try:
            data=json.loads(path.read_text())
            self.anchors=[a for a in data['anchors'] if isinstance(a,dict) and isinstance(a.get('profile'),dict)
                          and all(math.isfinite(float(a[k])) for k in ('x','y','size')) and float(a['size'])>0][:8]
        except (OSError,ValueError,TypeError,KeyError):pass

    def begin(self,now):
        self.collecting=now;self.samples=[]

    def observe(self,o,profile):
        if self.collecting is None:return None
        if o is None or not o.usable() or o.finger_mask.bit_count()<3:
            self.samples=[];return None
        if self.samples and (o.hand!=self.samples[-1].hand or o.t-self.samples[-1].t>.15):self.samples=[]
        self.samples.append(o)
        self.samples=self.samples[-40:]
        if len(self.samples)<18 or o.t-self.samples[0].t<.7:return None
        import statistics as stats
        if max(p.x for p in self.samples)-min(p.x for p in self.samples)>.06 or max(p.y for p in self.samples)-min(p.y for p in self.samples)>.06:
            self.samples=self.samples[-3:];return None
        x=stats.median(p.x for p in self.samples);y=stats.median(p.y for p in self.samples)
        size=stats.median(p.palm_fraction for p in self.samples)
        match=self.nearest(x,y,size,o.hand)
        if match is None:
            if len(self.anchors)>=8:self.collecting=None;return 'Eight positions saved · remove room-positions.json to start again'
            match=dict(name='Position '+str(len(self.anchors)+1));self.anchors.append(match)
        match.update(x=x,y=y,size=size,hand=o.hand,profile=asdict(profile))
        self.active=match['name'];self.collecting=None
        self.path.parent.mkdir(parents=True,exist_ok=True)
        tmp=self.path.with_suffix('.tmp');tmp.write_text(json.dumps(dict(anchors=self.anchors),indent=2));tmp.replace(self.path)
        return self.active+' saved · wave back and forth to recall'

    def nearest(self,x,y,size,hand):
        def distance(a):
            if a.get('hand')!=hand:return 100.
            return math.hypot((x-a['x'])/.22,(y-a['y'])/.25)+abs(math.log(max(size,1e-6)/a['size']))/.45
        ranked=sorted(((distance(a),a) for a in self.anchors),key=lambda p:p[0])
        if not ranked or ranked[0][0]>1.3:return None
        if len(ranked)>1 and ranked[1][0]-ranked[0][0]<.25:return None
        return ranked[0][1]

    def recall(self,o):
        if o is None or not o.usable():return None
        anchor=self.nearest(o.x,o.y,o.palm_fraction,o.hand)
        if anchor:self.active=anchor['name']
        return anchor

    def snapshot(self):
        return dict(active=self.active,collecting=self.collecting is not None,
                    anchors=[{k:a[k] for k in ('name','x','y','size','hand')} for a in self.anchors],
                    kind='camera positions · relative distance, not room geometry')
