// swift-tools-version: 5.9
import PackageDescription

let package = Package(
    name: "Chess101iOS",
    platforms: [.iOS(.v16), .macOS(.v13)],
    products: [],
    targets: [
        // Pure chess engine — no UIKit dependency
        .target(
            name: "Chess101Engine",
            path: "Sources/Chess101Engine"
        ),
        // iOS app executable
        .executableTarget(
            name: "Chess101iOS",
            dependencies: ["Chess101Engine"],
            path: "Sources/Chess101iOS",
            resources: [.process("Assets.xcassets")]
        ),
        // macOS CLI bridge for lockstep fuzzing
        .executableTarget(
            name: "SwiftBridge",
            dependencies: ["Chess101Engine"],
            path: "Sources/SwiftBridge"
        ),
        .testTarget(
            name: "Chess101IOSTests",
            dependencies: ["Chess101iOS", "Chess101Engine"],
            path: "Tests/Chess101IOSTests"
        ),
    ]
)
