// =====================
// ADMIN MODULE
// =====================

let adminApiKey = sessionStorage.getItem('adminApiKey') || '';
let adminRebuildPollTimer = null;

function adminHeaders() {
    return { 'X-API-Key': adminApiKey, 'Content-Type': 'application/json' };
}

function adminOnTabOpen() {
    if (adminApiKey) {
        document.getElementById('admin-auth').style.display = 'none';
        document.getElementById('admin-dashboard').style.display = '';
        adminFetchHealth();
        adminFetchGames();
    } else {
        document.getElementById('admin-auth').style.display = '';
        document.getElementById('admin-dashboard').style.display = 'none';
        const input = document.getElementById('admin-key-input');
        input.value = '';
        input.focus();
    }
}

async function adminLogin() {
    const key = document.getElementById('admin-key-input').value.trim();
    if (!key) return;

    const errEl = document.getElementById('admin-auth-error');
    errEl.style.display = 'none';

    try {
        const res = await fetch('/api/admin/health', {
            headers: { 'X-API-Key': key },
        });
        if (res.status === 401) {
            errEl.textContent = 'Invalid API key.';
            errEl.style.display = '';
            return;
        }
        if (!res.ok) {
            errEl.textContent = `Server error (${res.status}).`;
            errEl.style.display = '';
            return;
        }
        adminApiKey = key;
        sessionStorage.setItem('adminApiKey', key);
        document.getElementById('admin-auth').style.display = 'none';
        document.getElementById('admin-dashboard').style.display = '';
        const data = await res.json();
        renderAdminHealth(data);
        adminFetchGames();
    } catch (err) {
        errEl.textContent = 'Connection failed.';
        errEl.style.display = '';
        console.error(err);
    }
}

// Allow Enter key to submit
document.addEventListener('DOMContentLoaded', () => {
    const input = document.getElementById('admin-key-input');
    if (input) input.addEventListener('keydown', (e) => { if (e.key === 'Enter') adminLogin(); });
});

async function adminFetchHealth() {
    const loading = document.getElementById('admin-health-loading');
    const container = document.getElementById('admin-health-cards');
    loading.style.display = '';
    container.style.display = 'none';

    try {
        const res = await fetch('/api/admin/health', { headers: adminHeaders() });
        if (res.status === 401) { adminLogout(); return; }
        const data = await res.json();
        renderAdminHealth(data);
    } catch (err) {
        loading.innerHTML = '<div class="loading-text">Failed to load health data.</div>';
        console.error(err);
    }
}

function renderAdminHealth(data) {
    const loading = document.getElementById('admin-health-loading');
    const container = document.getElementById('admin-health-cards');
    loading.style.display = 'none';
    container.style.display = '';

    const sc = data.status_counts || {};
    const processed = sc.processed || 0;
    const statusBreakdown = Object.entries(sc)
        .map(([k, v]) => `<span class="admin-status-tag admin-status-${k}">${k}: ${v}</span>`)
        .join(' ');

    const dateRange = data.date_range || {};
    const earliest = dateRange.earliest ? dateRange.earliest.slice(0, 10) : 'N/A';
    const latest = dateRange.latest ? dateRange.latest.slice(0, 10) : 'N/A';
    const lastUpdated = data.last_updated ? new Date(data.last_updated).toLocaleString() : 'Never';

    container.innerHTML = `
        <div class="admin-card">
            <div class="admin-card-value">${data.total_games}</div>
            <div class="admin-card-label">Total Games</div>
        </div>
        <div class="admin-card">
            <div class="admin-card-value">${processed}</div>
            <div class="admin-card-label">Processed</div>
        </div>
        <div class="admin-card">
            <div class="admin-card-value">${data.total_players}</div>
            <div class="admin-card-label">Players</div>
        </div>
        <div class="admin-card">
            <div class="admin-card-value">${data.db_size_mb} MB</div>
            <div class="admin-card-label">DB Size</div>
        </div>
        <div class="admin-card admin-card-wide">
            <div class="admin-card-value" style="font-size:0.9rem">${earliest} &mdash; ${latest}</div>
            <div class="admin-card-label">Date Range</div>
        </div>
        <div class="admin-card admin-card-wide">
            <div class="admin-card-value" style="font-size:0.85rem">${lastUpdated}</div>
            <div class="admin-card-label">Last Rebuild${data.rebuild_pending ? ' <span class="admin-badge">Pending</span>' : ''}</div>
        </div>
        <div class="admin-status-breakdown">${statusBreakdown}</div>
    `;
}

function adminLogout() {
    adminApiKey = '';
    sessionStorage.removeItem('adminApiKey');
    document.getElementById('admin-auth').style.display = '';
    document.getElementById('admin-dashboard').style.display = 'none';
}

// --- Full Rebuild ---

async function adminFullRebuild() {
    const btn = document.getElementById('admin-rebuild-btn');
    const statusEl = document.getElementById('admin-rebuild-status');
    btn.disabled = true;
    btn.textContent = 'Starting...';
    statusEl.style.display = '';
    statusEl.innerHTML = '<div class="loading-text">Initiating rebuild...</div>';

    try {
        const res = await fetch('/api/rebuild', {
            method: 'POST',
            headers: adminHeaders(),
        });
        if (res.status === 401) { adminLogout(); return; }
        const data = await res.json();

        if (data.error) {
            statusEl.innerHTML = `<div class="admin-error">${data.error}</div>`;
            btn.disabled = false;
            btn.textContent = 'Start Full Rebuild';
            return;
        }

        statusEl.innerHTML = `<div class="admin-info">${data.message || 'Rebuild started.'}</div>`;
        adminPollRebuild();
    } catch (err) {
        statusEl.innerHTML = '<div class="admin-error">Failed to start rebuild.</div>';
        btn.disabled = false;
        btn.textContent = 'Start Full Rebuild';
        console.error(err);
    }
}

function adminPollRebuild() {
    if (adminRebuildPollTimer) clearInterval(adminRebuildPollTimer);
    adminRebuildPollTimer = setInterval(async () => {
        try {
            const res = await fetch('/api/rebuild/status', { headers: adminHeaders() });
            if (res.status === 401) { adminLogout(); clearInterval(adminRebuildPollTimer); return; }
            const data = await res.json();
            const statusEl = document.getElementById('admin-rebuild-status');
            const btn = document.getElementById('admin-rebuild-btn');
            const progress = data.progress || {};
            const phase = progress.phase || data.status || 'unknown';
            const current = progress.current || 0;
            const total = progress.total || 0;
            const counts = progress.counts || {};

            let html = `<div class="admin-rebuild-progress">`;
            html += `<div class="admin-progress-phase">Phase: <strong>${phase}</strong></div>`;
            if (total > 0) {
                const pct = Math.round((current / total) * 100);
                html += `<div class="admin-progress-bar-bg"><div class="admin-progress-bar-fill" style="width:${pct}%"></div></div>`;
                html += `<div class="admin-progress-text">${current} / ${total} (${pct}%)</div>`;
            }
            if (Object.keys(counts).length > 0) {
                html += '<div class="admin-progress-counts">';
                for (const [k, v] of Object.entries(counts)) {
                    html += `<span class="admin-status-tag admin-status-${k}">${k}: ${v}</span> `;
                }
                html += '</div>';
            }
            if (progress.duration_seconds) {
                html += `<div class="admin-progress-text">Completed in ${progress.duration_seconds}s</div>`;
            }
            html += '</div>';
            statusEl.innerHTML = html;

            if (data.status === 'complete' || phase === 'done') {
                clearInterval(adminRebuildPollTimer);
                adminRebuildPollTimer = null;
                btn.disabled = false;
                btn.textContent = 'Start Full Rebuild';
                adminFetchHealth();
            }
        } catch (err) {
            console.error('Rebuild poll error:', err);
        }
    }, 2000);
}

// --- Sync from Disk ---

async function adminSyncFromDisk() {
    const btn = document.getElementById('admin-sync-btn');
    const resultEl = document.getElementById('admin-sync-result');
    btn.disabled = true;
    btn.textContent = 'Syncing...';
    resultEl.style.display = '';
    resultEl.innerHTML = '<div class="loading-text">Scanning replay directory...</div>';

    try {
        const res = await fetch('/api/admin/sync-from-disk', {
            method: 'POST',
            headers: adminHeaders(),
        });
        if (res.status === 401) { adminLogout(); return; }
        const data = await res.json();

        if (data.error) {
            resultEl.innerHTML = `<div class="admin-error">${data.error}</div>`;
        } else {
            const bd = data.status_breakdown || {};
            let bdHtml = Object.entries(bd).map(([k, v]) => `${k}: ${v}`).join(', ');
            resultEl.innerHTML = `
                <div class="admin-sync-summary">
                    <p><strong>${data.new || 0}</strong> new games added</p>
                    <p>${data.skipped_existing || 0} already in registry, ${data.skipped_duplicate || 0} fingerprint duplicates</p>
                    <p>Total files scanned: ${data.total_files || 0}</p>
                    ${bdHtml ? `<p>Breakdown: ${bdHtml}</p>` : ''}
                </div>
            `;
            adminFetchHealth();
        }
    } catch (err) {
        resultEl.innerHTML = '<div class="admin-error">Sync request failed.</div>';
        console.error(err);
    } finally {
        btn.disabled = false;
        btn.textContent = 'Sync Now';
    }
}

// --- Game Management ---

async function adminFetchGames() {
    const status = document.getElementById('admin-status-filter').value;
    const loading = document.getElementById('admin-games-loading');
    const container = document.getElementById('admin-games-container');
    loading.style.display = '';
    container.innerHTML = '';

    try {
        const res = await fetch(`/api/admin/games?status=${encodeURIComponent(status)}`, {
            headers: adminHeaders(),
        });
        if (res.status === 401) { adminLogout(); return; }
        const data = await res.json();
        loading.style.display = 'none';

        if (data.error) {
            container.innerHTML = `<div class="admin-error">${data.error}</div>`;
            return;
        }

        if (data.games.length === 0) {
            container.innerHTML = `<div class="empty-state"><p>No games with status "${status}".</p></div>`;
            return;
        }

        const showStatus = status === 'all';
        let html = `<div class="admin-games-count">${data.total} game(s)</div>`;
        html += '<div class="table-wrapper"><table class="admin-games-table"><thead><tr>';
        html += '<th>SHA256</th><th>Filename</th><th>Date</th>';
        if (showStatus) html += '<th>Status</th>';
        html += '<th>Duration</th><th>Players</th><th>Actions</th>';
        html += '</tr></thead><tbody>';

        for (const g of data.games) {
            const teams = g.teams || {};
            const teamEntries = Object.entries(teams);
            const players = teamEntries.length > 0
                ? teamEntries.map(([tid, names]) => `<span class="admin-team-group"><span class="admin-team-label">T${tid}</span>${names.join(', ')}</span>`).join(' <span class="admin-team-vs">vs</span> ')
                : 'N/A';
            const dur = g.duration_seconds ? `${Math.round(g.duration_seconds / 60)}m` : '-';
            const date = g.datetime ? g.datetime.slice(0, 16).replace('T', ' ') : 'N/A';

            // Build actions cell
            let actions = '';
            if (g.status === 'no_winner' && Object.keys(teams).length > 0) {
                const teamEntries = Object.entries(teams);
                for (const [tid, names] of teamEntries) {
                    const label = names.join(', ');
                    actions += `<button class="btn-admin btn-admin-sm btn-set-winner" `
                        + `onclick="adminSetWinner('${g.sha256}', '${tid}')" `
                        + `title="Set Team ${tid} as winner: ${label}">`
                        + `T${tid} wins</button> `;
                }
            }
            actions += `<button class="btn-admin btn-admin-sm btn-danger" onclick="adminDeleteGame('${g.sha256}')">Delete</button>`;

            html += `<tr>
                <td class="admin-sha" title="${g.sha256}">${g.sha256.slice(0, 12)}...</td>
                <td>${g.filename || 'N/A'}</td>
                <td>${date}</td>`;
            if (showStatus) html += `<td><span class="admin-status-tag admin-status-${g.status}">${g.status}</span></td>`;
            html += `<td>${dur}</td>
                <td>${players}</td>
                <td class="admin-actions-cell">${actions}</td>
            </tr>`;
        }

        html += '</tbody></table></div>';
        container.innerHTML = html;
    } catch (err) {
        loading.style.display = 'none';
        container.innerHTML = '<div class="admin-error">Failed to load games.</div>';
        console.error(err);
    }
}

async function adminDeleteGame(sha256) {
    if (!confirm(`Delete game ${sha256.slice(0, 12)}...? This cannot be undone.`)) return;

    try {
        const res = await fetch(`/api/admin/games/${sha256}`, {
            method: 'DELETE',
            headers: adminHeaders(),
        });
        if (res.status === 401) { adminLogout(); return; }
        const data = await res.json();

        if (data.error) {
            alert(`Error: ${data.error}`);
            return;
        }

        adminFetchGames();
        adminFetchHealth();
    } catch (err) {
        alert('Delete request failed.');
        console.error(err);
    }
}

async function adminSetWinner(sha256, teamId) {
    if (!confirm(`Set Team ${teamId} as winner for game ${sha256.slice(0, 12)}...?`)) return;

    try {
        const res = await fetch(`/api/admin/games/${sha256}/set-winner`, {
            method: 'POST',
            headers: adminHeaders(),
            body: JSON.stringify({ winning_team_id: teamId }),
        });
        if (res.status === 401) { adminLogout(); return; }
        const data = await res.json();

        if (data.error) {
            alert(`Error: ${data.error}`);
            return;
        }

        adminFetchGames();
        adminFetchHealth();
    } catch (err) {
        alert('Set winner request failed.');
        console.error(err);
    }
}

