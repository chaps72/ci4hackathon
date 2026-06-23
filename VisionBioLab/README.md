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

You can work either by tapping or by physically grabbing the pipette:

**Tap mode**
1. **Tap a reagent** (a bottle in 3D, or a button in the window) to draw it up
   into the pipette.
2. **Tap the Eppendorf tube** (or the *Dispense* button) to add it.

**Grab mode (direct manipulation)**

Everything is grabbable with your hands via RealityKit's ManipulationComponent —
on a real Vision Pro you can use **both hands at once** (e.g. hold a reagent in
one hand and the pipette in the other). Objects stay where you release them.

1. **Pick up and move** the reagent bottles, the tube, and the pipette.
2. **Dip the pipette tip into a reagent bottle** to draw it up (the cap pops
   open and the tip changes color).
3. **Dip the pipette tip into the tube** to dispense. Dip into the full tube to
   mix.

In the simulator you only have a mouse, so you grab one object at a time;
two-handed manipulation requires a real device.

Then, for both modes:
3. Follow the protocol **in order** (water → buffer → dNTPs → template →
   polymerase last). A wrong order shows an error and empties the tube.
4. Once all five reagents are in, **Mix / run reaction** (the button, or drop
   the pipette on the full tube) — the layers blend into the finished reaction.
5. **Restart** to try again.

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
