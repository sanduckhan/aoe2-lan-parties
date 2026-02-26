from functools import wraps

from flask import Flask, Response, jsonify, render_template, request

from analyzer_lib import config
from web import services

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50 MB


# --- CORS ---


@app.after_request
def add_cors_headers(response):
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type, X-API-Key"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    return response


# --- Auth ---


def require_api_key(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not config.API_KEY:
            return jsonify({"error": "API key not configured"}), 503
        key = request.headers.get("X-API-Key", "")
        if key != config.API_KEY:
            return jsonify({"error": "Invalid API key"}), 401
        return f(*args, **kwargs)

    return decorated


# --- Read-only endpoints (no auth) ---


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/players")
def api_players():
    try:
        return jsonify(services.get_players_for_api())
    except FileNotFoundError:
        return jsonify({"error": "No player ratings found. Run main.py first."}), 404


@app.route("/api/teams/generate", methods=["POST"])
def api_generate_teams():
    data = request.get_json()
    if not data or "players" not in data:
        return jsonify({"error": "Request must include 'players' array"}), 400

    player_names = data["players"]
    if len(player_names) < 2:
        return jsonify({"error": "Need at least 2 players"}), 400

    top_n = data.get("top_n", 3)
    result = services.generate_teams(player_names, top_n)

    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


@app.route("/api/teams/rebalance", methods=["POST"])
def api_rebalance_teams():
    data = request.get_json()
    if not data:
        return jsonify({"error": "Request body required"}), 400

    team1 = data.get("team1", [])
    team2 = data.get("team2", [])
    weaker_team = data.get("weaker_team")

    if not team1 or not team2:
        return jsonify({"error": "Both team1 and team2 are required"}), 400
    if weaker_team not in (1, 2):
        return jsonify({"error": "weaker_team must be 1 or 2"}), 400

    top_n = data.get("top_n", 5)
    result = services.rebalance_teams(team1, team2, weaker_team, top_n)

    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


@app.route("/api/lan-events")
def api_lan_events():
    try:
        return jsonify(services.get_lan_events_for_api())
    except FileNotFoundError:
        return jsonify([])


@app.route("/api/awards")
def api_awards():
    event_id = request.args.get("event_id")
    if event_id:
        try:
            awards = services.compute_event_awards(event_id)
            if awards is None:
                return jsonify({"error": "LAN event not found"}), 404
            return jsonify(awards)
        except FileNotFoundError:
            return (
                jsonify({"error": "Game registry not found. Run main.py first."}),
                404,
            )
    try:
        return jsonify(services.get_awards_for_api())
    except FileNotFoundError:
        return jsonify({"error": "No analysis data found. Run main.py first."}), 404


@app.route("/api/games")
def api_games():
    try:
        return jsonify(services.get_games_for_api())
    except FileNotFoundError:
        return jsonify({"error": "No analysis data found. Run main.py first."}), 404


@app.route("/api/games/<sha256>/detail")
def api_game_detail(sha256):
    try:
        detail = services.get_game_detail_for_api(sha256)
        if detail is None:
            return jsonify({"error": "Game not found"}), 404
        return jsonify(detail)
    except FileNotFoundError:
        return jsonify({"error": "Game registry not found. Run main.py first."}), 404


@app.route("/api/games/<sha256>/download")
def api_game_download(sha256):
    result = services.get_replay_download(sha256)
    if result is None:
        return jsonify({"error": "Replay file not found"}), 404
    file_bytes, filename = result
    return Response(
        file_bytes,
        mimetype="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.route("/api/stats")
def api_stats():
    try:
        return jsonify(services.get_stats_for_api())
    except FileNotFoundError:
        return jsonify({"error": "No analysis data found. Run main.py first."}), 404


@app.route("/api/player/<name>")
def api_player_profile(name):
    try:
        profile = services.get_player_profile_for_api(name)
        if profile is None:
            return jsonify({"error": f"Player '{name}' not found"}), 404
        return jsonify(profile)
    except FileNotFoundError:
        return jsonify({"error": "No analysis data found. Run main.py first."}), 404


@app.route("/api/rating-history")
def api_rating_history():
    try:
        return jsonify(services.get_rating_history_for_api())
    except FileNotFoundError:
        return jsonify({"error": "No rating history found. Run main.py first."}), 404


# --- Write endpoints (API key required) ---


@app.route("/api/upload", methods=["POST"])
@require_api_key
def api_upload():
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    sha256 = request.form.get("sha256", "").strip()
    if not sha256:
        return jsonify({"error": "sha256 field is required"}), 400

    file_bytes = file.read()
    result = services.process_upload(file_bytes, sha256)

    if "error" in result:
        return jsonify(result), 400
    if result.get("status") == "duplicate":
        return (
            jsonify({"status": "duplicate", "message": "Game already processed"}),
            409,
        )
    return jsonify(result), 200


@app.route("/api/rebuild", methods=["POST"])
@require_api_key
def api_rebuild():
    result = services.trigger_rebuild()
    if "error" in result:
        return jsonify(result), 500
    return jsonify(result), 200


@app.route("/api/rebuild/status")
@require_api_key
def api_rebuild_status():
    return jsonify(services.get_rebuild_status()), 200
