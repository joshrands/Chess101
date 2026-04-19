"""Hardware-In-The-Loop testing infrastructure for Chess101.

Provides mock hardware (HilSensor, HilRGBMatrix) and a WebSocket control
interface (ControlServer) so the Pi game code can run in a Docker container
with external test control.
"""
