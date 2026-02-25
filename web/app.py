from flask import Flask, jsonify, render_template, request

from web import services

app = Flask(__name__)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/players")
def api_players():
    try:
        return jsonify(services.get_players_for_api())
    except FileNotFoundError:
        return jsonify({"error": "player_ratings.json not found. Run calculate_trueskill.py first."}), 404


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


@app.route("/api/awards")
def api_awards():
    try:
        return jsonify(services.get_awards_for_api())
    except FileNotFoundError:
        return jsonify({"error": "analysis_data.json not found. Run main.py first."}), 404


@app.route("/api/games")
def api_games():
    try:
        return jsonify(services.get_games_for_api())
    except FileNotFoundError:
        return jsonify({"error": "analysis_data.json not found. Run main.py first."}), 404


@app.route("/api/stats")
def api_stats():
    try:
        return jsonify(services.get_stats_for_api())
    except FileNotFoundError:
        return jsonify({"error": "analysis_data.json not found. Run main.py first."}), 404


@app.route("/api/player/<name>")
def api_player_profile(name):
    try:
        profile = services.get_player_profile_for_api(name)
        if profile is None:
            return jsonify({"error": f"Player '{name}' not found"}), 404
        return jsonify(profile)
    except FileNotFoundError:
        return jsonify({"error": "analysis_data.json not found. Run main.py first."}), 404


@app.route("/api/rating-history")
def api_rating_history():
    try:
        return jsonify(services.get_rating_history_for_api())
    except FileNotFoundError:
        return jsonify({"error": "rating_history.json not found. Run calculate_trueskill.py first."}), 404
