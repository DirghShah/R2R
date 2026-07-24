import SharedKit
import SwiftData
import SwiftUI

struct AddReelScreen: View {
    @EnvironmentObject private var store: ActivityStore
    @Environment(\.modelContext) private var context
    @FocusState private var focused: Bool

    @State private var text = ""
    @State private var fieldError: String?
    @State private var submitting = false

    var body: some View {
        ZStack {
            Color.canvas.ignoresSafeArea()
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    Text("ADD A PLACE")
                        .font(.system(size: 13, weight: .semibold)).tracking(0.4)
                        .foregroundStyle(.linkBlue)
                    Text("Analyze a Reel").font(.display(30, .bold)).foregroundStyle(.ink)
                        .padding(.bottom, 16)

                    inputCard
                    if let processing { analyzingNow(processing).padding(.top, 20) }
                    dashboard.padding(.top, 22)
                    queueSection.padding(.top, 22)
                }
                .padding(.horizontal, 22).padding(.top, 8).padding(.bottom, 30)
            }
            .scrollIndicators(.hidden)
            .scrollDismissesKeyboard(.immediately)
        }
        .task { await store.refreshNow(context) }
        .refreshable { await store.refreshNow(context) }
    }

    // MARK: Input card

    private var inputCard: some View {
        VStack(spacing: 0) {
            HStack(spacing: 10) {
                Image(systemName: "link").font(.system(size: 16, weight: .semibold)).foregroundStyle(.inkMuted)
                TextField("", text: $text, prompt: Text("Paste a reel, Short, or TikTok link").foregroundColor(.inkMuted))
                    .font(.system(size: 14)).foregroundStyle(.ink)
                    .textInputAutocapitalization(.never).autocorrectionDisabled().keyboardType(.URL)
                    .focused($focused).submitLabel(.done)
                    .onSubmit { focused = false }
                    .onChange(of: text) { fieldError = nil }
                if !text.isEmpty {
                    Button { text = ""; fieldError = nil } label: {
                        Image(systemName: "xmark").font(.system(size: 12, weight: .bold)).foregroundStyle(.inkSecondary)
                            .frame(width: 22, height: 22).background(Color(hex: 0xE6E6DF), in: Circle())
                    }.buttonStyle(.plain)
                } else {
                    Button("Paste") {
                        let pb = UIPasteboard.general
                        if let v = pb.url?.absoluteString ?? pb.string { text = v.trimmingCharacters(in: .whitespacesAndNewlines) }
                        focused = false
                    }
                    .font(.system(size: 13, weight: .semibold)).foregroundStyle(.appAccent)
                }
            }
            .padding(.horizontal, 14).padding(.vertical, 12)
            .background(Color.cardStroke, in: RoundedRectangle(cornerRadius: 15, style: .continuous))

            if let fieldError {
                Label(fieldError, systemImage: "exclamationmark.circle.fill")
                    .font(.footnote).foregroundStyle(.closedRed)
                    .frame(maxWidth: .infinity, alignment: .leading).padding(.top, 8)
            }

            Button { focused = false; analyzeTapped() } label: {
                HStack(spacing: 8) {
                    if submitting { ProgressView().tint(.white) }
                    else { Image(systemName: "waveform.path.ecg").font(.system(size: 16, weight: .semibold)) }
                    Text("Analyze reel").font(.system(size: 15, weight: .semibold))
                }
                .foregroundStyle(.white).frame(maxWidth: .infinity).padding(.vertical, 15)
                .background(Color.appAccent, in: RoundedRectangle(cornerRadius: 15, style: .continuous))
                .shadow(color: Color.appAccent.opacity(0.5), radius: 12, y: 6)
            }
            .buttonStyle(.plain)
            .disabled(text.trimmingCharacters(in: .whitespaces).isEmpty || submitting)
            .opacity(text.trimmingCharacters(in: .whitespaces).isEmpty ? 0.5 : 1)
            .padding(.top, 11)

            HStack(spacing: 10) {
                ForEach(["Instagram", "TikTok", "YouTube"], id: \.self) { p in
                    if p != "Instagram" { Text("·").foregroundStyle(.inkMuted) }
                    Text(p).font(.system(size: 12)).foregroundStyle(.inkMuted)
                }
            }
            .frame(maxWidth: .infinity).padding(.top, 12)
        }
        .padding(14)
        .card(22)
    }

    // MARK: Live dashboard

    private var dashboard: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 8) {
                Circle().fill(Color.appAccent).frame(width: 8, height: 8)
                    .symbolEffect(.pulse)
                Text("Live dashboard").font(.display(16, .semibold)).foregroundStyle(.ink)
            }
            HStack(spacing: 10) {
                statCard("\(analyzedToday)", "Analyzed today", .appAccent)
                statCard("\(queuedCount)", "In queue", .linkBlue)
                statCard("\(placesFound)", "Places found", .ink)
            }
        }
    }

    private func statCard(_ value: String, _ label: String, _ color: Color) -> some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(value).font(.display(24, .bold)).foregroundStyle(color)
            Text(label).font(.system(size: 11.5)).foregroundStyle(.inkSecondary).lineLimit(2)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(.horizontal, 12).padding(.vertical, 13)
        .card(18)
    }

    // MARK: Analyzing now (dark card)

    private func analyzingNow(_ item: ReelActivity) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(spacing: 8) {
                Circle().fill(Color(hex: 0x4ADE9B)).frame(width: 7, height: 7).symbolEffect(.pulse)
                Text("ANALYZING NOW").font(.system(size: 12, weight: .semibold)).tracking(0.3)
                    .foregroundStyle(Color(hex: 0x8FE6BD))
                Spacer()
                Text(PlatformStyle.name(item.platform).uppercased())
                    .font(.system(size: 10, weight: .bold)).tracking(0.3).foregroundStyle(.white)
                    .padding(.horizontal, 8).padding(.vertical, 3)
                    .background(PlatformStyle.color(item.platform), in: RoundedRectangle(cornerRadius: 6))
            }
            Text(item.title ?? PlatformStyle.name(item.platform) + " reel")
                .font(.display(17, .semibold)).foregroundStyle(.white).lineLimit(2)
                .padding(.top, 9)
            Text("Extracting places & tips").font(.system(size: 13)).foregroundStyle(Color(hex: 0x89B3A2))
                .padding(.top, 2)
            ProgressView().progressViewStyle(.linear).tint(Color(hex: 0x4ADE9B))
                .padding(.top, 14)
        }
        .padding(16)
        .background(Color.deepGreen, in: RoundedRectangle(cornerRadius: 22, style: .continuous))
    }

    // MARK: Queue

    @ViewBuilder private var queueSection: some View {
        let queued = store.items.filter { $0.status == "pending" }
        let done = store.items.filter { $0.status == "done" || $0.status == "failed" }
        if !queued.isEmpty {
            VStack(alignment: .leading, spacing: 9) {
                HStack {
                    Text("In queue").font(.display(15, .semibold)).foregroundStyle(.ink)
                    Spacer()
                    Text("\(queued.count) waiting").font(.system(size: 13)).foregroundStyle(.inkSecondary)
                }
                ForEach(Array(queued.enumerated()), id: \.element.id) { idx, q in
                    queueRow(pos: idx + 1, item: q, chip: "Queued", chipColor: .inkMuted)
                }
            }
        }
        if !done.isEmpty {
            VStack(alignment: .leading, spacing: 9) {
                Text("Recent").font(.display(15, .semibold)).foregroundStyle(.ink).padding(.top, queued.isEmpty ? 0 : 14)
                ForEach(done.prefix(8)) { d in
                    queueRow(pos: nil, item: d,
                             chip: d.status == "failed" ? "Failed" : (d.placeCount > 0 ? "\(d.placeCount) place\(d.placeCount == 1 ? "" : "s")" : "No places"),
                             chipColor: d.status == "failed" ? .closedRed : (d.placeCount > 0 ? .appAccent : .inkMuted))
                }
            }
        }
    }

    private func queueRow(pos: Int?, item: ReelActivity, chip: String, chipColor: Color) -> some View {
        HStack(spacing: 12) {
            ZStack {
                if let s = item.thumbnailURL, let url = URL(string: s) {
                    AsyncImage(url: url) { $0.resizable().scaledToFill() } placeholder: { Color.cardStroke }
                } else if let pos {
                    Text("\(pos)").font(.system(size: 13, weight: .bold)).foregroundStyle(.inkMuted)
                } else {
                    Image(systemName: PlatformStyle.icon(item.platform)).font(.system(size: 14)).foregroundStyle(.inkMuted)
                }
            }
            .frame(width: 38, height: 38)
            .background(Color.cardStroke)
            .clipShape(RoundedRectangle(cornerRadius: 11, style: .continuous))

            VStack(alignment: .leading, spacing: 1) {
                Text(item.title ?? PlatformStyle.name(item.platform) + " reel")
                    .font(.system(size: 14, weight: .semibold)).foregroundStyle(.ink).lineLimit(1)
                Text(PlatformStyle.name(item.platform)).font(.system(size: 12)).foregroundStyle(.inkMuted)
            }
            Spacer(minLength: 6)
            Text(chip).font(.system(size: 11, weight: .semibold)).foregroundStyle(chipColor)
                .padding(.horizontal, 9).padding(.vertical, 4)
                .background(chipColor.opacity(0.12), in: Capsule())
        }
        .padding(.horizontal, 14).padding(.vertical, 12)
        .background(Color.cardFill, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
        .overlay(RoundedRectangle(cornerRadius: 16, style: .continuous).strokeBorder(Color.cardStroke))
    }

    // MARK: Derived data

    private var processing: ReelActivity? { store.items.first { $0.status == "processing" } }
    private var queuedCount: Int { store.items.filter { $0.status == "pending" }.count }
    private var analyzedToday: Int {
        store.items.filter { $0.status == "done" && Calendar.current.isDateInToday($0.createdAt) }.count
    }
    private var placesFound: Int { store.items.filter { $0.status == "done" }.reduce(0) { $0 + $1.placeCount } }

    // MARK: Flow

    private func analyzeTapped() {
        let trimmed = text.trimmingCharacters(in: .whitespacesAndNewlines)
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
            store.resume(context)
        } catch {
            fieldError = error.localizedDescription
        }
    }
}
