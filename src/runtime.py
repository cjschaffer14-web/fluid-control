"""Latest-frame camera pipeline and local speech. UI and HID never run on capture thread."""
from dataclasses import asdict, replace
from pathlib import Path
import json
import logging
import math
import os
import queue
import threading
import time
import cv2
import numpy as np
from control_core import Controller, Profile, Calibration, Observation, COMMANDS, parse_command
from native import Output, trusted
from attempts import Attempt
from swipes import DesktopSwipes
from tracking import hand_region, search_region, restore
from hand_geometry import hand_points, extensions, extension_scores, map_hand, HandPoseFilter, BONES
from positions import RoomPositions, WaveRecall
from shortcuts import FingerShortcuts

LOG = logging.getLogger('control')
DATA = Path(os.environ.get('CONTROL_DATA_DIR', str(Path.home() / 'Library/Application Support/Control')))
HERE = Path(__file__).resolve().parent
MODEL = Path(os.environ.get('CONTROL_HAND_MODEL', str(HERE/'hand_landmarker.task')))
if not MODEL.exists() and 'CONTROL_HAND_MODEL' not in os.environ:
    MODEL = HERE.parent/'models/hand_landmarker.task'
    if not MODEL.exists():
        MODEL = HERE.parent/'Control.app/Contents/Resources/hand_landmarker.task'


def profile_load():
    try:
        return Profile.from_dict(json.loads((DATA / 'profile.json').read_text()))
    except (OSError, ValueError, TypeError):
        return Profile()


def profile_save(profile):
    DATA.mkdir(parents=True, exist_ok=True)
    path = DATA / 'profile.json'
    temp = DATA / 'profile.tmp'
    temp.write_text(json.dumps(asdict(profile), indent=2))
    temp.replace(path)


def segment_distance(point, a, b):
    d = b-a
    t = max(0, min(1, float(np.dot(point-a, d) / max(1e-8, np.dot(d, d)))))
    return float(np.linalg.norm(point-a-t*d))


def extract(result, shape, t, style):
    if not result.hand_landmarks:
        return None
    lm = result.hand_landmarks[0]
    h, w = shape[:2]
    p = np.array([(v.x*w, v.y*h) for v in lm], dtype=float)
    # Normalize distances by visible palm anatomy, not an invented centimetre estimate.
    scale = max(np.linalg.norm(p[0]-p[9]), np.linalg.norm(p[5]-p[17]), 1)
    if len(lm)!=21 or not np.isfinite(p).all():return None
    geometry,geometry_source=hand_points(result,w,h)
    mapped=map_hand(geometry,geometry_source)
    anatomy=max(np.linalg.norm(geometry[0]-geometry[9]),np.linalg.norm(geometry[5]-geometry[17]),1e-6)
    pinch = np.linalg.norm(geometry[4]-geometry[8]) / anatomy
    side = min(segment_distance(geometry[4], geometry[5], geometry[6]), segment_distance(geometry[4], geometry[6], geometry[7])) / anatomy
    contact = float(side if style == 'side' else pinch)
    scores=extension_scores(geometry)
    ext = [v>.60 for v in scores[1:]]
    curled = not any(ext)
    pose = 'point'
    if curled:
        thumb_out = np.linalg.norm(geometry[4]-geometry[5]) > np.linalg.norm(geometry[2]-geometry[5])*1.25
        direction = (p[4,1]-p[2,1])/scale
        if thumb_out and abs(direction) > .35:
            pose = 'scroll_up' if direction < 0 else 'scroll_down'
        elif contact > .46:
            pose = 'fist'
    anchor = .2*p[0] + .5*p[5] + .3*p[9]
    if style=='grab':
        contact=.08 if curled and pose not in ('scroll_up','scroll_down') else .85
        pose='point'
    hand = result.handedness[0][0].category_name if result.handedness else 'unknown'
    figure='one_finger' if ext[0] and not any(ext[1:]) else ('open_hand' if sum(ext)>=3 else 'neutral')
    tips=np.mean(p[[8,12]],axis=0)
    return Observation(t, float(1-anchor[0]/w), float(anchor[1]/h), contact, float(scale), pose, hand,
                       float(pinch),float(side),bool(curled),all(ext) and pinch>.55,float(scale/w),figure,geometry_source,
                       sum(1<<i for i,v in enumerate(ext) if v),
                       gesture_x=float(1-tips[0]/w),gesture_y=float(tips[1]/h),
                       palm_height_fraction=float(scale/h),extension_scores=tuple(scores[1:]),
                       hand_map=mapped,palm_basis=tuple(mapped['basis']),
                       in_frame=all(.005<v.x<.995 and .005<v.y<.995 for v in lm),
                       palm_in_frame=all(.005<lm[i].x<.995 and .005<lm[i].y<.995 for i in (0,5,9,17)),
                       pinch_visible=all(.005<lm[i].x<.995 and .005<lm[i].y<.995 for i in (4,8)),
                       visible_fingers=sum(1<<i for i,joints in enumerate(((5,6,7,8),(9,10,11,12),(13,14,15,16),(17,18,19,20)))
                                           if all(.005<lm[j].x<.995 and .005<lm[j].y<.995 for j in joints)))


class Runtime:
    def __init__(self, bounds, dry_run=False):
        self.lock = threading.RLock()
        self.core = Controller(bounds, profile_load())
        self.core.fx.cutoff = self.core.fy.cutoff = self.core.profile.cutoff
        self.output = Output(bounds)
        self.dry_run = dry_run
        self.stop = threading.Event()
        self.capture_stop = threading.Event()
        self.capture_stop.set()
        self.camera_index = 0
        self.room_camera = 0
        self.frame = None
        self.frame_id = 0
        self.frame_time = 0
        self.jpeg = None
        self.preview = True
        self.metrics = {'fps': 0, 'palm_px': 0, 'age_ms': 0, 'tracked': False, 'inference_ms': 0}
        self.message = 'Start the camera to check your setup'
        self.last_error = ''
        self.calibration = None
        self.cal_started = None
        self.cal_resume = False
        self.previous_profile = None
        self.voice_until = 0
        self.voice_wake = False
        self.voice_message = 'Voice off'
        self.voice_thread = None
        self.voice_hold = False
        self.ui_actions = queue.SimpleQueue()
        self.threads = []
        self.events_count = {}
        self.attempt = None
        self.practice = False
        self.desktop_swipes = False
        self.swipes = DesktopSwipes()
        self.shortcuts = FingerShortcuts()
        self.shortcut_reserved=False
        self.pose_filter=HandPoseFilter()
        self.room=RoomPositions(DATA/'room-positions.json')
        self.wave=WaveRecall()
        self.latest_obs=None
        self.scroll_remaining=0.0
        self.scroll_time=time.monotonic()
        self.last_shortcut=None
        self.shortcut_diagnostics={}
        self.last_desktop = None
        self.takeover_until=0.0
        self.last_takeover_source=None
        t = threading.Thread(target=self._pump, name='control-output', daemon=True)
        t.start()
        self.threads.append(t)

    def _dispatch(self):
        for e in self.core.drain():
            self.events_count[e['kind']] = self.events_count.get(e['kind'], 0) + 1
            if self.practice:
                if self.attempt:
                    self.attempt.event(e)
                self.ui_actions.put(('practice',e))
            elif not self.dry_run:
                self.output.handle(e)
                if e['kind']=='up':
                    # Window manipulation uses a virtual hand delta; the actual cursor stays put.
                    self.core.x, self.core.y = self.output.position()

    def _fail(self, text):
        self.desktop_swipes=False
        self.last_error = str(text)
        self.voice_hold = False
        self.core.pause(True)
        self._dispatch()
        try:
            self.output.release()
        except Exception:
            LOG.exception('Release failed')
        self.output.enabled = False
        LOG.warning('%s', text)

    def pause(self, value=True):
        with self.lock:
            self.takeover_until=0
            if not value and self.core.profile.gesture=='side' and not self.core.profile.calibrated:
                self.message = 'Calibrate the side tap before starting control'
                return False
            if not value and not self.practice and not self.dry_run and not trusted():
                self.message = 'Enable Accessibility for Control (or Python) in System Settings, then try Start.'
                return False
            if not value and self.capture_stop.is_set():
                self.message = 'Start the camera first'
                return False
            if self.calibration:
                self.calibration = None
                self.message = 'Calibration cancelled'
            self.voice_hold = False
            self.core.pause(value)
            if value:
                self.desktop_swipes=False
                self.swipes.reset()
                self.shortcuts.clear()
                self.shortcut_reserved=False
                self.scroll_remaining=0
            self._dispatch()
            self.output.release()
            self.output.enabled = not value and not self.dry_run and not self.practice
            if not value and not self.practice:
                self.desktop_swipes=self.core.profile.shortcuts or self.core.profile.motion_scheme!='fluid'
            x, y = self.output.position()
            self.core.x, self.core.y = x, y
            self.output.current = (x, y)
            self.message = self.core.status
            return True

    def restore_pointer(self, shortcuts=True):
        """Restore translation pointing without discarding the user's calibration."""
        with self.lock:
            DATA.mkdir(parents=True, exist_ok=True)
            old = DATA/'profile.json'
            backup = DATA/'profile-before-0.8.2.json'
            if old.exists() and not backup.exists():
                # Exclusive creation preserves the first pre-recovery profile.
                with backup.open('x') as saved:
                    saved.write(old.read_text())
            self.previous_profile=replace(self.core.profile)
            self.core.cancel('Pointer restored · release pinch to resume')
            self._dispatch();self.output.release()
            self.core.profile.motion_scheme='fluid'
            self.core.profile.shortcuts=shortcuts
            self.core.profile.tilt_precision=False
            self.core.mode='pointer'
            self.desktop_swipes=shortcuts and not self.core.paused
            self.swipes.reset();self.shortcuts.clear();self.wave.clear()
            self.shortcut_reserved=False
            self.scroll_remaining=0
            self.takeover_until=0
            self.last_shortcut=None
            self.core.x,self.core.y=self.output.position()
            self.output.current=(self.core.x,self.core.y)
            profile_save(self.core.profile)
            self.message='Fluid pointer restored · pinch to click; hold to drag'
            LOG.info('Restored fluid pointer; tilt off, finger shortcuts=%s; calibration retained',shortcuts)

    def takeover(self, source=None, now=None):
        """Yield to physical input briefly; only an explicit pause stays paused."""
        if self.core.paused or self.practice:
            return
        now=time.monotonic() if now is None else now
        first=not self.takeover_until
        self.takeover_until=now+.8
        self.last_takeover_source=source
        if first:
            self.core.cancel('Mouse in use · hand control resumes automatically')
            self._dispatch();self.output.release()
            self.output.enabled=False
            self.shortcuts.clear();self.shortcut_reserved=False
            self.scroll_remaining=0
            LOG.info('Temporary mouse handoff: %s',source)

    def resume_takeover(self, now):
        if not self.takeover_until or now<self.takeover_until:return
        self.takeover_until=0
        if self.core.paused:return
        self.core.cancel('Hand control resumed · show one or two fingers')
        self.core.x,self.core.y=self.output.position()
        self.output.current=(self.core.x,self.core.y)
        self.output.enabled=not self.dry_run and not self.practice
        LOG.info('Hand control resumed after mouse handoff')

    def set_mode(self, mode):
        with self.lock:
            if mode!='pointer' and self.core.profile.motion_scheme=='fluid':
                self.core.profile.motion_scheme='figures'
                profile_save(self.core.profile)
            self.voice_hold = False
            self.core.set_mode(mode)
            self._dispatch()
            self.output.release()
            self.core.x, self.core.y = self.output.position()
            self.message = {'move':'Move window · point inside a window, then pinch and hold',
                            'resize':'Resize window · point inside a window, then pinch and hold',
                            'pointer':'Pointer · pinch to click; hold to drag',
                            'scroll':'Scroll · move your open hand up or down'}[mode]

    def start_camera(self, index=0):
        if not self.capture_stop.is_set():
            self.stop_camera()
        self.capture_stop = threading.Event()
        token = self.capture_stop
        if index!=self.room_camera:
            self.room_camera=index
            self.room=RoomPositions(DATA/('room-positions.json' if index==0 else f'room-positions-camera-{index}.json'))
        self.camera_index = index
        self.pose_filter.clear();self.wave.clear()
        self.frame = self.jpeg = None
        self.frame_id = 0
        self.message = 'Opening camera…'
        for fn, name in ((self._capture, 'camera'), (self._vision, 'vision')):
            thread = threading.Thread(target=fn, args=(token, index), name='control-'+name, daemon=True)
            thread.start()
            self.threads.append(thread)

    def stop_camera(self):
        with self.lock:
            self.pause(True)
            self.capture_stop.set()
            self.frame = self.jpeg = None
            self.latest_obs=None
            self.metrics.update(fps=0,palm_px=0,age_ms=0,tracked=False,inference_ms=0,
                                camera_width=0,camera_height=0,observed_at=0)
            self.message = 'Camera off'
            LOG.info('Camera stopped; control paused')

    def _capture(self, token, index):
        cap = None
        try:
            cap = cv2.VideoCapture(index, cv2.CAP_AVFOUNDATION)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)
            cap.set(cv2.CAP_PROP_FPS, 30)
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            if not cap.isOpened():
                raise RuntimeError('Camera unavailable. Allow camera access or choose another camera.')
            with self.lock:
                self.metrics.update(camera_width=int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),camera_height=int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)))
                self.message = 'Camera ready · test from 5–10 feet'
            failures = 0
            while not token.is_set() and not self.stop.is_set():
                ok, frame = cap.read()
                if not ok:
                    failures += 1
                    if failures > 8:
                        raise RuntimeError('Camera stopped delivering frames')
                    token.wait(.03)
                    continue
                failures = 0
                # No frame queue: inference always consumes the most recent capture.
                with self.lock:
                    if token.is_set():
                        break
                    self.frame, self.frame_time = frame, time.monotonic()
                    self.frame_id += 1
        except Exception as e:
            with self.lock:
                if token is self.capture_stop:
                    self._fail(str(e))
                    self.message = str(e)
                    token.set()
        finally:
            if cap is not None:
                cap.release()

    def _vision(self, token, index):
        try:
            import mediapipe as mp
            from mediapipe.tasks.python import BaseOptions
            from mediapipe.tasks.python.vision import HandLandmarker, HandLandmarkerOptions, RunningMode
            options = HandLandmarkerOptions(base_options=BaseOptions(model_asset_path=str(MODEL)),
                                           running_mode=RunningMode.VIDEO, num_hands=1,
                                           min_hand_detection_confidence=.65,
                                           min_hand_presence_confidence=.65,
                                           min_tracking_confidence=.65)
            previous_id, previous_ms = -1, -1
            count, since, preview_at = 0, time.monotonic(), 0
            zoom_options=HandLandmarkerOptions(base_options=BaseOptions(model_asset_path=str(MODEL)),
                                               running_mode=RunningMode.IMAGE,num_hands=1,
                                               min_hand_detection_confidence=.65,min_hand_presence_confidence=.65)
            region=None
            search_step=0
            with HandLandmarker.create_from_options(options) as detector, HandLandmarker.create_from_options(zoom_options) as zoom:
                while not token.is_set() and not self.stop.is_set():
                    with self.lock:
                        frame, ident, stamp = self.frame, self.frame_id, self.frame_time
                        style = self.calibration_profile.gesture if self.calibration else self.core.profile.gesture
                    if frame is None or ident == previous_id:
                        token.wait(.003)
                        continue
                    previous_id = ident
                    ms = max(previous_ms+1, int(stamp*1000))
                    previous_ms = ms
                    begin = time.monotonic()
                    rgb=cv2.cvtColor(frame,cv2.COLOR_BGR2RGB)
                    cropped=False
                    if region:
                        x,y,cw,ch=region
                        found=zoom.detect(mp.Image(image_format=mp.ImageFormat.SRGB,data=np.ascontiguousarray(rgb[y:y+ch,x:x+cw])))
                        result=restore(found,region,frame.shape)
                        cropped=bool(result.hand_landmarks)
                    if not cropped:
                        result=detector.detect_for_video(mp.Image(image_format=mp.ImageFormat.SRGB,data=rgb),ms)
                    if not result.hand_landmarks:
                        region=search_region(frame.shape,search_step)
                        search_step+=1
                        x,y,cw,ch=region
                        found=zoom.detect(mp.Image(image_format=mp.ImageFormat.SRGB,data=np.ascontiguousarray(rgb[y:y+ch,x:x+cw])))
                        result=restore(found,region,frame.shape)
                        cropped=bool(result.hand_landmarks)
                    region=hand_region(result,frame.shape)
                    now = time.monotonic()
                    obs = self.pose_filter.feed(extract(result, frame.shape, stamp, style))
                    with self.lock:
                        if token.is_set():
                            break
                        self.metrics.update(tracked=obs is not None, palm_px=round(obs.palm_px) if obs else 0,
                                            inference_ms=round((now-begin)*1000), age_ms=round((now-stamp)*1000),
                                            figure=obs.figure if obs else 'none',detail_crop=cropped,
                                            geometry=obs.geometry if obs else 'none',contact=round(obs.contact,3) if obs else None,
                                            fingers=obs.finger_mask.bit_count() if obs else 0,
                                            finger_mask=obs.finger_mask if obs else 0,
                                            hand_map=obs.hand_map if obs else None,
                                            in_frame=obs.in_frame if obs else False,
                                            palm_in_frame=obs.palm_in_frame if obs else False,
                                            pinch_visible=obs.pinch_visible if obs else False,observed_at=now)
                        if self.attempt and not self.attempt.finished:
                            self.attempt.tracking(obs,now,self.metrics,self.core.tilt.active)
                        if obs and self.attempt and not self.attempt.finished:
                            self.attempt.sample(obs,self.core.state)
                        self.latest_obs=obs
                        position_reserved=self.process_position(obs,now)
                        reserved=position_reserved or self.process_shortcuts(obs,now)
                        direction=self.swipes.feed(obs,allowed=(not self.core.profile.shortcuts and self.desktop_swipes and not self.room.anchors and not self.practice
                                                   and not self.calibration and not self.core.finger_down
                                                   and self.core.state not in ('contact','drag') and now-stamp<=.15))
                        if direction:
                            self.switch_desktop(direction)
                        if obs is None or now-stamp > .15:
                            self.core.cancel('Hand not clear · release and show your hand again')
                        elif self.calibration:
                            self.calibration.add(obs)
                            self.message = self.calibration.prompt
                            if self.calibration.done:
                                self._finish_calibration()
                        elif not reserved and not self.takeover_until:
                            if self.voice_hold:
                                obs = Observation(obs.t, obs.x, obs.y, 0.0, obs.palm_px, 'point', obs.hand)
                            self.core.feed(obs)
                        self._dispatch()
                        count += 1
                        if now-since >= 1:
                            self.metrics['fps'] = round(count/(now-since))
                            count, since = 0, now
                    if self.preview and now-preview_at > .10:
                        preview_at = now
                        image = cv2.resize(cv2.flip(frame, 1), (640, 360))
                        if result.hand_landmarks:
                            lm = result.hand_landmarks[0]
                            for a,b in BONES:
                                cv2.line(image, (int((1-lm[a].x)*640),int(lm[a].y*360)),
                                         (int((1-lm[b].x)*640),int(lm[b].y*360)), (150,230,130), 2)
                            for point in lm:
                                cv2.circle(image,(int((1-point.x)*640),int(point.y*360)),3,(90,210,255),-1)
                            if obs and obs.hand_map:
                                image[12:170,475:628]=(24,29,35)
                                joints=np.asarray(obs.hand_map['joints'])
                                projection=np.column_stack((joints[:,0]*.8+joints[:,2]*.45, joints[:,1]*.85-joints[:,2]*.25))
                                span=max(2.5,float(np.max(np.abs(projection)))*2.2)
                                xy=(projection/span*120+np.array([550,95])).astype(int)
                                for a,b in BONES:cv2.line(image,tuple(xy[a]),tuple(xy[b]),(255,170,80),2)
                                for joint in xy:cv2.circle(image,tuple(joint),3,(240,240,240),-1)
                                cv2.putText(image,'3D estimate',(483,29),cv2.FONT_HERSHEY_SIMPLEX,.36,(220,220,220),1)
                        ok, encoded = cv2.imencode('.jpg', image, [cv2.IMWRITE_JPEG_QUALITY, 70])
                        if ok:
                            self.jpeg = encoded.tobytes()
        except Exception as e:
            LOG.exception('Vision pipeline failed')
            with self.lock:
                if token is self.capture_stop:
                    self._fail(str(e))
                    self.message = 'Tracking failed: ' + str(e)
                    token.set()

    def calibrate(self, style=None):
        with self.lock:
            if self.capture_stop.is_set():
                self.message = 'Start the camera before calibration'
                return
            self.cal_resume = not self.core.paused
            self.pause(True)
            self.calibration = Calibration(time.monotonic())
            self.calibration_profile = Profile(**asdict(self.core.profile))
            if style:
                self.calibration_profile.gesture = style
            self.cal_started = time.monotonic()
            self.message = self.calibration.prompt

    def _finish_calibration(self):
        candidate = self.calibration.finish(self.calibration_profile)
        error = self.calibration.error
        self.calibration = None
        if candidate:
            self.previous_profile = self.core.profile
            self.core.profile = candidate
            self.core.fx.cutoff = self.core.fy.cutoff = candidate.cutoff
            profile_save(candidate)
            self.message = 'Calibration saved · Start control when ready'
        else:
            self.message = error + ' Previous settings retained.'

    def adjust(self, factor):
        with self.lock:
            self.previous_profile = Profile(**asdict(self.core.profile))
            self.core.profile.sensitivity = max(.4, min(2.5, self.core.profile.sensitivity*factor))
            profile_save(self.core.profile)
            self.message = f'Sensitivity {self.core.profile.sensitivity:.2f}×'

    def reset_profile(self, undo=False):
        with self.lock:
            self.pause(True)
            old = self.core.profile
            self.core.profile = self.previous_profile if undo and self.previous_profile else Profile()
            self.previous_profile = old
            self.core.fx.cutoff = self.core.fy.cutoff = self.core.profile.cutoff
            profile_save(self.core.profile)
            self.message = 'Previous settings restored' if undo else 'Default settings restored'

    def _pump(self):
        while not self.stop.is_set():
            with self.lock:
                try:
                    now=time.monotonic()
                    self.resume_takeover(now)
                    self.core.tick(now)
                    self.pump_scroll(now)
                    if self.calibration and time.monotonic()-self.cal_started > 40:
                        self.calibration = None
                        self.message = 'Calibration timed out · previous settings retained'
                    if self.voice_hold and not self.core.finger_down:
                        self.voice_hold = False
                    self._dispatch()
                    if not self.dry_run:
                        self.output.pump(time.monotonic())
                except Exception as e:
                    self._fail(str(e))
                    self.message = str(e)
            self.stop.wait(1/120)

    def listen(self):
        if self.voice_until > time.monotonic():
            self.voice_until = 0
            self.voice_message = 'Voice off'
            return
        self.voice_until = time.monotonic()+12
        self.voice_message = 'Listening for one command…'
        if self.voice_thread is None or not self.voice_thread.is_alive():
            self.voice_thread = threading.Thread(target=self._voice, name='control-voice', daemon=True)
            self.voice_thread.start()

    def set_wake(self,enabled):
        self.voice_wake=bool(enabled)
        if enabled:
            self.voice_message='Listening locally for “Control” · wave also recalls a saved position'
            if self.voice_thread is None or not self.voice_thread.is_alive():
                self.voice_thread=threading.Thread(target=self._voice,name='control-voice',daemon=True)
                self.voice_thread.start()
        else:
            self.voice_until=0;self.voice_message='Wake listening off'

    def _voice(self):
        try:
            import sounddevice as sd
            from vosk import Model, KaldiRecognizer, SetLogLevel
            SetLogLevel(-1)
            candidates = [HERE/'vosk-model-small-en-us-0.15',
                          Path(os.environ.get('CONTROL_SPEECH_MODEL', str(HERE.parent/'models/vosk-model-small-en-us-0.15'))),
                          Path.home()/'vosk-model-small-en-us-0.15']
            path = next((p for p in candidates if p.is_dir()), None)
            if path is None:
                raise RuntimeError('Local speech model missing; see README')
            model = Model(str(path))
            grammar = list(COMMANDS)+['[unk]']
            while (self.voice_wake or self.voice_until > time.monotonic()) and not self.stop.is_set():
                rec = KaldiRecognizer(model, 16000, json.dumps(grammar))
                rec.SetWords(True)
                audio = queue.Queue(maxsize=12)
                def callback(data, frames, clock, status):
                    try:
                        audio.put_nowait(bytes(data))
                    except queue.Full:
                        pass
                with sd.RawInputStream(samplerate=16000, blocksize=1600, dtype='int16', channels=1, callback=callback):
                    while (self.voice_wake or self.voice_until > time.monotonic()) and not self.stop.is_set():
                        try:
                            data = audio.get(timeout=.15)
                        except queue.Empty:
                            continue
                        if rec.AcceptWaveform(data):
                            recognized=json.loads(rec.Result())
                            text=recognized.get('text','')
                            if self.voice_wake and time.monotonic()>self.voice_until:
                                words=recognized.get('result',[])
                                if text=='control' and words and min(w.get('conf',0) for w in words)>=.8:
                                    self.ui_actions.put(('voice','position_recall'))
                                    self.voice_until=time.monotonic()+8
                                    self.voice_message='Control heard · say “calibrate here” or another command'
                                    break
                                continue
                            cmd = parse_command(text)
                            if cmd:
                                self.ui_actions.put(('voice', cmd))
                                self.voice_message = ('Listening for “Control” · ' if self.voice_wake else '')+'Heard: ' + text
                                self.voice_until = 0
                                break
                            elif text:
                                self.voice_message = 'Try “click”, “move window”, or “pause control”'
                # Always close microphone on timeout or cancellation.
            if self.voice_message.startswith('Listening'):
                self.voice_message = 'Voice off · no command heard'
        except Exception as e:
            self.voice_until = 0
            self.voice_wake = False
            self.voice_message = 'Voice unavailable: ' + str(e)
            LOG.warning('%s', self.voice_message)

    def command(self, cmd):
        if cmd=='position_save':
            self.save_position();return
        if cmd=='position_recall':
            with self.lock:self.recall_position()
            return
        if cmd in ('desktop_left','desktop_right'):
            if self.desktop_swipes:
                with self.lock:
                    self.switch_desktop(cmd.split('_')[1])
            return
        if cmd == 'pause' or cmd == 'cancel':
            self.pause(True); return
        if cmd == 'resume':
            self.pause(False); return
        if cmd in ('move', 'resize', 'pointer', 'scroll'):
            self.set_mode(cmd); return
        if cmd in ('faster', 'slower'):
            self.adjust(1.15 if cmd == 'faster' else 1/1.15); return
        with self.lock:
            if self.core.paused:
                self.message = 'Paused · start control before sending commands'
                return
            if self.calibration:
                return
            if cmd == 'drop':
                self.voice_hold = False
                self.core.cancel('Released · open hand to resume')
            elif cmd == 'drag':
                if self.core.last_obs is None or time.monotonic()-self.core.last_obs.t > .15:
                    self.message = 'Show your hand before starting a drag'
                    return
                observation = self.core.last_obs
                self.core.cancel('Dragging')
                self.core.last_obs = observation  # The watchdog must also protect voice-started holds.
                self.core.rearmed = True
                self.core.state = 'drag'
                self.core.finger_down = True
                self.core.emit('down', mode=self.core.mode)
                self.voice_hold = True
            elif cmd in ('click', 'double_click', 'right_click'):
                self.core.cancel('Show an open hand to resume')
                self.core.emit('click', count=1, right=cmd=='right_click')
                if cmd == 'double_click':
                    self.core.emit('click', count=2)
            elif cmd in ('scroll_up', 'scroll_down'):
                self.core.emit('scroll', dy=450 if cmd=='scroll_up' else -450)
            elif cmd in ('media', 'volume_up', 'volume_down', 'back', 'forward'):
                self.ui_actions.put(('system', cmd))
            self._dispatch()

    def close(self):
        self.voice_wake = False
        self.voice_until = 0
        self.pause(True)
        if self.attempt and not self.attempt.finished:
            self.attempt.finish('app_closed')
        self.stop.set()
        self.capture_stop.set()
        for thread in self.threads:
            if thread is not threading.current_thread():
                thread.join(timeout=.4)
        if self.voice_thread and self.voice_thread is not threading.current_thread():
            self.voice_thread.join(timeout=1)

    def switch_desktop(self, direction):
        if not self.dry_run and not trusted():
            self.message='Desktop swipes need Accessibility access'
            return
        self.core.cancel('Desktop '+direction+' · lower your hand to rearm')
        self._dispatch()
        self.output.release()
        if not self.dry_run:
            self.output.switch_desktop(direction)
        self.last_desktop=dict(direction=direction,time=time.time())
        DATA.mkdir(parents=True,exist_ok=True)
        with (DATA/'desktop-swipes.jsonl').open('a') as f:
            f.write(json.dumps(dict(kind='desktop_swipe',**self.last_desktop))+'\n')

    def process_shortcuts(self, obs, now):
        allowed=(self.core.profile.shortcuts and (not self.core.paused or self.desktop_swipes) and not self.calibration
                 and not self.core.finger_down and self.core.state not in ('contact','drag')
                 and not self.voice_hold and not self.takeover_until and obs is not None and now-obs.t<=.15)
        action=self.shortcuts.feed(obs,allowed=allowed,scale=self.core.profile.shortcut_scale,
                                   allow_desktop=(self.desktop_swipes or self.practice) and not
                                   (self.room.anchors and obs and obs.finger_mask==15 and not self.practice),
                                   allow_two=not self.core.paused,
                                   allow_tap=self.core.profile.motion_scheme!='fluid')
        reason=('off' if not self.core.profile.shortcuts else
                'paused' if self.core.paused and not self.desktop_swipes else
                'mouse handoff' if self.takeover_until else
                'pinch held' if self.core.finger_down or self.core.state in ('contact','drag') else
                'calibrating' if self.calibration else
                'tracking unavailable' if obs is None or now-obs.t>.15 or not obs.pointer_usable() else
                'active fingers hidden' if obs.finger_mask & obs.visible_fingers != obs.finger_mask else
                'listening' if self.voice_hold else 'watching')
        self.shortcut_diagnostics=dict(reason=reason,allowed=bool(allowed),
            fingers=obs.finger_mask if obs else 0,group=self.shortcuts.group,
            progress=round(self.shortcuts.progress,2),desktops=bool(self.desktop_swipes),
            last_action=action,observed_at=now)
        if self.core.profile.motion_scheme=='fluid' and self.core.mode=='pointer':
            # Recognize alongside pointing. A tentative finger chord owns nothing.
            self.shortcut_reserved=False
            if action:
                self.handle_shortcut(action)
                self.core.previous=None
            return bool(action)
        reserved=allowed and self.shortcuts.reserved and (self.shortcuts.group!='two' or
                    (self.shortcuts.anchor is not None and obs.t-self.shortcuts.anchor.t>=.10))
        if reserved and not self.shortcut_reserved:
            self.core.cancel('Finger shortcut · relax your fingers to resume pointing')
            self._dispatch();self.output.release()
        self.shortcut_reserved=reserved
        if action:self.handle_shortcut(action)
        return reserved

    def handle_shortcut(self, action):
        self.last_shortcut=dict(time=time.time(),**action)
        DATA.mkdir(parents=True,exist_ok=True)
        with (DATA/'finger-shortcuts.jsonl').open('a') as f:
            f.write(json.dumps(dict(kind='recognized',action=action,practice=self.practice,time=time.time()))+'\n')
        if self.practice and self.attempt and self.attempt.task=='shortcuts':
            self.attempt.event(dict(kind='shortcut',action=action))
            self.ui_actions.put(('practice_shortcut',action))
            return
        kind=action['kind']
        if kind=='double_click':
            self.core.last_click=(-100,0,0,0)
            self.core.emit('click',count=1)
            self.core.emit('click',count=2)
            self._dispatch()
            self.message='Two-finger tap · double click'
        elif kind=='scroll':
            self.scroll_remaining=max(-1200,min(1200,self.scroll_remaining+action['dy']))
            self.scroll_time=time.monotonic()
            self.message='Two-finger flick · scrolling'
        elif kind=='desktop' and self.desktop_swipes and not self.practice:
            self.switch_desktop(action['direction'])

    def pump_scroll(self, now):
        dt=max(0,min(.04,now-self.scroll_time))
        self.scroll_time=now
        if self.core.paused:
            self.scroll_remaining=0
            return
        if abs(self.scroll_remaining)<1:
            self.scroll_remaining=0
            return
        delta=self.scroll_remaining*(1-math.exp(-dt/.18))
        self.scroll_remaining-=delta
        self.core.emit('scroll',dy=delta)

    def enable_swipes(self, enabled=True):
        with self.lock:
            self.swipes.reset()
            self.desktop_swipes=enabled and (self.core.profile.shortcuts or self.core.profile.motion_scheme!='fluid')
            if enabled and not self.desktop_swipes:
                self.message='Fluid pointer · desktop gestures are off'
                return
            self.message='Desktop swipes on · three fingers, sweep left or right' if enabled else 'Desktop swipes off'

    def save_position(self):
        with self.lock:
            if self.capture_stop.is_set():
                self.message='Start the camera before saving a position';return
            if self.practice or self.calibration:
                self.message='Finish the current trial before saving a position';return
            self.room.begin(time.monotonic())
            self.core.cancel('Hold your open hand comfortably still for one second')
            self._dispatch();self.output.release()
            self.message=self.core.status

    def recall_position(self):
        obs=self.latest_obs
        if obs is None or time.monotonic()-obs.t>.15:
            self.message='Show your hand to recall a position';return
        anchor=self.room.recall(obs)
        if anchor is None:
            self.message='No clear saved position · choose Save position here first';return
        self.core.cancel('Position recalled · release to resume')
        self._dispatch();self.output.release()
        self.core.profile=Profile.from_dict(anchor['profile'])
        self.core.fx.cutoff=self.core.fy.cutoff=self.core.profile.cutoff
        profile_save(self.core.profile)
        self.core.x,self.core.y=self.output.position()
        if self.core.paused:self.pause(False)
        self.desktop_swipes=self.core.profile.shortcuts
        self.message=anchor['name']+' recalled · pointer recentered at current cursor'
        self.ui_actions.put(('position_feedback',self.message))

    def process_position(self,obs,now):
        if self.practice or self.calibration or self.voice_hold or self.takeover_until or self.core.finger_down or self.core.state in ('contact','drag'):
            self.wave.clear();return False
        if self.room.collecting is not None:
            if now-self.room.collecting>8:
                self.room.collecting=None;self.message='Position not saved · keep your hand visible and still';return False
            message=self.room.observe(obs,self.core.profile)
            if message:
                self.message=message;self.ui_actions.put(('position_feedback',message))
            return True
        # Fluid pointing never automatically recalls another saved profile.
        if self.core.profile.motion_scheme=='fluid':
            self.wave.clear();return False
        # Open palm is reserved for recall only after a user has taught a position.
        if self.room.anchors and obs and obs.finger_mask==15:
            if self.wave.feed(obs):self.recall_position();return True
        else:self.wave.clear()
        return False
