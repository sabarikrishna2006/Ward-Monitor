"""
Ward Monitor — Clinical Decision Support Dashboard
Flask application entry point.
"""
import os
from flask import Flask
from config import SECRET_KEY, DEBUG
from utils.db import init_db


def create_app():
    app = Flask(__name__)
    app.secret_key = SECRET_KEY
    app.debug = DEBUG

    # Initialize database on first run
    init_db()

    # Register blueprints
    from modules.dashboard import dashboard_bp
    from modules.alerts import alerts_bp
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(alerts_bp)

    return app


if __name__ == '__main__':
    app = create_app()
    print("\n[+] Ward Monitor -- Clinical Decision Support")
    print("=" * 50)
    app.run(host='0.0.0.0', port=5001, debug=True, use_reloader=False)
