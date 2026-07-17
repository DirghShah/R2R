import SharedKit
import SwiftUI

/// The reel queue: what's analyzing, what's queued, what's done. Live-updated
/// from ActivityStore (which polls the backend). Users open this to check status
/// while their reels process in the background.
struct ActivityView: View {
    @EnvironmentObject private var store: ActivityStore
    @Environment(\.modelContext) private var context
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            Group {
                if store.items.isEmpty {
                    ContentUnavailableView {
                        Label("Nothing here yet", systemImage: "square.stack.3d.up")
                    } description: {
                        Text("Share a reel to ReelMap or paste a link — it'll show up here while it analyzes.")
                    }
                } else {
                    List {
                        ForEach(store.items) { ActivityRow(item: $0) }
                    }
                    .listStyle(.plain)
                }
            }
            .navigationTitle("Activity")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                }
            }
            .refreshable { await store.refreshNow(context) }
        }
    }
}

private struct ActivityRow: View {
    let item: ReelActivity

    var body: some View {
        HStack(spacing: 12) {
            thumbnail
            VStack(alignment: .leading, spacing: 4) {
                Text(item.title ?? platformName)
                    .font(.subheadline.weight(.medium))
                    .lineLimit(2)
                statusChip
            }
            Spacer()
        }
        .padding(.vertical, 4)
    }

    private var thumbnail: some View {
        Group {
            if let s = item.thumbnailURL, let url = URL(string: s) {
                AsyncImage(url: url) { $0.resizable().scaledToFill() }
                    placeholder: { placeholderIcon }
            } else {
                placeholderIcon
            }
        }
        .frame(width: 52, height: 52)
        .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
    }

    private var placeholderIcon: some View {
        ZStack {
            Color.appAccent.opacity(0.12)
            Image(systemName: platformIcon).foregroundStyle(.tint)
        }
    }

    @ViewBuilder private var statusChip: some View {
        switch item.status {
        case "pending":
            chip("Queued", icon: "clock", tint: .secondary)
        case "processing":
            HStack(spacing: 6) {
                ProgressView().controlSize(.mini)
                Text("Analyzing…").font(.caption.weight(.semibold)).foregroundStyle(.secondary)
            }
        case "done":
            chip(item.placeCount > 0
                 ? "\(item.placeCount) place\(item.placeCount == 1 ? "" : "s")"
                 : "No places found",
                 icon: item.placeCount > 0 ? "checkmark.circle.fill" : "minus.circle",
                 tint: item.placeCount > 0 ? .green : .secondary)
        default:  // failed
            chip("Failed", icon: "exclamationmark.triangle.fill", tint: .orange)
        }
    }

    private func chip(_ text: String, icon: String, tint: Color) -> some View {
        Label(text, systemImage: icon)
            .font(.caption.weight(.semibold))
            .foregroundStyle(tint)
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
