import SwiftUI

@main
struct VisionBioLabApp: App {
    /// One shared model drives both the window and the immersive scene.
    @State private var model = LabModel()
    @State private var immersionStyle: ImmersionStyle = .mixed

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environment(model)
        }
        .windowResizability(.contentSize)

        // The 3D lab bench, shown in mixed immersion so it sits in your room.
        ImmersiveSpace(id: "Lab") {
            ImmersiveLabView()
                .environment(model)
        }
        .immersionStyle(selection: $immersionStyle, in: .mixed)
    }
}
