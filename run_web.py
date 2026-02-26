#!/usr/bin/env python3
import os

from dotenv import load_dotenv

load_dotenv()  # Load .env file if present (local dev only)

from web.app import app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5050))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
