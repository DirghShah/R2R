import SharedKit
import SwiftData
import SwiftUI

@main
struct ReelMapApp: App {
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var app = AppState()
    @StateObject private var activity = ActivityStore()

    private let container: ModelContainer = {
        // Fail-fast on schema errors; models are simple value stores.
        try! ModelContainer(for: CachedPlace.self, CachedList.self)
    }()

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
            .environmentObject(activity)
            .task {
                await app.start()
                activity.resume(container.mainContext)
            }
            .onChange(of: scenePhase) { _, phase in
                // Returning from Instagram after a share lands here: refresh the
                // queue, show status, and sync pins as reels finish.
                if phase == .active, app.ready {
                    activity.resume(container.mainContext)
                } else if phase != .active {
                    activity.pause()
                }
            }
        }
        .modelContainer(container)
    }
}

/// No sign-in screen for now: acquire a session silently on launch so the user
/// lands straight on the map. (Swap `dev:me` for real Sign in with Apple before
/// App Store release — see the README checklist.)
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
