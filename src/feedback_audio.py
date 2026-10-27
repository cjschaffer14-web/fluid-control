"""Short generated acoustic tap; mixes with existing audio without changing its volume."""
import io
import math
import struct
import wave


def tap_wav():
    rate=44100;frames=[];state=7
    for i in range(int(rate*.032)):
        t=i/rate
        state=(1664525*state+1013904223)&0xffffffff
        noise=(state/0xffffffff)*2-1
        attack=min(1,t/.0015)
        value=attack*(.55*math.sin(2*math.pi*720*t)*math.exp(-t/0.006)
                      +.20*math.sin(2*math.pi*1450*t)*math.exp(-t/.004)
                      +.25*noise*math.exp(-t/.0025))
        frames.append(struct.pack('<h',int(max(-1,min(1,value))*.4*32767)))
    out=io.BytesIO()
    with wave.open(out,'wb') as audio:
        audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(rate);audio.writeframes(b''.join(frames))
    return out.getvalue()


class ClickAudio:
    def __init__(self):
        import AppKit as A
        import Foundation as F
        payload=tap_wav()
        data=F.NSData.dataWithBytes_length_(payload,len(payload))
        self.sounds=[A.NSSound.alloc().initWithData_(data) for _ in range(3)]
        self.enabled=True;self.index=0;self.failed=False
        for sound in self.sounds:
            if sound is None:
                self.failed=True;self.enabled=False
            else:sound.setVolume_(.55)

    def play(self):
        if not self.enabled or self.failed:return
        try:
            sound=self.sounds[self.index];self.index=(self.index+1)%len(self.sounds)
            sound.stop();sound.play()
        except Exception:
            self.failed=True  # Feedback must never interrupt input delivery.
