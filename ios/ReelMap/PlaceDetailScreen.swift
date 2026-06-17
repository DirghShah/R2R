import MapKit
import SharedKit
import SwiftUI

struct PlaceDetailScreen: View {
    let saved: SavedPlace
    @Environment(\.dismiss) private var dismiss

    private var category: PlaceCategory { saved.categoryEnum }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    header
                    if let desc = saved.description, !desc.isEmpty {
                        Text(desc).font(.body)
                    }
                    card("What to order", "fork.knife", saved.whatToOrder)
                    card("Tips", "lightbulb.fill", saved.tips)
                    actions
                }
                .padding(20)
            }
            .background(backdrop)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button { dismiss() } label: { Image(systemName: "xmark") }
                        .buttonStyle(.glass)
                }
            }
        }
    }

    // MARK: Pieces

    private var header: some View {
        VStack(alignment: .leading, spacing: 12) {
            photos
            HStack(spacing: 10) {
                Label(category.displayName, systemImage: category.symbol)
                    .font(.caption.weight(.semibold))
                    .padding(.horizontal, 12).padding(.vertical, 7)
                    .foregroundStyle(.white)
                    .glassEffect(.regular.tint(category.tint), in: .capsule)
                if let r = saved.place.rating {
                    Label(String(format: "%.1f", r), systemImage: "star.fill")
                        .font(.caption.weight(.semibold))
                        .padding(.horizontal, 12).padding(.vertical, 7)
                        .glassEffect(.regular, in: .capsule)
                }
            }
            Text(saved.place.name).font(.largeTitle.bold())
            if let a = saved.place.address {
                Text(a).font(.subheadline).foregroundStyle(.secondary)
            }
        }
    }

    @ViewBuilder private var photos: some View {
        if let urls = saved.place.photos, !urls.isEmpty {
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 10) {
                    ForEach(urls, id: \.self) { u in
                        AsyncImage(url: URL(string: u)) { $0.resizable().scaledToFill() }
                            placeholder: { category.tint.opacity(0.15) }
                            .frame(width: 240, height: 160)
                            .clipShape(.rect(cornerRadius: 18))
                    }
                }
            }
        }
    }

    @ViewBuilder private func card(_ title: String, _ icon: String, _ items: [String]?) -> some View {
        if let items, !items.isEmpty {
            VStack(alignment: .leading, spacing: 10) {
                Label(title, systemImage: icon).font(.headline)
                ForEach(items, id: \.self) { item in
                    HStack(alignment: .top, spacing: 8) {
                        Image(systemName: "checkmark.circle.fill")
                            .foregroundStyle(category.tint)
                        Text(item)
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(16)
            .glassEffect(.regular, in: .rect(cornerRadius: 20))
        }
    }

    private var actions: some View {
        VStack(spacing: 10) {
            if let reel = saved.reelURL, let url = URL(string: reel) {
                action("Open in Instagram", "play.rectangle.fill") { openInstagram(url) }
            }
            action("Google Maps", "map.fill") { openGoogleMaps() }
            action("Apple Maps", "location.fill") { openAppleMaps() }
        }
        .padding(.top, 4)
    }

    private func action(_ title: String, _ icon: String, _ run: @escaping () -> Void) -> some View {
        Button(action: run) {
            Label(title, systemImage: icon)
                .font(.headline).frame(maxWidth: .infinity).padding(.vertical, 6)
        }
        .buttonStyle(.glassProminent)
        .tint(category.tint)
    }

    private var backdrop: some View {
        LinearGradient(colors: [category.tint.opacity(0.12), .clear],
                       startPoint: .top, endPoint: .center)
            .ignoresSafeArea()
    }

    // MARK: Deep links

    private func openInstagram(_ webURL: URL) {
        let app = URL(string: webURL.absoluteString
            .replacingOccurrences(of: "https://www.instagram.com", with: "instagram://"))
        if let app, UIApplication.shared.canOpenURL(app) {
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
