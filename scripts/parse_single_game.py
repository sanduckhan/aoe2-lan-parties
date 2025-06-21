import json
import os
import argparse
from mgz.model import parse_match, serialize

def main():
    parser = argparse.ArgumentParser(description='Parse a single Age of Empires II recorded game file and save its content to a JSON file.')
    parser.add_argument('input_file', help='Path to the .aoe2record input file.')
    parser.add_argument('output_file', help='Path to the .json output file.')

    args = parser.parse_args()

    input_path = args.input_file
    output_path = args.output_file

    if not os.path.isfile(input_path):
        print(f"Error: Input file not found at '{input_path}'")
        return

    # Ensure output directory exists
    output_dir = os.path.dirname(output_path)
    if output_dir and not os.path.exists(output_dir):
        try:
            os.makedirs(output_dir)
            print(f"Created output directory: {output_dir}")
        except OSError as e:
            print(f"Error creating output directory {output_dir}: {e}")
            return

    print(f"Processing: {input_path}")
    try:
        with open(input_path, 'rb') as f:
            match_data = parse_match(f)
        
        serialized_data = serialize(match_data)
        
        with open(output_path, 'w') as outfile:
            json.dump(serialized_data, outfile, indent=2)
        
        print(f"Successfully processed and saved to: {output_path}")

    except FileNotFoundError:
        print(f"Error: Input file disappeared during processing: '{input_path}'")
    except Exception as e:
        print(f"Error processing file {input_path}: {e}")

if __name__ == '__main__':
    main()