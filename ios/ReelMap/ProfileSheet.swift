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

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    identityCard
                    usageCard
                    sharedMapsCard
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
            .task { profile = try? await APIClient.shared.me() }
            .alert("Your name", isPresented: $editingName) {
                TextField("Name", text: $draftName)
                Button("Save") { Task { await saveName() } }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text("This is what people see next to places you add to shared maps.")
            }
            .confirmationDialog("Sign out?", isPresented: $confirmSignOut, titleVisibility: .visible) {
                Button("Sign out", role: .destructive) { Task { await signOut() } }
                Button("Cancel", role: .cancel) {}
            } message: {
                Text("Your places stay on your account — signing back in restores them.")
            }
            .confirmationDialog("Delete your account?", isPresented: $confirmDelete,
                                titleVisibility: .visible) {
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
