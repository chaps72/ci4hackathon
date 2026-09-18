import SwiftUI

/// The 2D control window: reagent controls, status, and buttons to open the
/// immersive lab and the floating protocol notepad. Works hand-in-hand with the
/// 3D scene — both drive the same `LabModel`.
struct ContentView: View {
    @Environment(LabModel.self) private var model
    @Environment(\.openImmersiveSpace) private var openImmersiveSpace
    @Environment(\.dismissImmersiveSpace) private var dismissImmersiveSpace
    @Environment(\.openWindow) private var openWindow

    @State private var immersiveOpen = false

    var body: some View {
        NavigationStack {
            controls
                .navigationTitle("Virtual Bio Lab")
                .toolbar {
                    ToolbarItem(placement: .primaryAction) {
                        Button {
                            openWindow(id: ProtocolWindow.windowID)
                        } label: {
                            Label("Protocol", systemImage: "list.clipboard")
                        }
                    }
                }
        }
    }

    // MARK: - Controls

    private var controls: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {

                HStack(spacing: 12) {
                    Button {
                        Task { await toggleImmersive() }
                    } label: {
                        Label(immersiveOpen ? "Exit Lab" : "Enter Lab",
                              systemImage: immersiveOpen ? "xmark.circle" : "cube.transparent")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.borderedProminent)

                    Button {
                        openWindow(id: ProtocolWindow.windowID)
                    } label: {
                        Label("Open Protocol", systemImage: "list.clipboard")
                            .frame(maxWidth: .infinity)
                    }
                    .buttonStyle(.bordered)
                }

                statusCard

                Text("Reagents")
                    .font(.title3.bold())

                LazyVGrid(columns: [GridItem(.adaptive(minimum: 150))], spacing: 12) {
                    ForEach(LabProtocol.reagents) { reagent in
                        Button {
                            model.loadPipette(with: reagent)
                        } label: {
                            HStack {
                                Circle()
                                    .fill(reagent.color.swiftUI)
                                    .frame(width: 20, height: 20)
                                Text(reagent.name)
                                    .font(.subheadline)
                                    .multilineTextAlignment(.leading)
                            }
                            .frame(maxWidth: .infinity, alignment: .leading)
                        }
                        .buttonStyle(.bordered)
                        .disabled(model.isComplete)
                    }
                }

                HStack {
                    Button {
                        model.dispenseIntoTube()
                    } label: {
                        Label("Dispense into tube", systemImage: "drop.fill")
                    }
                    .buttonStyle(.borderedProminent)
                    .disabled(model.loadedReagent == nil || model.isComplete)

                    Button {
                        model.mix()
                    } label: {
                        Label("Mix / run reaction", systemImage: "tornado")
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(.purple)
                    .disabled(!model.canMix)

                    Button {
                        model.emptyPipette()
                    } label: {
                        Label("Empty pipette", systemImage: "arrow.uturn.backward")
                    }
                    .disabled(model.loadedReagent == nil)

                    Spacer()

                    Button(role: .destructive) {
                        model.restart()
                    } label: {
                        Label("Restart", systemImage: "trash")
                    }
                }

                tubeContents
            }
            .padding(24)
        }
    }

    private var statusCard: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Text("Pipette:")
                    .font(.headline)
                if let loaded = model.loadedReagent {
                    Circle().fill(loaded.color.swiftUI).frame(width: 16, height: 16)
                    Text(loaded.name)
                } else {
                    Text("empty").foregroundStyle(.secondary)
                }
            }
            Text(model.statusMessage)
                .font(.callout)
                .foregroundStyle(model.lastActionWasError ? .red : .primary)
        }
        .padding()
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 14))
    }

    private var tubeContents: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text("Tube contents")
                .font(.title3.bold())
            if model.dispensedReagents.isEmpty {
                Text("Empty").foregroundStyle(.secondary)
            } else {
                ForEach(Array(model.dispensedReagents.enumerated()), id: \.offset) { idx, reagent in
                    HStack {
                        Text("\(idx + 1).")
                            .foregroundStyle(.secondary)
                        Circle().fill(reagent.color.swiftUI).frame(width: 14, height: 14)
                        Text(reagent.label)
                    }
                }
            }
        }
    }

    // MARK: - Immersive space

    private func toggleImmersive() async {
        if immersiveOpen {
            await dismissImmersiveSpace()
            immersiveOpen = false
        } else {
            switch await openImmersiveSpace(id: "Lab") {
            case .opened:
                immersiveOpen = true
            case .userCancelled, .error:
                immersiveOpen = false
            @unknown default:
                immersiveOpen = false
            }
        }
    }
}

// MARK: - Protocol notepad window

/// A standalone floating window that shows the protocol like a notepad. The user
/// can open it, drag it anywhere in space, and close it independently.
struct ProtocolWindow: View {
    static let windowID = "protocol"

    var body: some View {
        ProtocolListView()
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
            .background(.regularMaterial)
    }
}

/// The ordered protocol steps with live completion status. Shared so the same
/// content could appear anywhere; here it lives in the notepad window.
struct ProtocolListView: View {
    @Environment(LabModel.self) private var model

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 10) {
                Image(systemName: "list.clipboard.fill")
                    .font(.title2)
                    .foregroundStyle(.tint)
                VStack(alignment: .leading, spacing: 2) {
                    Text("Master Mix Protocol")
                        .font(.title2.bold())
                    Text("Add the reagents in order")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
            .padding(20)

            Divider()

            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    ForEach(Array(model.steps.enumerated()), id: \.element.id) { idx, step in
                        stepRow(step)
                        if idx < model.steps.count - 1 {
                            Divider().padding(.leading, 20)
                        }
                    }
                }
            }

            Divider()

            HStack(spacing: 8) {
                Image(systemName: model.isMixed ? "checkmark.seal.fill" : "flask")
                    .foregroundStyle(model.isMixed ? .green : .secondary)
                Text(footerMessage)
                    .font(.callout)
                    .foregroundStyle(model.isMixed ? .green : .secondary)
            }
            .padding(20)
        }
    }

    private func stepRow(_ step: ProtocolStep) -> some View {
        let done = model.dispensedReagents.contains(step.reagent)
            && model.dispensedReagents.count >= step.order
        let isCurrent = model.currentStep?.id == step.id

        return HStack(alignment: .top, spacing: 14) {
            Image(systemName: done ? "checkmark.circle.fill"
                  : (isCurrent ? "arrow.right.circle.fill" : "circle"))
                .foregroundStyle(done ? .green : (isCurrent ? .blue : .secondary))
                .font(.title3)

            Circle()
                .fill(step.reagent.color.swiftUI)
                .frame(width: 18, height: 18)
                .overlay(Circle().strokeBorder(.secondary.opacity(0.4)))
                .padding(.top, 3)

            VStack(alignment: .leading, spacing: 3) {
                Text("\(step.order). \(step.reagent.name)")
                    .font(.headline)
                    .strikethrough(done, color: .secondary)
                Text("\(step.reagent.volumeUL) µL · \(step.note)")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            Spacer(minLength: 0)
        }
        .padding(20)
        .background(isCurrent ? Color.blue.opacity(0.08) : .clear)
    }

    private var footerMessage: String {
        if model.isMixed { return "Protocol complete — reaction assembled." }
        if model.isComplete { return "All reagents added — mix to finish." }
        if let step = model.currentStep {
            return "Next: step \(step.order), \(step.reagent.name)."
        }
        return ""
    }
}

#Preview(windowStyle: .automatic) {
    ContentView()
        .environment(LabModel())
}
