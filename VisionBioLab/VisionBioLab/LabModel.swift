import Foundation
import Observation

/// Holds all of the lab's game state and the rules for the protocol.
///
/// The window UI and the 3D immersive scene both read from and drive this
/// single model, so they always stay in sync.
@Observable
final class LabModel {

    /// The ordered protocol the user is following.
    let steps: [ProtocolStep] = LabProtocol.steps

    /// What is currently loaded in the pipette (nil = empty).
    private(set) var loadedReagent: Reagent?

    /// Reagents that have been correctly dispensed into the tube, in order.
    private(set) var dispensedReagents: [Reagent] = []

    /// Index of the step the user should perform next.
    private(set) var currentStepIndex: Int = 0

    /// Short message describing the result of the last action.
    private(set) var statusMessage: String = "Tap a reagent to load the pipette."

    /// Whether the last action was an error (used for red styling).
    private(set) var lastActionWasError: Bool = false

    /// The step the user should do next, if any remain.
    var currentStep: ProtocolStep? {
        guard currentStepIndex < steps.count else { return nil }
        return steps[currentStepIndex]
    }

    /// True once every step has been completed correctly.
    var isComplete: Bool { dispensedReagents.count == steps.count }

    // MARK: - Actions

    /// Draw a reagent up into the pipette.
    func loadPipette(with reagent: Reagent) {
        guard !isComplete else { return }
        loadedReagent = reagent
        lastActionWasError = false
        statusMessage = "Pipette loaded with \(reagent.name). Tap the tube to dispense."
    }

    /// Dispense whatever is in the pipette into the Eppendorf tube and check it
    /// against the current protocol step.
    func dispenseIntoTube() {
        guard !isComplete else { return }

        guard let loaded = loadedReagent else {
            lastActionWasError = true
            statusMessage = "The pipette is empty — load a reagent first."
            return
        }

        guard let expected = currentStep else { return }

        if loaded == expected.reagent {
            // Correct reagent at the right time.
            dispensedReagents.append(loaded)
            currentStepIndex += 1
            loadedReagent = nil
            lastActionWasError = false

            if isComplete {
                statusMessage = "✅ Master mix complete — protocol finished!"
            } else if let next = currentStep {
                statusMessage = "Added \(loaded.name). Next: step \(next.order), \(next.reagent.name)."
            }
        } else {
            // Wrong reagent for this step — protocol violated, start over.
            lastActionWasError = true
            statusMessage = "❌ Out of order! Step \(expected.order) needs \(expected.reagent.name). Resetting tube."
            resetTube()
        }
    }

    /// Empty the pipette without dispensing.
    func emptyPipette() {
        loadedReagent = nil
        lastActionWasError = false
        statusMessage = "Pipette emptied."
    }

    /// Discard the tube contents and restart the protocol from step 1.
    func resetTube() {
        dispensedReagents = []
        currentStepIndex = 0
        loadedReagent = nil
    }

    /// Full reset back to the starting state.
    func restart() {
        resetTube()
        lastActionWasError = false
        statusMessage = "Tap a reagent to load the pipette."
    }
}
