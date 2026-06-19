import SwiftUI
import RealityKit

/// The immersive 3D lab bench. Reads from the shared `LabModel` and updates the
/// tube / pipette visuals as the user works through the protocol.
struct ImmersiveLabView: View {
    @Environment(LabModel.self) private var model

    // Long-lived entities we mutate in response to state changes.
    @State private var sceneRoot = Entity()
    @State private var pipetteLiquid = ModelEntity()
    @State private var eppendorfLiquids = Entity()

    var body: some View {
        RealityView { content in
            LabSceneBuilder.build(root: sceneRoot,
                                  pipetteLiquid: pipetteLiquid,
                                  eppendorfLiquids: eppendorfLiquids,
                                  model: model)
            content.add(sceneRoot)
        }
        // Tap a reagent bottle to load the pipette; tap the tube to dispense.
        .gesture(
            SpatialTapGesture()
                .targetedToAnyEntity()
                .onEnded { value in
                    switch LabSceneBuilder.classifyTap(on: value.entity) {
                    case .reagent(let id):
                        if let reagent = LabProtocol.reagent(id) {
                            model.loadPipette(with: reagent)
                        }
                    case .tube:
                        model.dispenseIntoTube()
                    case .none:
                        break
                    }
                }
        )
        // Keep the 3D visuals in sync with the model.
        .onChange(of: model.loadedReagent) { _, loaded in
            LabSceneBuilder.refreshPipette(pipetteLiquid, loaded: loaded)
        }
        .onChange(of: model.dispensedReagents) { _, dispensed in
            LabSceneBuilder.refreshEppendorf(eppendorfLiquids, dispensed: dispensed)
        }
    }
}
