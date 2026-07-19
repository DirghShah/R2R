import SharedKit
import SwiftData
import SwiftUI

/// Paste/type a link and Analyze, with a live queue dashboard below: every reel
/// you've submitted (from here OR the Share Extension), newest/active first, as
/// expandable cards showing Queued → Analyzing → N places / Failed. Share as many
/// reels as you like — they all stack here and process one-by-one on the server.
struct AddReelScreen: View {
    @EnvironmentObject private var store: ActivityStore
    @Environment(\.modelContext) private var context
    @FocusState private var focused: Bool

    @State private var text = ""
    @State private var fieldError: String?
    @State private var submitting = false
    @State private var expanded: Set<String> = []

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 18) {
                    hero
                    inputSection
                    analyzeButton
                    queueSection
                }
                .padding(20)
            }
            .scrollDismissesKeyboard(.immediately)
            .navigationTitle("Add a place")
            .refreshable { await store.refreshNow(context) }
            .task { await store.refreshNow(context) }
        }
    }

    // MARK: Header

    private var hero: some View {
        VStack(spacing: 8) {
            Image(systemName: "mappin.and.ellipse")
                .font(.system(size: 36, weight: .semibold))
                .foregroundStyle(.tint)
            Text("Paste a link, get a pin").font(.title2.bold())
            Text("Instagram, TikTok, or YouTube Shorts. Share as many as you like — they queue up here.")
                .font(.callout).foregroundStyle(.secondary).multilineTextAlignment(.center)
        }
        .padding(.top, 4)
    }

    private var inputSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 10) {
                TextField("Type or paste a link", text: $text)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .keyboardType(.URL)
                    .submitLabel(.done)
                    .focused($focused)
                    .onSubmit { focused = false }
                    .onChange(of: text) { fieldError = nil }

                if trimmed.isEmpty {
                    // Reads BOTH url and string pasteboard payloads (Instagram's
                    // "Copy link" is often a URL object, which string-only
                    // readers silently miss).
                    Button("Paste") {
                        let pb = UIPasteboard.general
                        if let value = pb.url?.absoluteString ?? pb.string {
                            text = value.trimmingCharacters(in: .whitespacesAndNewlines)
                        }
                        focused = false
                    }
                    .font(.subheadline.weight(.semibold))
                    .buttonStyle(.bordered)
                    .buttonBorderShape(.capsule)
                } else {
                    Button { text = ""; fieldError = nil } label: {
                        Image(systemName: "xmark.circle.fill").foregroundStyle(.secondary)
                    }
                    .buttonStyle(.plain)
                    .accessibilityLabel("Clear")
                }
            }
            .padding(.vertical, 12).padding(.horizontal, 16)
            .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
            .overlay(
                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .strokeBorder(fieldError == nil ? Color.primary.opacity(0.06) : .red,
                                  lineWidth: fieldError == nil ? 1 : 1.5))

            if let fieldError {
                Label(fieldError, systemImage: "exclamationmark.circle.fill")
                    .font(.footnote).foregroundStyle(.red).transition(.opacity)
            }
        }
        .animation(.easeInOut(duration: 0.15), value: fieldError)
    }

    private var analyzeButton: some View {
        Button { focused = false; analyzeTapped() } label: {
            HStack {
                if submitting { ProgressView().tint(.white); Spacer().frame(width: 8) }
                Text("Analyze").font(.headline)
            }
            .frame(maxWidth: .infinity).padding(.vertical, 6)
        }
        .buttonStyle(.borderedProminent)
        .disabled(trimmed.isEmpty || submitting)
    }

    // MARK: Queue dashboard

    @ViewBuilder private var queueSection: some View {
        if !store.items.isEmpty {
            VStack(alignment: .leading, spacing: 10) {
                HStack {
                    Text("Queue").font(.headline)
                    Spacer()
                    if store.activeCount > 0 {
                        Label("\(store.activeCount) analyzing", systemImage: "circle.dashed")
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(.tint)
                            .symbolEffect(.pulse, options: .repeating)
                    }
                }
                ForEach(sortedItems) { item in
                    QueueCard(item: item, expanded: expanded.contains(item.id)) {
                        withAnimation(.snappy) {
                            if expanded.contains(item.id) { expanded.remove(item.id) }
                            else { expanded.insert(item.id) }
                        }
                    }
                }
            }
            .padding(.top, 6)
        }
    }

    private var sortedItems: [ReelActivity] {
        store.items.sorted { a, b in
            if a.isActive != b.isActive { return a.isActive }  // active on top
            return a.createdAt > b.createdAt                    // then newest
        }
    }

    private var trimmed: String { text.trimmingCharacters(in: .whitespacesAndNewlines) }

    // MARK: Flow

    private func analyzeTapped() {
        guard let link = LinkValidator.firstSupportedLink(in: trimmed) else {
            fieldError = "That doesn't look like an Instagram, TikTok, or YouTube link."
            return
        }
        fieldError = nil
        Task { await submit(link) }
    }

    private func submit(_ link: String) async {
        submitting = true
        defer { submitting = false }
        do {
            _ = try await APIClient.shared.submitReel(url: link)
            text = ""
            UINotificationFeedbackGenerator().notificationOccurred(.success)
            store.resume(context)   // refresh the queue + resume polling immediately
        } catch {
            fieldError = error.localizedDescription
        }
    }
}

// MARK: - Queue card

private struct QueueCard: View {
    let item: ReelActivity
    let expanded: Bool
    let toggle: () -> Void

    var body: some View {
        VStack(spacing: 0) {
            Button(action: toggle) {
                HStack(spacing: 12) {
                    thumbnail
                    VStack(alignment: .leading, spacing: 4) {
                        Text(item.title ?? platformName)
                            .font(.subheadline.weight(.medium)).lineLimit(1)
                            .foregroundStyle(.primary)
                        statusChip
                    }
                    Spacer()
                    Image(systemName: "chevron.right")
                        .font(.caption.weight(.bold)).foregroundStyle(.secondary)
                        .rotationEffect(.degrees(expanded ? 90 : 0))
                }
                .padding(14)
            }
            .buttonStyle(.plain)

            if expanded {
                VStack(alignment: .leading, spacing: 8) {
                    Divider()
                    detailRow("Source", platformName)
                    detailRow("Added", item.createdAt.formatted(.relative(presentation: .named)))
                    if item.status == "done" {
                        detailRow("Result", item.placeCount > 0
                                  ? "\(item.placeCount) place\(item.placeCount == 1 ? "" : "s") on your map"
                                  : "No places found in this reel")
                    }
                    if let err = item.error, !err.isEmpty {
                        detailRow("Error", err)
                    }
                }
                .padding(.horizontal, 14).padding(.bottom, 14)
                .transition(.opacity.combined(with: .move(edge: .top)))
            }
        }
        .card(18)
    }

    private var thumbnail: some View {
        Group {
            if let s = item.thumbnailURL, let url = URL(string: s) {
                AsyncImage(url: url) { $0.resizable().scaledToFill() } placeholder: { icon }
            } else { icon }
        }
        .frame(width: 46, height: 46)
        .clipShape(RoundedRectangle(cornerRadius: 10, style: .continuous))
    }

    private var icon: some View {
        ZStack {
            Color.appAccent.opacity(0.12)
            Image(systemName: platformIcon).foregroundStyle(.tint)
        }
    }

    @ViewBuilder private var statusChip: some View {
        switch item.status {
        case "pending":
            Label("Queued", systemImage: "clock")
                .font(.caption.weight(.semibold)).foregroundStyle(.secondary)
        case "processing":
            HStack(spacing: 6) {
                ProgressView().controlSize(.mini)
                Text("Analyzing…").font(.caption.weight(.semibold)).foregroundStyle(.tint)
            }
        case "done":
            Label(item.placeCount > 0 ? "\(item.placeCount) place\(item.placeCount == 1 ? "" : "s")" : "No places",
                  systemImage: item.placeCount > 0 ? "checkmark.circle.fill" : "minus.circle")
                .font(.caption.weight(.semibold))
                .foregroundStyle(item.placeCount > 0 ? .green : .secondary)
        default:
            Label("Failed", systemImage: "exclamationmark.triangle.fill")
                .font(.caption.weight(.semibold)).foregroundStyle(.orange)
        }
    }

    private func detailRow(_ label: String, _ value: String) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Text(label).font(.caption).foregroundStyle(.secondary).frame(width: 60, alignment: .leading)
            Text(value).font(.caption).foregroundStyle(.primary)
                .fixedSize(horizontal: false, vertical: true)
            Spacer(minLength: 0)
        }
    }

    private var platformName: String {
        switch item.platform {
        case "tiktok": return "TikTok video"
        case "youtube": return "YouTube Short"
        default: return "Instagram reel"
        }
    }
    private var platformIcon: String {
        switch item.platform {
        case "tiktok": return "music.note"
        case "youtube": return "play.rectangle.fill"
        default: return "camera.fill"
        }
    }
}
