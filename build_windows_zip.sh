#!/bin/bash
# Builds a zip file with only the files needed for the Windows web UI

set -e

ZIP_NAME="aoe2-lan-party-web.zip"
rm -f "$ZIP_NAME"

zip "$ZIP_NAME" \
    run_web.py \
    start.bat \
    requirements-web.txt \
    player_ratings.json \
    analyzer_lib/__init__.py \
    analyzer_lib/config.py \
    web/__init__.py \
    web/app.py \
    web/services.py \
    web/templates/index.html \
    web/static/app.js \
    web/static/style.css \
    scripts/team_balancer.py \
    scripts/handicap_recommender.py

echo ""
echo "Created $ZIP_NAME"
echo "Copy this file to the Windows machine, extract it, and double-click start.bat"
