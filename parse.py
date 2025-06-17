import json
import os
from mgz.model import parse_match, serialize

RECORDED_GAMES_DIR = 'recorded_games'

# Ensure the directory exists
if not os.path.isdir(RECORDED_GAMES_DIR):
    print(f"Error: Directory '{RECORDED_GAMES_DIR}' not found.")
    exit()

for filename in os.listdir(RECORDED_GAMES_DIR):
    file_path = os.path.join(RECORDED_GAMES_DIR, filename)
    # Process only files, skip directories
    if os.path.isfile(file_path):
        print(f"Processing: {file_path}")
        try:
            with open(file_path, 'rb') as f:
                match = parse_match(f)
            print(json.dumps(serialize(match), indent=2))
            print(f"Successfully processed: {file_path}")
        except Exception as e:
            print(f"Error processing file {file_path}: {e}")
        print("---")

print("Finished processing all files.")
