import os
import json
from datetime import timedelta
from mgz.summary import Summary

# --- Configuration ---
RECORDED_GAMES_DIR = 'recorded_games'
OUTPUT_FILE = 'debug_summary_output.json'

def build_serializable_dict(obj, visited=None):
    """Recursively build a dictionary from an object, handling circular references."""
    if visited is None:
        visited = set()

    if id(obj) in visited:
        return "<circular reference>"

    if isinstance(obj, (int, str, bool, float, type(None))):
        return obj
    if isinstance(obj, timedelta):
        return str(obj)

    visited.add(id(obj))

    if isinstance(obj, (list, tuple, set)):
        result = [build_serializable_dict(item, visited) for item in obj]
    elif isinstance(obj, dict):
        result = {str(k): build_serializable_dict(v, visited) for k, v in obj.items()}
    elif hasattr(obj, '__dict__'):
        result = {key: build_serializable_dict(value, visited) for key, value in obj.__dict__.items() if not key.startswith('_')}
    else:
        try:
            result = str(obj)
        except Exception:
            result = f"<unhandled type: {type(obj).__name__}>"
    
    visited.remove(id(obj))
    return result

def dump_full_summary_object():
    """Parses the first valid game and writes the entire summary object to a JSON file."""
    if not os.path.isdir(RECORDED_GAMES_DIR):
        print(f"Error: Directory '{RECORDED_GAMES_DIR}' not found.")
        return

    first_game_file = None
    for filename in sorted(os.listdir(RECORDED_GAMES_DIR)):
        if filename.endswith(('.aoe2record', '.mgz', '.mgx')):
            first_game_file = filename
            break
    
    if not first_game_file:
        print("No replay file found in 'recorded_games' directory.")
        return

    file_path = os.path.join(RECORDED_GAMES_DIR, first_game_file)
    print(f"Dumping full summary object for: {file_path}")

    with open(file_path, 'rb') as f, open(OUTPUT_FILE, 'w') as out:
        try:
            summary = Summary(f)
            summary_dict = build_serializable_dict(summary)
            json.dump(summary_dict, out, indent=4)
            print(f"Full summary object successfully written to {OUTPUT_FILE}")
        except Exception as e:
            print(f"An error occurred: {e}")
            out.write(f'{{"error": "An error occurred during parsing: {e}"}}')

if __name__ == "__main__":
    dump_full_summary_object()
