/**
 * SalesShortcut Dashboard — Client-side JavaScript
 * Handles WebSocket connection, UI updates, and workflow triggers.
 */

// ── State ────────────────────────────────────────────────────

const state = {
    ws: null,
    connected: false,
    businesses: [],
    events: [],
    stats: {
        totalLeads: 0,
        contacted: 0,
        meetings: 0,
        hotLeads: 0,
    },
};

// ── WebSocket ────────────────────────────────────────────────

function connectWebSocket() {
    const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
    state.ws = new WebSocket(`${protocol}//${location.host}/ws`);

    state.ws.onopen = () => {
        state.connected = true;
        updateConnectionStatus(true);
        console.log('WebSocket connected');
    };

    state.ws.onclose = () => {
        state.connected = false;
        updateConnectionStatus(false);
        console.log('WebSocket disconnected, reconnecting in 2s...');
        setTimeout(connectWebSocket, 2000);
    };

    state.ws.onerror = (err) => {
        console.error('WebSocket error:', err);
    };

    state.ws.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            handleMessage(data);
        } catch (e) {
            console.error('Failed to parse message:', e);
        }
    };
}

function handleMessage(data) {
    if (data.type === 'init') {
        // Initial state dump
        if (data.businesses) {
            state.businesses = data.businesses;
            renderLeadsTable();
            updateStats();
        }
        if (data.recent_events) {
            data.recent_events.forEach(evt => addEventToLog(evt));
        }
    } else if (data.type === 'agent_event') {
        addEventToLog(data);
        handleAgentEvent(data);
    } else if (data.type === 'human_input_request') {
        showHumanInputModal(data);
    }
}

function handleAgentEvent(evt) {
    if (evt.event === 'lead_found' && evt.data) {
        const existing = state.businesses.find(b => b.place_id === evt.data.place_id);
        if (!existing) {
            state.businesses.push(evt.data);
        }
        renderLeadsTable();
        updateStats();
    }

    if (evt.event === 'search_completed' && evt.data && evt.data.leads) {
        evt.data.leads.forEach(lead => {
            const existing = state.businesses.find(b => b.place_id === lead.place_id);
            if (!existing) {
                state.businesses.push(lead);
            }
        });
        renderLeadsTable();
        updateStats();
    }

    if (evt.event === 'meeting_scheduled') {
        state.stats.meetings++;
        updateStats();
    }

    if (evt.event === 'hot_lead_detected') {
        state.stats.hotLeads++;
        updateStats();
    }

    // Re-enable buttons on completion/error
    if (['search_completed', 'sdr_completed', 'processing_completed', 'error'].includes(evt.event)) {
        enableButtons();
    }
}

// ── UI Updates ───────────────────────────────────────────────

function updateConnectionStatus(connected) {
    const dot = document.getElementById('status-dot');
    const text = document.getElementById('status-text');
    if (dot) {
        dot.className = 'status-dot' + (connected ? ' connected' : '');
    }
    if (text) {
        text.textContent = connected ? 'Connected' : 'Disconnected';
    }
}

function updateStats() {
    const totalLeads = state.businesses.length;
    const contacted = state.businesses.filter(b => b.lead_status !== 'new').length;
    const hotLeads = state.businesses.filter(b => b.lead_status === 'hot_lead').length;

    setStatValue('stat-leads', totalLeads);
    setStatValue('stat-contacted', contacted);
    setStatValue('stat-meetings', state.stats.meetings);
    setStatValue('stat-hot', hotLeads || state.stats.hotLeads);
}

function setStatValue(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
}

function addEventToLog(evt) {
    const log = document.getElementById('event-log');
    if (!log) return;

    const item = document.createElement('div');
    item.className = 'event-item';

    const time = evt.timestamp ? new Date(evt.timestamp).toLocaleTimeString() : new Date().toLocaleTimeString();
    const agentType = evt.agent_type || 'system';
    const message = evt.message || evt.event || '';

    item.innerHTML = `
        <span class="event-time">${time}</span>
        <span class="event-badge badge-${agentType}">${agentType.replace('_', ' ')}</span>
        <span class="event-message">${escapeHtml(message)}</span>
    `;

    // Prepend (newest first)
    log.insertBefore(item, log.firstChild);

    // Keep max 100 events
    while (log.children.length > 100) {
        log.removeChild(log.lastChild);
    }

    state.events.push(evt);
}

function renderLeadsTable() {
    const tbody = document.getElementById('leads-tbody');
    if (!tbody) return;

    tbody.innerHTML = '';

    state.businesses.forEach(biz => {
        const tr = document.createElement('tr');
        const status = biz.lead_status || 'new';
        tr.innerHTML = `
            <td><strong>${escapeHtml(biz.business_name || '')}</strong></td>
            <td>${escapeHtml(biz.address || '')}</td>
            <td>${escapeHtml(biz.phone || '—')}</td>
            <td>${biz.rating ? biz.rating.toFixed(1) + ' ⭐' : '—'}</td>
            <td><span class="status status-${status}">${status.replace('_', ' ')}</span></td>
            <td>
                <button class="btn btn-primary btn-small" onclick="startSDR('${escapeHtml(biz.business_name)}', '${escapeHtml(biz.phone || '')}', '${escapeHtml(biz.email || '')}', '${escapeHtml(biz.address || '')}', '${escapeHtml(biz.city || '')}', '${escapeHtml(biz.place_id || '')}')">
                    Run SDR
                </button>
            </td>
        `;
        tbody.appendChild(tr);
    });
}

// ── Actions ──────────────────────────────────────────────────

async function findLeads() {
    const city = document.getElementById('city-input').value.trim();
    if (!city) {
        alert('Please enter a city name');
        return;
    }

    const maxResults = parseInt(document.getElementById('max-results').value) || 20;
    const btn = document.getElementById('find-leads-btn');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Searching...';

    try {
        const resp = await fetch('/start_lead_finding', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                city: city,
                max_results: maxResults,
                business_types: [],
                exclude_chains: true,
                min_rating: 0,
            }),
        });
        const data = await resp.json();
        if (data.status === 'error') {
            alert('Error: ' + data.message);
        }
    } catch (e) {
        alert('Failed to start lead finding: ' + e.message);
    }

    enableButtons();
}

async function startSDR(name, phone, email, address, city, placeId) {
    const skipCall = document.getElementById('skip-call')?.checked ?? false;

    try {
        const resp = await fetch('/start_sdr', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                business_name: name,
                phone: phone,
                email: email,
                address: address,
                city: city,
                place_id: placeId,
                skip_call: skipCall,
            }),
        });
        const data = await resp.json();
        if (data.status === 'error') {
            alert('SDR Error: ' + data.message);
        }
    } catch (e) {
        alert('Failed to start SDR: ' + e.message);
    }
}

async function processEmails() {
    const btn = document.getElementById('process-emails-btn');
    btn.disabled = true;
    btn.innerHTML = '<span class="spinner"></span> Processing...';

    try {
        const resp = await fetch('/start_email_processing', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ max_emails: 10 }),
        });
        const data = await resp.json();
        if (data.status === 'error') {
            alert('Error: ' + data.message);
        }
    } catch (e) {
        alert('Failed to process emails: ' + e.message);
    }

    enableButtons();
}

function enableButtons() {
    const findBtn = document.getElementById('find-leads-btn');
    if (findBtn) {
        findBtn.disabled = false;
        findBtn.innerHTML = '🔍 Find Leads';
    }
    const emailBtn = document.getElementById('process-emails-btn');
    if (emailBtn) {
        emailBtn.disabled = false;
        emailBtn.innerHTML = '📧 Process Inbox';
    }
}

// ── Tabs ─────────────────────────────────────────────────────

function switchTab(tabName) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(tc => tc.classList.remove('active'));

    document.querySelector(`.tab[data-tab="${tabName}"]`)?.classList.add('active');
    document.getElementById(`tab-${tabName}`)?.classList.add('active');
}

// ── Human Input Modal ────────────────────────────────────────

function showHumanInputModal(data) {
    const overlay = document.getElementById('modal-overlay');
    const prompt = document.getElementById('modal-prompt');
    const input = document.getElementById('modal-input');
    const submitBtn = document.getElementById('modal-submit');

    if (!overlay || !prompt) return;

    prompt.textContent = data.prompt || 'Agent needs your input:';
    input.value = '';
    overlay.classList.add('active');

    submitBtn.onclick = async () => {
        const response = input.value.trim();
        if (!response) return;

        try {
            await fetch('/api/human-input/respond', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    request_id: data.request_id,
                    response: response,
                }),
            });
        } catch (e) {
            console.error('Failed to send human input:', e);
        }

        overlay.classList.remove('active');
    };
}

function closeModal() {
    document.getElementById('modal-overlay')?.classList.remove('active');
}

// ── Helpers ──────────────────────────────────────────────────

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

// ── Init ─────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
    connectWebSocket();

    // Tab click handlers
    document.querySelectorAll('.tab').forEach(tab => {
        tab.addEventListener('click', () => switchTab(tab.dataset.tab));
    });
});
