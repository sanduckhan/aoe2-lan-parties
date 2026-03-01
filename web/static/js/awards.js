// =====================
// AWARDS TAB
// =====================
const AWARD_DEFS = {
    favorite_unit_fanatic: { title: "Favorite Unit Fanatic", subtitle: "Each player's most spammed unit", icon: "\u2694\uFE0F", statLabel: "units created", valueKey: "count", perPlayer: true },
    bitter_salt_baron: { title: "The Bitter Salt Baron", subtitle: "Longest losing streak without a win", icon: "\u2620\uFE0F", statLabel: "losses in a row", valueKey: "streak" },
    wall_street_tycoon: { title: "Wall Street Tycoon", subtitle: "Most wall sections built across all games", icon: "\uD83E\uDDF1", statLabel: "wall sections built", valueKey: "count" },
    demolition_expert: { title: "Demolition Expert", subtitle: "Most own buildings deleted", icon: "\uD83D\uDCA5", statLabel: "buildings deleted", valueKey: "count" },
    market_mogul: { title: "The Market Mogul", subtitle: "Most market buys and sells", icon: "\u2696\uFE0F", statLabel: "market transactions", valueKey: "transactions" },
    forgetful_upgrades: { title: "Forgetful Commander", subtitle: "Most likely to skip crucial upgrades", icon: "\u2753", statLabel: "% forgetfulness", valueKey: "avg_forgetfulness" },
    jittery_fingers: { title: "Jittery Caffeinated Fingers", subtitle: "Highest average effective APM", icon: "\u26A1", statLabel: "avg eAPM", valueKey: "avg_eapm" },
    cheat_code: { title: "The Cheat Code", subtitle: "The person you want on your team", icon: "\uD83C\uDFAE", statLabel: "% win rate", valueKey: "win_rate", top3: true },
    stonks: { title: "Stonks", subtitle: "Rating line only goes up", icon: "\uD83D\uDCC8", statLabel: "rating gained", valueKey: "rating_gain", top3: true, eventOnly: true },
    not_stonks: { title: "Not Stonks", subtitle: "Rating line only goes down", icon: "\uD83D\uDCC9", statLabel: "rating lost", valueKey: "rating_loss", top3: true, eventOnly: true },
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
        renderAwards(data, eventId);
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

function applyAwardEvent(eventId) {
    const selector = document.getElementById('award-event-selector');
    selector.value = eventId;
    updateEventInfo(eventId);
    fetchAwards(eventId);
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
            // Update hash without re-triggering handleRoute (navigateTo is idempotent)
            navigateTo(eventId ? 'awards/' + encodeURIComponent(eventId) : 'awards');
            updateEventInfo(eventId);
            fetchAwards(eventId || undefined);
        });

        // Apply pending event from route (e.g. #awards/lan-2023-03-17)
        if (pendingAwardEvent) {
            applyAwardEvent(pendingAwardEvent);
            pendingAwardEvent = null;
        }
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

function renderAwards(data, eventId) {
    const grid = document.getElementById('awards-grid');
    grid.innerHTML = '';
    const isEvent = !!eventId;

    // Top-3 awards first (gold/silver/bronze)
    const medals = [
        { cls: '', symbol: '\u265B' },
        { cls: 'silver', symbol: '\u2726' },
        { cls: 'bronze', symbol: '\u2726' },
    ];
    for (const [key, def] of Object.entries(AWARD_DEFS)) {
        if (!def.top3) continue;
        if (def.eventOnly && !isEvent) continue;
        const entries = data[key];
        if (!entries || entries.length === 0) continue;

        const card = document.createElement('div');
        card.className = 'award-card';
        const rows = entries.slice(0, 3).map((e, i) => {
            const medal = medals[i] || medals[2];
            const val = key === 'stonks' ? `+${e[def.valueKey]}`
                : key === 'not_stonks' ? `-${e[def.valueKey]}`
                : `${e[def.valueKey]}%`;
            const rowClass = i === 0 ? 'award-winner' : 'award-runner-up';
            return `
                <div class="${rowClass}">
                    <span class="award-medal ${medal.cls}">${medal.symbol}</span>
                    <span class="award-name"><a class="player-link" onclick="openPlayerProfile('${e.player}')">${e.player}</a></span>
                    <span class="award-stat">${val} ${def.statLabel}</span>
                </div>`;
        }).join('');
        card.innerHTML = `
            <div class="award-icon">${def.icon}</div>
            <h3 class="award-title">${def.title}</h3>
            <p class="award-subtitle">${def.subtitle}</p>
            ${rows}
        `;
        grid.appendChild(card);
    }

    // Standard awards (winner + runner-up)
    for (const [key, def] of Object.entries(AWARD_DEFS)) {
        if (key === 'favorite_unit_fanatic' || def.top3) continue;
        const entries = data[key];
        if (!entries || entries.length === 0) continue;

        const winner = entries[0];
        const runnerUp = entries.length > 1 ? entries[1] : null;

        const card = document.createElement('div');
        card.className = 'award-card';
        card.innerHTML = `
            <div class="award-icon">${def.icon}</div>
            <h3 class="award-title">${def.title}</h3>
            <p class="award-subtitle">${def.subtitle}</p>
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

    // Bottom row: balanced matchup + favorite unit fanatic (50/50)
    const bottomRow = document.createElement('div');
    bottomRow.className = 'awards-bottom-row';

    // Balanced matchup
    if (data.balanced_matchup) {
        const m = data.balanced_matchup;
        const fmtTeam = (names, hcMap) => names.map(n => {
            const hc = hcMap && hcMap[n];
            const link = `<a class="player-link" onclick="openPlayerProfile('${n}')">${n}</a>`;
            return hc ? `${link} <span class="gc-hc">(${Math.round(hc)}%)</span>` : link;
        }).join(', ');
        const card = document.createElement('div');
        card.className = 'award-card';
        card.innerHTML = `
            <div class="award-icon">\u2696\uFE0F</div>
            <h3 class="award-title">Most Balanced Matchup</h3>
            <p class="award-subtitle">Closest head-to-head rivalry</p>
            <div class="matchup-display">
                <div class="matchup-team">${fmtTeam(m.team_a, m.team_a_handicaps)}</div>
                <div class="matchup-mid">
                    <span class="matchup-score">${m.wins_a}</span>
                    <span class="matchup-vs">VS</span>
                    <span class="matchup-score">${m.wins_b}</span>
                </div>
                <div class="matchup-team">${fmtTeam(m.team_b, m.team_b_handicaps)}</div>
            </div>
        `;
        bottomRow.appendChild(card);
    }

    // Favorite Unit Fanatic — per-player list
    if (data.favorite_unit_fanatic && data.favorite_unit_fanatic.length > 0) {
        const entries = data.favorite_unit_fanatic;
        const card = document.createElement('div');
        card.className = 'award-card';
        card.innerHTML = `
            <div class="award-icon">\u2694\uFE0F</div>
            <h3 class="award-title">Favorite Unit Fanatic</h3>
            <p class="award-subtitle">Each player's most spammed unit</p>
            <div class="award-per-player">
                ${entries.map((e, i) => `
                    <div class="award-entry ${i === 0 ? 'award-winner' : ''}">
                        <span class="award-name"><a class="player-link" onclick="openPlayerProfile('${e.player}')">${e.player}</a></span>
                        <span class="award-stat">${e.unit} (${e.count})</span>
                    </div>
                `).join('')}
            </div>
        `;
        bottomRow.appendChild(card);
    }

    if (bottomRow.children.length > 0) {
        grid.appendChild(bottomRow);
    }
}
