"""
test_python_bridge.py — unit tests for harness/python_bridge.py JsBridge.

All tests mock subprocess.Popen so no real Node.js process is required.
Covers:
  - close() calling stdin.close (line 46)
  - __exit__ calling close (line 49)
  - _call() raising when the subprocess returns an empty line (lines 61-64)
  - ping() raising RuntimeError on an error response (line 72)
  - decode_frame() raising RuntimeError on an error response (line 97)
"""
from __future__ import annotations

import json
import pytest
from unittest.mock import MagicMock, patch


def _mock_proc(stdout_lines=None, stderr_output=b""):
    """Build a MagicMock simulating a subprocess.Popen return value."""
    proc = MagicMock()
    proc.stdin = MagicMock()
    if stdout_lines is not None:
        proc.stdout.readline.side_effect = [
            line if isinstance(line, bytes) else line.encode()
            for line in stdout_lines
        ]
    proc.stderr.read.return_value = stderr_output
    return proc


class TestJsBridgeClose:
    def test_close_closes_stdin(self):
        # Covers line 46: self._proc.stdin.close()
        proc = _mock_proc(stdout_lines=[])
        with patch("subprocess.Popen", return_value=proc):
            from harness.python_bridge import JsBridge
            bridge = JsBridge()
            bridge.close()
        proc.stdin.close.assert_called_once()

    def test_context_manager_calls_close(self):
        # Covers line 49: self.close() called from __exit__
        proc = _mock_proc(stdout_lines=[])
        with patch("subprocess.Popen", return_value=proc):
            from harness.python_bridge import JsBridge
            with JsBridge():
                pass
        proc.stdin.close.assert_called_once()


class TestJsBridgeCall:
    def test_call_raises_when_bridge_dies_with_stderr(self):
        # Covers lines 61-64: empty readline → RuntimeError with stderr text.
        proc = _mock_proc(stdout_lines=[b""], stderr_output=b"node crashed")
        with patch("subprocess.Popen", return_value=proc):
            from harness.python_bridge import JsBridge
            bridge = JsBridge()
            with pytest.raises(RuntimeError, match="JS bridge died"):
                bridge._call({"op": "ping"})

    def test_call_raises_includes_stderr_in_message(self):
        proc = _mock_proc(stdout_lines=[b""], stderr_output=b"fatal: bad module")
        with patch("subprocess.Popen", return_value=proc):
            from harness.python_bridge import JsBridge
            bridge = JsBridge()
            with pytest.raises(RuntimeError) as exc_info:
                bridge._call({"op": "test"})
            assert "fatal: bad module" in str(exc_info.value)


class TestJsBridgePing:
    def test_ping_raises_on_error_response(self):
        # Covers line 72: raise RuntimeError(resp["error"])
        error_resp = json.dumps({"error": "unknown op"}).encode() + b"\n"
        proc = _mock_proc(stdout_lines=[error_resp])
        with patch("subprocess.Popen", return_value=proc):
            from harness.python_bridge import JsBridge
            bridge = JsBridge()
            with pytest.raises(RuntimeError, match="unknown op"):
                bridge.ping()

    def test_ping_returns_result_on_success(self):
        ok_resp = json.dumps({"result": "pong"}).encode() + b"\n"
        proc = _mock_proc(stdout_lines=[ok_resp])
        with patch("subprocess.Popen", return_value=proc):
            from harness.python_bridge import JsBridge
            bridge = JsBridge()
            assert bridge.ping() == "pong"


class TestJsBridgeDecodeFrame:
    def test_decode_frame_raises_on_error_response(self):
        # Covers line 97: raise RuntimeError(resp["error"])
        error_resp = json.dumps({"error": "decode failed"}).encode() + b"\n"
        proc = _mock_proc(stdout_lines=[error_resp])
        with patch("subprocess.Popen", return_value=proc):
            from harness.python_bridge import JsBridge
            bridge = JsBridge()
            with pytest.raises(RuntimeError, match="decode failed"):
                bridge.decode_frame(b"\x00" * 4, 1, 1)

    def test_decode_frame_returns_none_on_null_result(self):
        null_resp = json.dumps({"result": None}).encode() + b"\n"
        proc = _mock_proc(stdout_lines=[null_resp])
        with patch("subprocess.Popen", return_value=proc):
            from harness.python_bridge import JsBridge
            bridge = JsBridge()
            result = bridge.decode_frame(b"\x00" * 4, 1, 1)
            assert result is None
