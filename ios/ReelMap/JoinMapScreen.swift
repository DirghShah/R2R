import SharedKit
import SwiftUI

/// What you land on when someone sends you an invite link.
///
/// The preview is fetched *unauthenticated* on purpose: you should be able to
/// see what you're being invited to before deciding whether to sign in for it.
struct JoinMapScreen: View {
    let code: String
    var onJoined: (MapSummary) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var preview: MapPreview?
    @State private var loading = true
    @State private var joining = false
    @State private var errorText: String?

    var body: some View {
        NavigationStack {
            ZStack {
                Color.canvas.ignoresSafeArea()
                if loading {
                    ProgressView().tint(.appAccent)
                } else if let preview {
                    content(preview)
                } else {
                    expired
                }
            }
            .navigationTitle("Join map")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Not now") { dismiss() } }
            }
            .task { await load() }
            .alert("Couldn't join", isPresented: .init(get: { errorText != nil },
                                                      set: { if !$0 { errorText = nil } })) {
                Button("OK", role: .cancel) {}
            } message: { Text(errorText ?? "") }
        }
    }

    private func content(_ preview: MapPreview) -> some View {
        VStack(spacing: 0) {
            Spacer()
            Text(preview.emoji ?? "📍").font(.system(size: 56))
                .frame(width: 104, height: 104)
                .background(Color.cardFill, in: RoundedRectangle(cornerRadius: 28, style: .continuous))
                .overlay(RoundedRectangle(cornerRadius: 28, style: .continuous)
                    .strokeBorder(Color.cardStroke))

            Text(preview.name).font(.display(26, .bold)).foregroundStyle(.ink)
                .multilineTextAlignment(.center)
                .padding(.top, 18)

            Text(invitationLine(preview))
                .font(.system(size: 15)).foregroundStyle(.inkSecondary)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
                .padding(.top, 6)

            Spacer()

            Button { Task { await join() } } label: {
                HStack(spacing: 8) {
                    if joining { ProgressView().tint(.white) }
                    Text(joining ? "Joining…" : "Join map")
                        .font(.system(size: 16, weight: .semibold))
                }
                .foregroundStyle(.white).frame(maxWidth: .infinity).padding(.vertical, 15)
                .background(Color.appAccent, in: RoundedRectangle(cornerRadius: 15, style: .continuous))
            }
            .buttonStyle(.plain)
            .disabled(joining)

            Text("You'll be able to add places, and everyone in the map sees them.")
                .font(.system(size: 12)).foregroundStyle(.inkMuted)
                .multilineTextAlignment(.center)
                .padding(.top, 12)
        }
        .padding(.horizontal, 28).padding(.bottom, 34)
    }

    private func invitationLine(_ preview: MapPreview) -> String {
        let who = preview.ownerName ?? "Someone"
        let count = preview.memberCount
        let people = count == 1 ? "1 person is" : "\(count) people are"
        return "\(who) invited you. \(people) already in."
    }

    private var expired: some View {
        VStack(spacing: 10) {
            Image(systemName: "link.badge.plus").font(.system(size: 34))
                .foregroundStyle(.inkMuted)
            Text("This link no longer works").font(.display(18, .semibold)).foregroundStyle(.ink)
            Text("The map may have been deleted, or its owner reset the invite link. Ask them for a new one.")
                .font(.callout).foregroundStyle(.inkSecondary)
                .multilineTextAlignment(.center)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(32)
    }

    private func load() async {
        loading = true
        defer { loading = false }
        preview = try? await APIClient.shared.previewInvite(code: code)
    }

    private func join() async {
        joining = true
        defer { joining = false }
        do {
            let map = try await APIClient.shared.joinMap(code: code)
            Haptics.success()
            onJoined(map)
            dismiss()
        } catch {
            errorText = error.localizedDescription
        }
    }
}

/// Pulls the invite code out of a link, whichever form it arrives in.
enum InviteLink {
    /// Universal link (`https://…/join/ABC123`) or custom scheme
    /// (`reelmap://join/ABC123`).
    static func code(from url: URL) -> String? {
        let parts = url.pathComponents.filter { $0 != "/" }
        if let index = parts.firstIndex(of: "join"), index + 1 < parts.count {
            return parts[index + 1]
        }
        // reelmap://join/CODE puts "join" in the host, not the path.
        if url.host == "join", let first = parts.first { return first }
        return nil
    }
}
