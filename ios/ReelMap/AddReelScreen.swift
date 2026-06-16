import SharedKit
import SwiftUI

/// Free-account intake: paste an Instagram reel link (Instagram → Share → Copy
/// link) and submit it. Same backend pipeline as the native Share Extension —
/// this is how you test the whole flow without the paid App Group.
struct AddReelScreen: View {
    @State private var url = ""
    @State private var status: String?
    @State private var working = false
    @State private var error: String?

    var body: some View {
        NavigationStack {
            Form {
                Section("Paste an Instagram reel link") {
                    TextField("https://www.instagram.com/reel/…", text: $url)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                        .keyboardType(.URL)
                    Button {
                        if let s = UIPasteboard.general.string { url = s }
                    } label: { Label("Paste from clipboard", systemImage: "doc.on.clipboard") }
                }

                Section {
                    Button {
                        Task { await submit() }
                    } label: {
                        HStack {
                            Text("Analyze reel")
                            if working { Spacer(); ProgressView() }
                        }
                    }
                    .disabled(url.isEmpty || working)
                }

                if let status { Section("Status") { Text(status) } }
                if let error { Section { Text(error).foregroundStyle(.red) } }
            }
            .navigationTitle("Add reel")
        }
    }

    private func submit() async {
        working = true; error = nil; status = "Submitting…"
        defer { working = false }
        do {
            let submitted = try await APIClient.shared.submitReel(url: url)
            status = "Analyzing… (this takes ~15–60s)"
            try await poll(submitted.reelID)
        } catch {
            self.error = error.localizedDescription
            self.status = nil
        }
    }

    private func poll(_ reelID: String) async throws {
        for _ in 0..<30 {
            try await Task.sleep(for: .seconds(2))
            let s = try await APIClient.shared.reelStatus(reelID)
            switch s.status {
            case "done":
                status = "Done — \(s.placeCount) place(s) saved. Check the Map & Lists tabs."
                url = ""
                return
            case "failed":
                error = "Analysis failed. Try another reel."
                status = nil
                return
            default:
                status = "Analyzing… (\(s.status))"
            }
        }
        status = "Still working — check the Map tab shortly."
    }
}
