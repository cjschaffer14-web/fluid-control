# Validation

The source includes 157 automated tests covering controller transitions, calibration, smoothing, gesture geometry, shortcut state machines, desktop swipe gating, tracking regions, native event construction, local attempt handling and runtime safety behavior.

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
