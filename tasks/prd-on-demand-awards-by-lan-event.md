# PRD: On-Demand Awards by LAN Event

## Introduction

The AoE2 LAN Party Analyzer currently computes awards (Hall of Fame) across all games ever played. This PRD adds the ability to view awards scoped to a specific LAN event, with LAN events auto-detected from game date clusters. A dropdown in the "Hall of Fame" tab lets users switch between "All Time" and any detected LAN event, and the awards are recomputed on the fly for the selected scope.

LAN events are already detected by `detect_lan_events()` in `calculate_trueskill.py` and stored in `rating_history.json`. This PRD builds on that existing detection to expose events via API, compute scoped awards from registry data, and add the UI selector.

## Goals

- Expose auto-detected LAN events via a new API endpoint
- Compute awards for any specific LAN event by filtering registry data to that event's date range
- Add an event selector dropdown to the "Hall of Fame" tab in the web UI
- Keep "All Time" as the default view, using pre-computed data from `analysis_data.json`
- Awards for a specific event are computed on demand (not pre-cached) since there are few events and computation is fast

## User Stories

### US-001: List LAN events via API
**Description:** As a web UI user, I want to see a list of detected LAN events so that I can choose which event's awards to view.

**Acceptance Criteria:**
- [ ] `GET /api/lan-events` returns a JSON array of LAN event objects
- [ ] Each event has: `id` (string, e.g., `"lan-2025-11-07"`), `label` (e.g., `"LAN 07 Nov 25"`), `start_date`, `end_date`, `num_games`
- [ ] Event `id` is derived from the start date: `"lan-{start_date}"` (e.g., `"lan-2025-11-07"`)
- [ ] Events are sorted by start date descending (most recent first)
- [ ] Returns empty array if no LAN events detected

### US-002: Compute awards for a specific LAN event
**Description:** As a web UI user, I want to view awards scoped to a specific LAN event so that I can see who was the Market Mogul or Bitter Salt Baron at each particular gathering.

**Acceptance Criteria:**
- [ ] `GET /api/awards?event_id=lan-2025-11-07` returns awards computed only from games in that event's date range
- [ ] `GET /api/awards` (no `event_id` param) returns all-time awards from `analysis_data.json` (existing behavior preserved)
- [ ] Scoped awards use the same JSON structure as all-time awards (all 8 award categories)
- [ ] If `event_id` is not found, returns 404 with `{"error": "LAN event not found"}`
- [ ] Awards are computed on the fly from registry data (not pre-cached)

### US-003: Add event selector to Hall of Fame UI
**Description:** As a web UI user, I want a dropdown at the top of the Hall of Fame tab to switch between "All Time" and specific LAN events.

**Acceptance Criteria:**
- [ ] A `<select>` dropdown appears at the top of the Hall of Fame section, styled consistently with the existing dark medieval theme
- [ ] First option is "All Time" (default selected)
- [ ] Subsequent options are LAN events, most recent first, labeled with their `label` field (e.g., "LAN 07 Nov 25")
- [ ] Changing the dropdown selection fetches awards for the selected scope and re-renders the awards grid
- [ ] Loading state is shown while fetching scoped awards
- [ ] Verify in browser that the dropdown and re-rendering work correctly

### US-004: Service layer for event-scoped awards
**Description:** As the server, I want a service function that computes awards from registry data filtered to a date range so that any event can be computed on demand.

**Acceptance Criteria:**
- [ ] New function `get_lan_events_for_api()` in `web/services.py` that reads LAN events from `rating_history.json` and adds stable `id` fields
- [ ] New function `compute_event_awards(event_id)` in `web/services.py` that:
  1. Looks up the event's date range from LAN events data
  2. Filters `game_registry.json` to games within that range (by `datetime` field)
  3. Reconstructs `player_stats` and `game_stats` from the filtered games' stored metadata and `player_deltas`
  4. Calls `compute_all_awards()` from `report_generator.py`
  5. Returns the awards dict
- [ ] Returns `None` if event_id not found

## Functional Requirements

- FR-1: New route `GET /api/lan-events` in `web/app.py`. No authentication required. Calls `services.get_lan_events_for_api()`.
- FR-2: Modify existing `GET /api/awards` route to accept optional `event_id` query parameter. When present, calls `services.compute_event_awards(event_id)`. When absent, returns all-time awards from `analysis_data.json` (existing behavior).
- FR-3: `get_lan_events_for_api()` reads from mtime-cached `rating_history.json`. Maps each event from `detect_lan_events()` output to API format:
  ```python
  {
      "id": f"lan-{event['start_date']}",
      "label": event["label"],
      "start_date": event["start_date"],
      "end_date": event["end_date"],
      "num_games": event["num_games"],
  }
  ```
- FR-4: `compute_event_awards(event_id)` performs these steps:
  1. Get LAN events list, find the one matching `event_id`
  2. Load `game_registry.json` (via mtime cache or direct read)
  3. Filter games to those with `status` in `("processed", "no_winner")` and `datetime` between `start_date` and `end_date` (inclusive, comparing date portion)
  4. Build `player_stats` dict: for each game, accumulate core stats (games_played, wins, playtime, civs, eAPM) from the `teams` metadata, and action-based stats (units, market, walls, deletions, upgrades) from `player_deltas`
  5. Build `game_stats` dict: total_games, total_duration, longest_game, overall_civ_picks, total_units_created, team_matchups
  6. Compute losing streaks from the filtered game chronology
  7. Call `compute_all_awards(player_stats, game_stats)` and return the result
- FR-5: In `web/templates/index.html`, add event selector inside the `#awards-content` div, before the `#awards-grid`:
  ```html
  <div class="event-selector">
      <select id="award-event-selector">
          <option value="">All Time</option>
      </select>
  </div>
  ```
- FR-6: In `web/static/app.js`:
  - On awards tab activation (first load), fetch `GET /api/lan-events` and populate the dropdown options
  - Wire `change` event on `#award-event-selector` to re-fetch awards with the selected `event_id`
  - Modify `fetchAwards()` to accept an optional `eventId` parameter and append `?event_id=...` to the fetch URL when provided
  - Show loading state in the awards grid during fetch; restore content when done
- FR-7: Style the event selector dropdown in `web/static/style.css` to match the existing dark medieval theme (dark background, gold accents, Cinzel/Cormorant fonts).

## Non-Goals

- No ability to create or edit LAN events manually (auto-detection only)
- No per-event player profiles or per-event game history view (only awards are scoped)
- No per-event rating changes view
- No caching of per-event award computation results (computation is fast, events are few)
- No event detection parameter tuning via UI (2-day gap, 10+ games threshold are hardcoded)

## Design Considerations

- The dropdown should be visually subtle and not dominate the Hall of Fame header. A small dropdown with a label like "Event:" fits naturally below the section header.
- When a specific event is selected, consider showing a small info line below the dropdown: "12 games, Nov 7-9 2025" to give context on the scope.
- The awards grid rendering function already exists in `app.js`. The same `renderAwards()` function should work for both all-time and per-event awards since the JSON structure is identical.

## Technical Considerations

- **Computation cost**: `compute_event_awards` iterates over filtered registry entries (typically 15-40 games per LAN event) and calls `compute_all_awards`. This should take < 100ms. No caching needed.
- **Registry dependency**: This feature requires `game_registry.json` to exist, which is created by the processing pipeline (PRD 1) or migration (PRD 5). Until migration is run, per-event awards will return 404 or empty results.
- **`compute_all_awards` compatibility**: The function in `report_generator.py` expects `player_stats` and `game_stats` dicts with the same structure as the module-level globals in `analyze_games.py`. `compute_event_awards` must construct dicts matching this exact structure, including all nested defaultdict patterns.
- **Date comparison**: LAN events store `start_date` and `end_date` as ISO date strings (e.g., `"2025-11-07"`). Registry entries store `datetime` as ISO datetime strings. Compare by extracting the date portion: `entry["datetime"][:10] >= event["start_date"]`.
- **Existing `detect_lan_events()` output**: The function returns a list of dicts with keys `start_date`, `end_date`, `game_index_start`, `game_index_end`, `num_games`, `label`. The `game_index_*` fields are only meaningful for the TrueSkill plot. For filtering registry entries, use `start_date`/`end_date`.

## Success Metrics

- LAN event dropdown populates with at least the known historical events
- Selecting an event shows awards scoped to that event within 1 second
- Switching back to "All Time" shows the same awards as before
- Award JSON structure is identical between all-time and per-event responses

## Open Questions

- Should per-event awards also include "General Stats" (total games, avg duration, most popular civs) for that event? This would add more context to the event view but is not strictly part of the awards.
- Should we show per-event leaderboards (win rate, games played within the event)? This would require adding another scoped view beyond just awards.
