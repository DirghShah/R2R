import SwiftData
import SwiftUI

struct RootView: View {
    @EnvironmentObject private var push: PushManager
    @Environment(\.modelContext) private var context
    @State private var tab: Tab = .map

    enum Tab { case map, lists, add }

    var body: some View {
        TabView(selection: $tab) {
            MapScreen()
                .tabItem { Label("Map", systemImage: "mappin.and.ellipse") }
                .tag(Tab.map)
            CityListsScreen()
                .tabItem { Label("Lists", systemImage: "list.bullet") }
                .tag(Tab.lists)
            AddReelScreen()
                .tabItem { Label("Analyze", systemImage: "waveform.path.ecg") }
                .tag(Tab.add)
        }
        // Tapping "3 places saved from your reel" should land on the pins it's
        // talking about, not wherever the app was last left.
        .onChange(of: push.pendingDeepLink) { _, link in
            guard link != nil else { return }
            tab = .map
            push.pendingDeepLink = nil
            Task { await Syncer.refresh(context, force: true) }
        }
    }
}
