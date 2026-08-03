import AuthenticationServices
import SharedKit
import SwiftData
import SwiftUI

@main
struct ReelMapApp: App {
    @UIApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @Environment(\.scenePhase) private var scenePhase
    @StateObject private var app = AppState()
    @StateObject private var activity = ActivityStore()
    @StateObject private var push = PushManager.shared
    @StateObject private var maps = MapStore()

    private let container: ModelContainer = LocalStore.makeContainer()

    var body: some Scene {
        WindowGroup {
            Group {
                switch app.phase {
                case .loading:
                    SplashView()
                case .signedOut:
                    // Flip one flag and nothing else. Routing the whole session
                    // startup back through the App struct from a captured
                    // closure is exactly the kind of thing that quietly does
                    // nothing; the phase change below drives the rest.
                    SignInScreen { app.phase = .signedIn }
                case .signedIn:
                    RootView()
                }
            }
            .tint(.appAccent)
            .environmentObject(activity)
            .environmentObject(push)
            .environmentObject(maps)
            .task { await app.start() }
            .onChange(of: app.phase) { _, phase in
                // Single place that reacts to becoming signed in — whether that
                // came from launch, a fresh sign-in, or re-auth.
                guard phase == .signedIn else { return }
                Task { await startSession() }
            }
            .onReceive(NotificationCenter.default.publisher(for: SessionExpiry.didExpire)) { _ in
                // A refresh failed: the session is genuinely gone. Show sign-in
                // rather than a silently empty map.
                activity.pause()
                app.phase = .signedOut
            }
            .onChange(of: scenePhase) { _, phase in
                guard app.phase == .signedIn else { return }
                // Returning from Instagram after a share lands here: refresh the
                // queue, show status, and sync pins as reels finish.
                if phase == .active {
                    activity.resume(container.mainContext)
                    Task { await maps.refresh() }
                } else {
                    activity.pause()
                }
            }
        }
        .modelContainer(container)
    }

    private func startSession() async {
        await maps.refresh()
        activity.resume(container.mainContext)
        // Tokens rotate; re-register each launch or notifications quietly stop.
        await push.registerIfAuthorized()
    }
}

/// Session state. There is no silent `dev:` sign-in any more — production
/// rejects those tokens, so the app has to ask.
@MainActor
final class AppState: ObservableObject {
    enum Phase { case loading, signedOut, signedIn }

    @Published var phase: Phase = .loading

    func start() async {
        guard AuthStore.isSignedIn else {
            phase = .signedOut
            return
        }

        // Show the app immediately when we already hold an access token. The
        // launch used to sit on a splash through two network round trips —
        // Apple's credential check and a token refresh — before rendering
        // anything, which is seconds of nothing on a cold start.
        if AuthStore.token != nil {
            phase = .signedIn
            Task { await validateInBackground() }
            return
        }

        // No access token, only a refresh token: we do have to wait, but this
        // is one request, not two.
        if (try? await APIClient.shared.refreshSession()) != nil {
            phase = .signedIn
            Task { await validateInBackground() }
        } else {
            AuthStore.signOut()
            phase = .signedOut
        }
    }

    /// Off the launch path: any request that 401s will refresh or sign out on
    /// its own, so this only has to catch the case iOS can tell us about —
    /// the user revoking the app under Settings → Apple ID.
    private func validateInBackground() async {
        guard await AppleIDStore.isStillAuthorized() else {
            AuthStore.signOut()
            phase = .signedOut
            return
        }
    }
}

private struct SplashView: View {
    var body: some View {
        ZStack {
            Color.canvas.ignoresSafeArea()
            VStack(spacing: 16) {
                Image(systemName: "mappin.and.ellipse")
                    .font(.system(size: 64, weight: .semibold))
                    .foregroundStyle(.appAccent)
                Text("ReelMap").font(.display(34, .bold)).foregroundStyle(.ink)
                ProgressView().padding(.top, 4)
            }
        }
    }
}
