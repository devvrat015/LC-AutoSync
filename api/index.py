import sys
from pathlib import Path

service_dir = Path(__file__).resolve().parent.parent / "service"
sys.path.insert(0, str(service_dir))

from app import app