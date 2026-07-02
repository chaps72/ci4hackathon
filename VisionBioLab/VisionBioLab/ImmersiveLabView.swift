import SwiftUI
import RealityKit

/// The immersive 3D lab. The interaction is deliberately simple: **tap a reagent
/// bottle, then tap the tube.** The pipette animates itself — flying over the
/// bottle, drawing the liquid up, then moving to the tube and dispensing — so it
/// looks like you're running the experiment without any fiddly grabbing.
struct ImmersiveLabView: View {
    @Environment(LabModel.self) private var model

    @State private var sceneRoot = Entity()
    @State private var pipette = Entity()
    @State private var pipetteLiquid = ModelEntity()
    @State private var eppendorfLiquids = Entity()
    @State private var guidanceText = ModelEntity()

    /// True while the pipette animation is playing (ignore taps until done).
    @State private var busy = false

    var body: some View {
        RealityView { content in
            LabSceneBuilder.build(root: sceneRoot,
                                  pipette: pipette,
                                  pipetteLiquid: pipetteLiquid,
                                  eppendorfLiquids: eppendorfLiquids,
                                  guidance: guidanceText,
                                  model: model)
            content.add(sceneRoot)
            updateGuidance()
        }
        .gesture(
            SpatialTapGesture()
                .targetedToAnyEntity()
                .onEnded { value in
                    handleTap(LabSceneBuilder.classifyTap(on: value.entity))
                }
        )
        .onChange(of: model.loadedReagent) { old, loaded in
            LabSceneBuilder.refreshPipette(pipetteLiquid, loaded: loaded)
            if let old { LabSceneBuilder.setBottleOpen(id: old.id, in: sceneRoot, open: false) }
            if let loaded { LabSceneBuilder.setBottleOpen(id: loaded.id, in: sceneRoot, open: true) }
            updateGuidance()
        }
        .onChange(of: model.dispensedReagents) { _, dispensed in
            LabSceneBuilder.refreshEppendorf(eppendorfLiquids,
                                             dispensed: dispensed,
                                             mixed: model.isMixed)
            updateGuidance()
        }
        .onChange(of: model.isMixed) { _, mixed in
            LabSceneBuilder.refreshEppendorf(eppendorfLiquids,
                                             dispensed: model.dispensedReagents,
                                             mixed: mixed)
            if mixed { LabSceneBuilder.playMixAnimation(eppendorfLiquids) }
            updateGuidance()
        }
    }

    /// Refresh the floating sign with the next instruction.
    private func updateGuidance() {
        LabSceneBuilder.setGuidance(guidanceText, text: guidanceMessage())
    }

    private func guidanceMessage() -> String {
        if model.isMixed {
            return "Done! Reaction assembled.\nPress Restart to run again."
        }
        if model.canMix {
            return "All reagents added!\nTap the tube to MIX."
        }
        if let loaded = model.loadedReagent {
            return "Pipette holds \(loaded.name).\nNow tap the tube to dispense."
        }
        let prefix = model.lastActionWasError ? "Out of order — tube reset.\n" : ""
        if let step = model.currentStep {
            return prefix + "Step \(step.order) of \(model.steps.count): tap the \(step.reagent.name) bottle."
        }
        return ""
    }

    // MARK: - Interaction

    private func handleTap(_ hit: LabSceneBuilder.Hit) {
        guard !busy else { return }
        switch hit {
        case .reagent(let id):
            // Pick up a reagent only if the pipette is free.
            guard model.loadedReagent == nil, !model.isComplete,
                  let reagent = LabProtocol.reagent(id) else { return }
            drawReagent(reagent)
        case .tube:
            if model.canMix { model.mix(); return }
            guard model.loadedReagent != nil else { return }
            dispenseIntoTube()
        case .none:
            break
        }
    }

    /// Tap a bottle → pipette flies over, uncaps, and draws the reagent up.
    private func drawReagent(_ reagent: Reagent) {
        let name = LabSceneBuilder.reagentPrefix + reagent.id
        guard let bottle = LabSceneBuilder.entity(named: name, in: sceneRoot),
              let parent = pipette.parent else { return }
        let base = bottle.position(relativeTo: parent)
        visit(x: base.x, z: base.z, mouthY: base.y + 0.19) {
            model.loadPipette(with: reagent)
        }
    }

    /// Tap the tube → pipette flies over and dispenses what it's holding.
    private func dispenseIntoTube() {
        guard let tube = LabSceneBuilder.entity(named: LabSceneBuilder.tubeName, in: sceneRoot),
              let parent = pipette.parent else { return }
        let base = tube.position(relativeTo: parent)
        visit(x: base.x, z: base.z, mouthY: base.y + 0.06) {
            model.dispenseIntoTube()
        }
    }

    // MARK: - Pipette animation

    /// Fly the pipette from its stand → above the target → down into it → back
    /// up → home, running `bottomAction` (draw / dispense) at the lowest point.
    private func visit(x: Float, z: Float, mouthY: Float,
                       bottomAction: @escaping () -> Void) {
        busy = true
        let hoverY = mouthY + 0.16
        let dipY = mouthY + 0.03
        let home = LabSceneBuilder.pipetteHome

        move(to: [x, hoverY, z], duration: 0.5)                 // travel over target
        after(0.55) { move(to: [x, dipY, z], duration: 0.3) }   // dip in
        after(0.95, bottomAction)                               // draw / dispense
        after(1.2) { move(to: [x, hoverY, z], duration: 0.3) }  // lift out
        after(1.6) { move(to: home, duration: 0.5) }            // return to stand
        after(2.2) { busy = false }
    }

    private func move(to translation: SIMD3<Float>, duration: Double) {
        guard let parent = pipette.parent else { return }
        var t = pipette.transform
        t.translation = translation
        pipette.move(to: t, relativeTo: parent, duration: duration)
    }

    private func after(_ seconds: Double, _ action: @escaping () -> Void) {
        DispatchQueue.main.asyncAfter(deadline: .now() + seconds, execute: action)
    }
}
