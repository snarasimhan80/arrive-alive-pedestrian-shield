"""Compatibility entry point; the maintained source packager is in scripts/."""
from pathlib import Path
import runpy
runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/build_source.py'), run_name='__main__')
