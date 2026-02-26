// =====================
// SOUND EFFECTS MODULE
// =====================
const SoundFX = (() => {
    let enabled = true;
    const cache = {};

    function play(name, volume = 0.5) {
        if (!enabled) return;
        try {
            if (!cache[name]) cache[name] = new Audio(`/static/sounds/${name}.ogg`);
            const sound = cache[name].cloneNode();
            sound.volume = volume;
            sound.play();
        } catch (e) { /* ignore audio errors */ }
    }

    return {
        forge()  { play('forge', 0.5); },
        horn()   { play('horn', 0.5); },
        clash()  { play('clash', 0.5); },
        scroll() { play('scroll', 0.3); },
        toggle() { enabled = !enabled; return enabled; },
        isEnabled() { return enabled; },
    };
})();

function toggleSound() {
    const on = SoundFX.toggle();
    document.getElementById('sound-icon').textContent = on ? '\uD83D\uDD0A' : '\uD83D\uDD07';
}

// =====================
// STATE
// =====================
const state = {
    allPlayers: [],
    currentTeam1: [],
    currentTeam2: [],
    benched: [],
    ratingChanges: {},
    matchQuality: null,
    expectedWinner: null,
    manualAssignments: {},
};

// ---- Tab switching & hash routing ----
let awardsFetched = false;
let historyFetched = false;
let lanEventsFetched = false;
let lanEventsData = [];

const VALID_TABS = ['ratings', 'awards', 'history', 'generator', 'game'];

document.querySelectorAll('.tab').forEach(btn => {
    btn.addEventListener('click', () => navigateTo(btn.dataset.tab));
});

// Navigate by updating the hash — this triggers hashchange which calls handleRoute
function navigateTo(route) {
    const newHash = '#' + route;
    if (location.hash === newHash) return;
    location.hash = newHash;
}

// Internal tab switch — does NOT touch the hash (called from handleRoute)
function switchTab(tabId) {
    SoundFX.scroll();
    document.querySelectorAll('.tab').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(s => s.classList.remove('active'));
    const tabBtn = document.querySelector(`.tab[data-tab="${tabId}"]`);
    if (tabBtn) tabBtn.classList.add('active');
    document.getElementById(tabId).classList.add('active');

    // Close player modal if open and we're navigating to a tab
    const modal = document.getElementById('player-modal');
    if (modal.style.display !== 'none') {
        modal.style.display = 'none';
        document.body.classList.remove('modal-open');
    }

    // Lazy-load tabs
    if (tabId === 'awards' && !awardsFetched) {
        awardsFetched = true;
        fetchAwards();
        fetchLanEvents();
    }
    if (tabId === 'history' && !historyFetched) {
        historyFetched = true;
        fetchGameHistory();
    }
}

// Parse the current hash and route accordingly
function handleRoute() {
    const hash = location.hash.slice(1); // remove '#'
    if (!hash) {
        switchTab('ratings');
        return;
    }

    // Player profile route: #player/Name
    if (hash.startsWith('player/')) {
        const playerName = decodeURIComponent(hash.slice('player/'.length));
        if (playerName) {
            openPlayerProfile(playerName, /* fromRoute */ true);
            return;
        }
    }

    // Tab route
    if (VALID_TABS.includes(hash)) {
        switchTab(hash);
        return;
    }

    // Unknown hash — default to ratings
    switchTab('ratings');
}

window.addEventListener('hashchange', handleRoute);

// =====================
// RATINGS TAB
// =====================
async function fetchPlayers() {
    try {
        const res = await fetch('/api/players');
        const data = await res.json();
        if (data.error) {
            document.getElementById('ratings-loading').innerHTML =
                `<div class="loading-text">${data.error}</div>`;
            return;
        }

        state.allPlayers = [...data.ranked, ...data.provisional];

        renderRatingsTable(data.ranked, 'ranked-table');
        if (data.provisional.length > 0) {
            document.getElementById('provisional-section').style.display = '';
            document.getElementById('min-games').textContent = data.min_games_for_ranking;
            renderRatingsTable(data.provisional, 'provisional-table');
        }
        document.getElementById('ratings-loading').style.display = 'none';
        document.getElementById('ratings-content').style.display = '';

        renderPlayerCheckboxes();
        fetchRatingHistory();
    } catch (err) {
        document.getElementById('ratings-loading').innerHTML =
            '<div class="loading-text">Failed to summon the champions.</div>';
        console.error(err);
    }
}

function renderRatingsTable(players, tableId) {
    const tbody = document.querySelector(`#${tableId} tbody`);
    tbody.innerHTML = players.map((p, i) => {
        const rank = i + 1;
        const rankClass = rank <= 3 ? ` rank-${rank}` : '';
        const medal = rank === 1 ? '\u265B' : rank === 2 ? '\u2726' : rank === 3 ? '\u2726' : rank;

        return `
        <tr class="${rankClass}">
            <td class="col-rank">${medal}</td>
            <td class="col-name"><a class="player-link" onclick="openPlayerProfile('${p.name}')">${p.name}</a></td>
            <td class="col-rating">${p.mu_scaled.toFixed(0)}</td>
            <td class="col-hc">${p.avg_handicap_last_30 > 100 ? p.avg_handicap_last_30.toFixed(0) + '%' : '100%'}</td>
            <td class="col-hc">${p.recommended_hc}%</td>
            <td class="col-games">${p.games_played}</td>
            <td class="col-conf">${p.confidence_percent.toFixed(1)}%</td>
        </tr>`;
    }).join('');
}

// =====================
// RATING EVOLUTION CHART
// =====================
const CHART_COLORS = [
    '#c9a84c', '#e4c766', '#7db866', '#d4503e', '#5b9bd5',
    '#f0dfa0', '#c08850', '#b0b0b0', '#6a9e55', '#b83a2a',
    '#a89b85', '#e0d4bc', '#7a6832', '#4a3d1e',
];
let ratingChart = null;

async function fetchRatingHistory() {
    try {
        const res = await fetch('/api/rating-history');
        const data = await res.json();
        if (data.error) return;
        // Support both old (flat array) and new (object with history + lan_events) formats
        const history = data.history || data;
        const lanEvents = data.lan_events || [];
        renderRatingChart(history, lanEvents);
    } catch (err) { console.error(err); }
}

function renderRatingChart(history, lanEvents) {
    const playerData = {};
    history.forEach(h => {
        if (!playerData[h.player_name]) playerData[h.player_name] = [];
        playerData[h.player_name].push({ x: h.game_index, y: Math.round(h.mu) });
    });

    const datasets = Object.entries(playerData).map(([name, points], i) => ({
        label: name,
        data: points,
        borderColor: CHART_COLORS[i % CHART_COLORS.length],
        backgroundColor: CHART_COLORS[i % CHART_COLORS.length] + '20',
        borderWidth: 2,
        pointRadius: 2,
        pointHoverRadius: 5,
        tension: 0.3,
        fill: false,
    }));

    // Custom plugin to draw LAN event markers
    const lanAnnotationPlugin = {
        id: 'lanAnnotations',
        afterDraw(chart) {
            const events = chart.options.plugins.lanAnnotations?.events || [];
            if (!events.length) return;
            const {ctx, chartArea, scales} = chart;

            events.forEach(event => {
                const xStart = scales.x.getPixelForValue(event.game_index_start);
                const xEnd = scales.x.getPixelForValue(event.game_index_end);

                ctx.save();
                // Shaded region
                ctx.fillStyle = 'rgba(201, 168, 76, 0.07)';
                ctx.fillRect(xStart, chartArea.top, xEnd - xStart, chartArea.bottom - chartArea.top);
                // Start line (dashed)
                ctx.strokeStyle = 'rgba(201, 168, 76, 0.4)';
                ctx.lineWidth = 1;
                ctx.setLineDash([4, 4]);
                ctx.beginPath();
                ctx.moveTo(xStart, chartArea.top);
                ctx.lineTo(xStart, chartArea.bottom);
                ctx.stroke();
                // Label
                const mid = (xStart + xEnd) / 2;
                ctx.fillStyle = 'rgba(201, 168, 76, 0.7)';
                ctx.font = "10px 'Cinzel', serif";
                ctx.textAlign = 'center';
                ctx.fillText(event.label, mid, chartArea.top + 14);
                ctx.restore();
            });
        }
    };

    const ctx = document.getElementById('rating-chart').getContext('2d');
    ratingChart = new Chart(ctx, {
        type: 'line',
        data: { datasets },
        plugins: [lanAnnotationPlugin],
        options: {
            responsive: true,
            maintainAspectRatio: false,
            interaction: { mode: 'nearest', intersect: false },
            plugins: {
                legend: { display: false },
                lanAnnotations: { events: lanEvents || [] },
                tooltip: {
                    backgroundColor: '#1c1915',
                    borderColor: '#302a22',
                    borderWidth: 1,
                    titleFont: { family: "'Cinzel', serif", size: 12 },
                    bodyFont: { family: "'Cormorant Garamond', serif", size: 14 },
                    titleColor: '#c9a84c',
                    bodyColor: '#e0d4bc',
                    callbacks: {
                        title: (items) => `Game #${items[0].parsed.x}`,
                        label: (item) => `${item.dataset.label}: ${item.parsed.y}`,
                    }
                },
                zoom: {
                    pan: {
                        enabled: true,
                        mode: 'x',
                    },
                    zoom: {
                        wheel: { enabled: true },
                        pinch: { enabled: true },
                        drag: {
                            enabled: true,
                            backgroundColor: 'rgba(201, 168, 76, 0.1)',
                            borderColor: 'rgba(201, 168, 76, 0.4)',
                            borderWidth: 1,
                        },
                        mode: 'x',
                        onZoom: () => { document.getElementById('reset-zoom-btn').style.display = ''; },
                    },
                }
            },
            scales: {
                x: {
                    type: 'linear',
                    title: { display: true, text: 'Game', color: '#7a6f60', font: { family: "'Cinzel', serif", size: 11 } },
                    ticks: { color: '#7a6f60' },
                    grid: { color: 'rgba(48, 42, 34, 0.4)' },
                },
                y: {
                    title: { display: true, text: 'Rating', color: '#7a6f60', font: { family: "'Cinzel', serif", size: 11 } },
                    ticks: { color: '#7a6f60' },
                    grid: { color: 'rgba(48, 42, 34, 0.4)' },
                }
            }
        }
    });

    const toggleContainer = document.getElementById('chart-player-toggles');
    toggleContainer.innerHTML = datasets.map((ds, i) => `
        <button class="chart-toggle active" data-index="${i}"
                style="border-color: ${ds.borderColor}; color: ${ds.borderColor}"
                onclick="toggleChartPlayer(${i}, this)">
            ${ds.label}
        </button>
    `).join('');
}

function toggleChartPlayer(index, btn) {
    const meta = ratingChart.getDatasetMeta(index);
    meta.hidden = !meta.hidden;
    btn.classList.toggle('active');
    ratingChart.update();
}

function resetChartZoom() {
    if (ratingChart) {
        ratingChart.resetZoom();
        document.getElementById('reset-zoom-btn').style.display = 'none';
    }
}

// =====================
// AWARDS TAB
// =====================
const AWARD_DEFS = {
    favorite_unit_fanatic: { title: "Favorite Unit Fanatic", icon: "\u2694\uFE0F", statLabel: "units created", valueKey: "count", perPlayer: true },
    bitter_salt_baron: { title: "The Bitter Salt Baron", icon: "\u2620\uFE0F", statLabel: "losses in a row", valueKey: "streak" },
    wall_street_tycoon: { title: "Wall Street Tycoon", icon: "\uD83E\uDDF1", statLabel: "wall sections built", valueKey: "count" },
    demolition_expert: { title: "Demolition Expert", icon: "\uD83D\uDCA5", statLabel: "buildings deleted", valueKey: "count" },
    market_mogul: { title: "The Market Mogul", icon: "\u2696\uFE0F", statLabel: "market transactions", valueKey: "transactions" },
    forgetful_upgrades: { title: "Forgetful Commander", icon: "\u2753", statLabel: "% forgetfulness", valueKey: "avg_forgetfulness" },
    jittery_fingers: { title: "Jittery Caffeinated Fingers", icon: "\u26A1", statLabel: "avg eAPM", valueKey: "avg_eapm" },
};

async function fetchAwards(eventId) {
    const grid = document.getElementById('awards-grid');
    const loading = document.getElementById('awards-loading');
    const content = document.getElementById('awards-content');

    // If already showing content, show inline loading in the grid
    if (content.style.display !== 'none') {
        grid.innerHTML = '<div class="loading-text">Unveiling the legends...</div>';
    }

    try {
        const url = eventId ? `/api/awards?event_id=${encodeURIComponent(eventId)}` : '/api/awards';
        const res = await fetch(url);
        const data = await res.json();
        if (data.error) {
            if (content.style.display === 'none') {
                loading.innerHTML = `<div class="loading-text">${data.error}</div>`;
            } else {
                grid.innerHTML = `<div class="loading-text">${data.error}</div>`;
            }
            return;
        }
        renderAwards(data);
        loading.style.display = 'none';
        content.style.display = '';
    } catch (err) {
        if (content.style.display === 'none') {
            loading.innerHTML = '<div class="loading-text">Failed to unveil the legends.</div>';
        } else {
            grid.innerHTML = '<div class="loading-text">Failed to unveil the legends.</div>';
        }
        console.error(err);
    }
}

async function fetchLanEvents() {
    if (lanEventsFetched) return;
    lanEventsFetched = true;
    try {
        const res = await fetch('/api/lan-events');
        lanEventsData = await res.json();
        const selector = document.getElementById('award-event-selector');
        lanEventsData.forEach(event => {
            const opt = document.createElement('option');
            opt.value = event.id;
            opt.textContent = event.label;
            selector.appendChild(opt);
        });
        selector.addEventListener('change', () => {
            const eventId = selector.value;
            updateEventInfo(eventId);
            fetchAwards(eventId || undefined);
        });
    } catch (err) {
        console.error('Failed to fetch LAN events:', err);
    }
}

function updateEventInfo(eventId) {
    const infoEl = document.getElementById('event-info');
    if (!eventId) {
        infoEl.textContent = '';
        return;
    }
    const event = lanEventsData.find(e => e.id === eventId);
    if (event) {
        const start = new Date(event.start_date + 'T00:00:00');
        const end = new Date(event.end_date + 'T00:00:00');
        const fmt = (d) => d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric' });
        const dateRange = event.start_date === event.end_date
            ? fmt(start)
            : `${fmt(start)} \u2013 ${fmt(end)}`;
        infoEl.textContent = `${event.num_games} games, ${dateRange}`;
    }
}

function renderAwards(data) {
    const grid = document.getElementById('awards-grid');
    grid.innerHTML = '';

    // Favorite Unit Fanatic — special: show per-player list
    if (data.favorite_unit_fanatic && data.favorite_unit_fanatic.length > 0) {
        const entries = data.favorite_unit_fanatic;
        const card = document.createElement('div');
        card.className = 'award-card award-card-wide';
        card.innerHTML = `
            <div class="award-icon">\u2694\uFE0F</div>
            <h3 class="award-title">Favorite Unit Fanatic</h3>
            <div class="award-per-player">
                ${entries.map((e, i) => `
                    <div class="award-entry ${i === 0 ? 'award-winner' : ''}">
                        <span class="award-name"><a class="player-link" onclick="openPlayerProfile('${e.player}')">${e.player}</a></span>
                        <span class="award-stat">${e.unit} (${e.count})</span>
                    </div>
                `).join('')}
            </div>
        `;
        grid.appendChild(card);
    }

    // Standard awards
    for (const [key, def] of Object.entries(AWARD_DEFS)) {
        if (key === 'favorite_unit_fanatic') continue;
        const entries = data[key];
        if (!entries || entries.length === 0) continue;

        const winner = entries[0];
        const runnerUp = entries.length > 1 ? entries[1] : null;

        const card = document.createElement('div');
        card.className = 'award-card';
        card.innerHTML = `
            <div class="award-icon">${def.icon}</div>
            <h3 class="award-title">${def.title}</h3>
            <div class="award-winner">
                <span class="award-medal">\u265B</span>
                <span class="award-name"><a class="player-link" onclick="openPlayerProfile('${winner.player}')">${winner.player}</a></span>
                <span class="award-stat">${winner[def.valueKey]} ${def.statLabel}</span>
            </div>
            ${runnerUp ? `
            <div class="award-runner-up">
                <span class="award-medal silver">\u2726</span>
                <span class="award-name"><a class="player-link" onclick="openPlayerProfile('${runnerUp.player}')">${runnerUp.player}</a></span>
                <span class="award-stat">${runnerUp[def.valueKey]} ${def.statLabel}</span>
            </div>` : ''}
        `;
        grid.appendChild(card);
    }

    // Balanced matchup — special card
    if (data.balanced_matchup) {
        const m = data.balanced_matchup;
        const card = document.createElement('div');
        card.className = 'award-card award-card-wide';
        card.innerHTML = `
            <div class="award-icon">\u2696\uFE0F</div>
            <h3 class="award-title">Most Balanced Matchup</h3>
            <div class="matchup-display">
                <span>${m.team_a.join(', ')}</span>
                <span class="matchup-vs">VS</span>
                <span>${m.team_b.join(', ')}</span>
            </div>
            <div class="matchup-score">${m.wins_a} - ${m.wins_b}</div>
        `;
        grid.appendChild(card);
    }
}

// =====================
// GAME HISTORY TAB
// =====================
let allGames = [];

async function fetchGameHistory() {
    try {
        const res = await fetch('/api/games');
        const data = await res.json();
        if (data.error) {
            document.getElementById('history-loading').innerHTML =
                `<div class="loading-text">${data.error}</div>`;
            return;
        }
        allGames = data.games || [];
        // Compute streaks in chronological order, then reverse back to newest-first
        const chronological = [...allGames].reverse();
        const withStreaks = computeStreaks(chronological).reverse();
        renderGameHistory(withStreaks);
        document.getElementById('history-loading').style.display = 'none';
        document.getElementById('history-content').style.display = '';
    } catch (err) {
        document.getElementById('history-loading').innerHTML =
            '<div class="loading-text">Failed to unroll the chronicles.</div>';
        console.error(err);
    }
}

function computeStreaks(games) {
    const streaks = {};
    return games.map(g => {
        const streakInfo = {};
        // Skip games with no winner — they have no outcome to streak on
        if (!g.has_winner) return { ...g, streaks: streakInfo };
        g.teams.forEach(team => {
            team.players.forEach(p => {
                if (team.is_winner) {
                    streaks[p.name] = (streaks[p.name] > 0 ? streaks[p.name] : 0) + 1;
                    if (streaks[p.name] >= 3) streakInfo[p.name] = `W${streaks[p.name]}`;
                } else {
                    streaks[p.name] = (streaks[p.name] < 0 ? streaks[p.name] : 0) - 1;
                    if (streaks[p.name] <= -3) streakInfo[p.name] = `L${Math.abs(streaks[p.name])}`;
                }
            });
        });
        return { ...g, streaks: streakInfo };
    });
}

function renderGameHistory(games) {
    const container = document.getElementById('history-list');
    if (games.length === 0) {
        container.innerHTML = '<div class="empty-state"><p>No battles recorded yet.</p></div>';
        return;
    }

    window._chronicleGames = {};

    container.innerHTML = games.map((g, i) => {
        const winTeam = g.teams.find(t => t.is_winner);
        const loseTeam = g.teams.find(t => !t.is_winner);
        if (!winTeam || !loseTeam) return '';

        window._chronicleGames[i] = g;

        const formatPlayers = (players, streaks) => players.map(p => {
            const badge = streaks && streaks[p.name]
                ? `<span class="streak-badge ${streaks[p.name][0] === 'W' ? 'win-streak' : 'loss-streak'}">${streaks[p.name]}</span>`
                : '';
            return `<a class="player-link" onclick="openPlayerProfile('${p.name}')">${p.name}</a>${badge}`;
        }).join(', ');

        const dateStr = g.datetime !== '0001-01-01T00:00:00' ? new Date(g.datetime).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: '2-digit' }) : '?';

        const redeployBtn = g.has_winner
            ? `<button class="btn-chronicle-redeploy" onclick="redeployFromChronicle(${i})" title="Redeploy these teams">&#9876;</button>`
            : '';

        return `
        <div class="history-entry" style="animation-delay: ${Math.min(i * 0.02, 0.5)}s">
            <div class="history-date">${dateStr}</div>
            <div class="history-teams">
                <div class="history-team history-winner">
                    <span class="history-team-label">Victory</span>
                    <span class="history-players">${formatPlayers(winTeam.players, g.streaks)}</span>
                </div>
                <span class="history-vs">\u2694</span>
                <div class="history-team history-loser">
                    <span class="history-team-label">Defeat</span>
                    <span class="history-players">${formatPlayers(loseTeam.players, g.streaks)}</span>
                </div>
            </div>
            <div class="history-meta">
                ${redeployBtn}
                <span class="history-duration">${g.duration_display}</span>
            </div>
        </div>`;
    }).join('');
}

function redeployFromChronicle(gameIdx) {
    const g = window._chronicleGames[gameIdx];
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

// History filter
document.addEventListener('DOMContentLoaded', () => {
    const filterInput = document.getElementById('history-filter');
    if (filterInput) {
        filterInput.addEventListener('input', (e) => {
            const q = e.target.value.toLowerCase();
            const matching = [...allGames].reverse().filter(g =>
                g.teams.some(t => t.players.some(p => p.name.toLowerCase().includes(q)))
            );
            renderGameHistory(computeStreaks(matching).reverse());
        });
    }
});

// =====================
// PLAYER PROFILE MODAL
// =====================
async function openPlayerProfile(name, fromRoute) {
    // If triggered by a click (not from hash routing), update the hash
    if (!fromRoute) {
        navigateTo('player/' + encodeURIComponent(name));
        return; // hashchange handler will call us back with fromRoute=true
    }

    const modal = document.getElementById('player-modal');
    modal.style.display = 'flex';
    document.body.classList.add('modal-open');
    document.getElementById('modal-loading').style.display = '';
    document.getElementById('modal-body').style.display = 'none';

    try {
        const res = await fetch(`/api/player/${encodeURIComponent(name)}`);
        const data = await res.json();
        if (data.error) {
            document.getElementById('modal-loading').innerHTML =
                `<div class="loading-text">${data.error}</div>`;
            return;
        }
        renderPlayerProfile(data);
        document.getElementById('modal-loading').style.display = 'none';
        document.getElementById('modal-body').style.display = '';
    } catch (err) {
        document.getElementById('modal-loading').innerHTML =
            '<div class="loading-text">Failed to summon profile.</div>';
        console.error(err);
    }
}

function renderPlayerProfile(p) {
    const rating = p.rating || {};
    const ratingVal = rating.mu_scaled || '?';
    const trend = p.trend || 0;
    const trendIcon = trend > 0 ? '\u25B2' : trend < 0 ? '\u25BC' : '\u25CF';
    const trendClass = trend > 0 ? 'trend-up' : trend < 0 ? 'trend-down' : 'trend-flat';

    document.getElementById('modal-body').innerHTML = `
        <div class="profile-header">
            <h2 class="profile-name">${p.name}</h2>
            <div class="profile-rating">
                <span class="profile-rating-value">${typeof ratingVal === 'number' ? ratingVal.toFixed(0) : ratingVal}</span>
                ${trend !== 0 ? `<span class="profile-trend ${trendClass}">${trendIcon} ${Math.abs(trend).toFixed(0)}</span>` : ''}
            </div>
            ${rating.confidence_percent != null ? `<div class="profile-meta">Confidence: ${rating.confidence_percent.toFixed(1)}%</div>` : ''}
        </div>

        <div class="profile-stats-grid">
            <div class="profile-stat">
                <span class="profile-stat-value">${p.games_played}</span>
                <span class="profile-stat-label">Battles</span>
            </div>
            <div class="profile-stat">
                <span class="profile-stat-value">${p.win_rate}%</span>
                <span class="profile-stat-label">Win Rate</span>
            </div>
            <div class="profile-stat">
                <span class="profile-stat-value">${p.wins}</span>
                <span class="profile-stat-label">Victories</span>
            </div>
            <div class="profile-stat">
                <span class="profile-stat-value">${p.total_playtime_display}</span>
                <span class="profile-stat-label">Playtime</span>
            </div>
        </div>

        ${p.civilizations && p.civilizations.length > 0 ? `
        <div class="profile-section">
            <h3>Favored Civilizations</h3>
            <div class="profile-civ-list">
                ${p.civilizations.slice(0, 5).map(c => `
                    <div class="profile-civ">
                        <span class="civ-name">${c.name}</span>
                        <span class="civ-played">${c.games} games</span>
                        <span class="civ-wr">${c.win_rate}% WR</span>
                    </div>
                `).join('')}
            </div>
        </div>` : ''}

        ${p.top_units && p.top_units.length > 0 ? `
        <div class="profile-section">
            <h3>Preferred Arms</h3>
            <div class="profile-units">
                ${p.top_units.slice(0, 8).map(u => `
                    <span class="unit-tag">${u.name} (${u.count})</span>
                `).join('')}
            </div>
        </div>` : ''}

        ${p.head_to_head && p.head_to_head.length > 0 ? `
        <div class="profile-section">
            <h3>Head-to-Head Record</h3>
            <div class="h2h-list">
                ${p.head_to_head.map(h => `
                    <div class="h2h-row">
                        <span class="h2h-opponent"><a class="player-link" onclick="openPlayerProfile('${h.opponent}')">${h.opponent}</a></span>
                        <span class="h2h-record ${h.wins > h.losses ? 'h2h-positive' : h.wins < h.losses ? 'h2h-negative' : ''}">${h.wins}W - ${h.losses}L</span>
                    </div>
                `).join('')}
            </div>
        </div>` : ''}

        ${p.avg_eapm ? `<div class="profile-section"><h3>Average eAPM</h3><p class="profile-eapm">${p.avg_eapm}</p></div>` : ''}
    `;
}

function closePlayerModal(event) {
    if (event && event.target !== event.currentTarget) return;
    const modal = document.getElementById('player-modal');
    if (modal.style.display === 'none') return;
    modal.style.display = 'none';
    document.body.classList.remove('modal-open');
    // Navigate back if we're on a player route
    if (location.hash.startsWith('#player/')) {
        history.back();
    }
}

document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') closePlayerModal();
});

// =====================
// PLAYER CHECKBOXES
// =====================
function renderPlayerCheckboxes() {
    const container = document.getElementById('player-checkboxes');
    container.innerHTML = state.allPlayers.map(p => `
        <label class="warrior-entry">
            <input type="checkbox" value="${p.name}" checked>
            <span class="warrior-name">${p.name}</span>
            <span class="warrior-rating">${p.mu_scaled.toFixed(0)}</span>
        </label>
    `).join('');
}

function getSelectedPlayers() {
    return Array.from(document.querySelectorAll('#player-checkboxes input:checked'))
        .map(cb => cb.value);
}

function selectAllPlayers() {
    document.querySelectorAll('#player-checkboxes input').forEach(cb => cb.checked = true);
}

function clearAllPlayers() {
    document.querySelectorAll('#player-checkboxes input').forEach(cb => cb.checked = false);
}

// =====================
// TEAM GENERATION
// =====================
async function generateTeams() {
    const players = getSelectedPlayers();
    if (players.length < 2) {
        alert('Select at least 2 warriors.');
        return;
    }

    const container = document.getElementById('suggestions-content');
    const placeholder = document.getElementById('suggestions-placeholder');
    container.innerHTML = '<div class="empty-state"><div class="loading-text">Forging battle plans...</div></div>';
    container.style.display = '';
    placeholder.style.display = 'none';

    try {
        const res = await fetch('/api/teams/generate', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ players, top_n: 5 }),
        });
        const data = await res.json();
        if (data.error) {
            container.innerHTML = `<div class="empty-state"><p style="color:var(--red-bright)">${data.error}</p></div>`;
            return;
        }
        SoundFX.forge();
        renderSuggestions(data);
    } catch (err) {
        container.innerHTML = '<div class="empty-state"><p style="color:var(--red-bright)">Request failed.</p></div>';
        console.error(err);
    }
}

function renderSuggestions(data) {
    const container = document.getElementById('suggestions-content');
    container.innerHTML = '';

    if (data.warnings && data.warnings.length > 0) {
        container.innerHTML = `<p class="warnings-bar">${data.warnings.join(', ')}</p>`;
    }

    data.suggestions.forEach((s, i) => {
        const card = document.createElement('div');
        card.className = 'suggestion-card';
        card.style.animationDelay = `${i * 0.08}s`;

        const changesId = `changes-${i}`;
        let changesHtml = '';
        if (s.rating_changes && Object.keys(s.rating_changes).length > 0) {
            changesHtml = `
                <div class="bp-changes-wrap">
                    <button class="card-changes-toggle" onclick="toggleChanges('${changesId}', this)">Show rating changes</button>
                    <div class="card-changes" id="${changesId}">
                        <div class="card-changes-grid">
                            <div>
                                ${s.team1.map(p => ratingChangeRowInline(p.name, s.rating_changes)).join('')}
                            </div>
                            <div>
                                ${s.team2.map(p => ratingChangeRowInline(p.name, s.rating_changes)).join('')}
                            </div>
                        </div>
                    </div>
                </div>
            `;
        }

        const t1Avg = s.team1.reduce((sum, p) => sum + p.rating, 0) / s.team1.length;
        const t2Avg = s.team2.reduce((sum, p) => sum + p.rating, 0) / s.team2.length;
        const totalAvg = t1Avg + t2Avg;
        const t1Pct = totalAvg > 0 ? (t1Avg / totalAvg * 100) : 50;

        const quality = s.match_quality;
        const qualityClass = quality >= 90 ? 'quality-excellent' : quality >= 80 ? 'quality-good' : quality >= 70 ? 'quality-fair' : 'quality-poor';

        // Determine which team is favored (1, 2, or 0 for even)
        const favored = s.expected_winner.includes('1') ? 1 : s.expected_winner.includes('2') ? 2 : 0;

        const renderPlayer = (p) => {
            const hasBoost = p.recommended_hc > 100;
            return `<div class="bp-player">
                <span class="bp-player-name"><a class="player-link" onclick="openPlayerProfile('${p.name}')">${p.name}</a></span>
                <span class="bp-player-hc ${hasBoost ? 'bp-hc-active' : ''}">${p.recommended_hc}%</span>
            </div>`;
        };

        card.innerHTML = `
            <div class="bp-accent ${qualityClass}"></div>
            <div class="bp-header">
                <div class="bp-plan-id">
                    <span class="bp-number">#${i + 1}</span>
                    <span class="bp-label">Battle Plan</span>
                </div>
                <div class="bp-quality ${qualityClass}">
                    <span class="bp-quality-value">${quality.toFixed(1)}<small>%</small></span>
                    <span class="bp-quality-label">Quality</span>
                </div>
            </div>

            <div class="bp-strength">
                <div class="bp-strength-track">
                    <div class="bp-strength-fill" style="width: ${t1Pct.toFixed(1)}%"></div>
                </div>
                <div class="bp-strength-labels">
                    <span>avg ${t1Avg.toFixed(0)}</span>
                    <span>avg ${t2Avg.toFixed(0)}</span>
                </div>
            </div>

            <div class="bp-teams">
                <div class="bp-team ${favored === 1 ? 'bp-team-favored' : ''}">
                    <div class="bp-team-header">Team I${favored === 1 ? ' <span class="bp-favored-icon">&#9734;</span>' : ''}</div>
                    <div class="bp-team-roster">
                        ${s.team1.map(renderPlayer).join('')}
                    </div>
                </div>
                <div class="bp-vs">&#9876;</div>
                <div class="bp-team ${favored === 2 ? 'bp-team-favored' : ''}">
                    <div class="bp-team-header">Team II${favored === 2 ? ' <span class="bp-favored-icon">&#9734;</span>' : ''}</div>
                    <div class="bp-team-roster">
                        ${s.team2.map(renderPlayer).join('')}
                    </div>
                </div>
            </div>

            ${s.benched && s.benched.length > 0 ? `
            <div class="bp-bench">
                <span class="bp-bench-label">Resting</span>
                <span class="bp-bench-names">${s.benched.map(p => p.name).join(', ')}</span>
            </div>` : ''}

            ${changesHtml}

            <div class="bp-footer">
                <button class="btn-primary" onclick='useSetup(${JSON.stringify(s)})'>Deploy</button>
            </div>
        `;
        container.appendChild(card);
    });
}

function ratingChangeRowInline(name, changes) {
    const c = changes[name];
    if (!c) return '';
    return `<div class="rating-change">
        <span class="change-name">${name}</span>
        <div class="change-values">
            <span class="win-val">${c.win >= 0 ? '+' : ''}${c.win.toFixed(1)}</span>
            <span class="loss-val">${c.loss >= 0 ? '+' : ''}${c.loss.toFixed(1)}</span>
        </div>
    </div>`;
}

function toggleChanges(id, btn) {
    const el = document.getElementById(id);
    el.classList.toggle('visible');
    btn.textContent = el.classList.contains('visible') ? 'Hide rating changes' : 'Show rating changes';
}

// =====================
// USE SETUP / GAME VIEW
// =====================
function useSetup(suggestion) {
    SoundFX.horn();
    state.currentTeam1 = suggestion.team1;
    state.currentTeam2 = suggestion.team2;
    state.benched = suggestion.benched || [];
    state.ratingChanges = suggestion.rating_changes || {};
    state.matchQuality = suggestion.match_quality;
    state.expectedWinner = suggestion.expected_winner;
    navigateTo('game');
    renderGameView();
}

function renderGameView() {
    document.getElementById('game-empty').style.display = 'none';
    document.getElementById('manual-setup').style.display = 'none';
    document.getElementById('game-content').style.display = '';
    document.getElementById('rebalance-results').style.display = 'none';

    document.getElementById('game-quality').textContent =
        state.matchQuality != null ? state.matchQuality.toFixed(1) + '%' : '-';
    document.getElementById('game-expected').textContent = state.expectedWinner || '-';

    const t1Avg = state.currentTeam1.reduce((sum, p) => sum + p.rating, 0) / state.currentTeam1.length;
    const t2Avg = state.currentTeam2.reduce((sum, p) => sum + p.rating, 0) / state.currentTeam2.length;
    document.getElementById('t1-avg').textContent = t1Avg.toFixed(0);
    document.getElementById('t2-avg').textContent = t2Avg.toFixed(0);

    document.getElementById('team1-players').innerHTML =
        state.currentTeam1.map(p => playerCard(p)).join('');
    document.getElementById('team2-players').innerHTML =
        state.currentTeam2.map(p => playerCard(p)).join('');

    const benchEl = document.getElementById('bench-section');
    if (state.benched && state.benched.length > 0) {
        benchEl.style.display = '';
        benchEl.innerHTML = `
            <div class="bench-title">Resting Warriors</div>
            <div class="bench-roster">
                ${state.benched.map(p => `
                    <div class="bench-player">
                        <span class="name"><a class="player-link" onclick="openPlayerProfile('${p.name}')">${p.name}</a></span>
                        <span class="bench-rating">${p.rating.toFixed(0)}</span>
                    </div>
                `).join('')}
            </div>
        `;
    } else {
        benchEl.style.display = 'none';
    }

    const hasChanges = Object.keys(state.ratingChanges).length > 0;
    document.getElementById('rating-changes-section').style.display = hasChanges ? '' : 'none';
    if (hasChanges) {
        document.getElementById('t1-changes').innerHTML =
            state.currentTeam1.map(p => ratingChangeRow(p.name)).join('');
        document.getElementById('t2-changes').innerHTML =
            state.currentTeam2.map(p => ratingChangeRow(p.name)).join('');
    }
}

function playerCard(p) {
    const bonusClass = p.recommended_hc > 100 ? ' has-bonus' : '';
    return `<div class="player-card">
        <span class="name"><a class="player-link" onclick="openPlayerProfile('${p.name}')">${p.name}</a></span>
        <span class="hc-badge${bonusClass}">${p.recommended_hc}%</span>
    </div>`;
}

function ratingChangeRow(name) {
    const c = state.ratingChanges[name];
    if (!c) return '';
    return `<div class="rating-change">
        <span class="change-name">${name}</span>
        <div class="change-values">
            <span class="win-val">${c.win >= 0 ? '+' : ''}${c.win.toFixed(1)}</span>
            <span class="loss-val">${c.loss >= 0 ? '+' : ''}${c.loss.toFixed(1)}</span>
        </div>
    </div>`;
}

// =====================
// MANUAL SETUP
// =====================
function goToManualSetup() {
    const players = getSelectedPlayers();
    if (players.length < 2) {
        alert('Select at least 2 warriors.');
        return;
    }

    state.manualAssignments = {};
    players.forEach(name => { state.manualAssignments[name] = 'unassigned'; });

    navigateTo('game');
    document.getElementById('game-empty').style.display = 'none';
    document.getElementById('game-content').style.display = 'none';
    document.getElementById('manual-setup').style.display = '';
    renderManualSetup();
}

function renderManualSetup() {
    const unassigned = [];
    const team1 = [];
    const team2 = [];

    for (const [name, assignment] of Object.entries(state.manualAssignments)) {
        const player = state.allPlayers.find(p => p.name === name);
        const rating = player ? player.mu_scaled.toFixed(0) : '?';
        const html = `<div class="manual-player" onclick="cycleAssignment('${name}')">
            <span class="mp-name">${name}</span>
            <span class="mp-rating">${rating}</span>
        </div>`;
        if (assignment === 'team1') team1.push(html);
        else if (assignment === 'team2') team2.push(html);
        else unassigned.push(html);
    }

    document.getElementById('manual-unassigned').innerHTML =
        unassigned.join('') || '<p class="manual-empty">Empty</p>';
    document.getElementById('manual-team1').innerHTML =
        team1.join('') || '<p class="manual-empty">Click to assign</p>';
    document.getElementById('manual-team2').innerHTML =
        team2.join('') || '<p class="manual-empty">Click to assign</p>';
}

function cycleAssignment(name) {
    const current = state.manualAssignments[name];
    if (current === 'unassigned') state.manualAssignments[name] = 'team1';
    else if (current === 'team1') state.manualAssignments[name] = 'team2';
    else state.manualAssignments[name] = 'unassigned';
    renderManualSetup();
}

function confirmManualSetup() {
    const t1Names = Object.entries(state.manualAssignments)
        .filter(([, a]) => a === 'team1').map(([n]) => n);
    const t2Names = Object.entries(state.manualAssignments)
        .filter(([, a]) => a === 'team2').map(([n]) => n);

    if (t1Names.length === 0 || t2Names.length === 0) {
        alert('Both armies need at least 1 warrior.');
        return;
    }

    SoundFX.horn();

    const findPlayer = name => {
        const p = state.allPlayers.find(pl => pl.name === name);
        return p ? {
            name: p.name,
            rating: p.mu_scaled,
            recommended_hc: p.recommended_hc,
            games_played: p.games_played,
        } : { name, rating: 0, recommended_hc: 100, games_played: 0 };
    };

    state.currentTeam1 = t1Names.sort().map(findPlayer);
    state.currentTeam2 = t2Names.sort().map(findPlayer);
    state.ratingChanges = {};
    state.matchQuality = null;
    state.expectedWinner = null;
    renderGameView();
}

function cancelManualSetup() {
    document.getElementById('manual-setup').style.display = 'none';
    document.getElementById('game-empty').style.display = '';
}

// =====================
// REBALANCE
// =====================
async function markWeaker(teamNum) {
    const team1 = state.currentTeam1.map(p => p.name);
    const team2 = state.currentTeam2.map(p => p.name);

    const container = document.getElementById('rebalance-results');
    container.innerHTML = '<div class="empty-state"><div class="loading-text">Calculating rebalance...</div></div>';
    container.style.display = '';

    try {
        const res = await fetch('/api/teams/rebalance', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ team1, team2, weaker_team: teamNum, top_n: 5 }),
        });
        const data = await res.json();
        if (data.error) {
            container.innerHTML = `<p style="color:var(--red-bright);text-align:center;padding:1rem">${data.error}</p>`;
            return;
        }
        SoundFX.clash();
        renderRebalanceResults(data);
    } catch (err) {
        container.innerHTML = '<p style="color:var(--red-bright);text-align:center;padding:1rem">Request failed.</p>';
        console.error(err);
    }
}

function renderRebalanceResults(data) {
    const container = document.getElementById('rebalance-results');

    if (!data.suggestions || data.suggestions.length === 0) {
        container.innerHTML = '<p class="manual-empty" style="padding:1.5rem">No single swap or move can help the weaker army.</p>';
        return;
    }

    container.innerHTML = '<p class="rebalance-results-title">Strategies (smallest change first)</p>';

    data.suggestions.forEach((s, i) => {
        const card = document.createElement('div');
        card.className = 'rebalance-card';
        card.style.animationDelay = `${i * 0.06}s`;
        card.innerHTML = `
            <div class="rebalance-desc">#${i + 1}: ${s.description}</div>
            <div class="rebalance-meta">
                Weaker army gains +${s.rating_gain} rating &middot; Quality: ${s.match_quality.toFixed(1)}%
            </div>
            <div class="rebalance-teams">
                <div>
                    <strong>Team I</strong><br>
                    ${s.team1.map(p => `${p.name} (${p.recommended_hc}%)`).join('<br>')}
                </div>
                <div class="rebalance-vs">VS</div>
                <div>
                    <strong>Team II</strong><br>
                    ${s.team2.map(p => `${p.name} (${p.recommended_hc}%)`).join('<br>')}
                </div>
            </div>
            <div class="rebalance-footer">
                <button class="btn-primary btn-small" onclick='applyRebalance(${JSON.stringify(s)})'>Apply</button>
            </div>
        `;
        container.appendChild(card);
    });
}

function applyRebalance(suggestion) {
    state.currentTeam1 = suggestion.team1;
    state.currentTeam2 = suggestion.team2;
    state.ratingChanges = {};
    state.matchQuality = suggestion.match_quality;
    state.expectedWinner = null;
    renderGameView();
}

// =====================
// INIT
// =====================
fetchPlayers();
handleRoute(); // Restore tab/modal from current URL hash
