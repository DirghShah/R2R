import SharedKit
import SwiftUI

/// Report content or a person.
///
/// Exists for App Store Guideline 1.2, which requires any app carrying
/// user-generated content to offer reporting *and* blocking. The content here
/// is modest — map names, display names, and the places someone adds to a
/// shared map — but it qualifies, and a reviewer will look for this.
struct ReportSheet: View {
    let target: ReportTarget
    let targetID: String
    /// What the user thinks they're reporting: "Dallas Eats", "Priya".
    let subject: String

    @Environment(\.dismiss) private var dismiss

    @State private var reason: ReportReason = .offensive
    @State private var note = ""
    @State private var sending = false
    @State private var sent = false
    @State private var errorText: String?

    var body: some View {
        NavigationStack {
            Group {
                if sent { confirmation } else { form }
            }
            .background(Color.canvas)
            .navigationTitle(sent ? "" : "Report")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(sent ? "Done" : "Cancel") { dismiss() }
                }
            }
            .alert("Couldn't send that report", isPresented: .init(
                get: { errorText != nil }, set: { if !$0 { errorText = nil } })) {
                Button("OK", role: .cancel) {}
            } message: { Text(errorText ?? "") }
        }
        .presentationDetents([.medium, .large])
    }

    private var form: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 18) {
                Text("Reporting \(subject)")
                    .font(.display(19, .bold)).foregroundStyle(.ink)
                Text("Reports are reviewed within 24 hours. Content that breaks our rules is removed and repeat offenders are banned.")
                    .font(.system(size: 14)).foregroundStyle(.inkSecondary)
                    .fixedSize(horizontal: false, vertical: true)

                VStack(alignment: .leading, spacing: 7) {
                    Text("WHAT'S WRONG?").font(.system(size: 11, weight: .semibold))
                        .tracking(0.4).foregroundStyle(.inkMuted)
                    VStack(spacing: 0) {
                        ForEach(Array(ReportReason.allCases.enumerated()), id: \.element) { i, option in
                            Button {
                                Haptics.select()
                                reason = option
                            } label: {
                                HStack {
                                    Text(option.label).font(.system(size: 15)).foregroundStyle(.ink)
                                    Spacer()
                                    if reason == option {
                                        Image(systemName: "checkmark")
                                            .font(.system(size: 14, weight: .bold))
                                            .foregroundStyle(.appAccent)
                                    }
                                }
                                .padding(.vertical, 13)
                                .contentShape(Rectangle())
                            }
                            .buttonStyle(.plain)
                            .overlay(alignment: .top) {
                                if i > 0 { Rectangle().fill(Color.hairline).frame(height: 1) }
                            }
                        }
                    }
                    .padding(.horizontal, 14)
                    .card(16)
                }

                VStack(alignment: .leading, spacing: 7) {
                    Text("ANYTHING ELSE? (OPTIONAL)").font(.system(size: 11, weight: .semibold))
                        .tracking(0.4).foregroundStyle(.inkMuted)
                    TextField("", text: $note, prompt: Text("What happened?").foregroundColor(.inkMuted),
                              axis: .vertical)
                        .lineLimit(3...6)
                        .font(.system(size: 15)).foregroundStyle(.ink)
                        .padding(14)
                        .background(Color.cardFill, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
                        .overlay(RoundedRectangle(cornerRadius: 14, style: .continuous)
                            .strokeBorder(Color.cardStroke))
                }

                Button { Task { await send() } } label: {
                    HStack(spacing: 8) {
                        if sending { ProgressView().tint(.white) }
                        Text(sending ? "Sending…" : "Submit report")
                            .font(.system(size: 16, weight: .semibold))
                    }
                    .foregroundStyle(.white).frame(maxWidth: .infinity).padding(.vertical, 15)
                    .background(Color.closedRed, in: RoundedRectangle(cornerRadius: 15, style: .continuous))
                }
                .buttonStyle(.plain)
                .disabled(sending)
            }
            .padding(20)
        }
    }

    private var confirmation: some View {
        VStack(spacing: 14) {
            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 44)).foregroundStyle(.appAccent)
            Text("Report sent").font(.display(21, .bold)).foregroundStyle(.ink)
            Text("Thanks — we'll review this within 24 hours.")
                .font(.system(size: 15)).foregroundStyle(.inkSecondary)
                .multilineTextAlignment(.center)
        }
        .padding(30)
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }

    private func send() async {
        sending = true
        defer { sending = false }
        do {
            let trimmed = note.trimmingCharacters(in: .whitespacesAndNewlines)
            try await APIClient.shared.report(
                target, id: targetID, reason: reason, note: trimmed.isEmpty ? nil : trimmed)
            Haptics.success()
            sent = true
        } catch {
            errorText = error.localizedDescription
        }
    }
}
