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
