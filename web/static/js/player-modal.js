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
