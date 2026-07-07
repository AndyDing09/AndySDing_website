"""Make ``src`` importable when running pytest from this directory."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
