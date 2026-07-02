import RealityKit
import UIKit
import simd

/// Builds and updates the 3D virtual lab: an enclosed room, a workbench, and the
/// reagents / pipette / tube. Everything is generated procedurally from
/// primitives and uses unlit materials, so it renders brightly and consistently
/// in a fully immersive space (no external assets or scene lighting required).
enum LabSceneBuilder {

    // Names used to identify what the user tapped / dragged.
    static let reagentPrefix = "reagent:"
    static let tubeName = "eppendorf"
    static let pipetteName = "pipette"
    static let capName = "cap"

    // Bench geometry (in the bench group's local space; the group sits in front
    // of the user, so these Y values are roughly world height in meters).
    private static let benchTopY: Float = 0.99
    private static let benchGroupOffset: SIMD3<Float> = [0, 0, -0.6]

    // Cap rest / lifted positions, local to a bottle.
    private static let capClosedLocal: SIMD3<Float> = [0, 0.205, 0]
    private static let capOpenLocal: SIMD3<Float> = [0.05, 0.275, 0]

    /// Resting position of the pipette on the bench (local to the bench group).
    /// Raised so the tip clears the worktop when standing in its holder.
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

        // The room is built around the origin (floor at y = 0).
        root.addChild(makeRoom())
        root.addChild(makeBackCounter())

        // Everything you work with sits on a bench in front of you.
        let bench = Entity()
        bench.position = benchGroupOffset
        bench.addChild(makeWorkbench())
        bench.addChild(makeReagentRack(model: model))
        bench.addChild(makePipetteStand())
        bench.addChild(makePipette(into: pipette, liquid: pipetteLiquid))
        bench.addChild(makeEppendorf(liquids: eppendorfLiquids))

        let panel = makeGuidancePanel(text: guidance)
        panel.position = [0, benchTopY + 0.46, -0.1]
        bench.addChild(panel)
        root.addChild(bench)
    }

    // MARK: - Room

    private static func makeRoom() -> Entity {
        let room = Entity()
        let size: Float = 6.0
        let height: Float = 3.0

        // Floor and ceiling.
        let floor = box(size, 0.04, size, unlit(0.46, 0.49, 0.53))
        floor.position = [0, -0.02, 0]
        room.addChild(floor)

        let ceiling = box(size, 0.04, size, unlit(0.90, 0.91, 0.93))
        ceiling.position = [0, height, 0]
        room.addChild(ceiling)

        // Four walls (pale clinical blue-grey).
        let wallColor = unlit(0.80, 0.84, 0.88)
        let back = box(size, height, 0.06, wallColor)
        back.position = [0, height / 2, -size / 2]
        room.addChild(back)

        let front = box(size, height, 0.06, wallColor)
        front.position = [0, height / 2, size / 2]
        room.addChild(front)

        let left = box(0.06, height, size, wallColor)
        left.position = [-size / 2, height / 2, 0]
        room.addChild(left)

        let right = box(0.06, height, size, wallColor)
        right.position = [size / 2, height / 2, 0]
        room.addChild(right)

        // Ceiling light panels (bright, to read as a lab).
        let panel = unlit(1.0, 1.0, 0.97)
        for x: Float in [-1.3, 1.3] {
            for z: Float in [-1.2, 1.2] {
                let p = box(1.1, 0.04, 0.45, panel)
                p.position = [x, height - 0.03, z]
                room.addChild(p)
            }
        }
        return room
    }

    /// A back counter with a little decorative glassware for atmosphere.
    private static func makeBackCounter() -> Entity {
        let group = Entity()
        let z: Float = -2.55

        let cabinet = box(4.0, 0.9, 0.6, unlit(0.74, 0.76, 0.78))
        cabinet.position = [0, 0.45, z]
        group.addChild(cabinet)

        let top = box(4.1, 0.06, 0.65, unlit(0.22, 0.24, 0.27))
        top.position = [0, 0.93, z]
        group.addChild(top)

        // Decorative beakers/flasks with colored contents.
        let contents: [ReagentColor] = [
            ReagentColor(r: 0.30, g: 0.78, b: 0.45),
            ReagentColor(r: 0.90, g: 0.32, b: 0.32),
            ReagentColor(r: 0.25, g: 0.55, b: 0.95),
            ReagentColor(r: 0.98, g: 0.82, b: 0.20),
        ]
        for (i, c) in contents.enumerated() {
            let x = -1.2 + Float(i) * 0.8
            let beaker = box(0.16, 0.22, 0.16, glassy())
            beaker.position = [x, 1.07, z]
            let liquid = ModelEntity(
                mesh: .generateBox(width: 0.14, height: 0.12, depth: 0.14, cornerRadius: 0.01),
                materials: [unlit(c)]
            )
            liquid.position = [0, -0.04, 0]
            beaker.addChild(liquid)
            group.addChild(beaker)
        }
        return group
    }

    // MARK: - Workbench

    private static func makeWorkbench() -> Entity {
        let bench = Entity()

        let cabinet = box(1.7, benchTopY - 0.06, 0.7, unlit(0.78, 0.80, 0.82))
        cabinet.position = [0, (benchTopY - 0.06) / 2, 0]
        bench.addChild(cabinet)

        // Dark stainless worktop.
        let top = box(1.8, 0.06, 0.78, unlit(0.20, 0.22, 0.25))
        top.position = [0, benchTopY - 0.03, 0]
        bench.addChild(top)
        return bench
    }

    // MARK: - Reagent rack + bottles

    private static func makeReagentRack(model: LabModel) -> Entity {
        let rack = Entity()
        let count = model.steps.count
        let spacing: Float = 0.17
        let startX = -spacing * Float(count - 1) / 2.0
        let rowZ: Float = -0.14

        // A holder block the bottles sit in.
        let holder = box(spacing * Float(count) + 0.05, 0.03, 0.12,
                         unlit(0.32, 0.34, 0.38))
        holder.position = [0, benchTopY + 0.015, rowZ]
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

    /// A labeled reagent bottle: glass body, colored contents, neck, a colored
    /// cap (which lifts off when in use), and a printed label.
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

        // Cap — coloured to match, lifts off when the bottle is opened.
        let cap = ModelEntity(
            mesh: .generateCylinder(height: 0.03, radius: 0.018),
            materials: [unlit(reagent.color.darker())]
        )
        cap.position = capClosedLocal
        cap.name = capName
        bottle.addChild(cap)

        // White label panel with the reagent name on it.
        let panel = ModelEntity(
            mesh: .generateBox(width: 0.05, height: 0.06, depth: 0.004, cornerRadius: 0.004),
            materials: [unlit(0.97, 0.97, 0.97)]
        )
        panel.position = [0, 0.07, bodyRadius + 0.001]
        bottle.addChild(panel)

        let labelText = makeTextEntity(shortName(reagent), fontSize: 0.009,
                                       color: .black, maxWidth: 0.05)
        labelText.position = [0, 0.07, bodyRadius + 0.005]
        bottle.addChild(labelText)

        makeTappable(bottle, size: [0.1, 0.36, 0.1], center: [0, 0.11, 0])
        return bottle
    }

    // MARK: - Pipette

    /// A micropipette built from primitives: plunger button, tip-ejector, an
    /// ergonomic body with a volume window, a metal shaft, and a translucent
    /// disposable tip. The origin sits where the tip meets the shaft (y = 0),
    /// with the tip pointing down.
    private static func makePipette(into pipette: Entity, liquid: ModelEntity) -> Entity {
        pipette.children.removeAll()

        let bodyWhite = unlit(0.93, 0.94, 0.96)
        let accent = unlit(0.12, 0.45, 0.85)
        let metal = unlit(0.55, 0.57, 0.60)
        let darkGrey = unlit(0.20, 0.21, 0.24)

        func part(_ mesh: MeshResource, _ material: UnlitMaterial, _ pos: SIMD3<Float>) {
            let e = ModelEntity(mesh: mesh, materials: [material])
            e.position = pos
            pipette.addChild(e)
        }

        // Translucent disposable tip (cone pointing down from the origin).
        let tip = ModelEntity(
            mesh: .generateCone(height: 0.07, radius: 0.012),
            materials: [translucent(0.9, 0.93, 0.97, 0.35)]
        )
        tip.position = [0, -0.035, 0]
        tip.scale = [1, -1, 1]
        pipette.addChild(tip)

        // Colored liquid drawn up into the tip; hidden until loaded.
        liquid.model = ModelComponent(
            mesh: .generateCone(height: 0.045, radius: 0.009),
            materials: [unlit(0.7, 0.7, 0.72)]
        )
        liquid.position = [0, -0.03, 0]
        liquid.scale = [1, -1, 1]
        liquid.isEnabled = false
        pipette.addChild(liquid)

        // Thin metal shaft.
        part(.generateCylinder(height: 0.05, radius: 0.0055), metal, [0, 0.025, 0])

        // Lower body (holds the volume window).
        part(.generateCylinder(height: 0.055, radius: 0.013), bodyWhite, [0, 0.075, 0])
        part(.generateBox(width: 0.017, height: 0.026, depth: 0.006, cornerRadius: 0.002),
             darkGrey, [0, 0.08, 0.013])

        // Colored channel band.
        part(.generateCylinder(height: 0.013, radius: 0.0182), accent, [0, 0.108, 0])

        // Upper ergonomic body / handle.
        part(.generateCylinder(height: 0.062, radius: 0.017), bodyWhite, [0, 0.14, 0])

        // Finger hook at the back of the handle.
        part(.generateBox(width: 0.022, height: 0.04, depth: 0.012, cornerRadius: 0.003),
             bodyWhite, [0, 0.155, -0.022])

        // Plunger shaft + button on top.
        part(.generateCylinder(height: 0.022, radius: 0.007), metal, [0, 0.182, 0])
        part(.generateCylinder(height: 0.02, radius: 0.015), accent, [0, 0.203, 0])

        // Tip-ejector arm + button down the side.
        part(.generateBox(width: 0.006, height: 0.075, depth: 0.01, cornerRadius: 0.002),
             metal, [0.019, 0.13, 0])
        part(.generateCylinder(height: 0.016, radius: 0.008), darkGrey, [0.019, 0.185, 0])

        pipette.name = pipetteName
        makeTappable(pipette, size: [0.08, 0.34, 0.08], center: [0, 0.07, 0])
        pipette.position = pipetteHome
        return pipette
    }

    /// A simple holder the pipette rests in.
    private static func makePipetteStand() -> Entity {
        let stand = Entity()
        let standColor = unlit(0.30, 0.32, 0.36)

        let base = box(0.1, 0.03, 0.1, standColor)
        base.position = [0.46, benchTopY + 0.015, 0.06]
        stand.addChild(base)

        let post = ModelEntity(
            mesh: .generateCylinder(height: 0.24, radius: 0.008),
            materials: [standColor]
        )
        post.position = [0.46, benchTopY + 0.14, 0.015]
        stand.addChild(post)

        let cradle = ModelEntity(
            mesh: .generateBox(width: 0.05, height: 0.008, depth: 0.04, cornerRadius: 0.002),
            materials: [standColor]
        )
        cradle.position = [0.46, benchTopY + 0.22, 0.04]
        stand.addChild(cradle)
        return stand
    }

    // MARK: - Eppendorf tube

    private static func makeEppendorf(liquids: Entity) -> Entity {
        // The tube entity's origin is placed at the tube base so distance-based
        // drop detection lines up with where it actually appears.
        let tube = Entity()
        tube.name = tubeName
        tube.position = [0, benchTopY + 0.05, 0.2]

        // A small stand just below the tube.
        let stand = ModelEntity(
            mesh: .generateBox(width: 0.07, height: 0.03, depth: 0.07, cornerRadius: 0.006),
            materials: [unlit(0.30, 0.32, 0.36)]
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
            materials: [unlit(0.95, 0.95, 0.55)]
        )
        cap.position = [0, bodyHeight + 0.007, 0]
        tube.addChild(cap)

        liquids.name = "\(tubeName)-liquids"
        liquids.position = [0, 0.001, 0]
        tube.addChild(liquids)

        makeTappable(tube, size: [0.1, 0.16, 0.1], center: [0, 0.03, 0])

        let label = makeTextEntity("Eppendorf tube", fontSize: 0.015,
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

    /// Open or close a specific bottle's cap (the "uncap it" animation).
    static func setBottleOpen(id: String, in root: Entity, open: Bool) {
        guard let bottle = findEntity(named: reagentPrefix + id, in: root),
              let cap = bottle.children.first(where: { $0.name == capName })
        else { return }
        var t = cap.transform
        t.translation = open ? capOpenLocal : capClosedLocal
        cap.move(to: t, relativeTo: cap.parent, duration: 0.2)
    }

    /// Rebuild the liquid inside the Eppendorf tube. While dispensing it shows
    /// stacked colored layers; once mixed it becomes one blended column.
    static func refreshEppendorf(_ container: Entity, dispensed: [Reagent], mixed: Bool) {
        container.children.removeAll()
        guard !dispensed.isEmpty else { return }

        let layerHeight: Float = 0.007

        if mixed {
            let totalHeight = layerHeight * Float(dispensed.count)
            let blob = ModelEntity(
                mesh: .generateCylinder(height: totalHeight, radius: 0.014),
                materials: [unlit(dispensed.blendedColor)]
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

    /// Briefly shake the tube's contents to suggest vortex-mixing.
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

        /// Stable identifier used to debounce repeated dips into the same target.
        var dipID: String? {
            switch self {
            case .reagent(let id): return "reagent:" + id
            case .tube: return "tube"
            case .none: return nil
            }
        }
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

    static func isPipette(_ entity: Entity) -> Bool {
        var current: Entity? = entity
        while let e = current {
            if e.name == pipetteName { return true }
            current = e.parent
        }
        return false
    }

    /// Walk up from a touched entity to the grabbable root it belongs to
    /// (the pipette, a reagent bottle, or the tube), if any.
    static func grabbable(_ entity: Entity) -> Entity? {
        var current: Entity? = entity
        while let e = current {
            if e.name == pipetteName || e.name == tubeName
                || e.name.hasPrefix(reagentPrefix) {
                return e
            }
            current = e.parent
        }
        return nil
    }

    /// Find the reagent bottle or tube nearest a world-space point (the dropped
    /// pipette tip), within `threshold` meters.
    static func dropTarget(near worldPos: SIMD3<Float>,
                           in root: Entity,
                           threshold: Float = 0.25) -> Hit {
        var best: (hit: Hit, dist: Float)?

        func consider(_ entity: Entity, _ hit: Hit) {
            let d = simd_distance(entity.position(relativeTo: nil), worldPos)
            if d <= threshold, best == nil || d < best!.dist { best = (hit, d) }
        }
        func walk(_ entity: Entity) {
            if entity.name == tubeName {
                consider(entity, .tube)
            } else if entity.name.hasPrefix(reagentPrefix) {
                consider(entity, .reagent(String(entity.name.dropFirst(reagentPrefix.count))))
            }
            for child in entity.children { walk(child) }
        }
        walk(root)
        return best?.hit ?? .none
    }

    // MARK: - Helpers

    private static func findEntity(named name: String, in root: Entity) -> Entity? {
        if root.name == name { return root }
        for child in root.children {
            if let found = findEntity(named: name, in: child) { return found }
        }
        return nil
    }

    /// Make an entity reliably tappable (gaze + pinch) with a hover highlight.
    private static func makeTappable(_ entity: Entity,
                                     size: SIMD3<Float>,
                                     center: SIMD3<Float> = .zero) {
        let shape = ShapeResource.generateBox(size: size)
            .offsetBy(translation: center)
        entity.components.set(CollisionComponent(shapes: [shape]))
        entity.components.set(InputTargetComponent())
        entity.components.set(HoverEffectComponent())
    }

    /// Public lookup used by the view to animate the pipette toward a target.
    static func entity(named name: String, in root: Entity) -> Entity? {
        findEntity(named: name, in: root)
    }

    private static func box(_ w: Float, _ h: Float, _ d: Float,
                            _ material: UnlitMaterial) -> ModelEntity {
        ModelEntity(mesh: .generateBox(width: w, height: h, depth: d, cornerRadius: 0.005),
                    materials: [material])
    }

    // MARK: - Guidance sign

    /// A signboard above the bench that tells the user the next step.
    private static func makeGuidancePanel(text guidance: ModelEntity) -> Entity {
        let panel = Entity()

        let board = ModelEntity(
            mesh: .generateBox(width: 0.7, height: 0.22, depth: 0.01, cornerRadius: 0.02),
            materials: [unlit(0.97, 0.97, 0.98)]
        )
        panel.addChild(board)

        // Header strip.
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

    /// Update the guidance sign's text.
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

    /// Returns a container entity holding centered text, so callers can freely
    /// set the container's position without losing the centering offset.
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

    /// A short label for a bottle (first couple of words).
    private static func shortName(_ reagent: Reagent) -> String {
        let words = reagent.name.split(separator: " ")
        return words.prefix(2).joined(separator: "\n")
    }

    // MARK: - Materials

    private static func unlit(_ c: ReagentColor) -> UnlitMaterial {
        UnlitMaterial(color: c.uiColor)
    }

    private static func unlit(_ r: CGFloat, _ g: CGFloat, _ b: CGFloat) -> UnlitMaterial {
        UnlitMaterial(color: UIColor(red: r, green: g, blue: b, alpha: 1.0))
    }

    /// A frosted glass look for bottle / tube bodies — fairly opaque so the
    /// glassware reads clearly.
    private static func glassy() -> UnlitMaterial {
        var material = UnlitMaterial(color: UIColor(white: 0.85, alpha: 0.45))
        material.blending = .transparent(opacity: 0.45)
        return material
    }

    /// A tinted translucent material (e.g. a clear plastic pipette tip).
    private static func translucent(_ r: CGFloat, _ g: CGFloat, _ b: CGFloat,
                                    _ a: CGFloat) -> UnlitMaterial {
        var material = UnlitMaterial(color: UIColor(red: r, green: g, blue: b, alpha: a))
        material.blending = .transparent(opacity: .init(floatLiteral: Float(a)))
        return material
    }
}
