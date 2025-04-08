import sys
import os

# Add your project directory to the sys.path
path = "/home/yourusername/gov_monitor"
if path not in sys.path:
    sys.path.insert(0, path)

# Set the environment variable to tell Flask where to find the application
os.environ["FLASK_APP"] = "app"

# Import your Flask application
from app import app as application
