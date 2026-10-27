# Validation

The source includes 110 automated tests covering controller transitions, calibration, smoothing, gesture geometry, shortcut state machines, desktop swipe gating, tracking regions, native event construction, local attempt handling and runtime safety behavior.

Run on macOS in the configured Python environment:

```sh
python -m unittest discover -s tests -v
```

Tests use synthetic observations and mocks. Passing them does not demonstrate that a real camera recognizes a person's hand or that another application accepts an injected event. In particular, the double-click, scroll and desktop shortcuts need further live testing after reports of unreliable activation.

The public build is also checked by compiling the Objective-C launcher, bundling sources/model/icon, and verifying its ad hoc code signature. Code signing here is a local integrity check; it is not Apple notarization.

## Live checks before calling a feature reliable

Use the guided demo to ask for a concrete action, record the attempt, and collect its five feedback answers before changing thresholds. Repeat for near and distant hands, palm down, palm facing the camera, side-on and partially occluded positions. Test each hand separately.

Check ordinary clicks and drag/release on buttons and window title bars, including tracking loss and physical mouse takeover. Check double-click recognition in Finder, scrolling in a long document, and Spaces switching with an actual full-screen video. Repeat with the intended Steam dialog or game overlay; ordinary native-window success does not establish game compatibility.

Keep personal logs local. Summarize reproducible conditions without uploading camera frames, profiles or private feedback.
