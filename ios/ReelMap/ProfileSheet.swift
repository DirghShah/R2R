import SharedKit
import SwiftData
import SwiftUI

/// Your account: name, usage, sign out, delete.
///
/// Deliberately no friend count. It would read "0" for every new user, and
/// there is no friend graph to count anyway — the people you know are the
/// members of the maps you share, which is what this shows instead.
struct ProfileSheet: View {
    @EnvironmentObject private var store: MapStore
    @Environment(\.dismiss) private var dismiss
    @Environment(\.modelContext) private var context

    @State private var profile: UserProfile?
    @State private var editingName = false
    @State private var draftName = ""
    @State private var confirmSignOut = false
    @State private var confirmDelete = false
    @State private var working = false
    @State private var errorText: String?
    // Guideline 1.2 requires blocking; it also requires the block to be
    // undoable, which means somewhere to see who you've blocked.
    @State private var blocked: [BlockedUser] = []

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    identityCard
                    usageCard
                    sharedMapsCard
                    safetyCard
                    accountActions
                }
                .padding(20)
            }
            .background(Color.canvas)
            .navigationTitle("Profile")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } }
            }
            .task {
                profile = try? await APIClient.shared.me()
                blocked = (try? await APIClient.shared.blockedUsers()) ?? []
            }
            .alert("Your name", isPresented: $editingName) {
                TextField("Name", text: $draftName)
                Button("Save") { Task { await saveName() } }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text("This is what people see next to places you add to shared maps.")
            }
            // Alerts, not confirmationDialogs: presented from inside a sheet,
            // a dialog anchors itself as a popover bubble instead of the
            // centred modal these destructive choices should be.
            .alert("Sign out?", isPresented: $confirmSignOut) {
                Button("Sign out", role: .destructive) { Task { await signOut() } }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text("Your places stay on your account — signing back in restores them.")
            }
            .alert("Delete your account?", isPresented: $confirmDelete) {
                Button("Delete everything", role: .destructive) { Task { await deleteAccount() } }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text("This permanently deletes your account, your maps and every place you've saved. Places you added to other people's shared maps stay with those maps. This can't be undone.")
            }
            .alert("Something went wrong", isPresented: .init(get: { errorText != nil },
                                                             set: { if !$0 { errorText = nil } })) {
                Button("OK", role: .cancel) {}
            } message: { Text(errorText ?? "") }
        }
        .presentationDetents([.medium, .large])
    }

    private var identityCard: some View {
        HStack(spacing: 14) {
            InitialAvatar(name: profile?.displayName, colorHex: profile?.avatarColor, size: 56)
            VStack(alignment: .leading, spacing: 3) {
                Text(profile?.displayName ?? "Your name")
                    .font(.display(19, .bold)).foregroundStyle(.ink)
                Button("Edit name") {
                    draftName = profile?.displayName ?? ""
                    editingName = true
                }
                .font(.system(size: 13, weight: .medium)).foregroundStyle(.linkBlue)
            }
            Spacer()
        }
        .padding(16).card(20)
    }

    private var usageCard: some View {
        HStack(spacing: 10) {
            stat("\(profile?.reelsThisMonth ?? 0)", "Reels this month")
            stat("\(store.maps.count)", "Maps")
            stat("\(store.maps.reduce(0) { $0 + $1.placeCount })", "Places")
        }
    }

    private func stat(_ value: String, _ label: String) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(value).font(.display(22, .bold)).foregroundStyle(.ink)
            Text(label).font(.system(size: 11.5)).foregroundStyle(.inkSecondary).lineLimit(2)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 12).padding(.vertical, 13)
        .card(18)
    }

    /// The honest version of a "friends" list: people you actually share with.
    @ViewBuilder private var sharedMapsCard: some View {
        let shared = store.maps.filter(\.isShared)
        if !shared.isEmpty {
            VStack(alignment: .leading, spacing: 10) {
                Text("Shared with others").font(.display(15, .semibold)).foregroundStyle(.ink)
                ForEach(shared) { map in
                    HStack(spacing: 11) {
                        Text(map.emoji ?? "📍").font(.system(size: 17))
                        Text(map.name).font(.system(size: 14, weight: .medium)).foregroundStyle(.ink)
                        Spacer()
                        Text("\(map.memberCount) people")
                            .font(.system(size: 13)).foregroundStyle(.inkSecondary)
                    }
                    .padding(.vertical, 4)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(16).card(20)
        }
    }

    /// Always rendered, even with nothing blocked.
    ///
    /// It used to appear only once you had blocked someone, which meant a brand
    /// new account — a reviewer's account — contained no evidence anywhere that
    /// blocking exists. Guideline 1.2 asks for reporting *and* blocking, and a
    /// feature reachable only from a shared map you haven't been invited to is
    /// a feature nobody can find. The empty state says where blocking lives.
    private var safetyCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("Safety").font(.display(15, .semibold)).foregroundStyle(.ink)

            if blocked.isEmpty {
                Text("You haven't blocked anyone. Open any shared map, tap a member and choose Block — you'll stop seeing the places they add. You can report a map, a place or a person from the same menu.")
                    .font(.system(size: 12.5)).foregroundStyle(.inkSecondary)
                    .fixedSize(horizontal: false, vertical: true)
            } else {
                Text("You don't see the places these people add. They stay listed in shared maps as blocked, so you can undo this or remove them.")
                    .font(.system(size: 12.5)).foregroundStyle(.inkSecondary)
                    .fixedSize(horizontal: false, vertical: true)
                ForEach(blocked) { person in
                    HStack(spacing: 11) {
                        InitialAvatar(name: person.displayName, colorHex: person.avatarColor, size: 30)
                        Text(person.displayName ?? "Someone")
                            .font(.system(size: 14, weight: .medium)).foregroundStyle(.ink)
                        Spacer()
                        Button("Unblock") { Task { await unblock(person) } }
                            .font(.system(size: 13, weight: .semibold))
                            .foregroundStyle(.linkBlue)
                    }
                    .padding(.vertical, 4)
                }
            }

            Rectangle().fill(Color.hairline).frame(height: 1).padding(.vertical, 2)

            // A contact route that doesn't depend on there being another user
            // on screen — the one thing an in-app report can't cover.
            if let mail = Support.mailURL {
                Link(destination: mail) {
                    HStack(spacing: 8) {
                        Image(systemName: "envelope").font(.system(size: 13, weight: .semibold))
                        Text("Report a problem").font(.system(size: 14, weight: .medium))
                        Spacer()
                        Image(systemName: "chevron.right").font(.system(size: 11, weight: .semibold))
                            .foregroundStyle(.inkMuted)
                    }
                    .foregroundStyle(.linkBlue)
                    .contentShape(Rectangle())
                }
                .padding(.vertical, 3)
            }
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(16).card(20)
    }

    private var accountActions: some View {
        VStack(spacing: 10) {
            Button { Haptics.tap(); confirmSignOut = true } label: {
                Text("Sign out").font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(.ink)
                    .frame(maxWidth: .infinity).padding(14)
                    .background(Color.cardFill, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                    .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous)
                        .strokeBorder(Color.cardStroke))
            }
            .buttonStyle(.plain)

            Button { Haptics.tap(); confirmDelete = true } label: {
                Text(working ? "Deleting…" : "Delete account")
                    .font(.system(size: 15, weight: .semibold)).foregroundStyle(.closedRed)
                    .frame(maxWidth: .infinity).padding(14)
                    .background(Color.closedRed.opacity(0.10),
                                in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            }
            .buttonStyle(.plain)
            .disabled(working)
        }
    }

    // MARK: Actions

    private func saveName() async {
        let name = draftName.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !name.isEmpty else { return }
        do {
            profile = try await APIClient.shared.updateDisplayName(name)
        } catch {
            errorText = error.localizedDescription
        }
    }

    private func unblock(_ person: BlockedUser) async {
        do {
            try await APIClient.shared.unblock(userID: person.userID)
            blocked.removeAll { $0.userID == person.userID }
            Haptics.success()
            // Their places come back on the next sync; nothing was deleted.
            await store.refresh(force: true)
        } catch {
            errorText = error.localizedDescription
        }
    }

    private func signOut() async {
        await APIClient.shared.signOut()
        Syncer.clear(context)
        CurrentMap.clear()
        await MainActor.run { SessionExpiry.notify() }
    }

    private func deleteAccount() async {
        working = true
        defer { working = false }
        do {
            try await APIClient.shared.deleteAccount()
            Syncer.clear(context)
            CurrentMap.clear()
            AppleIDStore.userID = nil
            await MainActor.run { SessionExpiry.notify() }
        } catch {
            errorText = error.localizedDescription
        }
    }
}


/// Where a person goes when the in-app report flow doesn't fit — Apple asks
/// for a working contact route, and the App Store listing's support URL is not
/// reachable from inside the app.
enum Support {
    static let email = "noshmap@outlook.com"

    static var mailURL: URL? {
        var c = URLComponents()
        c.scheme = "mailto"
        c.path = email
        c.queryItems = [URLQueryItem(name: "subject", value: "Nosh — report a problem")]
        return c.url
    }
}
