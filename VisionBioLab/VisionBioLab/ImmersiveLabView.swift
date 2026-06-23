import SwiftUI
import RealityKit

/// The immersive 3D lab. Reads from the shared `LabModel` and updates the
/// tube / pipette visuals as the user works through the protocol.
///
/// Interaction:
///  • Tap a reagent to load the pipette, tap the tube to dispense.
///  • Or grab things directly: pick up and move the reagent bottles / tube, and
///    grab the pipette and dip it into a bottle (draws it up) and into the tube
///    (dispenses). On a real Vision Pro you can use both hands at once; in the
///    simulator you grab one thing at a time with the mouse.
struct ImmersiveLabView: View {
    @Environment(LabModel.self) private var model

    // Long-lived entities we mutate in response to state changes / drags.
    @State private var sceneRoot = Entity()
    @State private var pipette = Entity()
    @State private var pipetteLiquid = ModelEntity()
    @State private var eppendorfLiquids = Entity()

    // Drag bookkeeping.
    @State private var draggedEntity: Entity?
    @State private var dragOffset: SIMD3<Float>?

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
        // Grab and move the pipette / bottles / tube directly.
        .simultaneousGesture(
            DragGesture()
                .targetedToAnyEntity()
                .onChanged { value in
                    // Figure out what we grabbed (once per drag).
                    let grabbed: Entity
                    if let current = draggedEntity {
                        grabbed = current
                    } else if let root = LabSceneBuilder.grabbable(value.entity) {
                        grabbed = root
                        draggedEntity = root
                    } else {
                        return
                    }

                    guard let parent = grabbed.parent else { return }
                    let pointer = value.convert(value.location3D, from: .local, to: parent)
                    if dragOffset == nil { dragOffset = grabbed.position - pointer }
                    grabbed.position = pointer + (dragOffset ?? .zero)
                }
                .onEnded { _ in
                    defer { draggedEntity = nil; dragOffset = nil }
                    guard let grabbed = draggedEntity else { return }

                    // Only the pipette triggers loading / dispensing — based on
                    // where its tip ends up. Bottles and the tube just stay put.
                    if grabbed.name == LabSceneBuilder.pipetteName {
                        let tip = grabbed.convert(position: [0, -0.06, 0], to: nil)
                        handleHit(LabSceneBuilder.dropTarget(near: tip, in: sceneRoot))

                        var home = grabbed.transform
                        home.translation = LabSceneBuilder.pipetteHome
                        grabbed.move(to: home, relativeTo: grabbed.parent, duration: 0.25)
                    }
                }
        )
        // Keep the 3D visuals in sync with the model.
        .onChange(of: model.loadedReagent) { old, loaded in
            LabSceneBuilder.refreshPipette(pipetteLiquid, loaded: loaded)
            // Uncap the bottle being drawn from; recap the previous one.
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
