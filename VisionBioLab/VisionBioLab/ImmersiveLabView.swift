import SwiftUI
import RealityKit

/// The immersive 3D lab bench. Reads from the shared `LabModel` and updates the
/// tube / pipette visuals as the user works through the protocol.
///
/// Two ways to interact:
///  • Tap a reagent to load the pipette, tap the tube to dispense.
///  • Or grab the pipette and drag it onto a reagent (to draw it up) and onto
///    the tube (to dispense). Drop the full tube to mix the reaction.
struct ImmersiveLabView: View {
    @Environment(LabModel.self) private var model

    // Long-lived entities we mutate in response to state changes / drags.
    @State private var sceneRoot = Entity()
    @State private var pipette = Entity()
    @State private var pipetteLiquid = ModelEntity()
    @State private var eppendorfLiquids = Entity()

    // Drag bookkeeping.
    @State private var dragging = false

    var body: some View {
        RealityView { content in
            LabSceneBuilder.build(root: sceneRoot,
                                  pipette: pipette,
                                  pipetteLiquid: pipetteLiquid,
                                  eppendorfLiquids: eppendorfLiquids,
                                  model: model)
            content.add(sceneRoot)
        }
        // Tap a reagent to load; tap the tube to dispense (or mix when full).
        .gesture(
            SpatialTapGesture()
                .targetedToAnyEntity()
                .onEnded { value in
                    handleHit(LabSceneBuilder.classifyTap(on: value.entity))
                }
        )
        // Grab and drag the pipette around the bench.
        .gesture(
            DragGesture()
                .targetedToAnyEntity()
                .onChanged { value in
                    guard LabSceneBuilder.isPipette(value.entity),
                          let parent = pipette.parent else { return }
                    dragging = true
                    pipette.position = value.convert(value.location3D,
                                                     from: .local, to: parent)
                }
                .onEnded { value in
                    guard dragging else { return }
                    dragging = false

                    // What did we drop the pipette on?
                    let worldPos = pipette.position(relativeTo: nil)
                    handleHit(LabSceneBuilder.dropTarget(near: worldPos, in: sceneRoot))

                    // Return the pipette to its stand.
                    var home = pipette.transform
                    home.translation = LabSceneBuilder.pipetteHome
                    pipette.move(to: home, relativeTo: pipette.parent, duration: 0.25)
                }
        )
        // Keep the 3D visuals in sync with the model.
        .onChange(of: model.loadedReagent) { _, loaded in
            LabSceneBuilder.refreshPipette(pipetteLiquid, loaded: loaded)
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

    /// Apply an interaction with a reagent bottle or the tube.
    private func handleHit(_ hit: LabSceneBuilder.Hit) {
        switch hit {
        case .reagent(let id):
            if let reagent = LabProtocol.reagent(id) {
                model.loadPipette(with: reagent)
            }
        case .tube:
            if model.canMix {
                model.mix()
            } else {
                model.dispenseIntoTube()
            }
        case .none:
            break
        }
    }
}
