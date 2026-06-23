import SwiftUI
import RealityKit

/// Retains scene subscriptions and the running dip state across frames.
@MainActor
final class LabRuntime {
    var subscriptions: [EventSubscription] = []
    var didSetup = false
    /// Identifier of the target the pipette tip is currently dipped into, so we
    /// only act once per dip (not every frame).
    var currentDip: String?
}

/// The immersive 3D lab. Reads from the shared `LabModel`, lets you grab objects
/// with your hands (RealityKit ManipulationComponent — two-handed on device),
/// and draws / dispenses when you dip the pipette tip into a bottle or the tube.
struct ImmersiveLabView: View {
    @Environment(LabModel.self) private var model

    @State private var sceneRoot = Entity()
    @State private var pipette = Entity()
    @State private var pipetteLiquid = ModelEntity()
    @State private var eppendorfLiquids = Entity()
    @State private var runtime = LabRuntime()

    var body: some View {
        RealityView { content in
            LabSceneBuilder.build(root: sceneRoot,
                                  pipette: pipette,
                                  pipetteLiquid: pipetteLiquid,
                                  eppendorfLiquids: eppendorfLiquids,
                                  model: model)
            content.add(sceneRoot)

            setUpDipDetection(content)
        }
        // Tap a reagent / the tube as a quick alternative to dipping.
        .gesture(
            SpatialTapGesture()
                .targetedToAnyEntity()
                .onEnded { value in
                    handleHit(LabSceneBuilder.classifyTap(on: value.entity))
                }
        )
        // Keep the 3D visuals in sync with the model.
        .onChange(of: model.loadedReagent) { old, loaded in
            LabSceneBuilder.refreshPipette(pipetteLiquid, loaded: loaded)
            if let old { LabSceneBuilder.setBottleOpen(id: old.id, in: sceneRoot, open: false) }
            if let loaded { LabSceneBuilder.setBottleOpen(id: loaded.id, in: sceneRoot, open: true) }
        }
        .onChange(of: model.dispensedReagents) { _, dispensed in
            LabSceneBuilder.refreshEppendorf(eppendorfLiquids,
                                             dispensed: dispensed,
                                             mixed: model.isMixed)
        }
        .onChange(of: model.isMixed) { _, mixed in
            LabSceneBuilder.refreshEppendorf(eppendorfLiquids,
                                             dispensed: model.dispensedReagents,
                                             mixed: mixed)
            if mixed { LabSceneBuilder.playMixAnimation(eppendorfLiquids) }
        }
    }

    /// Every frame, check whether the pipette tip has been dipped into a bottle
    /// (draw up) or the tube (dispense / mix), acting once per dip.
    private func setUpDipDetection(_ content: RealityViewContent) {
        guard !runtime.didSetup else { return }
        runtime.didSetup = true

        let model = self.model
        let root = sceneRoot
        let pip = pipette
        let runtime = self.runtime

        let token = content.subscribe(to: SceneEvents.Update.self) { _ in
            let tip = pip.convert(position: [0, -0.06, 0], to: nil)
            let hit = LabSceneBuilder.dropTarget(near: tip, in: root, threshold: 0.2)

            // Only act when the tip enters a new target.
            guard hit.dipID != runtime.currentDip else { return }
            runtime.currentDip = hit.dipID

            switch hit {
            case .reagent(let id):
                if let reagent = LabProtocol.reagent(id) { model.loadPipette(with: reagent) }
            case .tube:
                if model.canMix { model.mix() } else { model.dispenseIntoTube() }
            case .none:
                break
            }
        }
        runtime.subscriptions.append(token)
    }

    /// Apply a tap interaction with a reagent bottle or the tube.
    private func handleHit(_ hit: LabSceneBuilder.Hit) {
        switch hit {
        case .reagent(let id):
            if let reagent = LabProtocol.reagent(id) { model.loadPipette(with: reagent) }
        case .tube:
            if model.canMix { model.mix() } else { model.dispenseIntoTube() }
        case .none:
            break
        }
    }
}
