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
/// lands straight on the map. (Swap `dev:me` for real Sign in with Apple later.)
@MainActor
final class AppState: ObservableObject {
    @Published var ready = false

    func start() async {
        if AuthStore.token == nil {
            _ = try? await APIClient.shared.signInWithApple(identityToken: "dev:me")
        }
        ready = true
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
