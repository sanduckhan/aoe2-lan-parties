import os
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
sys.path.append(PROJECT_ROOT)

from analyzer_lib import config, db

FLOOR_RATING = 700  # Target: no one should play below this effective rating
ELO_PER_STEP = 300  # 300 rating deficit = 5% handicap
HC_STEP = 5


def round_to_nearest_5(value):
    return int(round(value / HC_STEP) * HC_STEP)


def recommended_handicap(rating, current_avg_hc):
    deficit = max(0, FLOOR_RATING - rating)
    if deficit == 0:
        return round_to_nearest_5(current_avg_hc)
    increments = deficit / ELO_PER_STEP
    bump = round(increments) * HC_STEP
    return min(200, max(100, round_to_nearest_5(current_avg_hc + bump)))


def print_table(players, label=None):
    if label:
        print(f"\n{label}")
    print(
        f"  {'Player':<22} {'Rating':>7}  {'Avg HC (30g)':>12}  {'Rec. HC':>7}  {'Games':>5}  {'Confidence':>10}"
    )
    print(f"  {'-'*72}")
    for r in players:
        avg_hc = r.get("avg_handicap_last_30", 100)
        avg_str = f"{avg_hc:.0f}%" if avg_hc > 100 else "100%"
        rec = recommended_handicap(r["mu_scaled"], avg_hc)
        rec_str = f"{rec}%"
        print(
            f"  {r['name']:<22} {r['mu_scaled']:>7.0f}  {avg_str:>12}  {rec_str:>7}  {r['games_played']:>5}  {r['confidence_percent']:>9.1f}%"
        )


def main():
    db_path = db.get_db_path(config.DATA_DIR)
    ratings = db.load_player_ratings(db_path)
    if not ratings:
        print("Error: No player ratings found in database. Run main.py first.")
        sys.exit(1)

    # Optional: filter to specific players
    player_filter = sys.argv[1:]
    if player_filter:
        filter_lower = {n.lower() for n in player_filter}
        filtered = [r for r in ratings if r["name"].lower() in filter_lower]
        missing = filter_lower - {r["name"].lower() for r in filtered}
        if missing:
            print(f"Warning: players not found in ratings: {', '.join(missing)}")
        ratings = filtered if filtered else ratings

    ranked = [r for r in ratings if r["games_played"] >= config.MIN_GAMES_FOR_RANKING]
    provisional = [
        r for r in ratings if r["games_played"] < config.MIN_GAMES_FOR_RANKING
    ]

    ranked.sort(key=lambda r: r["mu_scaled"], reverse=True)
    provisional.sort(key=lambda r: r["mu_scaled"], reverse=True)

    print(
        f"\n--- Player Ratings & Handicap (floor: {FLOOR_RATING}, rule: 5% per {ELO_PER_STEP} rating below floor) ---"
    )
    print_table(ranked)

    if provisional:
        print_table(
            provisional,
            label=f"--- Provisional (< {config.MIN_GAMES_FOR_RANKING} games) ---",
        )

    print()


if __name__ == "__main__":
    main()
