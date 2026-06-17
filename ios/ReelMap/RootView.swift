import SwiftUI

struct RootView: View {
    var body: some View {
        TabView {
            MapScreen()
                .tabItem { Label("Map", systemImage: "map.fill") }
            CityListsScreen()
                .tabItem { Label("Lists", systemImage: "square.stack.3d.up.fill") }
            AddReelScreen()
                .tabItem { Label("Add", systemImage: "plus.circle.fill") }
        }
    }
}
