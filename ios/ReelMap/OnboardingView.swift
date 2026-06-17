import AuthenticationServices
import SharedKit
import SwiftUI

struct OnboardingView: View {
    @ObservedObject var session: SessionViewModel
    @State private var error: String?
    @State private var busy = false

    var body: some View {
        ZStack {
            LinearGradient(
                colors: [Color(red: 0.96, green: 0.55, blue: 0.30).opacity(0.30),
                         Color(red: 0.36, green: 0.42, blue: 0.85).opacity(0.18), .clear],
                startPoint: .topLeading, endPoint: .bottomTrailing)
                .ignoresSafeArea()

            VStack(spacing: 20) {
                Spacer()
                Image(systemName: "mappin.and.ellipse")
                    .font(.system(size: 72, weight: .semibold))
                    .foregroundStyle(.tint)
                Text("ReelMap").font(.system(size: 40, weight: .bold, design: .rounded))
                Text("Every place you save from a reel —\nfinally on one map.")
                    .font(.title3).multilineTextAlignment(.center)
                    .foregroundStyle(.secondary)
                Spacer()
                buttons
            }
            .padding(32)
        }
        .tint(Color(red: 0.92, green: 0.45, blue: 0.20))
    }

    private var buttons: some View {
        VStack(spacing: 12) {
            #if DEBUG
            Button { Task { await signIn("dev:me") } } label: {
                Label("Continue (dev)", systemImage: "hammer.fill")
                    .font(.headline).frame(maxWidth: .infinity).padding(.vertical, 6)
            }
            .buttonStyle(.glassProminent)
            .disabled(busy)
            #endif

            SignInWithAppleButton(.continue) { req in
                req.requestedScopes = [.fullName, .email]
            } onCompletion: { result in
                Task { await handleApple(result) }
            }
            .signInWithAppleButtonStyle(.black)
            .frame(height: 52)
            .clipShape(.capsule)

            if let error {
                Text(error).font(.caption).foregroundStyle(.red).multilineTextAlignment(.center)
            }
        }
    }

    private func handleApple(_ result: Result<ASAuthorization, Error>) async {
        switch result {
        case .success(let auth):
            guard let cred = auth.credential as? ASAuthorizationAppleIDCredential,
                  let data = cred.identityToken, let token = String(data: data, encoding: .utf8) else {
                error = "Couldn't read Apple credential"; return
            }
            await signIn(token)
        case .failure(let err):
            error = err.localizedDescription
        }
    }

    private func signIn(_ token: String) async {
        busy = true; defer { busy = false }
        do {
            _ = try await APIClient.shared.signInWithApple(identityToken: token)
            session.signInCompleted()
        } catch {
            self.error = error.localizedDescription
        }
    }
}
