import SharedKit
import SwiftUI
import UserNotifications

/// APNs registration + the "your pins are ready" tap handling.
///
/// Analysis is asynchronous and the Share Extension dismisses immediately, so
/// without this nothing ever tells the user their pins landed — the app only
/// polls while it's in the foreground. The backend already sends the payload
/// (`worker/push.py`); this is the phone half.
@MainActor
final class PushManager: ObservableObject {
    static let shared = PushManager()

    /// Set when a notification tap should take the user somewhere. RootView
    /// observes it, switches to the Map tab, and clears it.
    @Published var pendingDeepLink: URL?

    /// We only ever show the system prompt once, and only at a moment where the
    /// reason is obvious (right after the first reel is submitted).
    private static let askedKey = "push_permission_requested"

    private var hasAsked: Bool {
        get { UserDefaults.standard.bool(forKey: Self.askedKey) }
        set { UserDefaults.standard.set(newValue, forKey: Self.askedKey) }
    }

    /// Re-register on every launch: APNs tokens rotate (restore from backup, app
    /// reinstall), and a stale token silently drops every notification.
    func registerIfAuthorized() async {
        let settings = await UNUserNotificationCenter.current().notificationSettings()
        guard settings.authorizationStatus == .authorized
                || settings.authorizationStatus == .provisional else { return }
        UIApplication.shared.registerForRemoteNotifications()
    }

    /// Ask for permission the first time the user submits a reel — the value of
    /// saying yes is self-evident at that moment, unlike a cold launch prompt.
    func requestOnFirstReel() async {
        guard !hasAsked else { return }
        let status = await UNUserNotificationCenter.current().notificationSettings().authorizationStatus
        guard status == .notDetermined else {
            hasAsked = true
            return
        }
        hasAsked = true
        let granted = (try? await UNUserNotificationCenter.current()
            .requestAuthorization(options: [.alert, .sound, .badge])) ?? false
        if granted { UIApplication.shared.registerForRemoteNotifications() }
    }

    /// Hand the device token to the backend so `notify_user` has somewhere to
    /// send. Silent failure is fine — we re-register on the next launch.
    func submit(deviceToken: Data) async {
        let hex = deviceToken.map { String(format: "%02x", $0) }.joined()
        try? await APIClient.shared.registerDevice(apnsToken: hex)
    }
}

/// UIKit is still the only way to receive an APNs device token, so the SwiftUI
/// app keeps a thin delegate for it.
final class AppDelegate: NSObject, UIApplicationDelegate, UNUserNotificationCenterDelegate {
    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions options: [UIApplication.LaunchOptionsKey: Any]? = nil
    ) -> Bool {
        UNUserNotificationCenter.current().delegate = self
        return true
    }

    func application(
        _ application: UIApplication,
        didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data
    ) {
        Task { await PushManager.shared.submit(deviceToken: deviceToken) }
    }

    func application(
        _ application: UIApplication,
        didFailToRegisterForRemoteNotificationsWithError error: Error
    ) {
        // Expected on the Simulator and on free developer accounts (no push
        // entitlement). The app works fine without it — you just have to open
        // it to see new pins.
        #if DEBUG
        print("[push] registration failed: \(error.localizedDescription)")
        #endif
    }

    /// Show the banner even when the user is already in the app — pins appearing
    /// on a map they're looking at is exactly when the message makes sense.
    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        willPresent notification: UNNotification
    ) async -> UNNotificationPresentationOptions {
        [.banner, .sound]
    }

    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        didReceive response: UNNotificationResponse
    ) async {
        let info = response.notification.request.content.userInfo
        let link = (info["deep_link"] as? String).flatMap(URL.init(string:))
        await MainActor.run { PushManager.shared.pendingDeepLink = link ?? URL(string: "reelmap://map") }
    }
}
