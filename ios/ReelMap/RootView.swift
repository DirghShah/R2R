import SwiftUI

struct RootView: View {
    var body: some View {
        TabView {
            MapScreen()
                .tabItem { Label("Map", systemImage: "mappin.and.ellipse") }
            CityListsScreen()
                .tabItem { Label("Lists", systemImage: "list.bullet") }
            AddReelScreen()
                .tabItem { Label("Analyze", systemImage: "waveform.path.ecg") }
        }
    }
}
