// =====================
// SOUND EFFECTS MODULE
// =====================
var SoundFX = (() => {
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

function toggleMobileNav() {
    const nav = document.getElementById('header-nav');
    nav.classList.toggle('open');
    document.body.classList.toggle('nav-open');
}

// =====================
// STATE
// =====================
var state = {
    allPlayers: [],
    currentTeam1: [],
    currentTeam2: [],
    benched: [],
    ratingChanges: {},
    matchQuality: null,
    expectedWinner: null,
    manualAssignments: {},
};

// ---- Persist team selections across refreshes ----
var TEAM_STATE_KEY = 'aoe2_team_state';

function saveTeamState() {
    try {
        localStorage.setItem(TEAM_STATE_KEY, JSON.stringify({
            currentTeam1: state.currentTeam1,
            currentTeam2: state.currentTeam2,
            benched: state.benched,
            ratingChanges: state.ratingChanges,
            matchQuality: state.matchQuality,
            expectedWinner: state.expectedWinner,
        }));
    } catch (e) { /* ignore quota errors */ }
}

function restoreTeamState() {
    try {
        const raw = localStorage.getItem(TEAM_STATE_KEY);
        if (!raw) return false;
        const saved = JSON.parse(raw);
        if (!saved.currentTeam1 || saved.currentTeam1.length === 0) return false;
        state.currentTeam1 = saved.currentTeam1;
        state.currentTeam2 = saved.currentTeam2;
        state.benched = saved.benched || [];
        state.ratingChanges = saved.ratingChanges || {};
        state.matchQuality = saved.matchQuality;
        state.expectedWinner = saved.expectedWinner;
        return true;
    } catch (e) { return false; }
}

// ---- Tab switching & hash routing ----
var awardsFetched = false;
var historyFetched = false;
let lanEventsFetched = false;
let lanEventsData = [];
var pendingAwardEvent = null;

var VALID_TABS = ['ratings', 'awards', 'history', 'generator', 'game', 'methodology', 'uploader', 'admin'];

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

    // Close mobile nav on tab switch
    const nav = document.getElementById('header-nav');
    if (nav) nav.classList.remove('open');
    document.body.classList.remove('nav-open');

    // Close player modal if open and we're navigating to a tab
    const modal = document.getElementById('player-modal');
    if (modal.style.display !== 'none') {
        modal.style.display = 'none';
        document.body.classList.remove('modal-open');
    }

    // Lazy-load tabs
    if (tabId === 'awards' && !awardsFetched) {
        awardsFetched = true;
        // If routed with an event, fetchLanEvents will apply it after populating the dropdown
        if (!pendingAwardEvent) fetchAwards();
        fetchLanEvents();
    } else if (tabId === 'awards' && pendingAwardEvent) {
        // Already loaded — apply the event directly
        applyAwardEvent(pendingAwardEvent);
        pendingAwardEvent = null;
    }
    if (tabId === 'history' && !historyFetched) {
        historyFetched = true;
        fetchGameHistory();
    }
    if (tabId === 'game' && state.currentTeam1.length === 0) {
        if (restoreTeamState()) renderGameView();
    }
    if (tabId === 'admin') {
        adminOnTabOpen();
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

    // Awards event route: #awards/<eventId>
    if (hash.startsWith('awards/')) {
        const eventId = decodeURIComponent(hash.slice('awards/'.length));
        if (eventId) {
            pendingAwardEvent = eventId;
            switchTab('awards');
            return;
        }
    }

    // Game deep-link route: #history/<sha256>
    if (hash.startsWith('history/')) {
        const sha = hash.slice('history/'.length);
        if (sha) {
            switchTab('history');
            scrollToGame(sha);
            return;
        }
    }

    // Tab route
    if (VALID_TABS.includes(hash)) {
        // Reset event selector when navigating to #awards (all-time)
        if (hash === 'awards' && awardsFetched) {
            pendingAwardEvent = null;
            applyAwardEvent('');
        }
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
            <td class="col-rating col-rating-link" onclick="showPlayerOnChart('${p.name}')">${p.mu_scaled.toFixed(0)}</td>
            <td class="col-hc">${p.avg_handicap_last_30 > 100 ? p.avg_handicap_last_30.toFixed(0) + '%' : '100%'}</td>
            <td class="col-hc">${p.recommended_hc}%</td>
            <td class="col-games">${p.games_played}</td>
            <td class="col-conf">${p.confidence_percent.toFixed(1)}%</td>
        </tr>`;
    }).join('');
}

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
