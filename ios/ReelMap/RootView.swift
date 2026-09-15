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

    /// Shown once, ever. A new person used to land on an empty map with
    /// nothing to press; two first-time testers both stopped there.
    @AppStorage("hasSeenWelcome") private var hasSeenWelcome = false
    @State private var showingSearch = false

    enum Tab { case map, lists, add }

    var body: some View {
        TabView(selection: $tab) {
            MapScreen(openSearch: { showingSearch = true },
                      openAdd: { tab = .add })
                .tabItem { Label("Map", systemImage: "mappin.and.ellipse") }
                .tag(Tab.map)
            CityListsScreen(openSearch: { showingSearch = true },
                            openAdd: { tab = .add })
                .tabItem { Label("Lists", systemImage: "list.bullet") }
                .tag(Tab.lists)
            AddReelScreen(openSearch: { showingSearch = true })
                // "Analyze" described the machinery; "Add" describes what the
                // person is trying to do, and the tab now holds two ways to.
                .tabItem { Label("Add", systemImage: "plus.circle") }
                .tag(Tab.add)
        }
        .fullScreenCover(isPresented: .init(get: { !hasSeenWelcome },
                                            set: { if !$0 { hasSeenWelcome = true } })) {
            WelcomeScreen { choice in
                hasSeenWelcome = true
                switch choice {
                case .example: tab = .map
                case .pasteLink: tab = .add
                case .search: showingSearch = true
                case .skip: break
                }
            }
        }
        .sheet(isPresented: $showingSearch) { PlaceSearchScreen() }
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
