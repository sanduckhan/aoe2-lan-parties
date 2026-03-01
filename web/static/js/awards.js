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
        const fmtTeam = (names, hcMap) => names.map(n => {
            const hc = hcMap && hcMap[n];
            const link = `<a class="player-link" onclick="openPlayerProfile('${n}')">${n}</a>`;
            return hc ? `${link} <span class="gc-hc">(${Math.round(hc)}%)</span>` : link;
        }).join(', ');
        const card = document.createElement('div');
        card.className = 'award-card award-card-wide';
        card.innerHTML = `
            <div class="award-icon">\u2696\uFE0F</div>
            <h3 class="award-title">Most Balanced Matchup</h3>
            <div class="matchup-display">
                <span>${fmtTeam(m.team_a, m.team_a_handicaps)}</span>
                <span class="matchup-vs">VS</span>
                <span>${fmtTeam(m.team_b, m.team_b_handicaps)}</span>
            </div>
            <div class="matchup-score">${m.wins_a} - ${m.wins_b}</div>
        `;
        grid.appendChild(card);
    }
}
