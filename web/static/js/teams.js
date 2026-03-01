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
    saveTeamState();
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
    saveTeamState();
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
    saveTeamState();
    renderGameView();
}

