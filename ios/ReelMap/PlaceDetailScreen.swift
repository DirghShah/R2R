import MapKit
import SharedKit
import SwiftUI

struct PlaceDetailScreen: View {
    let place: CachedPlace
    @Environment(\.dismiss) private var dismiss

    private var category: PlaceCategory { place.categoryEnum }
    private var hasCoords: Bool { place.coordinate != nil }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 20) {
                    header
                    if let desc = place.summary, !desc.isEmpty {
                        Text(desc).font(.body).fixedSize(horizontal: false, vertical: true)
                    }
                    vibeRow
                    infoRow
                    listCard("What to order", "fork.knife", place.whatToOrder)
                    listCard("Tips", "lightbulb.fill", place.tips)
                    actions
                }
                .padding(20)
            }
            .background(backdrop)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                }
            }
        }
    }

    // MARK: Header

    private var header: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 8) {
                categoryBadge
                if let stars = place.rating {
                    badge(String(format: "%.1f ★", stars), background: .regularMaterial)
                }
                if let price = place.priceString {
                    badge(price, background: .regularMaterial)
                }
                if !hasCoords {
                    badge("No map pin", systemImage: "mappin.slash", background: .regularMaterial)
                }
            }
            Text(place.name).font(.largeTitle.bold())
            if let a = place.address {
                Text(a).font(.subheadline).foregroundStyle(.secondary)
            } else if let city = place.city {
                Text(city).font(.subheadline).foregroundStyle(.secondary)
            }
        }
    }

    private var categoryBadge: some View {
        Label(category.displayName, systemImage: category.symbol)
            .font(.caption.weight(.semibold))
            .padding(.horizontal, 12).padding(.vertical, 7)
            .foregroundStyle(.white)
            .background(category.tint, in: .capsule)
    }

    // MARK: Vibe chips

    @ViewBuilder private var vibeRow: some View {
        if !place.vibe.isEmpty {
            FlowRow(items: place.vibe) { tag in
                Text(tag)
                    .font(.caption.weight(.medium))
                    .padding(.horizontal, 10).padding(.vertical, 5)
                    .background(category.tint.opacity(0.12), in: .capsule)
                    .foregroundStyle(category.tint)
            }
        }
    }

    // MARK: Info row (hours, Instagram, website)

    @ViewBuilder private var infoRow: some View {
        let hasInfo = place.hoursHint != nil || place.instagramHandle != nil || place.website != nil
        if hasInfo {
            VStack(alignment: .leading, spacing: 10) {
                if let h = place.hoursHint {
                    infoLine("clock", h)
                }
                if let handle = place.instagramHandle {
                    infoLink("camera", "@\(handle)",
                             url: URL(string: "https://www.instagram.com/\(handle)/"))
                }
                if let site = place.website, let url = URL(string: site) {
                    infoLink("globe", site
                        .replacingOccurrences(of: "https://", with: "")
                        .replacingOccurrences(of: "http://", with: "")
                        .trimmingCharacters(in: CharacterSet(charactersIn: "/")),
                             url: url)
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(16)
            .card(20)
        }
    }

    private func infoLine(_ icon: String, _ text: String) -> some View {
        Label(text, systemImage: icon)
            .font(.subheadline)
            .foregroundStyle(.primary)
    }

    private func infoLink(_ icon: String, _ label: String, url: URL?) -> some View {
        Group {
            if let url {
                Link(destination: url) {
                    Label(label, systemImage: icon)
                        .font(.subheadline)
                        .foregroundStyle(category.tint)
                }
            } else {
                infoLine(icon, label)
            }
        }
    }

    // MARK: List cards

    @ViewBuilder private func listCard(_ title: String, _ icon: String, _ items: [String]) -> some View {
        if !items.isEmpty {
            VStack(alignment: .leading, spacing: 10) {
                Label(title, systemImage: icon).font(.headline)
                ForEach(items, id: \.self) { item in
                    HStack(alignment: .top, spacing: 8) {
                        Image(systemName: "checkmark.circle.fill").foregroundStyle(category.tint)
                        Text(item).fixedSize(horizontal: false, vertical: true)
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(16)
            .card(20)
        }
    }

    // MARK: Actions

    private var actions: some View {
        VStack(spacing: 10) {
            if let reel = place.reelURL, let url = URL(string: reel) {
                action("Open original", "play.rectangle.fill") { openReel(url) }
            }
            if hasCoords {
                action("Google Maps", "map.fill") { openGoogleMaps() }
                action("Apple Maps", "location.fill") { openAppleMaps() }
            }
        }
        .padding(.top, 4)
    }

    private func action(_ title: String, _ icon: String, _ run: @escaping () -> Void) -> some View {
        Button(action: run) {
            Label(title, systemImage: icon)
                .font(.headline).frame(maxWidth: .infinity).padding(.vertical, 6)
        }
        .buttonStyle(.borderedProminent)
        .tint(category.tint)
    }

    // MARK: Backdrop

    private var backdrop: some View {
        LinearGradient(colors: [category.tint.opacity(0.12), .clear],
                       startPoint: .top, endPoint: .center).ignoresSafeArea()
    }

    // MARK: Helpers

    private func badge<S: ShapeStyle>(_ text: String, systemImage: String? = nil, background: S) -> some View {
        Group {
            if let icon = systemImage {
                Label(text, systemImage: icon)
            } else {
                Text(text)
            }
        }
        .font(.caption.weight(.semibold))
        .padding(.horizontal, 12).padding(.vertical, 7)
        .background(background, in: .capsule)
    }

    // MARK: Deep links

    private func openReel(_ webURL: URL) {
        // Deep-link into the Instagram app when applicable; TikTok / YouTube (and
        // Safari) handle their own links, so just open the URL for those.
        if webURL.host?.contains("instagram.com") == true,
           let app = URL(string: webURL.absoluteString
            .replacingOccurrences(of: "https://www.instagram.com", with: "instagram://")),
           UIApplication.shared.canOpenURL(app) {
            UIApplication.shared.open(app)
        } else {
            UIApplication.shared.open(webURL)
        }
    }

    private func openGoogleMaps() {
        guard let lat = place.lat, let lng = place.lng else { return }
        let q = place.name.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? ""
        let appURL = URL(string: "comgooglemaps://?q=\(q)&center=\(lat),\(lng)")!
        let webURL = URL(string: "https://www.google.com/maps/search/?api=1&query=\(lat),\(lng)")!
        UIApplication.shared.open(UIApplication.shared.canOpenURL(appURL) ? appURL : webURL)
    }

    private func openAppleMaps() {
        guard let lat = place.lat, let lng = place.lng else { return }
        let item = MKMapItem(placemark: MKPlacemark(
            coordinate: CLLocationCoordinate2D(latitude: lat, longitude: lng)))
        item.name = place.name
        item.openInMaps()
    }
}

// MARK: - FlowRow (wrapping chip layout)

private struct FlowRow<Item: Hashable, Content: View>: View {
    let items: [Item]
    let content: (Item) -> Content

    var body: some View {
        // iOS 16+ ViewThatFits / Layout. Simple wrapping via GeometryReader + tag layout.
        _FlowLayout(spacing: 8) {
            ForEach(items, id: \.self) { content($0) }
        }
    }
}

private struct _FlowLayout: Layout {
    var spacing: CGFloat = 8

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let rows = computeRows(proposal: proposal, subviews: subviews)
        let height = rows.map { row in row.map { $0.sizeThatFits(.unspecified).height }.max() ?? 0 }
            .reduce(0) { $0 + $1 + spacing } - spacing
        return CGSize(width: proposal.width ?? 0, height: max(height, 0))
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let rows = computeRows(proposal: proposal, subviews: subviews)
        var y = bounds.minY
        for row in rows {
            var x = bounds.minX
            let rowHeight = row.map { $0.sizeThatFits(.unspecified).height }.max() ?? 0
            for subview in row {
                let size = subview.sizeThatFits(.unspecified)
                subview.place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(size))
                x += size.width + spacing
            }
            y += rowHeight + spacing
        }
    }

    private func computeRows(proposal: ProposedViewSize, subviews: Subviews) -> [[LayoutSubviews.Element]] {
        let maxWidth = proposal.width ?? .infinity
        var rows: [[LayoutSubviews.Element]] = [[]]
        var x: CGFloat = 0
        for subview in subviews {
            let w = subview.sizeThatFits(.unspecified).width
            if x + w > maxWidth, !rows[rows.count - 1].isEmpty {
                rows.append([])
                x = 0
            }
            rows[rows.count - 1].append(subview)
            x += w + spacing
        }
        return rows
    }
}
