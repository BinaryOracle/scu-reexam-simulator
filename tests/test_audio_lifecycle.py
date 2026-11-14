"""Run frontend audio lifecycle regressions without microphone or external AI."""
from pathlib import Path
import shutil
import subprocess
import pytest


def test_detached_asr_results_never_reach_a_replacement_interview():
    node = shutil.which('node')
    if not node:
        pytest.skip('Node.js is required for frontend audio lifecycle checks')
    result = subprocess.run([node, '--experimental-vm-modules', 'tests/session_audio_lifecycle.mjs'],
                            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
