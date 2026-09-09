import AuthenticationServices
import SharedKit
import SwiftUI

/// Sign in with Apple, and nothing else.
///
/// No email/password: on an iOS-only app every user already has an Apple ID, it
/// costs a password-reset flow, email verification and breach liability, and
/// App Store Guideline 4.8 means offering any *other* third-party sign-in would
/// oblige us to offer Apple anyway.
struct SignInScreen: View {
    @Environment(\.colorScheme) private var scheme
    var onSignedIn: () -> Void

    @State private var working = false
    @State private var errorText: String?

    /// Pure black or pure white, not the app's warm canvas.
    ///
    /// This is the one screen that is only the mark, and the mark is drawn in
    /// flat black ink — sitting it on an off-white ground makes it look like a
    /// sticker on the wrong paper.
    private var ground: Color { scheme == .dark ? .black : .white }
    private var ink: Color { scheme == .dark ? .white : .black }

    var body: some View {
        ZStack {
            ground.ignoresSafeArea()
            VStack(spacing: 0) {
                Spacer()
                hero
                Spacer()
                signInButton
                footnote
            }
            .padding(.horizontal, 28)
            .padding(.bottom, 40)
        }
        // Suppress a stale failure if a concurrent attempt has since succeeded —
        // tapping OK on an error and finding yourself signed in is baffling.
        .alert("Couldn't sign in", isPresented: .init(get: { errorText != nil && !AuthStore.isSignedIn },
                                                     set: { if !$0 { errorText = nil } })) {
            Button("OK", role: .cancel) {}
        } message: {
            Text(errorText ?? "")
        }
        .task {
            // Recovery: if a previous attempt stored a session but the screen
            // never advanced, don't strand the user on a sign-in page they've
            // already completed.
            if AuthStore.isSignedIn {
                print("[signin] session already present — continuing")
                onSignedIn()
            }
        }
    }

    private var hero: some View {
        VStack(spacing: 20) {
            // The real wordmark, not the name set in a system font next to an
            // icon. Same SVG the website uses, drawn as a template so one file
            // is black on white and white on black without a second asset.
            Image("Wordmark")
                .renderingMode(.template)
                .resizable()
                .scaledToFit()
                .frame(height: 46)
                .foregroundStyle(ink)
                .accessibilityLabel("Nosh")

            Text("Share a reel. Get the pin.")
                .font(.system(size: 17))
                .foregroundStyle(ink.opacity(0.55))

            VStack(alignment: .leading, spacing: 14) {
                bullet("square.and.arrow.up", "Share reels straight from Instagram")
                bullet("sparkles", "Places, tips and hours pulled out automatically")
                bullet("person.2.fill", "Build maps together with friends")
            }
            .padding(.top, 16)
        }
    }

    private func bullet(_ icon: String, _ text: String) -> some View {
        HStack(spacing: 13) {
            Image(systemName: icon).font(.system(size: 16))
                .foregroundStyle(ink.opacity(0.45))
                .frame(width: 24)
            Text(text).font(.system(size: 15)).foregroundStyle(ink)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
        }
    }

    @ViewBuilder private var signInButton: some View {
        // No overlay on the button: SignInWithAppleButton is a bridged UIKit
        // control, and anything layered over it competes for the touch — which
        // is why it took several taps to register. The progress state is a
        // sibling instead.
        if working {
            HStack(spacing: 10) {
                ProgressView().tint(ink.opacity(0.55))
                Text("Signing in…").font(.system(size: 16, weight: .semibold))
                    .foregroundStyle(ink.opacity(0.55))
            }
            .frame(maxWidth: .infinity).frame(height: 52)
            .background(ink.opacity(0.08), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
        } else {
            SignInWithAppleButton(.signIn) { request in
                // fullName arrives ONLY on the very first authorization for
                // this Apple ID, and never inside the identity token — so we
                // ask for it here and forward it once.
                request.requestedScopes = [.fullName]
            } onCompletion: { result in
                handle(result)
            }
            .signInWithAppleButtonStyle(scheme == .dark ? .white : .black)
            .frame(height: 52)
            .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
        }
    }

    private var footnote: some View {
        Text("We only store the places from reels you share — never the videos.")
            .font(.system(size: 12)).foregroundStyle(ink.opacity(0.4))
            .multilineTextAlignment(.center)
            .fixedSize(horizontal: false, vertical: true)
            .padding(.top, 16)
    }

    @MainActor
    private func handle(_ result: Result<ASAuthorization, Error>) {
        switch result {
        case .failure(let error):
            // Cancelling isn't an error worth an alert.
            if (error as? ASAuthorizationError)?.code == .canceled { return }
            print("[signin] apple failed: \(error)")
            if (error as? ASAuthorizationError)?.code == .unknown {
                // Error 1000. Apple gives no detail, but the two real causes are
                // a missing entitlement (fixed) and re-requesting too soon after
                // a previous attempt.
                errorText = "Apple couldn't complete the sign-in. Wait a moment and try again — and check you're signed into iCloud in Settings."
            } else {
                errorText = error.localizedDescription
            }

        case .success(let auth):
            guard let credential = auth.credential as? ASAuthorizationAppleIDCredential,
                  let tokenData = credential.identityToken,
                  let identityToken = String(data: tokenData, encoding: .utf8) else {
                errorText = "Apple didn't return a usable sign-in token."
                return
            }
            // Both of these are first-authorization-only; nil on every later
            // sign-in, which the backend handles.
            let name = credential.fullName.flatMap(Self.formatted)
            let code = credential.authorizationCode.flatMap { String(data: $0, encoding: .utf8) }

            AppleIDStore.userID = credential.user
            working = true
            Task { @MainActor in
                defer { working = false }
                do {
                    print("[signin] apple ok, exchanging with backend…")
                    try await APIClient.shared.signInWithApple(
                        identityToken: identityToken, displayName: name, authorizationCode: code)
                    print("[signin] backend accepted; token stored=\(AuthStore.token != nil), refresh stored=\(AuthStore.refreshToken != nil)")
                    _ = try? await APIClient.shared.me()  // caches our own user id
                    onSignedIn()
                } catch let apiError as APIError {
                    // Apple worked; our server said no. Distinguishing the two
                    // halves matters — they have completely different fixes.
                    print("[signin] backend rejected: status=\(apiError.status) \(apiError.message)")
                    errorText = apiError.isNetwork
                        ? "\(apiError.message)\n\nApple signed you in, but ReelMap's server couldn't be reached."
                        : "Nosh's server rejected the sign-in.\n\n\(apiError.message)"
                } catch {
                    print("[signin] unexpected failure: \(error)")
                    errorText = "Signed in with Apple, but something went wrong afterwards.\n\n\(error.localizedDescription)"
                }
            }
        }
    }

    private static func formatted(_ components: PersonNameComponents) -> String? {
        let formatter = PersonNameComponentsFormatter()
        formatter.style = .default
        let name = formatter.string(from: components).trimmingCharacters(in: .whitespaces)
        return name.isEmpty ? nil : name
    }
}

/// The Apple user identifier, kept so we can ask Apple whether the credential
/// is still valid — users can revoke access in Settings, and without checking
/// the app would sit there broken.
public enum AppleIDStore {
    private static let key = "apple_user_id"

    public static var userID: String? {
        get { UserDefaults(suiteName: AuthStore.appGroup)?.string(forKey: key) }
        set {
            let store = UserDefaults(suiteName: AuthStore.appGroup)
            if let newValue { store?.set(newValue, forKey: key) }
            else { store?.removeObject(forKey: key) }
        }
    }

    /// True when Apple still considers our grant valid.
    static func isStillAuthorized() async -> Bool {
        guard let userID else { return true }  // nothing to check against
        let state = try? await ASAuthorizationAppleIDProvider().credentialState(forUserID: userID)
        return state != .revoked && state != .notFound
    }
}
