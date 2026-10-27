# Third-party components

Dependencies are installed separately and remain subject to their respective licenses. This repository does not include their source distributions or model weights.

- [MediaPipe Hand Landmarker](https://developers.google.com/edge/mediapipe/solutions/vision/hand_landmarker/python) supplies image and world landmarks. The model download in the README follows the [official sample](https://github.com/google-ai-edge/mediapipe-samples-web/blob/master/src/tasks/hand-landmarker.ts).
- [OpenCV](https://opencv.org/) handles camera frames.
- [NumPy](https://numpy.org/) supplies numerical operations.
- [PyObjC](https://pyobjc.readthedocs.io/) exposes native macOS APIs.
- [Vosk](https://alphacephei.com/vosk/) and [python-sounddevice](https://python-sounddevice.readthedocs.io/) support optional local voice input. Consult the [Vosk model table](https://alphacephei.com/vosk/models) for each model's license.
- Pointer smoothing draws on the [One Euro Filter](https://gery.casiez.net/1euro/) approach by Casiez, Roussel and Vogel.

No license grant for the application's own source has been selected for this initial publication.
