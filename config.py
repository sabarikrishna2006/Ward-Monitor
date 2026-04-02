"""Ward Monitor Configuration."""
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATABASE = os.path.join(BASE_DIR, 'data', 'ward.db')
SECRET_KEY = 'ward-monitor-dev-key'
DEBUG = True
