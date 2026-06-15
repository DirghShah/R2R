import MapKit
import SharedKit
import SwiftUI

struct PlaceDetailScreen: View {
    let saved: SavedPlace

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 16) {
                    photos
                    if let desc = saved.description {
                        Text(desc).font(.body)
                    }
                    section("What to order", saved.whatToOrder)
                    section("Tips", saved.tips)
                    links
                }
                .padding()
            }
            .navigationTitle(saved.place.name)
            .navigationBarTitleDisplayMode(.inline)
        }
    }

    @ViewBuilder private var photos: some View {
        if let urls = saved.place.photos, !urls.isEmpty {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack {
                    ForEach(urls, id: \.self) { u in
                        AsyncImage(url: URL(string: u)) { $0.resizable().scaledToFill() }
                            placeholder: { Color.gray.opacity(0.2) }
                            .frame(width: 220, height: 150)
                            .clipShape(RoundedRectangle(cornerRadius: 12))
                    }
                }
            }
        }
    }

    @ViewBuilder private func section(_ title: String, _ items: [String]?) -> some View {
        if let items, !items.isEmpty {
            VStack(alignment: .leading, spacing: 6) {
                Text(title).font(.headline)
                ForEach(items, id: \.self) { Label($0, systemImage: "checkmark.circle") }
            }
        }
    }

    private var links: some View {
        VStack(spacing: 10) {
            if let reel = saved.reelURL, let url = URL(string: reel) {
                LinkButton("Open in Instagram", systemImage: "play.rectangle.fill") {
                    openInstagram(url)
                }
            }
            LinkButton("Open in Google Maps", systemImage: "map.fill") { openGoogleMaps() }
            LinkButton("Open in Apple Maps", systemImage: "location.fill") { openAppleMaps() }
        }
        .padding(.top, 8)
    }

    // MARK: Deep links

    private func openInstagram(_ webURL: URL) {
        // Prefer the Instagram app, fall back to the web URL.
        if let app = URL(string: webURL.absoluteString.replacingOccurrences(
            of: "https://www.instagram.com", with: "instagram://")),
           UIApplication.shared.canOpenURL(app) {
            UIApplication.shared.open(app)
        } else {
            UIApplication.shared.open(webURL)
        }
    }

    private func openGoogleMaps() {
        guard let lat = saved.place.lat, let lng = saved.place.lng else { return }
        let q = saved.place.name.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? ""
        let appURL = URL(string: "comgooglemaps://?q=\(q)&center=\(lat),\(lng)")!
        let webURL = URL(string: "https://www.google.com/maps/search/?api=1&query=\(lat),\(lng)")!
        UIApplication.shared.open(UIApplication.shared.canOpenURL(appURL) ? appURL : webURL)
    }

    private func openAppleMaps() {
        guard let lat = saved.place.lat, let lng = saved.place.lng else { return }
        let item = MKMapItem(placemark: MKPlacemark(
            coordinate: CLLocationCoordinate2D(latitude: lat, longitude: lng)))
        item.name = saved.place.name
        item.openInMaps()
    }
}

private struct LinkButton: View {
    let title: String
    let systemImage: String
    let action: () -> Void
    init(_ title: String, systemImage: String, action: @escaping () -> Void) {
        self.title = title; self.systemImage = systemImage; self.action = action
    }
    var body: some View {
        Button(action: action) {
            Label(title, systemImage: systemImage).frame(maxWidth: .infinity)
        }
        .buttonStyle(.borderedProminent)
    }
}
