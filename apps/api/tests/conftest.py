import sys
from pathlib import Path

# Ensure the API app directory is in sys.path
api_dir = Path(__file__).resolve().parents[1]
if str(api_dir) not in sys.path:
    sys.path.insert(0, str(api_dir))
