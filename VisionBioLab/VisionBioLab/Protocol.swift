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
}

extension Array where Element == Reagent {
    /// The average color of these reagents — used to tint the mixed reaction.
    var blendedColor: ReagentColor {
        guard !isEmpty else { return ReagentColor(r: 0.8, g: 0.8, b: 0.8) }
        let n = Double(count)
        return ReagentColor(
            r: reduce(0) { $0 + $1.color.r } / n,
            g: reduce(0) { $0 + $1.color.g } / n,
            b: reduce(0) { $0 + $1.color.b } / n
        )
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

/// The built-in demo protocol: setting up a simple PCR-style master mix by
/// pipetting reagents into one Eppendorf tube, in order.
enum LabProtocol {

    static let reagents: [Reagent] = [
        Reagent(id: "water",
                name: "Nuclease-free Water",
                color: ReagentColor(r: 0.80, g: 0.92, b: 1.00),
                volumeUL: 10),
        Reagent(id: "buffer",
                name: "Reaction Buffer (10×)",
                color: ReagentColor(r: 0.30, g: 0.78, b: 0.45),
                volumeUL: 2),
        Reagent(id: "dntp",
                name: "dNTP Mix",
                color: ReagentColor(r: 0.98, g: 0.82, b: 0.20),
                volumeUL: 4),
        Reagent(id: "template",
                name: "Template DNA",
                color: ReagentColor(r: 0.90, g: 0.32, b: 0.32),
                volumeUL: 2),
        Reagent(id: "polymerase",
                name: "DNA Polymerase",
                color: ReagentColor(r: 0.62, g: 0.40, b: 0.85),
                volumeUL: 1),
    ]

    /// Look a reagent up by id.
    static func reagent(_ id: String) -> Reagent? {
        reagents.first { $0.id == id }
    }

    /// The ordered steps. Order matters — buffer and dNTPs go in before the
    /// template, and the polymerase is always added last.
    static let steps: [ProtocolStep] = [
        ProtocolStep(order: 1, reagent: reagents[0],
                     note: "Add water first to set the reaction volume."),
        ProtocolStep(order: 2, reagent: reagents[1],
                     note: "Add 10× reaction buffer."),
        ProtocolStep(order: 3, reagent: reagents[2],
                     note: "Add the dNTP mix."),
        ProtocolStep(order: 4, reagent: reagents[3],
                     note: "Add template DNA."),
        ProtocolStep(order: 5, reagent: reagents[4],
                     note: "Add polymerase LAST to avoid non-specific activity."),
    ]
}
