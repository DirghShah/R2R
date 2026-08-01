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

    private let container: ModelContainer = {
        // Fail-fast on schema errors; models are simple value stores.
        try! ModelContainer(for: CachedPlace.self, CachedList.self, PlaceMark.self)
    }()

    var body: some Scene {
        WindowGroup {
            Group {
                switch app.phase {
                case .loading:
                    SplashView()
                case .signedOut:
                    SignInScreen { Task { await signedIn() } }
                case .signedIn:
                    RootView()
                }
            }
            .tint(.appAccent)
            .environmentObject(activity)
            .environmentObject(push)
            .environmentObject(maps)
            .task {
                await app.start()
                if app.phase == .signedIn { await startSession() }
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

    private func signedIn() async {
        app.phase = .signedIn
        await startSession()
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
        // Users can revoke the app under Settings → Apple ID. Without checking,
        // the app would keep a dead session and fail every request.
        guard await AppleIDStore.isStillAuthorized() else {
            AuthStore.signOut()
            phase = .signedOut
            return
        }
        // The access token is short-lived; trade the refresh token for a fresh
        // one now rather than letting the first request of the session 401.
        if AuthStore.token == nil {
            guard (try? await APIClient.shared.refreshSession()) != nil else {
                AuthStore.signOut()
                phase = .signedOut
                return
            }
        }
        phase = .signedIn
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
