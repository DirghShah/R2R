import MapKit
import SharedKit
import SwiftUI

struct PlaceDetailScreen: View {
    let place: CachedPlace
    @Environment(\.dismiss) private var dismiss
    @State private var showMapsDialog = false

    private var cat: PlaceCategory { place.categoryEnum }
    private var tint: Color { place.pinColor }
    private var hasCoords: Bool { place.coordinate != nil }

    var body: some View {
        ScrollView {
            VStack(spacing: 0) {
                hero
                VStack(alignment: .leading, spacing: 14) {
                    badgeRow
                    if let s = place.summary, !s.isEmpty {
                        Text(s).font(.system(size: 15)).foregroundStyle(Color(hex: 0x3A423D)).lineSpacing(3)
                            .fixedSize(horizontal: false, vertical: true)
                    }
                    if !place.tips.isEmpty { tipsCard }
                    if !place.whatToOrder.isEmpty { orderCard }
                    infoCard
                    sourcedFrom
                    actions
                }
                .padding(.horizontal, 20).padding(.top, 16).padding(.bottom, 34)
            }
        }
        .scrollIndicators(.hidden)
        .background(Color.canvas)
        .presentationDetents([.large])
        .presentationDragIndicator(.visible)
        .confirmationDialog("Open in Maps", isPresented: $showMapsDialog, titleVisibility: .visible) {
            Button("Apple Maps") { openAppleMaps() }
            Button("Google Maps") { openGoogleMaps() }
        }
    }

    // MARK: Hero

    private var hero: some View {
        ZStack(alignment: .bottomLeading) {
            gradient
            Button { dismiss() } label: {
                Image(systemName: "xmark").font(.system(size: 15, weight: .bold)).foregroundStyle(.white)
                    .frame(width: 32, height: 32).background(Color(hex: 0x101A14).opacity(0.35), in: Circle())
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topTrailing)
            .padding(16)

            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 6) {
                    Image(systemName: cat.symbol).font(.system(size: 10, weight: .bold))
                    Text(place.filterLabel.uppercased())
                        .font(.system(size: 11, weight: .bold)).tracking(0.5)
                }
                .foregroundStyle(.white)
                .padding(.horizontal, 10).padding(.vertical, 5)
                .background(.white.opacity(0.22), in: RoundedRectangle(cornerRadius: 8))
                Text(place.name).font(.display(28, .bold)).foregroundStyle(.white)
                    .shadow(color: .black.opacity(0.3), radius: 12, y: 2)
            }
            .padding(20)
        }
        .frame(height: 210)
        .clipped()
    }

    private var gradient: some View {
        LinearGradient(colors: [tint, tint.opacity(0.73), Color.deepGreen],
                       startPoint: .topLeading, endPoint: .bottomTrailing)
    }

    // MARK: Rows

    private var badgeRow: some View {
        HStack(spacing: 10) {
            if let r = place.rating {
                HStack(spacing: 6) {
                    Image(systemName: "star.fill").font(.system(size: 14)).foregroundStyle(.starGold)
                    Text(String(format: "%.1f", r)).font(.display(16, .bold)).foregroundStyle(.ink)
                }
                .padding(.horizontal, 13).padding(.vertical, 9).card(14)
            }
            if let price = place.priceString {
                Text(price).font(.system(size: 15, weight: .semibold)).foregroundStyle(.ink)
                    .padding(.horizontal, 13).padding(.vertical, 9).card(14)
            }
            if let h = place.hoursHint {
                Text(h).font(.system(size: 13, weight: .semibold)).foregroundStyle(.appAccent)
                    .padding(.horizontal, 13).padding(.vertical, 9)
                    .background(Color(hex: 0xEAF5EF), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
            }
        }
    }

    private var tipsCard: some View {
        card(header: "Tips from the reel", icon: "lightbulb.fill") {
            ForEach(Array(place.tips.enumerated()), id: \.offset) { i, tip in
                HStack(alignment: .top, spacing: 10) {
                    Image(systemName: "checkmark").font(.system(size: 13, weight: .heavy)).foregroundStyle(.appAccent)
                        .padding(.top, 2)
                    Text(tip).font(.system(size: 14)).foregroundStyle(Color(hex: 0x3A423D))
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(.vertical, 7)
                .overlay(alignment: .top) { if i > 0 { Rectangle().fill(Color.hairline).frame(height: 1) } }
            }
        }
    }

    private var orderCard: some View {
        card(header: "What to order", icon: "fork.knife") {
            ForEach(Array(place.whatToOrder.enumerated()), id: \.offset) { i, item in
                HStack(alignment: .top, spacing: 10) {
                    Image(systemName: "circle.fill").font(.system(size: 5)).foregroundStyle(.appAccent).padding(.top, 7)
                    Text(item).font(.system(size: 14)).foregroundStyle(Color(hex: 0x3A423D))
                        .fixedSize(horizontal: false, vertical: true)
                }
                .padding(.vertical, 6)
            }
        }
    }

    @ViewBuilder private var infoCard: some View {
        let rows = infoRows
        if !rows.isEmpty {
            VStack(spacing: 0) {
                ForEach(Array(rows.enumerated()), id: \.offset) { i, row in
                    HStack(spacing: 12) {
                        Image(systemName: row.icon).font(.system(size: 17)).foregroundStyle(.inkMuted).frame(width: 20)
                        VStack(alignment: .leading, spacing: 1) {
                            Text(row.label).font(.system(size: 13)).foregroundStyle(.inkMuted)
                            Text(row.value).font(.system(size: 14, weight: .medium))
                                .foregroundStyle(row.link ? .linkBlue : .ink).lineLimit(1)
                        }
                        Spacer()
                    }
                    .padding(.vertical, 13)
                    .overlay(alignment: .top) { if i > 0 { Rectangle().fill(Color.hairline).frame(height: 1) } }
                }
            }
            .padding(.horizontal, 16).card(20)
        }
    }

    private var sourcedFrom: some View {
        HStack(spacing: 11) {
            ZStack {
                LinearGradient(colors: [tint, Color.deepGreen], startPoint: .topLeading, endPoint: .bottomTrailing)
                Image(systemName: "play.fill").font(.system(size: 15)).foregroundStyle(.white)
            }
            .frame(width: 44, height: 44).clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
            VStack(alignment: .leading, spacing: 1) {
                Text("Sourced from").font(.system(size: 13)).foregroundStyle(.inkMuted)
                Text(sourceLabel).font(.system(size: 14, weight: .semibold)).foregroundStyle(.ink).lineLimit(1)
            }
            Spacer()
        }
        .padding(.horizontal, 15).padding(.vertical, 13).card(20)
    }

    private var actions: some View {
        HStack(spacing: 11) {
            if let reel = place.reelURL, let url = URL(string: reel) {
                Button { openReel(url) } label: {
                    Label("Open reel", systemImage: "play.fill")
                        .font(.system(size: 15, weight: .semibold)).foregroundStyle(.white)
                        .frame(maxWidth: .infinity).padding(15)
                        .background(Color.linkBlue, in: RoundedRectangle(cornerRadius: 16, style: .continuous))
                }.buttonStyle(.plain)
            }
            if hasCoords {
                Button { showMapsDialog = true } label: {
                    Label("Maps", systemImage: "mappin.and.ellipse")
                        .font(.system(size: 15, weight: .semibold)).foregroundStyle(.appAccent)
                        .frame(maxWidth: .infinity).padding(15)
                        .background(RoundedRectangle(cornerRadius: 16, style: .continuous).strokeBorder(Color.appAccent, lineWidth: 1.6))
                }.buttonStyle(.plain)
            }
        }
    }

    // MARK: Helpers

    private func card<Content: View>(header: String, icon: String, @ViewBuilder content: () -> Content) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 8) {
                Image(systemName: icon).font(.system(size: 15)).foregroundStyle(.appAccent)
                Text(header).font(.display(15, .semibold)).foregroundStyle(.ink)
            }
            .padding(.bottom, 4)
            content()
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(16).card(20)
    }

    private struct InfoRow { let icon: String; let label: String; let value: String; var link = false }
    private var infoRows: [InfoRow] {
        var rows: [InfoRow] = []
        if let h = place.hoursHint { rows.append(.init(icon: "clock", label: "Hours", value: h)) }
        if let a = place.address ?? place.city { rows.append(.init(icon: "mappin.and.ellipse", label: "Area", value: a)) }
        if let handle = place.instagramHandle { rows.append(.init(icon: "camera", label: "Instagram", value: "@\(handle)", link: true)) }
        if let site = place.website {
            let clean = site.replacingOccurrences(of: "https://", with: "").replacingOccurrences(of: "http://", with: "")
            rows.append(.init(icon: "globe", label: "Website", value: clean, link: true))
        }
        return rows
    }

    private var sourceLabel: String {
        let platform = platformName
        if let h = place.instagramHandle { return "@\(h) · \(platform)" }
        return platform
    }

    private var platformName: String {
        let u = (place.reelURL ?? "").lowercased()
        if u.contains("tiktok") { return "TikTok" }
        if u.contains("youtu") { return "YouTube" }
        return "Instagram"
    }

    // MARK: Deep links

    private func openReel(_ url: URL) {
        if url.host?.contains("instagram.com") == true,
           let app = URL(string: url.absoluteString.replacingOccurrences(of: "https://www.instagram.com", with: "instagram://")),
           UIApplication.shared.canOpenURL(app) {
            UIApplication.shared.open(app)
        } else { UIApplication.shared.open(url) }
    }

    private func openAppleMaps() {
        guard let lat = place.lat, let lng = place.lng else { return }
        let item = MKMapItem(placemark: MKPlacemark(coordinate: CLLocationCoordinate2D(latitude: lat, longitude: lng)))
        item.name = place.name
        item.openInMaps()
    }

    private func openGoogleMaps() {
        guard let lat = place.lat, let lng = place.lng else { return }
        let q = place.name.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? ""
        let app = URL(string: "comgooglemaps://?q=\(q)&center=\(lat),\(lng)")!
        let web = URL(string: "https://www.google.com/maps/search/?api=1&query=\(lat),\(lng)")!
        UIApplication.shared.open(UIApplication.shared.canOpenURL(app) ? app : web)
    }
}
