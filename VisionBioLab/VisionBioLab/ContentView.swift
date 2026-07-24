import SwiftUI

/// The 2D window: protocol sheet, reagent controls, status, and a button to
/// open / close the immersive lab. Works hand-in-hand with the 3D scene — both
/// drive the same `LabModel`.
struct ContentView: View {
    @Environment(LabModel.self) private var model
    @Environment(\.openImmersiveSpace) private var openImmersiveSpace
    @Environment(\.dismissImmersiveSpace) private var dismissImmersiveSpace

    @State private var immersiveOpen = false

    var body: some View {
        NavigationSplitView {
            protocolSheet
                .navigationTitle("Protocol")
                .frame(minWidth: 320)
        } detail: {
            controls
                .navigationTitle("Virtual Bio Lab")
        }
    }

    // MARK: - Protocol sheet

    private var protocolSheet: some View {
        List {
            Section("Master Mix — add in order") {
                ForEach(model.steps) { step in
                    HStack(spacing: 12) {
                        statusIcon(for: step)
                        Circle()
                            .fill(step.reagent.color.swiftUI)
                            .frame(width: 18, height: 18)
                            .overlay(Circle().strokeBorder(.secondary.opacity(0.4)))
                        VStack(alignment: .leading, spacing: 2) {
                            Text("\(step.order). \(step.reagent.name)")
                                .font(.headline)
                            Text("\(step.reagent.volumeUL) µL · \(step.note)")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                    .padding(.vertical, 4)
                }
            }
        }
    }

    private func statusIcon(for step: ProtocolStep) -> some View {
        let done = model.dispensedReagents.contains(step.reagent)
            && model.dispensedReagents.count >= step.order
        let isCurrent = model.currentStep?.id == step.id
        return Image(systemName: done ? "checkmark.circle.fill"
                     : (isCurrent ? "arrow.right.circle.fill" : "circle"))
            .foregroundStyle(done ? .green : (isCurrent ? .blue : .secondary))
            .font(.title3)
    }

    // MARK: - Controls

    private var controls: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {

                Button {
                    Task { await toggleImmersive() }
                } label: {
                    Label(immersiveOpen ? "Exit Lab" : "Enter Lab",
                          systemImage: immersiveOpen ? "xmark.circle" : "cube.transparent")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)

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

#Preview(windowStyle: .automatic) {
    ContentView()
        .environment(LabModel())
}
