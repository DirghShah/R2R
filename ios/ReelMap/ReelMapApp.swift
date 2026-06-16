import SharedKit
import SwiftUI

@main
struct ReelMapApp: App {
    @StateObject private var session = SessionViewModel()

    var body: some Scene {
        WindowGroup {
            Group {
                if session.isAuthenticated {
                    RootView()
                } else {
                    OnboardingView(session: session)
                }
            }
            .task { await session.bootstrap() }
        }
    }
}

@MainActor
final class SessionViewModel: ObservableObject {
    @Published var isAuthenticated = AuthStore.token != nil

    func bootstrap() async {
        // (Paid build) the Share Extension drains its offline queue here. The
        // free build adds reels via the Add tab, so nothing to do on launch.
    }

    func signInCompleted() { isAuthenticated = AuthStore.token != nil }
    func signOut() { AuthStore.token = nil; isAuthenticated = false }
}
