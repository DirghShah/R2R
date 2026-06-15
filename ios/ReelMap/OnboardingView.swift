import AuthenticationServices
import SharedKit
import SwiftUI

struct OnboardingView: View {
    @ObservedObject var session: SessionViewModel
    @State private var error: String?

    var body: some View {
        VStack(spacing: 24) {
            Spacer()
            Image(systemName: "mappin.and.ellipse").font(.system(size: 64))
            Text("ReelMap").font(.largeTitle.bold())
            Text("Every place you save from Instagram, finally on one map.")
                .multilineTextAlignment(.center)
                .foregroundStyle(.secondary)
            Spacer()
            SignInWithAppleButton(.signIn) { request in
                request.requestedScopes = [.fullName, .email]
            } onCompletion: { result in
                Task { await handle(result) }
            }
            .signInWithAppleButtonStyle(.black)
            .frame(height: 50)
            if let error { Text(error).font(.caption).foregroundStyle(.red) }
        }
        .padding(32)
    }

    private func handle(_ result: Result<ASAuthorization, Error>) async {
        switch result {
        case .success(let auth):
            guard let cred = auth.credential as? ASAuthorizationAppleIDCredential,
                  let tokenData = cred.identityToken,
                  let token = String(data: tokenData, encoding: .utf8) else {
                error = "Could not read Apple credential"
                return
            }
            do {
                _ = try await APIClient.shared.signInWithApple(identityToken: token)
                session.signInCompleted()
            } catch {
                self.error = error.localizedDescription
            }
        case .failure(let err):
            error = err.localizedDescription
        }
    }
}
