import SwiftUI

@main
struct VisionBioLabApp: App {
    /// One shared model drives both the window and the immersive scene.
    @State private var model = LabModel()
    @State private var immersionStyle: ImmersionStyle = .full

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environment(model)
        }
        .windowResizability(.contentSize)
        .defaultSize(width: 620, height: 500)

        // The protocol "notepad" — a separate floating window the user can open,
        // reposition, and close independently of the main controls.
        WindowGroup(id: ProtocolWindow.windowID) {
            ProtocolWindow()
                .environment(model)
        }
        .windowResizability(.contentSize)
        .defaultSize(width: 380, height: 520)

        // The full virtual lab room (fully immersive — replaces passthrough).
        ImmersiveSpace(id: "Lab") {
            ImmersiveLabView()
                .environment(model)
        }
        .immersionStyle(selection: $immersionStyle, in: .full)
    }
}
