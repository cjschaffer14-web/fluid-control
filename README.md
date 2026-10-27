# Fluid Control

<img src="assets/icon.png" alt="Fluid Control pointer icon" width="96">

An experimental macOS app that turns camera-tracked hand movement into pointer control. Built for playful, low-effort interaction and quick personal calibration.

**Status: prototype, version 0.7.0.** Pointer control has been used interactively, but gesture shortcuts, distant tracking, rotated hands, and compatibility across games and popups still need live validation. This source publication does not certify those features as reliable.

The native app currently appears as **Control**. Keeping that internal name and bundle identifier preserves continuity with earlier local builds; this public edition is called **Fluid Control**.

## New in 0.7.0

- Scrolling measures index/middle fingertip movement, so the palm can stay still. Brief finger-shape fluctuations are tolerated and diagonal desktop sweeps need less rigid alignment.
- Fluid mode preserves enabled desktop shortcuts. With saved room positions, use **three fingers** for desktops; a four-finger open-hand wave is reserved for position recall.
- The preview draws all 21 joints, including the thumb, with an inset showing estimated 3D geometry. Finger curls and a palm coordinate frame use the model's world landmarks when available. Camera depth remains an estimate; occluded joints can be wrong.
- Actual mouse presses have a short generated acoustic tap. Toggle **Click sound on / off** in Control's menu. It mixes with existing audio; it does not change the volume of other applications or provide physical haptics.

## Room positions and calling Control

This is a map of saved camera positions and relative hand size, **not a scan of walls or furniture**. Keep the camera fixed. In each comfortable seated or standing location, click **Save here**, then hold an open hand still for about one second. Up to eight positions retain the current profile. Use **Room map** to see them.

Wave an open hand back and forth with three direction changes to recall a matching profile and resume at the current cursor. A single sweep is not a recall wave. Ambiguous or unmatched positions do not load a profile; the app asks you to save a position. Apparent hand size varies with orientation, so use a similar relaxed open hand when teaching and recalling positions. Moving the camera invalidates the map: save positions again. Save a position again after tuning its profile.

Press **Voice** and say “calibrate here” to save a position or “Control” to recall it. Optional **Listen for “Control” on / off** enables local microphone listening for this session. It is off at launch. While waiting, only a sufficiently confident exact “Control” result opens an eight-second command window; it also tries to recall your position. Commands such as “calibrate here” can then be spoken. Camera tracking must see your hand to save or recall. A webcam does not locate a voice in the room. Wake recognition is experimental and may miss speech or respond incorrectly in background audio. Turn it off from the menu to close wake listening.

Room anchors store camera-relative hand location, relative size, handedness and profiles locally under application support. No room imagery is saved. Separate camera selections use separate anchor files. To reset a map, quit Control and remove the corresponding `room-positions*.json` file there. Microphone audio is processed locally and is not saved.

## What is here

- Camera-based pointer with adaptive smoothing, hand-size-aware tracking and a distance search pass.
- Finger and whole-hand control schemes, plus a Fluid pointer mode.
- Pinch click and drag, and native window movement and resizing modes.
- Experimental two-finger curl/reopen for double click, two-finger vertical flick for scrolling, and three-finger horizontal swipe for switching desktops.
- Guided live demos: attempt recording, five feedback questions, and profile adjustments for the next round.
- Optional local voice commands, a native Dock icon and a macOS permission panel.

Actual behavior depends on the selected mode and shortcut settings. A two-finger tap means curling and reopening the two fingers in camera view; it is not contact with a physical surface. Use the app's camera preview and demo feedback to check recognition before relying on a gesture.

## Build on your Mac

Requires macOS 14 or later, a camera, Xcode Command Line Tools (`xcode-select --install`), and a Python installation with a loadable shared library or framework. The development environment was tested with Python 3.15 and the exact versions in `requirements.txt`; other combinations have not been verified.

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
mkdir -p models
curl -fL https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task -o models/hand_landmarker.task
python build.py
open dist/Control.app
```

The build script discovers the active Python runtime, generates the icon, bundles the app's Python sources and the supplied hand model, and signs the result ad hoc. It does not download dependencies or models. Use `python build.py --help` for model and output options.

**This build uses the Python environment on the machine where it was built.** Keep that interpreter and virtual environment in place. Copying the `.app` to another Mac is not a supported distribution method. A standalone, notarized installer is not included.

For optional speech, install `requirements-voice.txt`, obtain the [Vosk small English model](https://alphacephei.com/vosk/models), and build with `--speech-model /path/to/vosk-model-small-en-us-0.15`. Voice is activated explicitly in the app.

## First run and controls

1. Open Control and grant Camera and Accessibility access when prompted. Microphone is needed only for optional voice input.
2. Confirm that the preview sees your hand, choose a scheme and calibrate your comfortable movement range.
3. Start with a guided Live demo. Complete the requested action and answer its five questions to tune the next attempt.
4. Enable and test gesture shortcuts separately. Desktop switching also depends on macOS Spaces settings.

Escape pauses control. Physical mouse input temporarily yields gesture control and then resumes it. Lower or remove the hand if recognition becomes uncertain. Window actions depend on the target application's accessibility support; Steam and game overlays may behave differently from ordinary macOS windows.

For source development, set `CONTROL_HAND_MODEL` to the model path and run `python src/app.py`; permissions may then belong to the launching interpreter or terminal. Use the bundled launcher for consistent app identity.

## Privacy and local data

Camera frames are processed locally. The application code does not upload video or audio, and guided trials do not save raw media. Optional voice recognition uses a local Vosk model. Installing dependencies and downloading models require network access.

Profiles and launch logs are stored in `~/Library/Application Support/Control`. Guided trials save timestamps, derived hand signals, pointer coordinates, event timing, task outcomes, configuration and your written feedback. Source runs put trials in `attempts/`; packaged runs use the application-support directory. These records can contain personal information. They are ignored by Git and are not included in this repository.

`CONTROL_DATA_DIR` overrides the runtime profile/log directory. It does not override the native launcher's log or the guided trial directory. Delete the corresponding local files to remove those records.

## Development and validation

```sh
python -m unittest discover -s tests -v
python build.py --model /path/to/hand_landmarker.task
codesign --verify dist/Control.app
```

See [VALIDATION.md](VALIDATION.md) for what the automated checks cover and the live checks still needed. See [THIRD_PARTY.md](THIRD_PARTY.md) for model and dependency sources. No model binaries, personal trials, calibration profiles, recordings, or machine-specific app bundles are distributed here.
