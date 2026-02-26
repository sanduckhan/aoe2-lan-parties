"""Shared replay file utilities for AoE2 recorded games."""

import re
from datetime import datetime


def get_datetime_from_filename(filename):
    """Extract datetime from replay filename for chronological sorting."""
    match = re.search(r"@(\d{4}\.\d{2}\.\d{2} \d{6})", filename)
    if match:
        try:
            return datetime.strptime(match.group(1), "%Y.%m.%d %H%M%S")
        except ValueError:
            return datetime.min
    return datetime.min
