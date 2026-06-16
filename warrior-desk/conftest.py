"""Make the ``warrior`` package importable when running pytest from this dir."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
