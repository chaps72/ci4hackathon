import RealityKit
import UIKit
import simd

/// Builds and updates the 3D lab bench scene using procedurally generated
/// RealityKit primitives — no external 3D assets required.
enum LabSceneBuilder {

    // Name prefixes used to identify what the user tapped.
    static let reagentPrefix = "reagent:"
    static let tubeName = "eppendorf"

    /// Build the whole bench into `root`. `pipetteLiquid` and `eppendorfLiquids`
    /// are passed in so the view can recolor / refill them later without
    /// rebuilding the scene.
    static func build(root: Entity,
                      pipetteLiquid: ModelEntity,
                      eppendorfLiquids: Entity,
                      model: LabModel) {

        root.children.removeAll()

        // Lift the whole bench up near eye level and pull it ~0.7 m in front so
        // the objects (not just the floating labels) are clearly in view.
        // (In a mixed immersive space the origin sits on the floor.)
        root.position = [0, 0.35, -0.7]

        root.addChild(makeBench())
        root.addChild(makeReagentRack(model: model))
        root.addChild(makePipette(liquid: pipetteLiquid))
        root.addChild(makeEppendorf(liquids: eppendorfLiquids))
        root.addChild(makeTitleLabel())
    }

    // MARK: - Bench

    private static func makeBench() -> Entity {
        let topThickness: Float = 0.04
        let benchTop = ModelEntity(
            mesh: .generateBox(width: 1.0, height: topThickness, depth: 0.5,
                               cornerRadius: 0.01),
            materials: [unlit(0.85, 0.86, 0.88)]
        )
        benchTop.position = [0, 0.9, 0]
        return benchTop
    }

    // MARK: - Reagent rack

    private static func makeReagentRack(model: LabModel) -> Entity {
        let rack = Entity()
        let benchTopY: Float = 0.92
        let count = model.steps.count
        let spacing: Float = 0.16
        let startX = -spacing * Float(count - 1) / 2.0

        for (index, step) in model.steps.enumerated() {
            let reagent = step.reagent
            let x = startX + spacing * Float(index)

            let bottle = makeReagentBottle(reagent: reagent)
            bottle.position = [x, benchTopY, -0.12]
            bottle.name = reagentPrefix + reagent.id
            rack.addChild(bottle)

            let label = makeTextEntity(reagent.name, fontSize: 0.018,
                                       color: .white, maxWidth: 0.15)
            label.position = [x, benchTopY + 0.17, -0.12]
            rack.addChild(label)
        }
        return rack
    }

    /// A small bottle: clear-ish body with a colored liquid inside and a cap.
    private static func makeReagentBottle(reagent: Reagent) -> Entity {
        let bottle = Entity()

        let bodyHeight: Float = 0.12
        let body = ModelEntity(
            mesh: .generateCylinder(height: bodyHeight, radius: 0.028),
            materials: [glassy()]
        )
        body.position = [0, bodyHeight / 2, 0]

        let liquid = ModelEntity(
            mesh: .generateCylinder(height: bodyHeight * 0.7, radius: 0.024),
            materials: [unlit(reagent.color)]
        )
        liquid.position = [0, bodyHeight * 0.35, 0]

        let cap = ModelEntity(
            mesh: .generateCylinder(height: 0.02, radius: 0.03),
            materials: [unlit(0.2, 0.2, 0.22)]
        )
        cap.position = [0, bodyHeight + 0.01, 0]

        bottle.addChild(body)
        bottle.addChild(liquid)
        bottle.addChild(cap)

        // Make the whole bottle tappable.
        makeTappable(bottle, radius: 0.05, height: bodyHeight)
        return bottle
    }

    // MARK: - Pipette

    private static func makePipette(liquid: ModelEntity) -> Entity {
        let pipette = Entity()
        let benchTopY: Float = 0.92

        let bodyHeight: Float = 0.18
        let body = ModelEntity(
            mesh: .generateCylinder(height: bodyHeight, radius: 0.01),
            materials: [unlit(0.15, 0.45, 0.85)]
        )
        body.position = [0, bodyHeight / 2, 0]

        let plunger = ModelEntity(
            mesh: .generateCylinder(height: 0.03, radius: 0.012),
            materials: [unlit(0.85, 0.85, 0.88)]
        )
        plunger.position = [0, bodyHeight + 0.015, 0]

        // The tip — a thin cone whose color shows what's loaded.
        let tip = ModelEntity(
            mesh: .generateCone(height: 0.05, radius: 0.008),
            materials: [unlit(0.7, 0.7, 0.72)]
        )
        tip.position = [0, -0.025, 0]
        tip.scale = [1, -1, 1]  // point the cone downward

        // The colored "liquid" inside the tip; hidden until something is loaded.
        liquid.model = ModelComponent(
            mesh: .generateCylinder(height: 0.02, radius: 0.005),
            materials: [unlit(0.7, 0.7, 0.72)]
        )
        liquid.position = [0, 0.005, 0]
        liquid.isEnabled = false

        pipette.addChild(body)
        pipette.addChild(plunger)
        pipette.addChild(tip)
        pipette.addChild(liquid)

        // Stand the pipette upright on the right side of the bench.
        pipette.position = [0.42, benchTopY + 0.025, 0.0]
        return pipette
    }

    // MARK: - Eppendorf tube

    private static func makeEppendorf(liquids: Entity) -> Entity {
        let tube = Entity()
        let benchTopY: Float = 0.92

        let bodyHeight: Float = 0.05
        let body = ModelEntity(
            mesh: .generateCylinder(height: bodyHeight, radius: 0.013),
            materials: [glassy()]
        )
        body.position = [0, bodyHeight / 2, 0]

        let cone = ModelEntity(
            mesh: .generateCone(height: 0.025, radius: 0.013),
            materials: [glassy()]
        )
        cone.position = [0, -0.0125, 0]
        cone.scale = [1, -1, 1]

        let cap = ModelEntity(
            mesh: .generateCylinder(height: 0.012, radius: 0.016),
            materials: [unlit(0.95, 0.95, 0.55)]
        )
        cap.position = [0, bodyHeight + 0.006, 0]

        // Container for the stacked liquid layers added as you dispense.
        liquids.name = "\(tubeName)-liquids"
        liquids.position = [0, 0.001, 0]

        tube.addChild(body)
        tube.addChild(cone)
        tube.addChild(cap)
        tube.addChild(liquids)

        tube.name = tubeName
        // Make the tube tappable (to dispense into it).
        makeTappable(tube, radius: 0.04, height: bodyHeight + 0.05)

        // Front and center on the bench.
        tube.position = [0.0, benchTopY + 0.025, 0.12]

        let label = makeTextEntity("Eppendorf tube", fontSize: 0.016,
                                   color: .white, maxWidth: 0.2)
        label.position = [0.0, benchTopY + 0.13, 0.12]
        tube.addChild(label)

        return tube
    }

    // MARK: - Live updates

    /// Recolor the pipette tip's liquid based on what's loaded.
    static func refreshPipette(_ liquid: ModelEntity, loaded: Reagent?) {
        if let reagent = loaded {
            liquid.model?.materials = [unlit(reagent.color)]
            liquid.isEnabled = true
        } else {
            liquid.isEnabled = false
        }
    }

    /// Rebuild the stack of liquid layers inside the Eppendorf tube.
    static func refreshEppendorf(_ container: Entity, dispensed: [Reagent]) {
        container.children.removeAll()
        guard !dispensed.isEmpty else { return }

        // Stack thin disks from the bottom of the tube upward.
        let layerHeight: Float = 0.006
        var y: Float = 0.004
        for reagent in dispensed {
            let layer = ModelEntity(
                mesh: .generateCylinder(height: layerHeight, radius: 0.011),
                materials: [unlit(reagent.color)]
            )
            layer.position = [0, y, 0]
            container.addChild(layer)
            y += layerHeight
        }
    }

    // MARK: - Tap handling

    /// Walk up from a tapped entity to find the meaningful named ancestor and
    /// report what was hit.
    enum Hit {
        case reagent(String)
        case tube
        case none
    }

    static func classifyTap(on entity: Entity) -> Hit {
        var current: Entity? = entity
        while let e = current {
            if e.name == tubeName { return .tube }
            if e.name.hasPrefix(reagentPrefix) {
                return .reagent(String(e.name.dropFirst(reagentPrefix.count)))
            }
            current = e.parent
        }
        return .none
    }

    // MARK: - Helpers

    private static func makeTappable(_ entity: Entity, radius: Float, height: Float) {
        let shape = ShapeResource.generateCapsule(height: height, radius: radius)
        entity.components.set(CollisionComponent(shapes: [shape]))
        entity.components.set(InputTargetComponent())
        // Subtle hover highlight when the user looks at it.
        entity.components.set(HoverEffectComponent())
    }

    private static func makeTitleLabel() -> Entity {
        let label = makeTextEntity("Virtual Bio Lab — Pipetting Protocol",
                                   fontSize: 0.03, color: .white, maxWidth: 0.9)
        label.position = [0, 1.35, -0.1]
        return label
    }

    private static func makeTextEntity(_ text: String,
                                       fontSize: CGFloat,
                                       color: UIColor,
                                       maxWidth: CGFloat) -> ModelEntity {
        let mesh = MeshResource.generateText(
            text,
            extrusionDepth: 0.001,
            font: .systemFont(ofSize: fontSize),
            containerFrame: CGRect(x: 0, y: 0, width: maxWidth, height: fontSize * 2.2),
            alignment: .center,
            lineBreakMode: .byTruncatingTail
        )
        let entity = ModelEntity(mesh: mesh, materials: [unlitMaterial(color)])
        // generateText origins at the lower-left of the container; nudge so the
        // text is roughly centered on the entity's position.
        entity.position.x -= Float(maxWidth / 2)
        return entity
    }

    // MARK: - Materials

    private static func unlit(_ c: ReagentColor) -> UnlitMaterial {
        UnlitMaterial(color: c.uiColor)
    }

    private static func unlit(_ r: CGFloat, _ g: CGFloat, _ b: CGFloat) -> UnlitMaterial {
        UnlitMaterial(color: UIColor(red: r, green: g, blue: b, alpha: 1.0))
    }

    private static func unlitMaterial(_ color: UIColor) -> UnlitMaterial {
        UnlitMaterial(color: color)
    }

    /// A frosted "glass" look for tube and bottle bodies — kept fairly opaque so
    /// the glassware is easy to see against passthrough.
    private static func glassy() -> UnlitMaterial {
        var material = UnlitMaterial(color: UIColor(white: 0.85, alpha: 0.55))
        material.blending = .transparent(opacity: 0.55)
        return material
    }
}
