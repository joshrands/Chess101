import SwiftUI

@main
struct Chess101App: App {
    @State private var splashDone = false

    var body: some Scene {
        WindowGroup {
            ZStack {
                Color(red: 0.04, green: 0.05, blue: 0.07).ignoresSafeArea()
                if splashDone {
                    ContentView()
                        .transition(.opacity)
                } else {
                    SplashView {
                        withAnimation(.easeIn(duration: 0.4)) { splashDone = true }
                    }
                    .transition(.opacity)
                }
            }
            .animation(.easeIn(duration: 0.4), value: splashDone)
        }
    }
}
