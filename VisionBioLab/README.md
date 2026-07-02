# VisionBioLab — a basic virtual bio lab for Apple Vision Pro

A minimal **visionOS** app that teaches a pipetting protocol in spatial 3D. You
set up a PCR-style master mix by pipetting reagents into an Eppendorf tube **in
the correct order**, following a protocol sheet. Get the order wrong and the
tube resets — just like the real bench.

> Built with SwiftUI + RealityKit. All 3D objects are generated procedurally, so
> there are **no external 3D assets** to download — open and run.

## What's in the lab

- **A full virtual lab room** (fully immersive — walls, floor, ceiling light
  panels, and a back counter with glassware) that replaces passthrough.
- **A workbench** in front of you holding everything.
- **Labeled reagent bottles** (color-coded) in a rack — Nuclease-free Water,
  Reaction Buffer (10×), dNTP Mix, Template DNA, DNA Polymerase — each with a
  cap that pops open when you draw from it.
- **A pipette** whose tip shows the color of whatever is currently loaded.
- **An Eppendorf tube** in a stand that fills with colored liquid layers as you
  dispense.
- **A protocol sheet** (the app window) listing the ordered steps with live
  check-marks and a status readout.

## How to use it

Two ways to work — use whichever feels better:

**Tap (hands-free):**
1. **Look at a reagent bottle and pinch.** The pipette flies over, uncaps the
   bottle, and draws the reagent up.
2. **Look at the tube and pinch.** The pipette dispenses; a colored layer appears.

**Grab the pipette (hands-on):**
1. **Pinch and hold the pipette, then dip its tip into a bottle** — the cap
   opens as you approach and it draws the reagent up on release.
2. **Dip the pipette into the tube** to dispense. It returns to its stand.

Then, for both:
3. Follow the protocol **in order** (water → buffer → dNTPs → template →
   polymerase last). A wrong order shows an error and empties the tube.
4. Once all five reagents are in, **pinch the tube** (or press *Mix / run
   reaction* in the window) to vortex-mix the reaction.
5. **Restart** to try again.

You can also drive everything from the app **window** (reagent buttons, Dispense,
Mix, Restart) if you prefer buttons to looking around.

Both the 3D scene and the window drive the same shared state, so you can use
whichever is more convenient.

## Requirements & running it

visionOS apps must be **built and run with Xcode on a Mac** — they cannot be
compiled on Linux.

- macOS with **Xcode 16** or later
- The **visionOS SDK** (install via Xcode → Settings → Components)

Steps:

```text
1. Open VisionBioLab.xcodeproj in Xcode.
2. Select the "VisionBioLab" scheme and a destination:
   - "Apple Vision Pro" simulator, or
   - a real Vision Pro (set your signing Team under
     Target → Signing & Capabilities first).
3. Press Run (⌘R).
4. When the window appears, tap "Enter Lab" to place the bench in your space.
```

> If you run on device, set a Development Team in **Signing & Capabilities**
> (the project ships with automatic signing and a placeholder bundle id
> `com.ci4hackathon.VisionBioLab` — change it to one you own).

## Project layout

```
VisionBioLab/
  VisionBioLab.xcodeproj/        Xcode project (file-system synchronized)
  VisionBioLab/
    VisionBioLabApp.swift        App entry: window + immersive space
    ContentView.swift            Protocol sheet, reagent controls, status
    ImmersiveLabView.swift       RealityView 3D scene + tap handling
    LabSceneBuilder.swift        Builds/updates bench, bottles, pipette, tube
    LabModel.swift               Shared state + protocol-order rules
    Protocol.swift               Reagents and the ordered protocol steps
```

## Extending it

- Add new reagents / steps in `Protocol.swift` — the UI and 3D scene adapt.
- Swap procedural shapes for real USDZ models by loading them in
  `LabSceneBuilder`.
- Add hand-tracking so you physically grab the pipette instead of tapping.
- Track timing/accuracy and write a lab report.
