#if canImport(UIKit)
import SwiftUI
import SceneKit

public struct Board3DView: UIViewRepresentable {
    public let board: Board?
    public let teamR: Team
    public let teamL: Team
    public let currentTeam: Team?
    public let selectedCell: Cell?
    public let legalTargets: [Cell]
    public let trails: [MoveTrail]
    public let activeAnimation: MoveAnimation?
    public let aiThinking: Bool
    public let onCellTapped: ((Cell) -> Void)?

    public init(board: Board?, teamR: Team, teamL: Team, currentTeam: Team?,
                selectedCell: Cell?, legalTargets: [Cell],
                trails: [MoveTrail] = [], activeAnimation: MoveAnimation? = nil,
                aiThinking: Bool = false, onCellTapped: ((Cell) -> Void)? = nil) {
        self.board = board; self.teamR = teamR; self.teamL = teamL
        self.currentTeam = currentTeam
        self.selectedCell = selectedCell; self.legalTargets = legalTargets
        self.trails = trails; self.activeAnimation = activeAnimation
        self.aiThinking = aiThinking; self.onCellTapped = onCellTapped
    }

    public func makeUIView(context: Context) -> SCNView {
        let view = SCNView()
        view.scene = context.coordinator.scene
        view.allowsCameraControl = true
        view.backgroundColor = .clear
        view.autoenablesDefaultLighting = false

        let tap = UITapGestureRecognizer(target: context.coordinator,
                                         action: #selector(Coordinator.handleTap(_:)))
        view.addGestureRecognizer(tap)
        context.coordinator.startDisplayLink()
        return view
    }

    public func updateUIView(_ uiView: SCNView, context: Context) {
        context.coordinator.onCellTapped = onCellTapped
        context.coordinator.update(board: board, teamR: teamR, teamL: teamL,
                                    currentTeam: currentTeam,
                                    selected: selectedCell, targets: legalTargets,
                                    trails: trails, activeAnimation: activeAnimation,
                                    aiThinking: aiThinking)
    }

    public func makeCoordinator() -> Coordinator { Coordinator() }

    // MARK: - Coordinator

    public final class Coordinator: NSObject {
        let scene = SCNScene()
        var onCellTapped: ((Cell) -> Void)?

        // SceneKit nodes
        private var squareNodes: [[SCNNode]] = []
        private var pieceNodes: [[SCNNode?]] = Array(repeating: Array(repeating: nil, count: 8), count: 8)
        private var pointLightR: SCNNode?
        private var pointLightL: SCNNode?
        private var templates: [String: SCNNode] = [:]
        private var animatingPiece: SCNNode?

        // State snapshot for display-link tick (written on main thread in update())
        private var tickTrails: [MoveTrail] = []
        private var tickSelected: Cell? = nil
        private var tickTargets: [Cell] = []
        private var tickActiveColor: (r: CGFloat, g: CGFloat, b: CGFloat) = (0, 1, 0.53)
        private var tickAIThinking: Bool = false
        private var lastAnimStart: Date? = nil
        private var lastTeamR: Team? = nil

        // Display link
        private var displayLink: CADisplayLink?

        override init() {
            super.init()
            loadTemplates()
            buildBoard()
        }

        func startDisplayLink() {
            guard displayLink == nil else { return }
            let dl = CADisplayLink(target: self, selector: #selector(tick))
            dl.add(to: .main, forMode: .common)
            displayLink = dl
        }

        deinit { displayLink?.invalidate() }

        // MARK: Per-frame square lighting

        @objc private func tick() {
            let now = Date()
            let t = now.timeIntervalSince1970

            for r in 0..<8 {
                for c in 0..<8 {
                    guard let mat = squareNodes[r][c].geometry?.materials.first else { continue }
                    let cell = Cell(r, c)
                    let isLight = (r + c) % 2 == 0

                    if tickSelected == cell {
                        // Full team-color LED — selected square
                        mat.emission.contents = UIColor(red: tickActiveColor.r,
                                                        green: tickActiveColor.g,
                                                        blue:  tickActiveColor.b, alpha: 1)
                    } else if tickTargets.contains(cell) {
                        // Dim team-color LED — legal move target
                        mat.emission.contents = UIColor(red: tickActiveColor.r * 0.38,
                                                        green: tickActiveColor.g * 0.38,
                                                        blue:  tickActiveColor.b * 0.38, alpha: 1)
                    } else {
                        // Accumulate trail glow on top of base
                        var tr: CGFloat = 0, tg: CGFloat = 0, tb: CGFloat = 0
                        for trail in tickTrails where trail.cells.contains(cell) {
                            let a = CGFloat(trail.alpha(at: now)) * 0.6
                            tr += CGFloat(trail.team.r) / 255 * a
                            tg += CGFloat(trail.team.g) / 255 * a
                            tb += CGFloat(trail.team.b) / 255 * a
                        }

                        if tickAIThinking {
                            // Traveling wave pulse across the board
                            let phase = Double(r + c) * 0.45
                            let pulse = CGFloat(0.45 + 0.55 * (sin(t * 3.2 + phase) * 0.5 + 0.5))
                            let base: CGFloat = isLight ? 0.055 : 0.008
                            mat.emission.contents = UIColor(
                                red:   tickActiveColor.r * 0.18 * pulse + tr,
                                green: tickActiveColor.g * 0.18 * pulse + tg,
                                blue:  tickActiveColor.b * 0.18 * pulse + tb + base * pulse,
                                alpha: 1)
                        } else {
                            // Checkerboard base glow — light squares emit cool blue, dark squares near-off
                            let (br, bg, bb): (CGFloat, CGFloat, CGFloat) = isLight
                                ? (0.038, 0.055, 0.095)
                                : (0.005, 0.005, 0.008)
                            mat.emission.contents = UIColor(red: br + tr, green: bg + tg,
                                                            blue: bb + tb, alpha: 1)
                        }
                    }
                }
            }
        }

        // MARK: Tap handling

        @objc func handleTap(_ gesture: UITapGestureRecognizer) {
            guard let view = gesture.view as? SCNView else { return }
            let pt = gesture.location(in: view)
            for hit in view.hitTest(pt, options: nil) {
                var node: SCNNode? = hit.node
                while let n = node {
                    if let name = n.name {
                        let parts = name.split(separator: "_")
                        if parts.count == 3, let r = Int(parts[1]), let c = Int(parts[2]) {
                            onCellTapped?(Cell(r, c))
                            return
                        }
                    }
                    node = n.parent
                }
            }
        }

        // MARK: OBJ loading

        private func loadTemplates() {
            let scale: Float = 0.72 / 91.5
            for name in ["pawn", "rook", "knight", "bishop", "queen", "king"] {
                templates[name] = loadOBJ(named: name, scale: scale) ?? makeFallback(type: name.capitalized)
            }
        }

        private func loadOBJ(named name: String, scale: Float) -> SCNNode? {
            guard let url = Bundle.main.url(forResource: name, withExtension: "obj"),
                  let src = SCNSceneSource(url: url, options: [.convertToYUp: true,
                                                               .flattenScene: false]),
                  let loaded = src.scene(options: nil) else { return nil }
            let root = SCNNode()
            for child in loaded.rootNode.childNodes { root.addChildNode(child.clone()) }
            root.scale = SCNVector3(scale, scale, scale)
            return root
        }

        // MARK: Board geometry

        private func buildBoard() {
            scene.background.contents = UIColor.clear

            let frame = SCNNode(geometry: SCNBox(width: 9, height: 0.1, length: 9, chamferRadius: 0))
            frame.geometry?.firstMaterial?.diffuse.contents = UIColor(white: 0.012, alpha: 1)
            frame.position = SCNVector3(3.5, -0.04, 3.5)
            scene.rootNode.addChildNode(frame)

            squareNodes = Array(repeating: Array(repeating: SCNNode(), count: 8), count: 8)
            let sqGeo = SCNBox(width: 0.88, height: 0.06, length: 0.88, chamferRadius: 0.02)
            for r in 0..<8 {
                for c in 0..<8 {
                    let node = SCNNode(geometry: sqGeo.copy() as! SCNGeometry)
                    node.name = "sq_\(r)_\(c)"
                    let mat = SCNMaterial()
                    mat.diffuse.contents  = UIColor(white: 0.02, alpha: 1)
                    mat.emission.contents = UIColor.black
                    mat.lightingModel     = .constant   // pure LED — emission is the whole color
                    node.geometry?.materials = [mat]
                    node.position = SCNVector3(Float(c), 0, Float(r))
                    scene.rootNode.addChildNode(node)
                    squareNodes[r][c] = node
                }
            }

            // Scene lights only affect pieces (squares use .constant)
            let ambient = SCNNode(); ambient.light = SCNLight()
            ambient.light!.type = .ambient
            ambient.light!.color = UIColor(red: 0.14, green: 0.17, blue: 0.28, alpha: 1)
            ambient.light!.intensity = 700
            scene.rootNode.addChildNode(ambient)

            let dir = SCNNode(); dir.light = SCNLight()
            dir.light!.type = .directional; dir.light!.color = UIColor.white
            dir.light!.intensity = 900; dir.position = SCNVector3(4, 12, 8)
            scene.rootNode.addChildNode(dir)

            let fill = SCNNode(); fill.light = SCNLight()
            fill.light!.type = .directional; fill.light!.color = UIColor.white
            fill.light!.intensity = 350; fill.position = SCNVector3(4, 6, 16)
            scene.rootNode.addChildNode(fill)

            let plR = SCNNode(); plR.light = SCNLight(); plR.light!.type = .omni
            plR.light!.intensity = 500; plR.position = SCNVector3(3.5, 3, 0)
            scene.rootNode.addChildNode(plR); pointLightR = plR

            let plL = SCNNode(); plL.light = SCNLight(); plL.light!.type = .omni
            plL.light!.intensity = 500; plL.position = SCNVector3(3.5, 3, 7)
            scene.rootNode.addChildNode(plL); pointLightL = plL

            let cam = SCNNode(); cam.camera = SCNCamera()
            cam.position = SCNVector3(3.5, 9, 13)
            cam.look(at: SCNVector3(3.5, 0, 3.5))
            scene.rootNode.addChildNode(cam)
        }

        // MARK: Update (called by SwiftUI on state changes)

        func update(board: Board?, teamR: Team, teamL: Team, currentTeam: Team?,
                    selected: Cell?, targets: [Cell], trails: [MoveTrail],
                    activeAnimation anim: MoveAnimation?, aiThinking: Bool) {

            // Update point lights to team colors
            pointLightR?.light?.color = UIColor(red: CGFloat(teamR.r)/255,
                                                green: CGFloat(teamR.g)/255,
                                                blue:  CGFloat(teamR.b)/255, alpha: 1)
            pointLightL?.light?.color = UIColor(red: CGFloat(teamL.r)/255,
                                                green: CGFloat(teamL.g)/255,
                                                blue:  CGFloat(teamL.b)/255, alpha: 1)

            // Snapshot state for tick()
            let active = currentTeam ?? teamR
            tickActiveColor = (CGFloat(active.r)/255, CGFloat(active.g)/255, CGFloat(active.b)/255)
            tickSelected   = selected
            tickTargets    = targets
            tickTrails     = trails
            tickAIThinking = aiThinking

            // Move animation — launch SCNAction arc when a new animation appears
            if let anim, anim.startTime != lastAnimStart {
                lastAnimStart = anim.startTime
                launchArc(anim, teamR: teamR)
            }

            // Rebuild piece nodes
            for r in 0..<8 {
                for c in 0..<8 {
                    pieceNodes[r][c]?.removeFromParentNode()
                    pieceNodes[r][c] = nil
                }
            }
            guard let board else { return }
            for r in 0..<8 {
                for c in 0..<8 {
                    guard let piece = board.grid[r][c] else { continue }
                    // Hide destination cell while the arc animation is in flight
                    if let anim, !anim.isComplete, anim.toRow == r, anim.toCol == c { continue }
                    placePiece(piece, row: r, col: c, isLight: piece.team == teamR)
                }
            }
            lastTeamR = teamR
        }

        private func placePiece(_ piece: Piece, row: Int, col: Int, isLight: Bool) {
            let mesh = templates[piece.typeName.lowercased()]?.clone() ?? makeFallback(type: piece.typeName)
            applyMaterial(mesh, isLight: isLight)
            let wrapper = SCNNode()
            wrapper.name = "piece_\(row)_\(col)"
            wrapper.addChildNode(mesh)
            wrapper.position = SCNVector3(Float(col), 0.03, Float(row))
            scene.rootNode.addChildNode(wrapper)
            pieceNodes[row][col] = wrapper
        }

        // MARK: Arc animation

        private func launchArc(_ anim: MoveAnimation, teamR: Team) {
            animatingPiece?.removeFromParentNode()

            let mesh = templates[anim.piece.lowercased()]?.clone() ?? makeFallback(type: anim.piece)
            applyMaterial(mesh, isLight: anim.team == teamR)

            let wrapper = SCNNode()
            wrapper.position = SCNVector3(Float(anim.fromCol), 0.03, Float(anim.fromRow))
            wrapper.addChildNode(mesh)
            scene.rootNode.addChildNode(wrapper)
            animatingPiece = wrapper

            let fc = Float(anim.fromCol), fr = Float(anim.fromRow)
            let tc = Float(anim.toCol),   tr = Float(anim.toRow)
            let dur = CGFloat(anim.duration)

            let arc = SCNAction.customAction(duration: anim.duration) { node, elapsed in
                let t = Double(elapsed / dur)
                let eased = 1 - pow(1 - t, 2)
                let x = fc + (tc - fc) * Float(eased)
                let z = fr + (tr - fr) * Float(eased)
                let y = 0.03 + 0.55 * Float(sin(t * .pi))  // arc up then down
                node.position = SCNVector3(x, y, z)
            }
            let finish = SCNAction.run { [weak self] node in
                node.removeFromParentNode()
                self?.animatingPiece = nil
            }
            wrapper.runAction(.sequence([arc, finish]))
        }

        // MARK: Materials

        private func applyMaterial(_ node: SCNNode, isLight: Bool) {
            node.enumerateChildNodes { child, _ in
                guard let geo = child.geometry else { return }
                let mat = SCNMaterial()
                if isLight {
                    mat.diffuse.contents   = UIColor(white: 0.92, alpha: 1)
                    mat.roughness.contents = 0.45
                    mat.metalness.contents = 0.08
                } else {
                    mat.diffuse.contents   = UIColor(white: 0.10, alpha: 1)
                    mat.roughness.contents = 0.35
                    mat.metalness.contents = 0.55
                }
                mat.emission.contents = UIColor.black
                mat.lightingModel     = .physicallyBased
                geo.firstMaterial     = mat
            }
        }

        // MARK: Procedural fallback

        private func makeFallback(type: String) -> SCNNode {
            let g = SCNNode()
            switch type {
            case "Pawn":
                g.addChildNode(cyl(r0: 0.13, r1: 0.18, h: 0.12, y: 0.06))
                g.addChildNode(sph(r: 0.17, y: 0.28))
            case "Rook":
                g.addChildNode(cyl(r0: 0.17, r1: 0.22, h: 0.16, y: 0.08))
                g.addChildNode(cyl(r0: 0.14, r1: 0.20, h: 0.52, y: 0.26))
            case "Knight":
                g.addChildNode(cyl(r0: 0.17, r1: 0.22, h: 0.16, y: 0.08))
                let head = SCNNode(geometry: SCNBox(width: 0.28, height: 0.24,
                                                    length: 0.14, chamferRadius: 0.04))
                head.position = SCNVector3(0.04, 0.38, 0); head.eulerAngles.x = -0.4
                g.addChildNode(head)
            case "Bishop":
                g.addChildNode(cyl(r0: 0.20, r1: 0.23, h: 0.42, y: 0.21))
                g.addChildNode(sph(r: 0.10, y: 0.50))
                g.addChildNode(cone(r: 0.04, h: 0.10, y: 0.65))
            case "Queen":
                g.addChildNode(cyl(r0: 0.20, r1: 0.26, h: 0.62, y: 0.31))
                let tn = SCNNode(geometry: SCNTorus(ringRadius: 0.18, pipeRadius: 0.04))
                tn.position = SCNVector3(0, 0.66, 0); g.addChildNode(tn)
                g.addChildNode(sph(r: 0.10, y: 0.80))
            case "King":
                g.addChildNode(cyl(r0: 0.20, r1: 0.26, h: 0.70, y: 0.35))
                let v = SCNNode(geometry: SCNBox(width: 0.08, height: 0.24, length: 0.08, chamferRadius: 0))
                v.position = SCNVector3(0, 0.87, 0); g.addChildNode(v)
                let h = SCNNode(geometry: SCNBox(width: 0.22, height: 0.08, length: 0.08, chamferRadius: 0))
                h.position = SCNVector3(0, 0.90, 0); g.addChildNode(h)
            default: break
            }
            return g
        }

        private func cyl(r0: Float, r1: Float, h: Float, y: Float) -> SCNNode {
            let geo = SCNCylinder(radius: CGFloat((r0 + r1) / 2), height: CGFloat(h))
            geo.radialSegmentCount = 48
            return geo.node(y: y)
        }
        private func sph(r: Float, y: Float) -> SCNNode {
            let geo = SCNSphere(radius: CGFloat(r)); geo.segmentCount = 32
            return geo.node(y: y)
        }
        private func cone(r: Float, h: Float, y: Float) -> SCNNode {
            let geo = SCNCone(topRadius: 0, bottomRadius: CGFloat(r), height: CGFloat(h))
            geo.radialSegmentCount = 48
            return geo.node(y: y)
        }
    }
}

private extension SCNGeometry {
    func node(y: Float) -> SCNNode {
        let n = SCNNode(geometry: self); n.position = SCNVector3(0, y, 0); return n
    }
}
#endif
