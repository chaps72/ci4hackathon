import RealityKit
import UIKit
import simd

/// Builds and updates the 3D virtual lab. Solid surfaces use lit `SimpleMaterial`
/// (shaded by the scene's directional lights) for a realistic look, while the
/// liquids, labels, and guidance sign stay unlit so the informative bits are
/// always clearly visible.
enum LabSceneBuilder {

    // Names used to identify what the user tapped.
    static let reagentPrefix = "reagent:"
    static let tubeName = "eppendorf"
    static let pipetteName = "pipette"
    static let capName = "cap"

    private static let benchTopY: Float = 0.99
    private static let benchGroupOffset: SIMD3<Float> = [0, 0, -1.05]

    private static let capClosedLocal: SIMD3<Float> = [0, 0.205, 0]
    private static let capOpenLocal: SIMD3<Float> = [0.05, 0.275, 0]

    /// Resting position of the pipette (local to the bench group).
    static let pipetteHome: SIMD3<Float> = [0.46, benchTopY + 0.09, 0.06]

    // MARK: - Build

    static func build(root: Entity,
                      pipette: Entity,
                      pipetteLiquid: ModelEntity,
                      eppendorfLiquids: Entity,
                      guidance: ModelEntity,
                      model: LabModel) {

        root.children.removeAll()
        root.transform = .identity

        root.addChild(makeLighting())
        root.addChild(makeRoom())

        let bench = Entity()
        bench.position = benchGroupOffset
        bench.addChild(makeWorkbench())
        bench.addChild(makeReagentRack(model: model))
        bench.addChild(makePipetteStand())
        bench.addChild(makePipette(into: pipette, liquid: pipetteLiquid))
        bench.addChild(makeEppendorf(liquids: eppendorfLiquids))

        let panel = makeGuidancePanel(text: guidance)
        panel.position = [0, benchTopY + 0.36, -0.16]
        bench.addChild(panel)
        root.addChild(bench)
    }

    // MARK: - Lighting

    /// Three directional lights (key + two fills) give even, bright, shaded
    /// lighting so nothing goes dark in the fully immersive space.
    private static func makeLighting() -> Entity {
        let lights = Entity()
        let aim: SIMD3<Float> = [0, benchTopY, -1.05]

        func directional(_ intensity: Float, from: SIMD3<Float>) {
            let e = Entity()
            e.components.set(DirectionalLightComponent(color: .white, intensity: intensity))
            e.look(at: aim, from: from, upVector: [0, 1, 0], relativeTo: nil)
            lights.addChild(e)
        }
        directional(4200, from: [1.6, 3.0, 0.6])    // key (upper right)
        directional(2600, from: [-1.8, 2.4, 0.8])   // fill (upper left)
        directional(2200, from: [0.0, 2.2, -2.6])   // back / rim
        return lights
    }

    // MARK: - Room

    private static func makeRoom() -> Entity {
        let room = Entity()
        let size: Float = 6.0
        let height: Float = 3.0

        let floor = box(size, 0.04, size, surface(0.55, 0.56, 0.60, roughness: 0.9))
        floor.position = [0, -0.02, 0]
        room.addChild(floor)

        let ceiling = box(size, 0.04, size, surface(0.97, 0.97, 0.98, roughness: 0.95))
        ceiling.position = [0, height, 0]
        room.addChild(ceiling)

        let wall = { surface(0.90, 0.92, 0.95, roughness: 0.9) }
        let back = box(size, height, 0.06, wall())
        back.position = [0, height / 2, -size / 2]
        room.addChild(back)
        let left = box(0.06, height, size, wall())
        left.position = [-size / 2, height / 2, 0]
        room.addChild(left)
        let right = box(0.06, height, size, wall())
        right.position = [size / 2, height / 2, 0]
        room.addChild(right)
        return room
    }

    // MARK: - Workbench

    private static func makeWorkbench() -> Entity {
        let bench = Entity()

        let cabinet = box(1.5, benchTopY - 0.06, 0.7, surface(0.86, 0.87, 0.89, roughness: 0.8))
        cabinet.position = [0, (benchTopY - 0.06) / 2, 0]
        bench.addChild(cabinet)

        // Glossy worktop.
        let top = box(1.6, 0.05, 0.78, surface(0.90, 0.91, 0.93, roughness: 0.28))
        top.position = [0, benchTopY - 0.025, 0]
        top.components.set(GroundingShadowComponent(castsShadow: false))
        bench.addChild(top)
        return bench
    }

    // MARK: - Source vials

    private static func makeReagentRack(model: LabModel) -> Entity {
        let rack = Entity()
        let count = model.steps.count
        let spacing: Float = 0.16
        let centerX: Float = -0.24
        let startX = centerX - spacing * Float(count - 1) / 2.0
        let rowZ: Float = -0.02

        let holder = box(spacing * Float(count) + 0.06, 0.03, 0.11,
                         surface(0.36, 0.38, 0.42, roughness: 0.6))
        holder.position = [centerX, benchTopY + 0.015, rowZ]
        rack.addChild(holder)

        for (index, step) in model.steps.enumerated() {
            let reagent = step.reagent
            let x = startX + spacing * Float(index)

            let bottle = makeReagentBottle(reagent: reagent)
            bottle.position = [x, benchTopY + 0.03, rowZ]
            bottle.name = reagentPrefix + reagent.id
            rack.addChild(bottle)

            let label = makeTextEntity(reagent.name, fontSize: 0.016,
                                       color: .white, maxWidth: 0.16)
            label.position = [x, benchTopY + 0.30, rowZ]
            rack.addChild(label)
        }
        return rack
    }

    private static func makeReagentBottle(reagent: Reagent) -> Entity {
        let bottle = Entity()

        let bodyHeight: Float = 0.16
        let bodyRadius: Float = 0.03

        let body = ModelEntity(
            mesh: .generateCylinder(height: bodyHeight, radius: bodyRadius),
            materials: [glassy()]
        )
        body.position = [0, bodyHeight / 2, 0]
        bottle.addChild(body)

        let liquid = ModelEntity(
            mesh: .generateCylinder(height: 0.10, radius: bodyRadius - 0.004),
            materials: [unlit(reagent.color)]
        )
        liquid.position = [0, 0.05, 0]
        bottle.addChild(liquid)

        let neck = ModelEntity(
            mesh: .generateCylinder(height: 0.03, radius: 0.014),
            materials: [glassy()]
        )
        neck.position = [0, bodyHeight + 0.015, 0]
        bottle.addChild(neck)

        let cap = ModelEntity(
            mesh: .generateCylinder(height: 0.03, radius: 0.018),
            materials: [litColor(reagent.color.darker(), roughness: 0.4)]
        )
        cap.position = capClosedLocal
        cap.name = capName
        bottle.addChild(cap)

        let panel = ModelEntity(
            mesh: .generateBox(width: 0.05, height: 0.06, depth: 0.004, cornerRadius: 0.004),
            materials: [surface(0.97, 0.97, 0.97, roughness: 0.7)]
        )
        panel.position = [0, 0.07, bodyRadius + 0.001]
        bottle.addChild(panel)

        let labelText = makeTextEntity(shortName(reagent), fontSize: 0.009,
                                       color: .black, maxWidth: 0.05)
        labelText.position = [0, 0.07, bodyRadius + 0.005]
        bottle.addChild(labelText)

        makeTappable(bottle, size: [0.1, 0.36, 0.1], center: [0, 0.11, 0])
        bottle.components.set(GroundingShadowComponent(castsShadow: true))
        return bottle
    }

    // MARK: - Pipette

    private static func makePipette(into pipette: Entity, liquid: ModelEntity) -> Entity {
        pipette.children.removeAll()

        let bodyWhite = surface(0.94, 0.95, 0.97, roughness: 0.35)
        let accent = litColor(ReagentColor(r: 0.12, g: 0.45, b: 0.85), roughness: 0.35)
        let metal = surface(0.62, 0.64, 0.68, roughness: 0.25)
        let darkGrey = surface(0.22, 0.23, 0.26, roughness: 0.4)

        func part(_ mesh: MeshResource, _ material: any Material, _ pos: SIMD3<Float>) {
            let e = ModelEntity(mesh: mesh, materials: [material])
            e.position = pos
            pipette.addChild(e)
        }

        // Translucent disposable tip.
        let tip = ModelEntity(
            mesh: .generateCone(height: 0.07, radius: 0.012),
            materials: [translucent(0.9, 0.93, 0.97, 0.35)]
        )
        tip.position = [0, -0.035, 0]
        tip.scale = [1, -1, 1]
        pipette.addChild(tip)

        // Colored liquid in the tip; hidden until loaded.
        liquid.model = ModelComponent(
            mesh: .generateCone(height: 0.045, radius: 0.009),
            materials: [unlit(0.7, 0.7, 0.72)]
        )
        liquid.position = [0, -0.03, 0]
        liquid.scale = [1, -1, 1]
        liquid.isEnabled = false
        pipette.addChild(liquid)

        part(.generateCylinder(height: 0.05, radius: 0.0055), metal, [0, 0.025, 0])
        part(.generateCylinder(height: 0.055, radius: 0.013), bodyWhite, [0, 0.075, 0])
        part(.generateBox(width: 0.017, height: 0.026, depth: 0.006, cornerRadius: 0.002),
             darkGrey, [0, 0.08, 0.013])
        part(.generateCylinder(height: 0.013, radius: 0.0182), accent, [0, 0.108, 0])
        part(.generateCylinder(height: 0.062, radius: 0.017), bodyWhite, [0, 0.14, 0])
        part(.generateBox(width: 0.022, height: 0.04, depth: 0.012, cornerRadius: 0.003),
             bodyWhite, [0, 0.155, -0.022])
        part(.generateCylinder(height: 0.022, radius: 0.007), metal, [0, 0.182, 0])
        part(.generateCylinder(height: 0.02, radius: 0.015), accent, [0, 0.203, 0])
        part(.generateBox(width: 0.006, height: 0.075, depth: 0.01, cornerRadius: 0.002),
             metal, [0.019, 0.13, 0])
        part(.generateCylinder(height: 0.016, radius: 0.008), darkGrey, [0.019, 0.185, 0])

        pipette.name = pipetteName
        makeTappable(pipette, size: [0.08, 0.34, 0.08], center: [0, 0.07, 0])
        pipette.components.set(GroundingShadowComponent(castsShadow: true))
        pipette.position = pipetteHome
        return pipette
    }

    private static func makePipetteStand() -> Entity {
        let stand = Entity()
        let standMat = { surface(0.32, 0.34, 0.38, roughness: 0.5) }

        let base = box(0.1, 0.03, 0.1, standMat())
        base.position = [0.46, benchTopY + 0.015, 0.06]
        stand.addChild(base)

        let post = ModelEntity(
            mesh: .generateCylinder(height: 0.24, radius: 0.008),
            materials: [standMat()]
        )
        post.position = [0.46, benchTopY + 0.14, 0.015]
        stand.addChild(post)

        let cradle = ModelEntity(
            mesh: .generateBox(width: 0.05, height: 0.008, depth: 0.04, cornerRadius: 0.002),
            materials: [standMat()]
        )
        cradle.position = [0.46, benchTopY + 0.22, 0.04]
        stand.addChild(cradle)
        return stand
    }

    // MARK: - Eppendorf tube

    private static func makeEppendorf(liquids: Entity) -> Entity {
        let tube = Entity()
        tube.name = tubeName
        tube.position = [0, benchTopY + 0.05, 0.2]

        let stand = ModelEntity(
            mesh: .generateBox(width: 0.07, height: 0.03, depth: 0.07, cornerRadius: 0.006),
            materials: [surface(0.32, 0.34, 0.38, roughness: 0.5)]
        )
        stand.position = [0, -0.035, 0]
        tube.addChild(stand)

        let bodyHeight: Float = 0.06
        let body = ModelEntity(
            mesh: .generateCylinder(height: bodyHeight, radius: 0.016),
            materials: [glassy()]
        )
        body.position = [0, bodyHeight / 2, 0]
        tube.addChild(body)

        let cone = ModelEntity(
            mesh: .generateCone(height: 0.03, radius: 0.016),
            materials: [glassy()]
        )
        cone.position = [0, -0.015, 0]
        cone.scale = [1, -1, 1]
        tube.addChild(cone)

        let cap = ModelEntity(
            mesh: .generateCylinder(height: 0.014, radius: 0.019),
            materials: [surface(0.95, 0.9, 0.4, roughness: 0.4)]
        )
        cap.position = [0, bodyHeight + 0.007, 0]
        tube.addChild(cap)

        liquids.name = "\(tubeName)-liquids"
        liquids.position = [0, 0.001, 0]
        tube.addChild(liquids)

        makeTappable(tube, size: [0.1, 0.16, 0.1], center: [0, 0.03, 0])
        tube.components.set(GroundingShadowComponent(castsShadow: true))

        let label = makeTextEntity("Reaction tube", fontSize: 0.015,
                                   color: .white, maxWidth: 0.2)
        label.position = [0, 0.12, 0]
        tube.addChild(label)
        return tube
    }

    // MARK: - Live updates

    static func refreshPipette(_ liquid: ModelEntity, loaded: Reagent?) {
        if let reagent = loaded {
            liquid.model?.materials = [unlit(reagent.color)]
            liquid.isEnabled = true
        } else {
            liquid.isEnabled = false
        }
    }

    static func setBottleOpen(id: String, in root: Entity, open: Bool) {
        guard let bottle = findEntity(named: reagentPrefix + id, in: root),
              let cap = bottle.children.first(where: { $0.name == capName })
        else { return }
        var t = cap.transform
        t.translation = open ? capOpenLocal : capClosedLocal
        cap.move(to: t, relativeTo: cap.parent, duration: 0.2)
    }

    /// Rebuild the liquid inside the tube: stacked colored layers while
    /// dispensing, one green column once mixed.
    static func refreshEppendorf(_ container: Entity, dispensed: [Reagent], mixed: Bool) {
        container.children.removeAll()
        guard !dispensed.isEmpty else { return }

        let layerHeight: Float = 0.007

        if mixed {
            let totalHeight = layerHeight * Float(dispensed.count)
            let blob = ModelEntity(
                mesh: .generateCylinder(height: totalHeight, radius: 0.014),
                materials: [unlit(LabProtocol.productColor)]
            )
            blob.position = [0, 0.004 + totalHeight / 2, 0]
            container.addChild(blob)
            return
        }

        var y: Float = 0.004 + layerHeight / 2
        for reagent in dispensed {
            let layer = ModelEntity(
                mesh: .generateCylinder(height: layerHeight, radius: 0.014),
                materials: [unlit(reagent.color)]
            )
            layer.position = [0, y, 0]
            container.addChild(layer)
            y += layerHeight
        }
    }

    static func playMixAnimation(_ container: Entity) {
        let original = container.transform
        var shaken = original
        shaken.rotation = simd_quatf(angle: .pi / 12, axis: [0, 0, 1])
        container.move(to: shaken, relativeTo: container.parent, duration: 0.12)
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.14) {
            container.move(to: original, relativeTo: container.parent, duration: 0.12)
        }
    }

    // MARK: - Hit testing

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

    private static func findEntity(named name: String, in root: Entity) -> Entity? {
        if root.name == name { return root }
        for child in root.children {
            if let found = findEntity(named: name, in: child) { return found }
        }
        return nil
    }

    private static func makeTappable(_ entity: Entity,
                                     size: SIMD3<Float>,
                                     center: SIMD3<Float> = .zero) {
        let shape = ShapeResource.generateBox(size: size)
            .offsetBy(translation: center)
        entity.components.set(CollisionComponent(shapes: [shape]))
        entity.components.set(InputTargetComponent())
        entity.components.set(HoverEffectComponent())
    }

    static func entity(named name: String, in root: Entity) -> Entity? {
        findEntity(named: name, in: root)
    }

    private static func box(_ w: Float, _ h: Float, _ d: Float,
                            _ material: any Material) -> ModelEntity {
        ModelEntity(mesh: .generateBox(width: w, height: h, depth: d, cornerRadius: 0.005),
                    materials: [material])
    }

    // MARK: - Guidance sign

    private static func makeGuidancePanel(text guidance: ModelEntity) -> Entity {
        let panel = Entity()

        let board = ModelEntity(
            mesh: .generateBox(width: 0.7, height: 0.22, depth: 0.01, cornerRadius: 0.02),
            materials: [surface(0.97, 0.97, 0.98, roughness: 0.6)]
        )
        panel.addChild(board)

        let strip = ModelEntity(
            mesh: .generateBox(width: 0.7, height: 0.045, depth: 0.011, cornerRadius: 0.01),
            materials: [unlit(0.12, 0.45, 0.85)]
        )
        strip.position = [0, 0.087, 0.001]
        panel.addChild(strip)

        let header = makeTextEntity("VIRTUAL BIO LAB", fontSize: 0.026,
                                    color: .white, maxWidth: 0.66)
        header.position = [0, 0.082, 0.008]
        panel.addChild(header)

        panel.addChild(guidance)
        return panel
    }

    static func setGuidance(_ guidance: ModelEntity, text: String) {
        let mesh = MeshResource.generateText(
            text,
            extrusionDepth: 0.001,
            font: .systemFont(ofSize: 0.03),
            containerFrame: CGRect(x: 0, y: 0, width: 0.62, height: 0.14),
            alignment: .center,
            lineBreakMode: .byWordWrapping
        )
        guidance.model = ModelComponent(mesh: mesh, materials: [UnlitMaterial(color: .black)])
        guidance.position = [-0.31, -0.07, 0.008]
    }

    private static func makeTextEntity(_ text: String,
                                       fontSize: CGFloat,
                                       color: UIColor,
                                       maxWidth: CGFloat) -> Entity {
        let mesh = MeshResource.generateText(
            text,
            extrusionDepth: 0.001,
            font: .systemFont(ofSize: fontSize),
            containerFrame: CGRect(x: 0, y: 0, width: maxWidth, height: fontSize * 3.2),
            alignment: .center,
            lineBreakMode: .byWordWrapping
        )
        let model = ModelEntity(mesh: mesh, materials: [UnlitMaterial(color: color)])
        model.position.x = -Float(maxWidth / 2)
        let container = Entity()
        container.addChild(model)
        return container
    }

    private static func shortName(_ reagent: Reagent) -> String {
        let words = reagent.name.split(separator: " ")
        return words.prefix(2).joined(separator: "\n")
    }

    // MARK: - Materials

    /// A lit, shaded opaque surface.
    private static func surface(_ r: CGFloat, _ g: CGFloat, _ b: CGFloat,
                                roughness: Float = 0.8) -> SimpleMaterial {
        SimpleMaterial(color: UIColor(red: r, green: g, blue: b, alpha: 1.0),
                       roughness: MaterialScalarParameter(floatLiteral: roughness),
                       isMetallic: false)
    }

    private static func litColor(_ c: ReagentColor, roughness: Float = 0.5) -> SimpleMaterial {
        SimpleMaterial(color: c.uiColor,
                       roughness: MaterialScalarParameter(floatLiteral: roughness),
                       isMetallic: false)
    }

    /// Unlit (always-bright) material — used for liquids, labels, and the sign.
    private static func unlit(_ c: ReagentColor) -> UnlitMaterial {
        UnlitMaterial(color: c.uiColor)
    }

    private static func unlit(_ r: CGFloat, _ g: CGFloat, _ b: CGFloat) -> UnlitMaterial {
        UnlitMaterial(color: UIColor(red: r, green: g, blue: b, alpha: 1.0))
    }

    /// A frosted-glass look for glassware — translucent and unlit so it always
    /// reads clearly.
    private static func glassy() -> UnlitMaterial {
        var material = UnlitMaterial(color: UIColor(white: 0.85, alpha: 0.4))
        material.blending = .transparent(opacity: 0.4)
        return material
    }

    private static func translucent(_ r: CGFloat, _ g: CGFloat, _ b: CGFloat,
                                    _ a: CGFloat) -> UnlitMaterial {
        var material = UnlitMaterial(color: UIColor(red: r, green: g, blue: b, alpha: a))
        material.blending = .transparent(opacity: .init(floatLiteral: Float(a)))
        return material
    }
}
