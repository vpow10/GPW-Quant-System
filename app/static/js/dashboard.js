function openTab(evt, tabName) {
    var i, tabcontent, tablinks;
    tabcontent = document.getElementsByClassName("tab-content");
    for (i = 0; i < tabcontent.length; i++) {
        tabcontent[i].style.display = "none";
    }
    tablinks = document.getElementsByClassName("tab-btn");
    for (i = 0; i < tablinks.length; i++) {
        tablinks[i].className = tablinks[i].className.replace(" active", "");
    }
    document.getElementById(tabName).style.display = "block";
    evt.currentTarget.className += " active";
}

function log(elementId, msg) {
    const box = document.getElementById(elementId);
    const line = document.createElement('div');
    line.textContent = `[${new Date().toLocaleTimeString()}] ${msg}`;
    box.appendChild(line);
    box.scrollTop = box.scrollHeight;
}

// Data Fetching
async function refreshBalance() {
    const display = document.getElementById('balance-display');
    display.textContent = "Fetching...";
    try {
        const res = await fetch('/api/balance');
        const data = await res.json();
        if (data.success) {
            display.textContent = `Total Value: ${data.total_value} ${data.currency}\nCash Avail: ${data.cash_available}`;
        } else {
            display.textContent = `Error: ${data.error}`;
        }
    } catch (e) {
        display.textContent = `Error: ${e}`;
    }
}

async function syncData() {
    const logBox = 'monitor-log';
    log(logBox, "Sync started...");
    try {
        const res = await fetch('/api/sync', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            if (data.logs) {
                data.logs.forEach(l => log(logBox, l));
            }
            log(logBox, "Sync complete.");
        } else {
            log(logBox, `Sync failed: ${data.error}`);
        }
    } catch (e) {
        log(logBox, `Network error: ${e}`);
    }
}

async function loadStrategiesAndSymbols() {
    try {
        const stratRes = await fetch('/api/strategies');
        const strats = await stratRes.json();
        const stratSel = document.getElementById('sel-strat');
        strats.forEach(s => {
            const opt = document.createElement('option');
            opt.value = s[0];
            opt.textContent = s[0]; // assuming tuple (name, name)
            stratSel.appendChild(opt);
        });

        const symRes = await fetch('/api/symbols');
        const syms = await symRes.json();

        const populate = (id) => {
            const sel = document.getElementById(id);
            syms.forEach(s => {
                const opt = document.createElement('option');
                opt.value = s.uic;
                opt.textContent = s.name;
                sel.appendChild(opt);
            });
        };
        populate('sel-symbol-auto');
        populate('sel-symbol-manual');

    } catch (e) {
        console.error("Failed to load init data", e);
    }
}

// Auto Strategy
let lastSignal = null;

async function analyze() {
    const strat = document.getElementById('sel-strat').value;
    const uic = document.getElementById('sel-symbol-auto').value;
    const logBox = 'auto-log';

    if (!strat || !uic) return alert('Select strategy and symbol');

    log(logBox, `Analyzing ${uic} with ${strat}...`);

    try {
        const res = await fetch('/api/analyze', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ strategy: strat, uic: uic })
        });
        const data = await res.json();

        if (data.error) {
            document.getElementById('signal-result').textContent = `ERROR: ${data.error}`;
            return;
        }

        const sig = data.signal;
        let text = "NEUTRAL";
        if (sig === 1) text = "BULLISH (Long)";
        if (sig === -1) text = "BEARISH (Short)";

        document.getElementById('signal-result').textContent = `Signal: ${text} | Date: ${data.date}`;
        document.getElementById('signal-explain').textContent = JSON.stringify(data.params);

        const btn = document.getElementById('btn-auto-trade');
        if (sig !== 0) {
            btn.disabled = false;
            btn.textContent = `Execute ${text}`;
            lastSignal = { uic: uic, signal: sig };
        } else {
            btn.disabled = true;
            lastSignal = null;
        }

    } catch (e) {
        log(logBox, `Error: ${e}`);
    }
}

async function executeAutoTrade() {
    if (!lastSignal) return;
    const amount = document.getElementById('auto-amount').value;
    const side = lastSignal.signal === 1 ? 'Buy' : 'Sell';

    await placeTrade(lastSignal.uic, side, amount, 'auto-log');
}

// Manual Trade
function togglePriceInput() {
    const type = document.getElementById('man-type').value;
    document.getElementById('man-price').disabled = (type !== 'Limit');
}

async function executeManualTrade() {
    const uic = document.getElementById('sel-symbol-manual').value;
    const side = document.querySelector('input[name="side"]:checked').value;
    const amount = document.getElementById('man-amount').value;
    const type = document.getElementById('man-type').value;
    const price = document.getElementById('man-price').value;

    await placeTrade(uic, side, amount, 'man-log', type, price);
}

// Report Logic
async function loadReportList() {
    const list = document.getElementById('report-list');
    list.innerHTML = '<li>Loading...</li>';
    try {
        const res = await fetch('/api/reports');
        const files = await res.json();
        list.innerHTML = '';
        if (files.length === 0) {
            list.innerHTML = '<li>No reports found.</li>';
            return;
        }

        files.forEach(f => {
            const li = document.createElement('li');
            li.innerHTML = `<a href="#" onclick="loadReport('${f}'); return false;">${f}</a>`;
            li.style.padding = '5px 0';
            list.appendChild(li);
        });
    } catch (e) {
        list.innerHTML = `<li>Error: ${e}</li>`;
    }
}

async function loadReport(filename) {
    const viewer = document.getElementById('report-viewer');
    const title = document.getElementById('report-title');
    title.textContent = `Report: ${filename}`;
    viewer.innerHTML = 'Loading content...';

    try {
        const res = await fetch(`/api/reports/${filename}`);
        if (!res.ok) throw new Error("Failed to load");
        const data = await res.json();

        // build table
        const rows = data.data; // list of lists
        if (!rows || rows.length === 0) {
            viewer.textContent = "Empty file.";
            return;
        }

        let html = '<table class="report-table" style="width:100%; border-collapse: collapse;">';
        // Header
        html += '<thead><tr>';
        rows[0].forEach(cell => {
            html += `<th style="border: 1px solid #444; padding: 8px; background: #333; text-align: left;">${cell}</th>`;
        });
        html += '</tr></thead>';

        // Body
        html += '<tbody>';
        for (let i = 1; i < rows.length; i++) {
            html += '<tr>';
            rows[i].forEach(cell => {
                html += `<td style="border: 1px solid #444; padding: 8px;">${cell}</td>`;
            });
            html += '</tr>';
        }
        html += '</tbody></table>';

        viewer.innerHTML = html;

    } catch (e) {
        viewer.textContent = `Error: ${e}`;
    }
}

async function placeTrade(uic, side, amount, logId, type = 'Market', price = null) {
    const logBox = logId;
    log(logBox, `Placing ${side} order for ${amount}...`);

    try {
        const res = await fetch('/api/trade', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                uic: uic,
                side: side,
                amount: amount,
                type: type,
                price: price
            })
        });
        const data = await res.json();
        if (data.error) {
            log(logBox, `Failed: ${data.error}`);
        } else {
            log(logBox, `Result: ${JSON.stringify(data.result)}`);
        }
    } catch (e) {
        log(logBox, `Error: ${e}`);
    }
}

// Auth Logic
async function checkAuth() {
    try {
        const res = await fetch('/api/auth/status');
        const data = await res.json();
        const lbl = document.getElementById('auth-status-label');
        const btnLogin = document.getElementById('btn-login');

        if (data.authenticated) {
            lbl.textContent = `Authenticated (expires in ${Math.round(data.expires_in / 60)}m)`;
            lbl.style.color = '#4ec9b0';
            btnLogin.style.display = 'none';
        } else {
            lbl.textContent = "Not Authenticated";
            lbl.style.color = '#f44747';
            btnLogin.style.display = 'block';
        }
    } catch (e) {
        console.error("Auth check failed", e);
    }
}

async function startLogin() {
    const lbl = document.getElementById('auth-status-label');
    const btn = document.getElementById('btn-login');

    lbl.textContent = "Logging in... Check browser window.";
    btn.disabled = true;

    try {
        const res = await fetch('/api/auth/login', { method: 'POST' });
        const data = await res.json();

        if (data.success) {
            alert("Login Successful!");
            checkAuth();
        } else {
            alert("Login Failed: " + data.message);
            checkAuth();
        }
    } catch (e) {
        alert("Error during login: " + e);
        checkAuth();
    } finally {
        btn.disabled = false;
    }
}

// Init
document.addEventListener('DOMContentLoaded', () => {
    loadStrategiesAndSymbols();
    checkAuth();
    loadReportList();
    // Poll auth every 60s
    setInterval(checkAuth, 60000);
});
