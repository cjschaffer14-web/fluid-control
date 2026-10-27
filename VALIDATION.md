# Validation

The source includes 179 automated tests covering controller transitions, calibration, smoothing, gesture geometry, shortcut state machines, desktop swipe gating, tracking regions, native event construction, local attempt handling and runtime safety behavior.

Run on macOS in the configured Python environment:

```sh
python -m unittest discover -s tests -v
```

Tests use synthetic observations and mocks. Passing them does not demonstrate that a real camera recognizes a person's hand or that another application accepts an injected event. In particular, the double-click, scroll and desktop shortcuts need further live testing after reports of unreliable activation.

The public build is also checked by compiling the Objective-C launcher, bundling sources/model/icon, and verifying its ad hoc code signature. Code signing here is a local integrity check; it is not Apple notarization.

The 0.7.0 checks also cover fingertip-only scrolling with a stationary palm, noisy finger classification, diagonal swipes, rearming, full 21-joint mapping across rotations, wave versus single-swipe separation, ambiguous position rejection, local profile recall and click feedback gated on actual mouse presses. Wake-word accuracy and real room-position recall still require user trials.

## Live checks before calling a feature reliable

Use the guided demo to ask for a concrete action, record the attempt, and collect its five feedback answers before changing thresholds. Repeat for near and distant hands, palm down, palm facing the camera, side-on and partially occluded positions. Test each hand separately.

Check ordinary clicks and drag/release on buttons and window title bars, including tracking loss and physical mouse takeover. Check double-click recognition in Finder, scrolling in a long document, and Spaces switching with an actual full-screen video. Repeat with the intended Steam dialog or game overlay; ordinary native-window success does not establish game compatibility.

Keep personal logs local. Summarize reproducible conditions without uploading camera frames, profiles or private feedback.

## Local verification, October 27, 2026

The 157-test suite passed in the existing macOS development environment. The local update launched at 30 camera frames per second with the existing Accessibility identity. A real AppKit event round trip passed single/double/right clicks, visible press duration, dragging, scrolling and release checks. The room map window rendered successfully. These checks do not substitute for the user's physical gesture and position-recall trials.

## Blocking usability result, October 27, 2026

The user reports that the current control is not working reliably even at approximately two feet and cannot select an answer in the assistant's question box. The halo's appearance was received positively; usable target selection was not demonstrated. Runtime “tilt active” / “output enabled” and generated move requests do not supersede this report. No completed scored trial establishes the 5–10-foot requirement.

See the [complete difficulties and judgment review](docs/reviews/2026-10-27-usability.md). Treat live usability as failed/unresolved despite passing automated checks.


## 0.8.1 recovery checks

The 165-test suite passes after adding regressions for legacy profile loading, ordinary translation after settling, consistent translation gain across synthetic apparent hand sizes, safe drag release and preservation of calibration during recovery, first-profile backup, disabled shortcut arbitration, accurate camera-off telemetry, and event ownership when the reported PID is zero. Existing tilt tests now explicitly enable tilt.

These checks demonstrate the repaired state transitions, not successful target selection at two feet or 5–10 feet. The earlier live failure remains blocking. Full-hand edge rejection, uncertain posture classification, rotated/occluded fingers and real-distance recognition remain possible causes of difficulty. Do not infer their resolution from this recovery.


The local 0.8.1 update launched with the existing Accessibility/post-event permissions, camera at 30 fps, Fluid pointing active, tilt off and finger shortcuts off. The installed sources matched the recovery source files. A first owned-window check cancelled on an untagged external click after successful single/double delivery and released safely; that result was preserved locally. A second complete AppKit round trip passed left/right pairs, double click counts, drag, scroll, visible/polled press, ownership-tag propagation and non-stuck release. These are event-delivery results only. The live status also reported partial-hand edge rejection during inspection; that gate remains unchanged and may still interrupt actual use.


## 0.8.2: fewer movement gates, controls enabled

The 179-test suite passes. New cases verify immediate palm movement before click arming, continued pointing despite fist/thumb classification or an unused clipped pinky, hidden thumb/index releasing a held drag without clicking, actual palm loss blocking output, candidate finger chords not reserving/disarming Fluid pointing, scroll and desktop recognition reaching the runtime, active versus unused clipped fingers, removal of two-finger curl double click in Fluid mode, and enabled shortcut/desktop state after Fluid restore. The initial test caught a backwards delta when click arming reset an already-moving filter baseline; that reset is now confined to the older non-Fluid path.

These are synthetic controller/pipeline checks. Real gesture recognition, application response, physical effort and selection accuracy remain unresolved until a user trial. The local updater backs up the previous profile, enables scroll/desktop finger controls, keeps tilt off, retains calibration and starts through the existing native host.


Local 0.8.2 deployment: the unchanged native host launched at 30 fps; installed sources matched; camera, pointer output, finger shortcuts and desktop swipes were enabled, tilt was off, and the previous profile backup existed. The visible UI showed `Fluid`, `Tilt OFF`, `Swipes ON`, and the scroll/desktop instructions. The initial post-update snapshot had no detected hand, so no physical scroll/swipe success is inferred from launch. The native event output module did not change in this update; its 0.8.1 owned-window round trip is prior evidence, not a new camera-gesture result.
