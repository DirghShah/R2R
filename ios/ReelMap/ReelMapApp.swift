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
        // Submit any reels the Share Extension queued while offline.
        for url in PendingQueue.drain() {
            try? await APIClient.shared.submitReel(url: url)
        }
    }

    func signInCompleted() { isAuthenticated = AuthStore.token != nil }
    func signOut() { AuthStore.token = nil; isAuthenticated = false }
}
