import SharedKit
import SwiftUI

/// Share a map, see who's in it, and leave or delete it.
struct MapDetailSheet: View {
    let map: MapSummary

    @EnvironmentObject private var store: MapStore
    @Environment(\.dismiss) private var dismiss

    @State private var members: [MapMemberSummary] = []
    @State private var invite: MapInvite?
    @State private var loadingInvite = false
    @State private var confirmRemoval = false
    @State private var errorText: String?
    @State private var pendingRemoval: MapMemberSummary?

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    header
                    shareCard
                    membersCard
                    dangerButton
                }
                .padding(20)
            }
            .background(Color.canvas)
            .navigationTitle(map.name)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } }
            }
            .task { await load() }
            .confirmationDialog(removalTitle, isPresented: $confirmRemoval, titleVisibility: .visible) {
                Button(removalVerb, role: .destructive) { Task { await removeSelf() } }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text(removalExplanation)
            }
            .alert("Something went wrong", isPresented: .init(get: { errorText != nil },
                                                             set: { if !$0 { errorText = nil } })) {
                Button("OK", role: .cancel) {}
            } message: { Text(errorText ?? "") }
        }
        .presentationDetents([.medium, .large])
    }

    private var header: some View {
        HStack(spacing: 13) {
            Text(map.emoji ?? "📍").font(.system(size: 30))
                .frame(width: 60, height: 60)
                .background(Color.cardStroke, in: RoundedRectangle(cornerRadius: 17, style: .continuous))
            VStack(alignment: .leading, spacing: 3) {
                Text(map.name).font(.display(20, .bold)).foregroundStyle(.ink)
                Text("\(map.placeCount) place\(map.placeCount == 1 ? "" : "s")")
                    .font(.system(size: 14)).foregroundStyle(.inkSecondary)
            }
            Spacer()
        }
    }

    // MARK: Share

    @ViewBuilder private var shareCard: some View {
        if map.isOwner {
            VStack(alignment: .leading, spacing: 12) {
                Label("Share this map", systemImage: "person.2.fill")
                    .font(.display(15, .semibold)).foregroundStyle(.ink)
                Text("Anyone with the link can join and add places. They don't need the app yet — the link takes them to the App Store first.")
                    .font(.system(size: 13)).foregroundStyle(.inkSecondary)
                    .fixedSize(horizontal: false, vertical: true)

                if let invite {
                    ShareLink(item: URL(string: invite.inviteURL) ?? URL(string: "https://reelmap.app")!,
                              message: Text("Join my ReelMap: \(map.name)")) {
                        Label("Share invite link", systemImage: "square.and.arrow.up")
                            .font(.system(size: 15, weight: .semibold)).foregroundStyle(.white)
                            .frame(maxWidth: .infinity).padding(.vertical, 13)
                            .background(Color.appAccent, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                    }
                    Button("Reset link") { Task { await makeInvite(rotate: true) } }
                        .font(.system(size: 13)).foregroundStyle(.inkSecondary)
                        .frame(maxWidth: .infinity)
                } else {
                    Button { Task { await makeInvite() } } label: {
                        HStack(spacing: 8) {
                            if loadingInvite { ProgressView().tint(.white) }
                            else { Image(systemName: "link") }
                            Text(loadingInvite ? "Creating…" : "Create invite link")
                                .font(.system(size: 15, weight: .semibold))
                        }
                        .foregroundStyle(.white).frame(maxWidth: .infinity).padding(.vertical, 13)
                        .background(Color.appAccent, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                    }
                    .buttonStyle(.plain)
                    .disabled(loadingInvite)
                }
            }
            .padding(16).card(20)
        }
    }

    // MARK: Members

    @ViewBuilder private var membersCard: some View {
        if !members.isEmpty {
            VStack(alignment: .leading, spacing: 0) {
                Text("\(members.count) member\(members.count == 1 ? "" : "s")")
                    .font(.display(15, .semibold)).foregroundStyle(.ink)
                    .padding(.bottom, 10)

                ForEach(Array(members.enumerated()), id: \.element.id) { index, member in
                    HStack(spacing: 12) {
                        InitialAvatar(name: member.displayName, colorHex: member.avatarColor)
                        VStack(alignment: .leading, spacing: 1) {
                            Text(displayName(member)).font(.system(size: 15, weight: .medium))
                                .foregroundStyle(.ink).lineLimit(1)
                            Text(member.isOwner ? "Owner" : "Can add places")
                                .font(.system(size: 12)).foregroundStyle(.inkMuted)
                        }
                        Spacer()
                        // Only the owner removes others, and the owner can't be
                        // removed — deleting the map is the way out for them.
                        if map.isOwner && !member.isOwner {
                            Button {
                                Haptics.tap()
                                pendingRemoval = member
                            } label: {
                                Image(systemName: "minus.circle")
                                    .font(.system(size: 17)).foregroundStyle(.closedRed)
                            }
                            .buttonStyle(.plain)
                        }
                    }
                    .padding(.vertical, 9)
                    .overlay(alignment: .top) {
                        if index > 0 { Rectangle().fill(Color.hairline).frame(height: 1) }
                    }
                }
            }
            .padding(16).card(20)
            .confirmationDialog("Remove \(pendingRemoval?.displayName ?? "this person")?",
                                isPresented: .init(get: { pendingRemoval != nil },
                                                   set: { if !$0 { pendingRemoval = nil } }),
                                titleVisibility: .visible) {
                Button("Remove", role: .destructive) {
                    if let member = pendingRemoval { Task { await remove(member) } }
                }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text("They lose access to this map. Places they added stay.")
            }
        }
    }

    private func displayName(_ member: MapMemberSummary) -> String {
        if member.userID == AuthStore.userID { return "You" }
        return member.displayName ?? "Someone"
    }

    // MARK: Leave / delete

    private var dangerButton: some View {
        Button { Haptics.tap(); confirmRemoval = true } label: {
            Label(removalVerb, systemImage: map.isOwner ? "trash" : "rectangle.portrait.and.arrow.right")
                .font(.system(size: 15, weight: .semibold)).foregroundStyle(.closedRed)
                .frame(maxWidth: .infinity).padding(14)
                .background(Color.closedRed.opacity(0.10),
                            in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        }
        .buttonStyle(.plain)
        .disabled(map.isPersonal)
        .opacity(map.isPersonal ? 0.4 : 1)
    }

    // The same API call means two very different things depending on who you
    // are, so the copy has to be explicit about which one is about to happen.
    private var removalVerb: String { map.isOwner ? "Delete map" : "Leave map" }
    private var removalTitle: String {
        map.isOwner ? "Delete \(map.name)?" : "Leave \(map.name)?"
    }
    private var removalExplanation: String {
        map.isOwner
            ? "This deletes it for everyone in it, along with all its places. This can't be undone."
            : "It disappears from your app. Everyone else keeps it, including places you added."
    }

    // MARK: Actions

    private func load() async {
        members = (try? await APIClient.shared.members(mapID: map.id)) ?? []
        if map.isOwner, map.inviteCode != nil {
            invite = try? await APIClient.shared.createInvite(mapID: map.id)
        }
    }

    private func makeInvite(rotate: Bool = false) async {
        loadingInvite = true
        defer { loadingInvite = false }
        do {
            invite = try await APIClient.shared.createInvite(mapID: map.id, rotate: rotate)
            Haptics.success()
        } catch {
            errorText = error.localizedDescription
        }
    }

    private func remove(_ member: MapMemberSummary) async {
        do {
            try await APIClient.shared.removeMember(mapID: map.id, userID: member.userID)
            await load()
            await store.refresh()
        } catch {
            errorText = error.localizedDescription
        }
    }

    private func removeSelf() async {
        do {
            try await store.deleteOrLeave(map)
            dismiss()
        } catch {
            errorText = error.localizedDescription
        }
    }
}

/// Initial-and-colour avatar. No photo upload means no storage, no moderation,
/// and nothing to go wrong offline.
struct InitialAvatar: View {
    let name: String?
    let colorHex: String?
    var size: CGFloat = 36

    var body: some View {
        Text(initial)
            .font(.system(size: size * 0.42, weight: .bold))
            .foregroundStyle(.white)
            .frame(width: size, height: size)
            .background(color, in: Circle())
    }

    private var initial: String {
        guard let first = name?.trimmingCharacters(in: .whitespaces).first else { return "?" }
        return String(first).uppercased()
    }

    private var color: Color {
        guard let hex = colorHex else { return .appAccent }
        return Color(hex: UInt(hex.dropFirst().prefix(6), radix: 16) ?? 0x159A6A)
    }
}
