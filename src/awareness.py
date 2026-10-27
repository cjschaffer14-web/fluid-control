"""Honest tracking states for the window halo; this does not infer eye gaze."""

def tracking_state(metrics,now,camera_on=True,paused=False,ready=False,handoff=False,precision=False,access=True,resting=False,tilt_enabled=False):
    if not camera_on:return dict(color='gray',label='Camera off')
    if not metrics.get('tracked') or now-metrics.get('observed_at',0)>.22:
        return dict(color='red',label='Hand lost · out of view or hidden')
    if metrics.get('age_ms',1000)>150:return dict(color='amber',label='Tracking delayed · holding control')
    if not metrics.get('in_frame',True):return dict(color='amber',label='Hand at edge · show the whole hand')
    if metrics.get('palm_px',0)<22:return dict(color='amber',label='Hand found · detail uncertain')
    if not access:return dict(color='white',label='Hand tracked · Accessibility needed')
    if handoff:return dict(color='white',label='Hand tracked · mouse in use')
    if paused:return dict(color='white',label='Hand tracked · control paused')
    if resting:return dict(color='white',label='Resting · open hand to resume')
    if not ready:return dict(color='white',label='Hand tracked · release pinch to arm')
    if precision:return dict(color='green',label='Tilt precision · small wrist tilts')
    return dict(color='green',label='Ready · move hand, then settle to tilt' if tilt_enabled else 'Ready · move hand to point; pinch to click')
