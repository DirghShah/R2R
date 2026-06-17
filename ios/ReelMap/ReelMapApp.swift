import SharedKit
import SwiftData
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
            .tint(.appAccent)
            .environmentObject(session)
        }
        .modelContainer(for: [CachedPlace.self, CachedList.self])
    }
}

@MainActor
final class SessionViewModel: ObservableObject {
    @Published var isAuthenticated = AuthStore.token != nil

    func signInCompleted() { isAuthenticated = AuthStore.token != nil }
    func signOut() { AuthStore.token = nil; isAuthenticated = false }
}
