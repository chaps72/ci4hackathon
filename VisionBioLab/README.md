# VisionBioLab — a basic virtual bio lab for Apple Vision Pro

A minimal **visionOS** app that teaches a pipetting protocol in spatial 3D. You
set up a PCR-style master mix by pipetting reagents into an Eppendorf tube **in
the correct order**, following a protocol sheet. Get the order wrong and the
tube resets — just like the real bench.

> Built with SwiftUI + RealityKit. All 3D objects are generated procedurally, so
> there are **no external 3D assets** to download — open and run.

## What's in the lab

A deliberately simple setup: mix **two solutions** into **one tube** with **one
pipette**.

- **A clean, bright virtual lab room** (fully immersive) with a workbench.
- **Two source vials** on the left — **Solution A** (blue) and **Solution B**
  (yellow) — each with a cap that pops open when you draw from it.
- **A micropipette** whose tip shows the solution currently loaded.
- **One Eppendorf tube** in a stand. Add A then B and they mix into the green
  product.
- **A floating sign** (and the app window) telling you the next step.

## How to use it

1. **Look at Solution A and pinch** (in the simulator: point at it and click).
   The pipette flies over, dips in, and draws the blue solution up.
2. **Look at the tube and pinch.** The pipette moves over and dispenses it.
3. **Pinch Solution B**, then **pinch the tube** to add the yellow solution.
4. **Pinch the tube once more** (or press *Mix / run reaction* in the window) to
   mix — A + B turn green.
5. **Restart** to run it again.

The floating sign always shows the next step, and you can also drive everything
from the app **window** (solution buttons, Dispense, Mix, Restart).

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
