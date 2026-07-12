import SharedKit
import SwiftData
import SwiftUI

@main
struct ReelMapApp: App {
    @StateObject private var app = AppState()

    var body: some Scene {
        WindowGroup {
            Group {
                if app.ready {
                    RootView()
                } else {
                    SplashView()
                }
            }
            .tint(.appAccent)
            .task { await app.start() }
        }
        .modelContainer(for: [CachedPlace.self, CachedList.self])
    }
}

/// No sign-in screen for now: acquire a session silently on launch so the user
/// lands straight on the map, then submit any links the Share Extension queued
/// while offline. (Swap `dev:me` for real Sign in with Apple before App Store release.)
@MainActor
final class AppState: ObservableObject {
    @Published var ready = false

    func start() async {
        if AuthStore.token == nil {
            _ = try? await APIClient.shared.signInWithApple(identityToken: "dev:me")
        }
        ready = true

        // Links shared while the backend was unreachable — submit them now.
        for url in PendingQueue.drain() {
            _ = try? await APIClient.shared.submitReel(url: url)
        }
    }
}

private struct SplashView: View {
    var body: some View {
        VStack(spacing: 16) {
            Image(systemName: "mappin.and.ellipse")
                .font(.system(size: 64, weight: .semibold))
                .foregroundStyle(.tint)
            Text("ReelMap").font(.system(size: 34, weight: .bold, design: .rounded))
            ProgressView().padding(.top, 4)
        }
    }
}
