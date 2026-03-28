load("@gazelle//:def.bzl", "gazelle")
load("@rules_python//gazelle:def.bzl", "GAZELLE_PYTHON_RUNTIME_DEPS")
load("@rules_python//python:defs.bzl", "py_binary", "py_library")

# gazelle:python_root
# gazelle:exclude .venv
# gazelle:exclude bazel-*
# gazelle:exclude include (trash)
# gazelle:exclude python_from_the_pi_sorry_messy
# gazelle:exclude PiControl
# gazelle:exclude arduinoConfig
# gazelle:exclude ArduinoTests
# gazelle:exclude FinalArduinoCode
# gazelle:exclude RowControl
# gazelle:exclude Chess Pieces
# gazelle:exclude deploy
# gazelle:exclude __pycache__
# gazelle:exclude tools
# gazelle:exclude plans

# ── pip resolve directives ───────────────────────────────────────────────────
# gazelle:resolve py numpy @pip//numpy
# gazelle:resolve py numpy.typing @pip//numpy
# gazelle:resolve py pygame @pip//pygame
# gazelle:resolve py pygame.event @pip//pygame
# gazelle:resolve py pygame.font @pip//pygame
# gazelle:resolve py pygame.time @pip//pygame
# gazelle:resolve py pygame.display @pip//pygame
# gazelle:resolve py websockets @pip//websockets
# gazelle:resolve py websockets.sync @pip//websockets
# gazelle:resolve py websockets.sync.client @pip//websockets
# gazelle:resolve py websockets.asyncio @pip//websockets
# gazelle:resolve py websockets.asyncio.server @pip//websockets
# gazelle:resolve py websockets.exceptions @pip//websockets
# gazelle:resolve py websockets.frames @pip//websockets
# gazelle:resolve py websockets.server @pip//websockets
# gazelle:resolve py websockets.serve @pip//websockets
# gazelle:resolve py zeroconf @pip//zeroconf
# gazelle:resolve py cv2 @pip//opencv_python
# gazelle:resolve py chessmatrix @pip//chessmatrix
# gazelle:resolve py pytest @pip//pytest
# gazelle:resolve py pygments @pip//pygments

# ── Pi-only hardware deps — not installable on Mac ──────────────────────────
# gazelle:resolve py smbus //hardware
# gazelle:resolve py RPi //hardware
# gazelle:resolve py RPi.GPIO //hardware

# ── Tools resolves ───────────────────────────────────────────────────────────
# gazelle:resolve py debug_quad_detection //tools
# gazelle:resolve py debug_quad_detection._run_pipeline //tools
# gazelle:resolve py debug_quad_detection._get_outer_corners //tools
# gazelle:resolve py debug_quad_detection._get_oriented_color //tools
# gazelle:resolve py debug_quad_detection._cell_center_px //tools
# gazelle:resolve py debug_quad_detection._sample_cell_bgr //tools
# gazelle:resolve py debug_quad_detection._color_calibrate_image //tools
# gazelle:resolve py debug_quad_detection.decode_oriented //tools

# ── Harness resolves (sys.path-based imports in fuzzer scripts) ──────────────
# gazelle:resolve py python_bridge //harness:python_bridge
# gazelle:resolve py python_bridge.JsBridge //harness:python_bridge

# ── Internal cross-package resolves ──────────────────────────────────────────
# gazelle:resolve py hardware //hardware
# gazelle:resolve py hardware.master //hardware
# gazelle:resolve py hardware.master.Master //hardware
# gazelle:resolve py hardware.sensor //hardware
# gazelle:resolve py hardware.sensor.BoardSensor //hardware
# gazelle:resolve py hardware.led_matrix //hardware
# gazelle:resolve py samplebase //:Chess101
# gazelle:resolve py samplebase.SampleBase //:Chess101
# gazelle:resolve py rgbmatrix //rgbmatrix
# gazelle:resolve py rgbmatrix.core //rgbmatrix

gazelle(
    name = "gazelle",
    gazelle = "@rules_python_gazelle_plugin//python:gazelle_binary",
)

py_binary(
    name = "GameManager",
    srcs = ["GameManager.py"],
    visibility = ["//:__subpackages__"],
    deps = [
        "//game",
        "//network",
    ],
)

py_binary(
    name = "grid",
    srcs = ["grid.py"],
    visibility = ["//:__subpackages__"],
    deps = ["//:Chess101"],
)

py_binary(
    name = "run_simulator",
    srcs = ["run_simulator.py"],
    visibility = ["//:__subpackages__"],
    deps = [
        "//network",
        "//simulator",
    ],
)

py_library(
    name = "Chess101",
    srcs = [
        "AI.py",
        "Bishop.py",
        "Cell.py",
        "King.py",
        "Knight.py",
        "Pawn.py",
        "Piece.py",
        "Queen.py",
        "Rook.py",
        "Team.py",
        "Tree.py",
        "constants.py",
        "samplebase.py",
    ],
    visibility = ["//:__subpackages__"],
    deps = [
        "//ai",
        "//core",
        "//pieces",
        "//rgbmatrix",
    ],
)
