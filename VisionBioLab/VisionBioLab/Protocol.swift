import SwiftUI

/// A color stored as RGB components so it can be shared between SwiftUI (the
/// protocol sheet) and RealityKit (the 3D liquids on the bench).
struct ReagentColor: Equatable, Hashable {
    let r: Double
    let g: Double
    let b: Double

    /// Color for SwiftUI views (swatches, list rows).
    var swiftUI: Color { Color(red: r, green: g, blue: b) }

    /// Color for RealityKit materials.
    var uiColor: UIColor { UIColor(red: r, green: g, blue: b, alpha: 1.0) }

    /// A darker shade, used for bottle caps.
    func darker(_ factor: Double = 0.6) -> ReagentColor {
        ReagentColor(r: r * factor, g: g * factor, b: b * factor)
    }
}

/// One reagent the user can load into the pipette and dispense.
struct Reagent: Identifiable, Equatable, Hashable {
    let id: String
    let name: String
    let color: ReagentColor
    /// Volume the protocol asks you to dispense, in microliters.
    let volumeUL: Int

    var label: String { "\(name) · \(volumeUL) µL" }
}

/// A single ordered step of the protocol: dispense `reagent` into the tube.
struct ProtocolStep: Identifiable, Equatable {
    let id = UUID()
    let order: Int
    let reagent: Reagent
    let note: String
}

/// A simple demo protocol: pipette two solutions into one tube and watch them
/// mix into the reaction product.
enum LabProtocol {

    static let reagents: [Reagent] = [
        Reagent(id: "solutionA",
                name: "Solution A",
                color: ReagentColor(r: 0.20, g: 0.55, b: 0.95),   // blue
                volumeUL: 50),
        Reagent(id: "solutionB",
                name: "Solution B",
                color: ReagentColor(r: 0.98, g: 0.80, b: 0.20),   // yellow
                volumeUL: 50),
    ]

    /// The color of the mixed reaction product (blue + yellow → green).
    static let productColor = ReagentColor(r: 0.25, g: 0.75, b: 0.42)

    /// Look a reagent up by id.
    static func reagent(_ id: String) -> Reagent? {
        reagents.first { $0.id == id }
    }

    /// Add A, then B — two steps.
    static let steps: [ProtocolStep] = [
        ProtocolStep(order: 1, reagent: reagents[0],
                     note: "Draw up Solution A and add it to the tube."),
        ProtocolStep(order: 2, reagent: reagents[1],
                     note: "Add Solution B — the two mix into the product."),
    ]
}
