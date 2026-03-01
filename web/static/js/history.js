// =====================
// GAME HISTORY TAB
// =====================
let historySortOrder = 'desc';
let historySearch = '';
let historyOffset = 0;
let historyTotal = 0;
let historyHasMore = false;
let historyLoading = false;
let historyAbortController = null;
let searchDebounceTimer = null;
let expandedGameSha = null;
const gameDetailCache = {};

async function fetchGameHistory(append = false) {
    // Cancel any in-flight request
    if (historyAbortController) historyAbortController.abort();
    historyAbortController = new AbortController();

    if (historyLoading && append) return;
    historyLoading = true;

    if (!append) {
        historyOffset = 0;
        expandedGameSha = null;
        const container = document.getElementById('history-list');
        container.innerHTML = '<div class="loading-text">Unrolling the chronicles...</div>';
    } else {
        showScrollLoadingIndicator(true);
    }

    try {
        const params = new URLSearchParams({
            offset: historyOffset,
            limit: 30,
            search: historySearch,
            sort: historySortOrder,
        });
        const res = await fetch(`/api/games?${params}`, { signal: historyAbortController.signal });
        const data = await res.json();

        if (data.error) {
            document.getElementById('history-loading').innerHTML =
                `<div class="loading-text">${data.error}</div>`;
            return;
        }

        historyTotal = data.total;
        historyHasMore = data.has_more;
        historyOffset += data.games.length;

        if (append) {
            appendGameCards(data.games);
        } else {
            renderGameHistory(data.games);
            document.getElementById('history-loading').style.display = 'none';
            document.getElementById('history-content').style.display = '';
        }

        updateHistoryStatus();
    } catch (err) {
        if (err.name === 'AbortError') return;
        if (!append) {
            document.getElementById('history-loading').innerHTML =
                '<div class="loading-text">Failed to unroll the chronicles.</div>';
        }
        console.error(err);
    } finally {
        historyLoading = false;
        showScrollLoadingIndicator(false);
    }
}

function toggleSortOrder() {
    historySortOrder = historySortOrder === 'asc' ? 'desc' : 'asc';
    const btn = document.getElementById('sort-toggle-btn');
    if (btn) btn.textContent = historySortOrder === 'asc' ? 'Newest First' : 'Oldest First';
    fetchGameHistory(false);
}

function formatPlayer(p, streaks, ratingChanges) {
    const badge = streaks && streaks[p.name]
        ? `<span class="streak-badge ${streaks[p.name][0] === 'W' ? 'win-streak' : 'loss-streak'}">${streaks[p.name]}</span>`
        : '';
    let ratingBadge = '';
    if (ratingChanges && ratingChanges[p.name] != null) {
        const delta = ratingChanges[p.name];
        const sign = delta >= 0 ? '+' : '';
        const cls = delta >= 0 ? 'rating-up' : 'rating-down';
        ratingBadge = `<span class="rating-delta ${cls}">${sign}${Math.round(delta)}</span>`;
    }
    const hcText = p.handicap && p.handicap > 100
        ? `<span class="gc-hc">(${p.handicap}%)</span>`
        : '';
    return `<span class="gc-player-chip">
        <a class="player-link" onclick="event.stopPropagation(); openPlayerProfile('${p.name}')">${p.name}</a>${hcText}${ratingBadge}${badge}
        <span class="gc-civ">${p.civilization || ''}</span>
    </span>`;
}

function buildGameCardHTML(g) {
    const winTeam = g.teams.find(t => t.is_winner);
    const loseTeam = g.teams.find(t => !t.is_winner);
    if (!winTeam || !loseTeam) return '';

    const sha = g.sha256 || '';
    window._chronicleGames[sha] = g;

    const dateObj = g.datetime && g.datetime !== '0001-01-01T00:00:00' ? new Date(g.datetime) : null;
    const dateStr = dateObj ? dateObj.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: '2-digit' }) : '?';

    const gameNum = g.game_number || '';

    return `
    <div class="gc-entry" data-sha="${sha}">
        <div class="gc-header" onclick="toggleGameDetail('${sha}')">
            <div class="gc-left">
                <span class="gc-number">#${gameNum}</span>
                <span class="gc-date">${dateStr}</span>
                <span class="gc-duration">${g.duration_display}</span>
            </div>
            <div class="gc-expand-icon">\u25BE</div>
        </div>
        <div class="gc-matchup" onclick="toggleGameDetail('${sha}')">
            <div class="gc-side gc-winner-side">
                <div class="gc-side-label gc-victory-label">Victory</div>
                <div class="gc-players">
                    ${winTeam.players.map(p => formatPlayer(p, g.streaks, g.rating_changes)).join('')}
                </div>
            </div>
            <div class="gc-vs-divider"><span>vs</span></div>
            <div class="gc-side gc-loser-side">
                <div class="gc-side-label gc-defeat-label">Defeat</div>
                <div class="gc-players">
                    ${loseTeam.players.map(p => formatPlayer(p, g.streaks, g.rating_changes)).join('')}
                </div>
            </div>
        </div>
        <div class="gc-actions-bar">
            ${g.has_winner ? `<button class="gc-action-btn gc-action-redeploy" onclick="event.stopPropagation(); redeployFromChronicle('${sha}')">\u2694 Redeploy</button>` : ''}
            ${sha ? `<a class="gc-action-btn gc-action-download" href="/api/games/${sha}/download" onclick="event.stopPropagation()">\u2193 Download</a>` : ''}
        </div>
        <div class="gc-detail" id="detail-${sha}" style="display:none">
            <div class="gc-detail-loading">Loading battle details...</div>
        </div>
    </div>`;
}

function renderGameHistory(games) {
    const container = document.getElementById('history-list');
    if (games.length === 0) {
        container.innerHTML = historySearch
            ? '<div class="empty-state"><p>No battles match your search.</p></div>'
            : '<div class="empty-state"><p>No battles recorded yet.</p></div>';
        return;
    }

    window._chronicleGames = {};
    container.innerHTML = games.map(g => buildGameCardHTML(g)).join('');
}

function appendGameCards(games) {
    const container = document.getElementById('history-list');
    const html = games.map(g => buildGameCardHTML(g)).join('');
    container.insertAdjacentHTML('beforeend', html);
}

function updateHistoryStatus() {
    const desc = document.querySelector('#history .section-desc');
    if (desc) {
        if (historySearch) {
            desc.textContent = `${historyTotal} battle${historyTotal !== 1 ? 's' : ''} matching "${historySearch}"`;
        } else {
            desc.textContent = `A record of all ${historyTotal} engagements`;
        }
    }
}

function showScrollLoadingIndicator(show) {
    let indicator = document.getElementById('history-scroll-loader');
    if (show) {
        if (!indicator) {
            const container = document.getElementById('history-list');
            const div = document.createElement('div');
            div.id = 'history-scroll-loader';
            div.className = 'scroll-loader';
            div.innerHTML = '<div class="loading-text">Loading more battles...</div>';
            container.appendChild(div);
        }
    } else {
        if (indicator) indicator.remove();
    }
}

function setupInfiniteScroll() {
    const container = document.getElementById('history-list');
    if (!container) return;
    container.addEventListener('scroll', () => {
        if (historyLoading || !historyHasMore) return;
        const { scrollTop, scrollHeight, clientHeight } = container;
        if (scrollTop + clientHeight >= scrollHeight - 200) {
            fetchGameHistory(true);
        }
    });
}

async function toggleGameDetail(sha256) {
    if (!sha256) return;

    const detailEl = document.getElementById(`detail-${sha256}`);
    const entryEl = detailEl?.closest('.gc-entry');
    if (!detailEl || !entryEl) return;

    if (detailEl.style.display !== 'none') {
        detailEl.style.display = 'none';
        entryEl.classList.remove('gc-expanded');
        expandedGameSha = null;
        return;
    }

    // Collapse any other expanded game
    if (expandedGameSha && expandedGameSha !== sha256) {
        const prev = document.getElementById(`detail-${expandedGameSha}`);
        if (prev) {
            prev.style.display = 'none';
            prev.closest('.gc-entry')?.classList.remove('gc-expanded');
        }
    }

    detailEl.style.display = 'block';
    entryEl.classList.add('gc-expanded');
    expandedGameSha = sha256;

    if (gameDetailCache[sha256]) {
        renderGameDetail(sha256, gameDetailCache[sha256]);
    } else {
        detailEl.innerHTML = '<div class="gc-detail-loading">Loading battle details...</div>';
        try {
            const res = await fetch(`/api/games/${sha256}/detail`);
            const data = await res.json();
            if (data.error) {
                detailEl.innerHTML = `<div class="gc-detail-error">${data.error}</div>`;
                return;
            }
            gameDetailCache[sha256] = data;
            renderGameDetail(sha256, data);
        } catch (err) {
            detailEl.innerHTML = '<div class="gc-detail-error">Failed to load details.</div>';
            console.error(err);
        }
    }
}

function renderGameDetail(sha256, data) {
    const detailEl = document.getElementById(`detail-${sha256}`);
    if (!detailEl) return;

    const teams = data.teams || {};
    const playerDeltas = data.player_deltas || {};
    const gameDeltas = data.game_level_deltas || {};
    const ratingChanges = data.rating_changes || {};

    const renderPlayerCard = (p) => {
        const deltas = playerDeltas[p.name] || {};
        const rc = ratingChanges[p.name];
        const rcStr = rc != null
            ? `<span class="gd-rating ${rc >= 0 ? 'rating-up' : 'rating-down'}">${rc >= 0 ? '+' : ''}${Math.round(rc)}</span>`
            : '';

        const units = deltas.units_created || {};
        const topUnits = Object.entries(units)
            .sort((a, b) => b[1] - a[1])
            .slice(0, 5);

        const techs = Object.keys(deltas.crucial_researched || {});
        const hcDisplay = p.handicap && p.handicap !== 100 ? `${p.handicap}%` : '100%';

        const statsRow = [
            { label: 'HC', value: hcDisplay },
            { label: 'eAPM', value: p.eapm != null ? Math.round(p.eapm) : '-' },
            { label: 'Units', value: deltas.total_units_created || 0 },
            { label: 'Market', value: deltas.market_transactions || 0 },
            { label: 'Walls', value: deltas.wall_segments_built || 0 },
            { label: 'Razed', value: deltas.buildings_deleted || 0 },
        ];

        return `
        <div class="gd-player-card ${p.winner ? 'gd-card-winner' : 'gd-card-loser'}">
            <div class="gd-card-top">
                <div class="gd-card-identity">
                    <span class="gd-card-name">
                        <a class="player-link" onclick="openPlayerProfile('${p.name}')">${p.name}</a>
                        ${rcStr}
                    </span>
                    <span class="gd-card-civ">${p.civilization}</span>
                </div>
            </div>
            <div class="gd-card-stats">
                ${statsRow.map(s => `<div class="gd-card-stat"><span class="gd-card-stat-val">${s.value}</span><span class="gd-card-stat-key">${s.label}</span></div>`).join('')}
            </div>
            ${topUnits.length > 0 ? `
            <div class="gd-card-section">
                <div class="gd-card-section-title">Army Composition</div>
                <div class="gd-army-list">
                    ${topUnits.map(([name, count]) => `<div class="gd-army-row"><span class="gd-army-name">${name}</span><span class="gd-army-count">${count}</span></div>`).join('')}
                </div>
            </div>` : ''}
            ${techs.length > 0 ? `
            <div class="gd-card-section">
                <div class="gd-card-section-title">Upgrades Researched</div>
                <div class="gd-tech-list">${techs.map(t => `<span class="gd-tech-tag">${t}</span>`).join('')}</div>
            </div>` : ''}
        </div>`;
    };

    const teamEntries = Object.values(teams);
    const winTeam = teamEntries.find(t => t.is_winner);
    const loseTeam = teamEntries.find(t => !t.is_winner);
    const totalUnits = gameDeltas.total_units_created_overall || 0;

    detailEl.innerHTML = `
        <div class="gd-panel">
            <div class="gd-battle-grid">
                <div class="gd-battle-side">
                    <div class="gd-side-header gd-side-victory">Victory</div>
                    ${winTeam ? winTeam.players.map(p => renderPlayerCard(p)).join('') : ''}
                </div>
                <div class="gd-battle-side">
                    <div class="gd-side-header gd-side-defeat">Defeat</div>
                    ${loseTeam ? loseTeam.players.map(p => renderPlayerCard(p)).join('') : ''}
                </div>
            </div>
            <div class="gd-footer">
                <div class="gd-footer-stats">
                    <span><b>${totalUnits}</b> units created</span>
                    <span>Duration <b>${data.duration_display}</b></span>
                </div>
                <div class="gd-footer-actions">
                    ${sha256 ? `<a class="gc-action-btn gc-action-download" href="/api/games/${sha256}/download">\u2193 Download Replay</a>` : ''}
                    ${winTeam ? `<button class="gc-action-btn gc-action-redeploy" onclick="redeployFromChronicle('${sha256}')">\u2694 Redeploy Teams</button>` : ''}
                </div>
            </div>
        </div>`;
}

function redeployFromChronicle(sha256Key) {
    const g = window._chronicleGames[sha256Key];
    if (!g) return;

    const ratingsMap = {};
    state.allPlayers.forEach(p => {
        ratingsMap[p.name] = {
            rating: p.mu_scaled,
            recommended_hc: p.recommended_hc,
            games_played: p.games_played,
        };
    });

    const winTeam = g.teams.find(t => t.is_winner);
    const loseTeam = g.teams.find(t => !t.is_winner);
    if (!winTeam || !loseTeam) return;

    const buildTeam = (team) => team.players.map(p => {
        const known = ratingsMap[p.name];
        return {
            name: p.name,
            rating: known ? known.rating : 0,
            recommended_hc: known ? known.recommended_hc : 100,
            games_played: known ? known.games_played : 0,
        };
    });

    useSetup({
        team1: buildTeam(winTeam),
        team2: buildTeam(loseTeam),
        benched: [],
        rating_changes: {},
        match_quality: null,
        expected_winner: null,
    });
}

// History filter (debounced server-side search) + infinite scroll
document.addEventListener('DOMContentLoaded', () => {
    const filterInput = document.getElementById('history-filter');
    if (filterInput) {
        filterInput.addEventListener('input', () => {
            clearTimeout(searchDebounceTimer);
            searchDebounceTimer = setTimeout(() => {
                historySearch = filterInput.value.trim();
                historyFetched = false;
                fetchGameHistory(false);
                historyFetched = true;
            }, 300);
        });
    }
    setupInfiniteScroll();
});
