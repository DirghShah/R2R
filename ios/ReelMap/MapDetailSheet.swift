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

    // Renaming is a content edit, not a structural one — like adding a place,
    // any member can do it, not just the owner. Tracked locally so the sheet
    // reflects the new name immediately rather than waiting on a full refresh.
    @State private var displayedName: String
    @State private var renaming = false
    @State private var draftName = ""

    // Guideline 1.2: an app with user-generated content must offer reporting
    // and blocking. Map names, display names and the places people add to a
    // shared map are that content.
    @State private var reporting: ReportSubject?
    @State private var pendingBlock: MapMemberSummary?

    init(map: MapSummary) {
        self.map = map
        _displayedName = State(initialValue: map.name)
    }

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
            .navigationTitle(displayedName)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } }
                ToolbarItem(placement: .navigationBarLeading) {
                    Menu {
                        Button(role: .destructive) {
                            reporting = ReportSubject(target: .map, id: map.id, name: displayedName)
                        } label: {
                            Label("Report this map", systemImage: "flag")
                        }
                    } label: {
                        Image(systemName: "ellipsis.circle")
                    }
                }
            }
            .task { await load() }
            .sheet(item: $reporting) {
                ReportSheet(target: $0.target, targetID: $0.id, subject: $0.name)
            }
            .confirmationDialog("Block \(pendingBlock?.displayName ?? "this person")?",
                                isPresented: .init(get: { pendingBlock != nil },
                                                   set: { if !$0 { pendingBlock = nil } }),
                                titleVisibility: .visible) {
                Button("Block", role: .destructive) {
                    if let member = pendingBlock { Task { await block(member) } }
                }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text("You'll stop seeing the places they add. They stay listed here as blocked so you can undo it or remove them, they keep their access unless the owner removes them, and they aren't told.")
            }
            .confirmationDialog(removalTitle, isPresented: $confirmRemoval, titleVisibility: .visible) {
                Button(removalVerb, role: .destructive) { Task { await removeSelf() } }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text(removalExplanation)
            }
            .alert("Rename map", isPresented: $renaming) {
                TextField("Map name", text: $draftName)
                Button("Save") { Task { await rename() } }
                Button("Cancel", role: .cancel) {}
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
                Text(displayedName).font(.display(20, .bold)).foregroundStyle(.ink)
                Text("\(map.placeCount) place\(map.placeCount == 1 ? "" : "s")")
                    .font(.system(size: 14)).foregroundStyle(.inkSecondary)
            }
            Spacer()
            // Every map, personal included. The personal map is the one you
            // can't *delete* — "My Map" is a default, not a fixed identity,
            // and it's frequently the one people share first.
            Button {
                Haptics.tap()
                draftName = displayedName
                renaming = true
            } label: {
                Image(systemName: "pencil")
                    .font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(.inkSecondary)
                    .frame(width: 32, height: 32)
                    .background(Color.cardStroke, in: Circle())
            }
            .buttonStyle(.plain)
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
                    ShareLink(item: URL(string: invite.inviteURL) ?? URL(string: "https://noshmap.app")!,
                              message: Text("Join my Nosh map: \(displayedName)")) {
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
                            .opacity(member.isBlocked ? 0.45 : 1)
                        VStack(alignment: .leading, spacing: 1) {
                            Text(displayName(member)).font(.system(size: 15, weight: .medium))
                                .foregroundStyle(.ink).lineLimit(1)
                                .opacity(member.isBlocked ? 0.5 : 1)
                            // A blocked member reads as blocked rather than
                            // disappearing, so the state is visible and the
                            // way out of it is one tap away.
                            Text(memberSubtitle(member))
                                .font(.system(size: 12))
                                .foregroundStyle(member.isBlocked ? Color.closedRed : .inkMuted)
                        }
                        Spacer()
                        // Anyone can report or block anyone else; only the owner
                        // can remove people, and the owner can't be removed at
                        // all — deleting the map is their way out.
                        if member.userID != AuthStore.userID {
                            Menu {
                                Button(role: .destructive) {
                                    reporting = ReportSubject(
                                        target: .user, id: member.userID,
                                        name: member.displayName ?? "this person")
                                } label: { Label("Report", systemImage: "flag") }

                                if member.isBlocked {
                                    Button {
                                        Task { await unblock(member) }
                                    } label: { Label("Unblock", systemImage: "hand.raised.slash") }
                                } else {
                                    Button(role: .destructive) {
                                        pendingBlock = member
                                    } label: { Label("Block", systemImage: "hand.raised") }
                                }

                                if map.isOwner && !member.isOwner {
                                    Divider()
                                    Button(role: .destructive) {
                                        pendingRemoval = member
                                    } label: {
                                        Label("Remove from map", systemImage: "minus.circle")
                                    }
                                }
                            } label: {
                                Image(systemName: "ellipsis")
                                    .font(.system(size: 15, weight: .semibold))
                                    .foregroundStyle(.inkMuted)
                                    .frame(width: 30, height: 30)
                                    .contentShape(Rectangle())
                            }
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

    private func memberSubtitle(_ member: MapMemberSummary) -> String {
        if member.isBlocked { return "Blocked — you don't see what they add" }
        return member.isOwner ? "Owner" : "Can add places"
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
        map.isOwner ? "Delete \(displayedName)?" : "Leave \(displayedName)?"
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

    private func block(_ member: MapMemberSummary) async {
        do {
            try await APIClient.shared.block(userID: member.userID)
            Haptics.success()
            // Their row comes back flagged, and their places drop out of the
            // next sync. Nothing is deleted, so unblocking restores all of it.
            await load()
            await store.refresh(force: true)
        } catch {
            errorText = error.localizedDescription
        }
    }

    private func unblock(_ member: MapMemberSummary) async {
        do {
            try await APIClient.shared.unblock(userID: member.userID)
            Haptics.success()
            await load()
            await store.refresh(force: true)
        } catch {
            errorText = error.localizedDescription
        }
    }

    private func rename() async {
        let trimmed = draftName.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty, trimmed != displayedName else { return }
        let previous = displayedName
        displayedName = trimmed  // optimistic — matches the rest of MapStore's pattern
        do {
            try await store.rename(map, to: trimmed)
            Haptics.success()
        } catch {
            displayedName = previous
            errorText = error.localizedDescription
        }
    }
}

/// `sheet(item:)` needs Identifiable, and the three report targets differ only
/// in what they point at.
struct ReportSubject: Identifiable {
    let target: ReportTarget
    let id: String
    let name: String
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
