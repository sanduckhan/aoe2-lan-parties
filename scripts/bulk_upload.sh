#!/usr/bin/env bash
# Bulk upload all replays to production server.
# Usage: ./scripts/bulk_upload.sh

SERVER="https://aoe2-lan-parties-production.up.railway.app"
API_KEY="wTjtVhDf2tN6xpvowVXGHOvJ9SU9GgoP6"
REPLAY_DIR="recorded_games"

TOTAL=$(ls "$REPLAY_DIR"/*.aoe2record 2>/dev/null | wc -l | tr -d ' ')
echo "=== Uploading $TOTAL replays to $SERVER ==="

i=0
ok=0
dup=0
err=0

for f in "$REPLAY_DIR"/*.aoe2record; do
    i=$((i + 1))
    SHA=$(shasum -a 256 "$f" | cut -d' ' -f1)
    BASENAME=$(basename "$f")

    RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "$SERVER/api/upload" \
        -F "file=@$f" \
        -F "sha256=$SHA" \
        -H "X-API-Key: $API_KEY" \
        --max-time 120)

    HTTP_CODE=$(echo "$RESPONSE" | tail -1)
    BODY=$(echo "$RESPONSE" | sed '$d')

    if [ "$HTTP_CODE" = "200" ]; then
        ok=$((ok + 1))
        STATUS=$(echo "$BODY" | python3 -c "import sys,json; print(json.load(sys.stdin).get('status','?'))" 2>/dev/null)
        echo "[$i/$TOTAL] OK ($STATUS): $BASENAME"
    elif [ "$HTTP_CODE" = "409" ]; then
        dup=$((dup + 1))
        echo "[$i/$TOTAL] DUP: $BASENAME"
    else
        err=$((err + 1))
        echo "[$i/$TOTAL] ERR ($HTTP_CODE): $BASENAME"
        echo "  $BODY"
    fi
done

echo ""
echo "=== DONE ==="
echo "  Processed: $ok"
echo "  Duplicate: $dup"
echo "  Errors:    $err"
echo "  Total:     $i"
