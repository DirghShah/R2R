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

    var body: some View {
        ZStack {
            Color.canvas.ignoresSafeArea()
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
        .alert("Couldn't sign in", isPresented: .init(get: { errorText != nil },
                                                     set: { if !$0 { errorText = nil } })) {
            Button("OK", role: .cancel) {}
        } message: {
            Text(errorText ?? "")
        }
    }

    private var hero: some View {
        VStack(spacing: 18) {
            ZStack {
                Circle().fill(Color.appAccent.opacity(0.12)).frame(width: 96, height: 96)
                Image(systemName: "mappin.and.ellipse")
                    .font(.system(size: 42, weight: .semibold))
                    .foregroundStyle(.appAccent)
            }
            VStack(spacing: 8) {
                Text("ReelMap").font(.display(34, .bold)).foregroundStyle(.ink)
                Text("Share a reel. Get the pin.")
                    .font(.system(size: 17)).foregroundStyle(.inkSecondary)
            }
            VStack(alignment: .leading, spacing: 14) {
                bullet("square.and.arrow.up", "Share reels straight from Instagram")
                bullet("sparkles", "Places, tips and hours pulled out automatically")
                bullet("person.2.fill", "Build maps together with friends")
            }
            .padding(.top, 12)
        }
    }

    private func bullet(_ icon: String, _ text: String) -> some View {
        HStack(spacing: 13) {
            Image(systemName: icon).font(.system(size: 16)).foregroundStyle(.appAccent)
                .frame(width: 24)
            Text(text).font(.system(size: 15)).foregroundStyle(.ink)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
        }
    }

    private var signInButton: some View {
        SignInWithAppleButton(.signIn) { request in
            // fullName arrives ONLY on the very first authorization for this
            // Apple ID, and never inside the identity token — so we ask for it
            // here and forward it once.
            request.requestedScopes = [.fullName]
        } onCompletion: { result in
            handle(result)
        }
        .signInWithAppleButtonStyle(scheme == .dark ? .white : .black)
        .frame(height: 52)
        .clipShape(RoundedRectangle(cornerRadius: 14, style: .continuous))
        .disabled(working)
        .opacity(working ? 0.5 : 1)
        .overlay { if working { ProgressView().tint(.inkSecondary) } }
    }

    private var footnote: some View {
        Text("We only store the places from reels you share — never the videos.")
            .font(.system(size: 12)).foregroundStyle(.inkMuted)
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
            errorText = error.localizedDescription

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
                    try await APIClient.shared.signInWithApple(
                        identityToken: identityToken, displayName: name, authorizationCode: code)
                    _ = try? await APIClient.shared.me()  // caches our own user id
                    onSignedIn()
                } catch {
                    errorText = error.localizedDescription
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
