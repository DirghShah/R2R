import CoreLocation
import MapKit
import SharedKit
import SwiftData
import SwiftUI

struct PlaceDetailScreen: View {
    let place: CachedPlace
    var userLocation: CLLocation? = nil
    var detents: Set<PresentationDetent> = [.large]

    @Environment(\.dismiss) private var dismiss
    @Environment(\.modelContext) private var context
    @State private var showMapsDialog = false
    @State private var mark: PlaceMark?
    @State private var visited = false
    @State private var note = ""
    @FocusState private var isNotesFocused: Bool

    private var cat: PlaceCategory { place.categoryEnum }
    private var tint: Color { place.pinColor }
    private var hasCoords: Bool { place.coordinate != nil }

    var body: some View {
        ZStack {
            Color.clear.onTapGesture { isNotesFocused = false }

            ScrollView {
                VStack(spacing: 0) {
                    hero
                    VStack(alignment: .leading, spacing: 14) {
                        badgeRow
                        if let s = place.summary, !s.isEmpty {
                            Text(s).font(.system(size: 15)).foregroundStyle(.ink).lineSpacing(3)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                        if !place.tips.isEmpty { tipsCard }
                        if !place.whatToOrder.isEmpty { orderCard }
                        infoCard
                        visitedCard
                        sourcedFrom
                        actions
                    }
                    .padding(.horizontal, 20).padding(.top, 16).padding(.bottom, 34)
                }
            }
            .scrollIndicators(.hidden)
        }
        .background(Color.canvas)
        .presentationDetents(detents)
        .presentationDragIndicator(.visible)
        .onAppear(perform: loadMark)
        .onDisappear(perform: persistMark)
        .confirmationDialog("Open in Maps", isPresented: $showMapsDialog, titleVisibility: .visible) {
            Button("Apple Maps") { openAppleMaps() }
            Button("Google Maps") { openGoogleMaps() }
        }
    }

    // MARK: Hero

    private var hero: some View {
        ZStack(alignment: .bottomLeading) {
            heroBackground
            HStack {
                ShareLink(item: shareText) { heroButton("square.and.arrow.up") }
                Spacer()
                Button { dismiss() } label: { heroButton("xmark") }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
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

    /// Real venue photo (Google) with a legibility scrim, or the gradient.
    @ViewBuilder private var heroBackground: some View {
        if let url = place.firstPhotoURL {
            AsyncImage(url: url) { img in
                img.resizable().scaledToFill()
            } placeholder: {
                gradient.overlay(ProgressView().tint(.white))
            }
            .overlay(LinearGradient(colors: [.clear, .black.opacity(0.55)],
                                    startPoint: .center, endPoint: .bottom))
        } else {
            gradient
        }
    }

    private func heroButton(_ system: String) -> some View {
        Image(systemName: system).font(.system(size: 15, weight: .bold)).foregroundStyle(.white)
            .frame(width: 32, height: 32).background(Color(hex: 0x101A14).opacity(0.35), in: Circle())
    }

    private var shareText: String {
        var parts = [place.name]
        if let a = place.address ?? place.city { parts.append(a) }
        if let g = place.googleMapsURL { parts.append(g) }
        else if let r = place.reelURL { parts.append(r) }
        return parts.joined(separator: "\n")
    }

    // MARK: Rows

    private var badgeRow: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 10) {
                if let r = place.rating {
                    HStack(spacing: 6) {
                        Image(systemName: "star.fill").font(.system(size: 14)).foregroundStyle(.starGold)
                        Text(String(format: "%.1f", r)).font(.display(16, .bold)).foregroundStyle(.ink)
                        if let n = place.reviewCount, n > 0 {
                            Text("(\(n.formatted()))").font(.system(size: 12)).foregroundStyle(.inkSecondary)
                        }
                    }
                    .padding(.horizontal, 13).padding(.vertical, 9).card(14)
                }
                if let price = place.priceString {
                    Text(price).font(.system(size: 15, weight: .semibold)).foregroundStyle(.ink)
                        .padding(.horizontal, 13).padding(.vertical, 9).card(14)
                }
                if let d = place.distanceMeters(from: userLocation) {
                    Label(DistanceFormat.short(d), systemImage: "location.fill")
                        .font(.system(size: 13, weight: .semibold)).foregroundStyle(.inkSecondary)
                        .padding(.horizontal, 13).padding(.vertical, 9).card(14)
                }
                openChip
            }
            .padding(.vertical, 2)
        }
        .scrollClipDisabled()
    }

    @ViewBuilder private var openChip: some View {
        if place.isPermanentlyClosed {
            statusChip("Permanently closed", color: .closedRed)
        } else if let st = place.openStatus {
            statusChip(st.label, color: st.open ? .appAccent : .closedRed)
        } else if let h = place.hoursHint {
            statusChip(h, color: .appAccent)
        }
    }

    private func statusChip(_ text: String, color: Color) -> some View {
        Text(text).font(.system(size: 13, weight: .semibold)).foregroundStyle(color).lineLimit(1)
            .padding(.horizontal, 13).padding(.vertical, 9)
            .background(color.opacity(0.12), in: RoundedRectangle(cornerRadius: 14, style: .continuous))
    }

    private var tipsCard: some View {
        card(header: "Tips from the reel", icon: "lightbulb.fill") {
            ForEach(Array(place.tips.enumerated()), id: \.offset) { i, tip in
                HStack(alignment: .top, spacing: 10) {
                    Image(systemName: "checkmark").font(.system(size: 13, weight: .heavy)).foregroundStyle(.appAccent)
                        .padding(.top, 2)
                    Text(tip).font(.system(size: 14)).foregroundStyle(.ink)
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
                    Text(item).font(.system(size: 14)).foregroundStyle(.ink)
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
                            Text(row.label).font(.system(size: 13)).foregroundStyle(.secondary)
                            Text(row.value).font(.system(size: 14, weight: .medium))
                                .foregroundStyle(row.link ? .linkBlue : .primary).lineLimit(1)
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

    // MARK: Visited + notes (local, survives sync)

    private var visitedCard: some View {
        VStack(alignment: .leading, spacing: 12) {
            Toggle(isOn: $visited) {
                Label("I've been here", systemImage: visited ? "checkmark.seal.fill" : "checkmark.seal")
                    .font(.system(size: 15, weight: .semibold)).foregroundStyle(.ink)
            }
            .tint(.appAccent)
            .onChange(of: visited) { _, _ in Haptics.select(); persistMark() }

            Rectangle().fill(Color.hairline).frame(height: 1)

            VStack(alignment: .leading, spacing: 6) {
                Text("YOUR NOTES").font(.system(size: 11, weight: .semibold)).tracking(0.4).foregroundStyle(.secondary)
                TextField("Add a private note…", text: $note, axis: .vertical)
                    .font(.system(size: 14)).foregroundStyle(.ink).lineLimit(1...4)
                    .focused($isNotesFocused)
            }
        }
        .padding(16).card(20)
    }

    private func loadMark() {
        let id = place.id
        let descriptor = FetchDescriptor<PlaceMark>(predicate: #Predicate { $0.placeID == id })
        if let m = try? context.fetch(descriptor).first {
            mark = m; visited = m.visited; note = m.note
        }
    }

    private func persistMark() {
        if let m = mark {
            m.visited = visited; m.note = note; m.updatedAt = .now
        } else if visited || !note.isEmpty {
            let m = PlaceMark(placeID: place.id, visited: visited, note: note)
            context.insert(m); mark = m
        }
        try? context.save()
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
        if let a = place.address ?? place.city { rows.append(.init(icon: "mappin.and.ellipse", label: "Address", value: a)) }
        if let phone = place.phone { rows.append(.init(icon: "phone", label: "Phone", value: phone)) }
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
        // Prefer the exact place URL Google gave us — it opens the resolved
        // listing (reviews, hours, photos) rather than a name search.
        if let s = place.googleMapsURL, let url = URL(string: s) {
            UIApplication.shared.open(url)
            return
        }
        guard let lat = place.lat, let lng = place.lng else { return }
        let q = place.name.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? ""
        let app = URL(string: "comgooglemaps://?q=\(q)&center=\(lat),\(lng)")!
        let web = URL(string: "https://www.google.com/maps/search/?api=1&query=\(lat),\(lng)")!
        UIApplication.shared.open(UIApplication.shared.canOpenURL(app) ? app : web)
    }
}
