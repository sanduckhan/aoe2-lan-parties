const state = {
    allPlayers: [],
    currentTeam1: [],
    currentTeam2: [],
    ratingChanges: {},
    matchQuality: null,
    expectedWinner: null,
    manualAssignments: {},
};

// ---- Tab switching ----
document.querySelectorAll('.tab').forEach(btn => {
    btn.addEventListener('click', () => switchTab(btn.dataset.tab));
});

function switchTab(tabId) {
    document.querySelectorAll('.tab').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(s => s.classList.remove('active'));
    document.querySelector(`.tab[data-tab="${tabId}"]`).classList.add('active');
    document.getElementById(tabId).classList.add('active');
}

// ---- Ratings ----
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
            <td class="col-name">${p.name}</td>
            <td class="col-rating">${p.mu_scaled.toFixed(0)}</td>
            <td class="col-hc">${p.avg_handicap_last_30 > 100 ? p.avg_handicap_last_30.toFixed(0) + '%' : '100%'}</td>
            <td class="col-hc">${p.recommended_hc}%</td>
            <td class="col-games">${p.games_played}</td>
            <td class="col-conf">${p.confidence_percent.toFixed(1)}%</td>
        </tr>`;
    }).join('');
}

// ---- Player Checkboxes ----
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

// ---- Team Generation ----
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
            `;
        }

        const t1Avg = (s.team1.reduce((sum, p) => sum + p.rating, 0) / s.team1.length).toFixed(0);
        const t2Avg = (s.team2.reduce((sum, p) => sum + p.rating, 0) / s.team2.length).toFixed(0);

        card.innerHTML = `
            <div class="card-header">
                <h3>Battle Plan #${i + 1}</h3>
                <span class="card-quality">Quality: ${s.match_quality.toFixed(1)}%</span>
            </div>
            <div class="card-teams">
                <div>
                    <div class="card-team-label">Team I <span class="card-team-avg">&mdash; avg ${t1Avg}</span></div>
                    <ul class="card-team-list">
                        ${s.team1.map(p => `<li>${p.name} <span class="player-hc">${p.recommended_hc}%</span></li>`).join('')}
                    </ul>
                </div>
                <div class="card-vs">VS</div>
                <div>
                    <div class="card-team-label">Team II <span class="card-team-avg">&mdash; avg ${t2Avg}</span></div>
                    <ul class="card-team-list">
                        ${s.team2.map(p => `<li>${p.name} <span class="player-hc">${p.recommended_hc}%</span></li>`).join('')}
                    </ul>
                </div>
            </div>
            ${changesHtml}
            <div class="card-footer">
                <span class="card-expected">Expected: ${s.expected_winner}</span>
                <button class="btn-primary btn-small" onclick='useSetup(${JSON.stringify(s)})'>Deploy</button>
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

// ---- Use Setup / Game View ----
function useSetup(suggestion) {
    state.currentTeam1 = suggestion.team1;
    state.currentTeam2 = suggestion.team2;
    state.ratingChanges = suggestion.rating_changes || {};
    state.matchQuality = suggestion.match_quality;
    state.expectedWinner = suggestion.expected_winner;
    switchTab('game');
    renderGameView();
}

function renderGameView() {
    document.getElementById('game-empty').style.display = 'none';
    document.getElementById('manual-setup').style.display = 'none';
    document.getElementById('game-content').style.display = '';
    document.getElementById('rebalance-results').style.display = 'none';

    // Match header
    document.getElementById('game-quality').textContent =
        state.matchQuality != null ? state.matchQuality.toFixed(1) + '%' : '-';
    document.getElementById('game-expected').textContent = state.expectedWinner || '-';

    // Team avg
    const t1Avg = state.currentTeam1.reduce((sum, p) => sum + p.rating, 0) / state.currentTeam1.length;
    const t2Avg = state.currentTeam2.reduce((sum, p) => sum + p.rating, 0) / state.currentTeam2.length;
    document.getElementById('t1-avg').textContent = t1Avg.toFixed(0);
    document.getElementById('t2-avg').textContent = t2Avg.toFixed(0);

    // Team players
    document.getElementById('team1-players').innerHTML =
        state.currentTeam1.map(p => playerCard(p)).join('');
    document.getElementById('team2-players').innerHTML =
        state.currentTeam2.map(p => playerCard(p)).join('');

    // Rating changes
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
        <span class="name">${p.name}</span>
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

// ---- Manual Setup ----
function goToManualSetup() {
    const players = getSelectedPlayers();
    if (players.length < 2) {
        alert('Select at least 2 warriors.');
        return;
    }

    state.manualAssignments = {};
    players.forEach(name => { state.manualAssignments[name] = 'unassigned'; });

    switchTab('game');
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

// ---- Rebalance ----
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

// ---- Init ----
fetchPlayers();
