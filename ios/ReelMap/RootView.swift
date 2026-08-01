import SharedKit
import SwiftData
import SwiftUI

struct RootView: View {
    @EnvironmentObject private var push: PushManager
    @EnvironmentObject private var maps: MapStore
    @Environment(\.modelContext) private var context
    @Environment(\.scenePhase) private var scenePhase
    @State private var tab: Tab = .map
    @State private var pendingInvite: String?

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
            guard let link else { return }
            push.pendingDeepLink = nil
            handle(link)
        }
        // Universal Link (https://…/join/CODE) or the custom scheme.
        .onOpenURL { url in handle(url) }
        .sheet(item: Binding(get: { pendingInvite.map(InviteCode.init) },
                             set: { pendingInvite = $0?.value })) { invite in
            JoinMapScreen(code: invite.value) { _ in
                tab = .map
                Task { await Syncer.refresh(context, force: true) }
            }
        }
    }

    private func handle(_ url: URL) {
        if let code = InviteLink.code(from: url) {
            pendingInvite = code
            return
        }
        // Anything else (a push deep link) just means "show me the map".
        tab = .map
        Task { await Syncer.refresh(context, force: true) }
    }
}

/// `sheet(item:)` needs Identifiable, and a bare String isn't.
private struct InviteCode: Identifiable {
    let value: String
    var id: String { value }
    init(_ value: String) { self.value = value }
}
