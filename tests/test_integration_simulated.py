"""Regression tests of the unchanged V4.3 SafeSync logic (simulated server)."""
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from test_v43 import test_safe
import skylanders_virtport_live as live

class SafeSyncTests(unittest.TestCase):
    def test_regression(self):
        test_safe()
    def test_virtport_fake_server(self):
        live.self_test()

if __name__ == '__main__': unittest.main()
