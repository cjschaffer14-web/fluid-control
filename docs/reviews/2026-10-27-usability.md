# Usability failures and decision review — October 27, 2026

Tracking issue: [#1 — blocking selection failure](https://github.com/cjschaffer14-web/fluid-control/issues/1).

## Current disposition: not reliable

The user reports that basic selection is currently unreliable **at approximately two feet**: they cannot select an answer in the assistant's feedback question box. The product requirement is comfortable control from **5–10 feet**. That requirement has not been demonstrated. A functioning visual halo, a detected hand, an active tilt state, and passing unit tests do not establish usable control.

This review is a written reconstruction from the user's reports, code inspection, local runtime status, and automated/owned-window checks. It is not a scored usability study. Distances are user-reported unless explicitly described as simulated. Earlier observations must not be retroactively labeled as 5–10-foot tests. No raw camera or microphone recordings, calibration profiles, personal room anchors, or detailed landmark traces are included here.

## Requirements that must guide the next iteration

- All core interactions must work while seated or standing 5–10 feet from the camera, with low arm effort.
- Large hand movements should provide travel; small wrist tilts, with the hand held in place, should provide fine adjustment. Changing distance must not be the fine-control mechanism.
- Click, double click, drag, window movement/resizing, scrolling, and desktop switching must have distinguishable intentions and reliable release/recovery.
- A visible window ring should communicate tracking and loss. The interpretation of “looking” as eye gaze has not been agreed; the implementation currently uses readiness, not eye gaze.
- Development should prioritize short live trials, record attempts locally, ask five questions per round, and adapt to the user's natural response.
- Feedback must remain possible when gesture selection fails. Asking the user to select a feedback option with the failing pointer is an unacceptable dependency.

## Reported difficulties and evidence

| Area | Evidence and source | Current conclusion |
| --- | --- | --- |
| Progress and regressions | Earlier user reports described improvement from roughly 0.5/10 to 1/10 to 3/10, then called the app fun and responsive. Later reports described the 0.7-era changes as a step backwards. These are subjective reports, not comparable measurements. | Preserve the earlier useful pointer behavior as a comparison baseline. Perfection has not been reached. |
| Window manipulation | Dragging and resizing windows were identified as the intended “wow” interaction. Earlier attempts produced reports that nothing happened. | Native event tests alone do not validate the user's complete grab/move/resize/release workflow. |
| Packaging and permission state | The user requested an identifiable downloadable app and reported repeated permission requests despite permissions appearing enabled. The development process later retained an unchanged native host and updated Python payloads. | The packaging choice preserves local app identity; it does not prove permission UX is solved on another Mac. Bundles still depend on a local Python environment. |
| Full-screen video and desktops | The user reported an unresponsive pointer and unreliable desktop escape from full-screen video. Earlier assistant messages claimed successful switching; later user feedback again reported inconsistent swipes. | Historical assistant success claims are not end-to-end acceptance evidence at the required distance. Test the actual full-screen workflow. |
| Fatigue and distance | The user described distant interaction as a workout and requested a more responsive single pointer with a slower whole-hand scheme. The explicit requirement is now 5–10 feet. | Physical range and effort were not treated as acceptance conditions early enough. |
| Orientation | The user reported particularly good responsiveness with the palm facing downward and requested other orientations. | Synthetic 3D rotation tests verify geometry formulas, not real-camera recognition of rotated or occluded hands. |
| Clicking outside the demo | The user reported that clicking did not work on a Steam game popup. | Delivery into the app's own AppKit test window does not establish compatibility with Steam, games, overlays, or the assistant's question UI. |
| Two-finger scrolling | The user repeatedly reported no scrolling. Version 0.7 switched scroll travel from the palm to the index/middle fingertip center and tolerated brief pose changes. | A plausible cause was addressed, but real usability was not established; the later regression report overrides any broad success claim. |
| Swipe consistency | The user reported unreliable swipes. Fluid mode could disable desktop swipes; open-palm pointing also competed with desktop recognition. | Version 0.8 preserves the setting and reserves finger-chord desktop swipes for exactly three extended fingers. Real recognition can still misclassify an open hand as three fingers. |
| 3D hand mapping | The user requested mapping the entire hand. The code retains all 21 estimated joints, palm orientation and finger curls. | This is camera-derived skeletal estimation. It does not recover an occluded hand with certainty or establish metric room geometry. |
| Room mapping and recall | The user requested room mapping and calibration when waving or calling the app. Saved camera positions and relative hand-size profiles were implemented. | This is a limited substitute for a room scan, not completion of a metric 3D room map. Wave recall, profile matching and optional wake-word reliability need live validation. |
| Click sound | A generated 32 ms acoustic tap was added on emitted mouse presses. | This mixes audio; it does not duck other audio or produce device haptics. A tap means a press was emitted, not that its target accepted it. Perceived loudness and comfort remain unreviewed. |
| Live crash | During a live 0.7 check, changing from a swipe pose to no recognized fingers caused a `None` timestamp subtraction and stopped tracking. | Fixed locally and covered by a regression test plus all 256 finger-mask transition pairs. This was a defect in the new code, not a user setup failure. |
| Halo appearance versus function | After the 0.8 changes, the user said the app was not working but looked good. | Visual feedback is positively received; it is not evidence of control success. |
| Tilt not engaging | An initial live status showed a tracked, armed hand with tilt inactive. Open-palm swipe arbitration and overly strict settling were identified as conflicts. | The revised runtime later reported active tilt and enabled output. Those flags show state progression only, not accurate pointer placement. |
| Present selection failure | The latest user report states approximately **two feet** and inability to select the answer question box. | Treat this as a blocking basic-usability failure. No successful distance claim is justified. The feedback-selection mechanism itself failed. |

## Engineering decisions, rationale, and their costs

These are engineering judgments, not user-approved usability outcomes. Values are heuristics pending measured trials.

| Decision | Rationale | Cost, uncertainty, or review concern |
| --- | --- | --- |
| MediaPipe estimated world landmarks with image-depth fallback | Use existing camera hardware and rotation-aware hand geometry. | Estimated depth and joints can be unstable at distance and under occlusion. Algebraic rotation invariance does not ensure perceptual accuracy. |
| Full 21-joint map and palm coordinate frame | Preserve the thumb and orientation needed for wrist-tilt control. | More visible detail can suggest more certainty than the camera provides. The preview is labeled as an estimate. |
| Request 1920×1080 at 30 fps and read back actual dimensions | Improve available hand detail and expose the capture configuration. The live readback showed that configuration. | Producer fps and frame-age telemetry are not input-to-target latency measurements, and do not quantify hit rate. |
| Reduce the minimum tracking crop from 320 to 160 native pixels, with 2.2× hand-box padding | Give a small, distant hand more of the model input. | Cropping does not add sensor information. A tighter crop may lose fast motion or clip anatomy; boundary recovery needs range trials. |
| Search six smaller image tiles plus a broad central region | Include a resting hand low in the image rather than searching only the middle band. | Search can add reacquisition delay. Coverage tests do not prove model detection in those locations. |
| Keep a 22-native-pixel palm minimum and existing detector confidence thresholds | Avoid gaining apparent responsiveness simply by accepting uncertain tiny hands. | This is not calibrated to physical feet; camera field of view, exposure, resolution and orientation determine whether a distant hand supplies enough detail. |
| Stop uncertain/partial-hand input and cancel stale tracking after about 150 ms | Prevent stale presses and unintended output. | Intermittent recognition may repeatedly disarm the controller, making control feel unresponsive. Re-arming plus tilt settling adds delay. |
| Relax finger classification briefly and debounce transient fist interpretation | Avoid resetting a gesture or clutching on a single uncertain pose estimate. | Adds recognition delay and can preserve an incorrect classification briefly. False gestures remain possible. |
| Finger-relative two-finger scrolling | Permit a flick while the palm stays still. Thresholds now scale with visible palm size, with smaller floors and speed requirements. | Finger estimates may be especially noisy at distance. The current stroke fires once and requires relaxing fingers before another stroke. This may not match natural continuous scrolling. |
| Exactly three extended fingers for desktop chords | Remove the open-palm conflict with pointing and tilt. | Changes the earlier three-or-more-finger scheme. Camera misclassification can still cause unintended desktop actions. Open-palm legacy swipes remain a separate path when finger shortcuts are disabled. |
| Delay two-finger pointer reservation until a brief stable chord | Avoid a one-frame false two-finger reading canceling precision control. | Adds latency; intentional scrolling can initially leave pointer travel enabled. Arbitration needs end-to-end tests. |
| Coarse travel gain can increase up to 2.2× for a small visible palm | Reduce arm travel when far from the camera. | May amplify position noise and varies with apparent palm size/orientation. It must not contaminate tilt gain. |
| Enter tilt after roughly 0.32 seconds of a stationary hand | Allow a rested hand to perform fine positioning. | Automatic switching may be hard to discover and can oscillate. The first positional threshold was too strict. Settling tolerance now scales from 0.008–0.035 normalized image units; exit tolerance spans 0.025–0.06. These values remain unvalidated. |
| Use relative rotation of the complete palm frame | Make fine displacement depend on wrist angle rather than translation or inferred distance. | The camera's orientation noise becomes cursor noise. Direction and gain may not match the user's intuition for every hand orientation. |
| Apply about a 0.35° dead zone and 65 ms angle smoothing | Reduce still-hand drift. | May suppress intended tiny tilts or add lag. Synthetic tests show stable output, not user comfort or target acquisition. |
| Use a non-interactive halo around the front window | Make tracking state visible in other apps and full-screen contexts without intercepting mouse input. | White/green meaning is a design assumption. Green currently means armed/ready, not successful targeting or eye gaze. All relevant full-screen/Space transitions have not been exhaustively verified. |
| Red for no visible hand; amber for insufficient detail, edge clipping or delay | Distinguish loss from a hand that is found but unsuitable for control. | “Out of view” cannot distinguish leaving the frame from occlusion or detector failure. No eye-gaze detector is present. |
| Save room anchors from hand position and apparent size; optional local wake listening | Reuse local processing and avoid requiring a depth camera. | Camera movement or hand orientation can invalidate matching. Voice does not locate the speaker. Wake listening is off by default, and background-audio false activation is unmeasured. |
| Keep five feedback questions and tune from answers | Meet the requested iterative-testing workflow. | Requiring all five selections blocks progress when selection is the failing feature. A typed/voice/deferred route is needed; this chat report is accepted as failure evidence without forcing the form. |

## Verification performed — and what it cannot establish

- **157 automated tests passed** in the local macOS environment after the current correction. They include controller transitions, synthetic geometry, mask transitions, crop coverage, distance-scaled gesture thresholds, tilt math, halo state selection and local attempt logging. Synthetic “near/far” tests change apparent palm size; no person was physically moved between measured distances by those tests.
- The earlier owned-window macOS event check passed single, double and right clicks, press duration, dragging, scrolling and release. It verifies a limited native output path. It does not prove the latest gesture recognizer or target acquisition in another application.
- The live camera reported 1920×1080 at roughly 30 tracking frames per second. Later runtime snapshots showed tilt active, output enabled and move requests being generated. A generated move request is not a successful target selection.
- The user reports liking the visual result. The user also reports continued functional failure and inability to select a feedback option at two feet. **The latter is the acceptance result.**
- There is no completed, scored trial demonstrating all controls at 5, 7–8 or 10 feet. There is no demonstrated “perfect” build.

## Process and communication failures

1. The agent expanded scope (more gestures, room anchors, wake listening, visualization) while basic pointing and selection were not established at the intended range.
2. Passing unit tests and an owned-window event check were reported too prominently relative to unresolved live usability. Installed or emitted does not mean usable.
3. Near-camera observations were not clearly separated from the required 5–10-foot condition until the user corrected the testing context. The latest two-foot report must remain explicit.
4. Several thresholds and mode changes were introduced together. This made it difficult to identify which change caused the regression or to compare against the earlier more usable pointer.
5. The first tilt-settling heuristic and the open-palm desktop shortcut competed with the requested fine-control interaction.
6. An assistant questionnaire was offered before establishing that the user could reliably select its choices. Repeating that requirement would hide the exact failure being investigated.
7. The live crash was caught after an installation. More realistic transition coverage was needed before calling the update ready.
8. Documentation and diagnostic status can lag behind a rapidly changed local payload. This review should be considered together with its source commit and version, not the version string alone.

## Review plan and unresolved work

Priority order is a recommendation for review, not a declaration of completion:

1. **Restore basic selection at two feet** in the actual question box and ordinary native buttons. Record target location/size, hit/miss, unexpected clicks and whether tilt remained active. Permit the user to give typed feedback without selecting the failing form.
2. Compare the earlier useful pointer baseline with the current build using one change at a time. Keep an easy rollback and avoid treating the halo as functional acceptance.
3. Run repeatable trials at user-confirmed 5, 7–8 and 10 feet with the actual camera and lighting. Collect successful and missed tracking frames, interruption duration, target acquisition, accidental gestures and comfort. Agree passing criteria before declaring reliability.
4. Validate tilt entry, direction, gain, hold stability and return to coarse travel with the arm supported. Check that pinching does not jump the pointer or cancel precision unexpectedly.
5. Only after basic selection is usable, validate double click, two-finger scrolling, drag, move/resize and full-screen desktop escape at each required distance. Include Steam/overlay and assistant UI targets rather than only the owned demo.
6. Review the meaning of white/green and whether “looking” requires actual face/gaze input. The current implementation must not be described as gaze detection.
7. Validate room recall and wake listening separately. A metric room scan, accurate distant hand reconstruction and physical haptics remain outside what this build demonstrates.
8. Complete the five-question loop through a route the user can actually operate; preserve failures and unfinished attempts rather than interpreting missing feedback as success.

## Code entry points for review

- [Pointer engine and arbitration](../../src/control_core.py)
- [Wrist-tilt precision](../../src/precision.py)
- [Camera pipeline and runtime gating](../../src/runtime.py)
- [Crop/search strategy](../../src/tracking.py)
- [Finger shortcuts](../../src/shortcuts.py)
- [Halo state meanings](../../src/awareness.py) and [window overlay](../../src/halo.py)
- [Trial and feedback UI](../../src/app.py) and [local attempt recording](../../src/attempts.py)
- [Room-position/wave logic](../../src/positions.py) and [click audio](../../src/feedback_audio.py)
- [Distance/tilt tests](../../tests/test_distance_precision.py)


## Follow-up diagnosis and recovery: 0.8.1

The user reported another backwards step and asked to check the installed controller. The installed Python source matched the public 0.8.0 source. The process was alive, with camera off and pointer paused; existing logs did not establish why it stopped. Old launch errors did not establish a new crash. No completed scored hand trial was available.

Two concrete behavior changes were identified against the earlier 0.5 pointer implementation:

1. `Profile.tilt_precision=True`, including when the key was absent in a legacy profile, silently enabled the new mode. After approximately 0.32 seconds still, `TiltPrecision` supplied rotation deltas in place of translation. Movement below its 0.025–0.06 normalized-image exit radius could therefore be ignored. A hand that paused could feel stuck on subsequent small translations.
2. Fluid translation gained an additional multiplier up to 2.2 based on apparent palm size. That altered the earlier response curve and could amplify aiming motion and jitter. It was not backed by a successful distant-selection trial.

The recovery defaults tilt to off when absent, removes the additional translation gain, and gives Fluid pointer a concrete restore operation: cancel/release, pointer mode, tilt off, finger shortcuts off, reset gesture reservations/momentum, retain thresholds and sensitivity, preserve the first pre-recovery profile locally. Tilt remains an explicit button/menu choice. The update launcher selects this recovery operation rather than automatically enabling desktop gestures. This temporarily prioritizes basic pointing; it does not claim to repair recognition of all requested gestures.

Judgment calls: retain the halo, click sound, tracking pipeline, pinch timing and existing calibration; do not retune several recognition thresholds without a recorded attempt. Keep full-hand edge gating unchanged for this recovery, although it is stricter than the earlier pointer and still needs live review. Physical mouse input continues to yield gesture control. Add a process-local event tag as a second ownership signal, but do not label PID-zero takeover messages as a proven self-trigger loop. Clear camera-off telemetry so stale frame rates cannot suggest a running camera.

Validation: 165 automated checks pass. New regression cases cover stationary-then-translate behavior, legacy opt-in semantics, gain consistency, restoring during a held drag, calibration retention, local backup preservation, camera-stop telemetry and tagged PID-zero events. Explicit tilt tests still exercise rotation behavior. Native delivery and the user’s actual selection task require separate evidence; issue #1 remains open and 5–10-foot usability remains unproven.


Local deployment evidence: the running 0.8.1 sources matched the public recovery files and used the existing approved native host. The camera ran at 30 fps with tilt/finger shortcuts off. The first native-window test was cancelled by an untagged external left click after correct single/double events; it released safely and was preserved locally. The second test completed all click/drag/scroll/release and event-tag checks. Inspection also observed `in_frame=False` with a visible large hand, causing the unchanged whole-hand gate to reject input; the physical cause and distance were not established. This remains a concrete next live-test condition, not a resolved failure. No synthetic or owned-window result is scored as a user gesture success.


## User-directed simplification: 0.8.2

The user said fluidity had acquired too many constraints, asked to walk back requests, and reported that scrolling and desktop controls still did not work. The immediate availability failure in 0.8.1 was an implementation decision: its recovery deliberately disabled both finger shortcut recognition and desktop swipes. It should not be characterized as a newly measured recognition failure.

Judgments in 0.8.2: re-enable scroll/desktop finger controls in Fluid restore, but remove candidate chord ownership of the pointer. A guessed two/three-finger pose must not cancel movement and force rearming. Separate movement from click arming, allow palm pointing with unused fingers outside the image, and remove fist/thumb posture clutching in Fluid mode. Retain palm-loss cancellation, held-button release, explicit pause, external-mouse yielding, jump rejection and visibility checks for the actual gesture fingers. Hidden pinch tips disable clicks/release a drag while the visible palm can keep moving.

Walked back in the default Fluid scheme: automatic settle-to-tilt, figure-dependent speed, two-finger curl double click, and automatic waving to recall a saved room profile. Tilt is still explicit; other schemes and manual position commands retain their functions. Two ordinary pinches supply double click; two-finger flick supplies scroll; exactly three visible fingers supply desktop swipe. No threshold was relaxed simply to produce an apparent test pass. Synthetic tests caught and corrected an arming-time filter-baseline reset that produced a backwards pointer delta.

179 tests pass, including recognition through the runtime and separation of a candidate chord from pointer ownership. Local diagnostics expose reasons a chord is gated. These do not establish live success, especially at 5–10 feet, on the assistant UI or in a Steam overlay. Issue #1 remains open.
