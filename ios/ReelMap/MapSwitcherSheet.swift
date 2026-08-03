import SharedKit
import SwiftUI

/// Switch maps, create one, and reach your profile.
///
/// A sheet off the header rather than a fourth tab: the tab bar is the app's
/// three *modes* (Map / Lists / Analyze), and which map you're looking at is
/// context that applies to all of them — the Notion/Slack workspace pattern.
struct MapSwitcherSheet: View {
    @EnvironmentObject private var store: MapStore
    @Environment(\.dismiss) private var dismiss

    @State private var showCreate = false
    @State private var showProfile = false
    @State private var manage: MapSummary?

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 10) {
                    ForEach(store.maps) { map in
                        row(map)
                    }
                    createButton
                    profileButton.padding(.top, 6)
                }
                .padding(20)
            }
            .background(Color.canvas)
            .navigationTitle("Your maps")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } }
            }
            .sheet(isPresented: $showCreate) { CreateMapSheet() }
            .sheet(isPresented: $showProfile) { ProfileSheet() }
            .sheet(item: $manage) { MapDetailSheet(map: $0) }
        }
        .presentationDetents([.medium, .large])
    }

    private func row(_ map: MapSummary) -> some View {
        let selected = map.id == store.currentID
        return HStack(spacing: 13) {
            Button {
                Haptics.select()
                store.currentID = map.id
                dismiss()
            } label: {
                HStack(spacing: 13) {
                    Text(map.emoji ?? "📍").font(.system(size: 22))
                        .frame(width: 44, height: 44)
                        .background(Color.cardStroke, in: RoundedRectangle(cornerRadius: 13, style: .continuous))
                    VStack(alignment: .leading, spacing: 2) {
                        Text(map.name).font(.display(16, .semibold)).foregroundStyle(.ink)
                            .lineLimit(1)
                        Text(subtitle(map)).font(.system(size: 13)).foregroundStyle(.inkSecondary)
                    }
                    Spacer(minLength: 4)
                    if selected {
                        Image(systemName: "checkmark").font(.system(size: 14, weight: .bold))
                            .foregroundStyle(.appAccent)
                    }
                }
                .contentShape(Rectangle())
            }
            .buttonStyle(.plain)

            Button { Haptics.tap(); manage = map } label: {
                Image(systemName: "ellipsis").font(.system(size: 15, weight: .semibold))
                    .foregroundStyle(.inkMuted).frame(width: 30, height: 30)
            }
            .buttonStyle(.plain)
        }
        .padding(12)
        .background(Color.cardFill, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous)
            .strokeBorder(selected ? Color.appAccent : Color.cardStroke,
                          lineWidth: selected ? 1.6 : 1))
    }

    private func subtitle(_ map: MapSummary) -> String {
        let places = "\(map.placeCount) place\(map.placeCount == 1 ? "" : "s")"
        guard map.isShared else { return places }
        return "\(places) · \(map.memberCount) people"
    }

    private var createButton: some View {
        Button { Haptics.tap(); showCreate = true } label: {
            HStack(spacing: 13) {
                Image(systemName: "plus").font(.system(size: 17, weight: .semibold))
                    .foregroundStyle(.appAccent).frame(width: 44, height: 44)
                    .background(Color.appAccent.opacity(0.10),
                                in: RoundedRectangle(cornerRadius: 13, style: .continuous))
                Text("New map").font(.display(16, .semibold)).foregroundStyle(.ink)
                Spacer()
            }
            .padding(12)
            .background(Color.cardFill, in: RoundedRectangle(cornerRadius: 18, style: .continuous))
            .overlay(RoundedRectangle(cornerRadius: 18, style: .continuous)
                .strokeBorder(Color.cardStroke))
        }
        .buttonStyle(.plain)
    }

    private var profileButton: some View {
        Button { Haptics.tap(); showProfile = true } label: {
            HStack(spacing: 13) {
                Image(systemName: "person.crop.circle").font(.system(size: 19))
                    .foregroundStyle(.inkSecondary).frame(width: 44, height: 44)
                Text("Profile & settings").font(.system(size: 15, weight: .medium))
                    .foregroundStyle(.ink)
                Spacer()
                Image(systemName: "chevron.right").font(.system(size: 12, weight: .bold))
                    .foregroundStyle(.inkMuted)
            }
            .padding(.horizontal, 12).padding(.vertical, 6)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
    }
}

// MARK: - Create

struct CreateMapSheet: View {
    @EnvironmentObject private var store: MapStore
    @Environment(\.dismiss) private var dismiss

    @State private var name = ""
    @State private var emoji = "📍"
    @State private var working = false
    @State private var errorText: String?
    @FocusState private var focused: Bool

    private let suggestions = ["📍", "🌮", "🍜", "☕️", "🍸", "🗽", "🏖️", "🍰", "🍕", "🍦"]

    var body: some View {
        NavigationStack {
            // No ScrollView: the content is short and fixed, and scrolling a
            // half-height sheet with a keyboard up just fights the user.
            VStack(alignment: .leading, spacing: 16) {
                VStack(alignment: .leading, spacing: 7) {
                    Text("NAME").font(.system(size: 11, weight: .semibold))
                        .tracking(0.4).foregroundStyle(.inkMuted)
                    TextField("", text: $name,
                              prompt: Text("NYC trip, Date nights…").foregroundColor(.inkMuted))
                        .font(.system(size: 16)).foregroundStyle(.ink)
                        .focused($focused)
                        .submitLabel(.done)
                        .onSubmit { if !trimmed.isEmpty { Task { await create() } } }
                        .padding(14)
                        .background(Color.cardFill, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                        .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous)
                            .strokeBorder(Color.cardStroke))
                }

                VStack(alignment: .leading, spacing: 7) {
                    Text("ICON").font(.system(size: 11, weight: .semibold))
                        .tracking(0.4).foregroundStyle(.inkMuted)
                    // Horizontally scrollable: ten 44pt tiles are wider than any
                    // iPhone, so a fixed HStack clipped the last few.
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 8) {
                            ForEach(suggestions, id: \.self) { option in
                                Button { Haptics.select(); emoji = option } label: {
                                    Text(option).font(.system(size: 21))
                                        .frame(width: 46, height: 46)
                                        .background(emoji == option ? Color.appAccent.opacity(0.15) : Color.cardFill,
                                                    in: RoundedRectangle(cornerRadius: 13, style: .continuous))
                                        .overlay(RoundedRectangle(cornerRadius: 13, style: .continuous)
                                            .strokeBorder(emoji == option ? Color.appAccent : Color.cardStroke,
                                                          lineWidth: emoji == option ? 1.6 : 1))
                                }
                                .buttonStyle(.plain)
                            }
                        }
                        .padding(.horizontal, 1)
                    }
                    .scrollClipDisabled()
                }

                Button { Task { await create() } } label: {
                    HStack(spacing: 8) {
                        if working { ProgressView().tint(.white) }
                        Text(working ? "Creating…" : "Create map")
                            .font(.system(size: 16, weight: .semibold))
                    }
                    .foregroundStyle(.white).frame(maxWidth: .infinity).padding(.vertical, 15)
                    .background(Color.appAccent, in: RoundedRectangle(cornerRadius: 15, style: .continuous))
                }
                .buttonStyle(.plain)
                .disabled(trimmed.isEmpty || working)
                .opacity(trimmed.isEmpty ? 0.5 : 1)

                Spacer(minLength: 0)
            }
            .padding(20)
            .frame(maxHeight: .infinity, alignment: .top)
            .background(Color.canvas)
            .navigationTitle("New map")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
            }
            .onAppear { focused = true }
            .alert("Couldn't create map", isPresented: .init(get: { errorText != nil },
                                                            set: { if !$0 { errorText = nil } })) {
                Button("OK", role: .cancel) {}
            } message: { Text(errorText ?? "") }
        }
        // Sized to the content rather than a generic .medium, which left a
        // large empty gap under the fields.
        .presentationDetents([.height(360)])
    }

    private var trimmed: String { name.trimmingCharacters(in: .whitespacesAndNewlines) }

    private func create() async {
        guard !trimmed.isEmpty, !working else { return }
        working = true
        defer { working = false }
        do {
            try await store.create(name: trimmed, emoji: emoji)
            Haptics.success()
            dismiss()
        } catch {
            errorText = error.localizedDescription
        }
    }
}
