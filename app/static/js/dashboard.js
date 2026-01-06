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
        const execSel = document.getElementById('exec-strat');

        // Clear existing options handled by re-run safety usually, but simplest to wipe first
        if (stratSel) stratSel.innerHTML = '';
        if (execSel) execSel.innerHTML = '';

        strats.forEach(s => {
            if (stratSel) {
                const opt1 = document.createElement('option');
                opt1.value = s;
                opt1.textContent = s;
                stratSel.appendChild(opt1);
            }
            else {
                const opt2 = document.createElement('option');
                opt2.value = s;
                opt2.textContent = s;
                execSel.appendChild(opt2);
            }
        });

        const symRes = await fetch('/api/symbols');
        const syms = await symRes.json();


        ['sel-symbol-auto', 'sel-symbol-manual'].forEach(id => {
            const symSel = document.getElementById(id);
            if (symSel) {
                symSel.innerHTML = '';
                syms.forEach(s => {
                    const opt = document.createElement('option');
                    opt.value = s.uic;
                    opt.textContent = s.name;
                    symSel.appendChild(opt);
                });
            }
        });
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

        log(logBox, `Analysis complete.`);

        const sig = data.signal;
        let text = "NEUTRAL";
        if (sig === 1) text = "BULLISH (Long)";
        if (sig === -1) text = "BEARISH (Short)";

        document.getElementById('signal-result').textContent = `Signal: ${text} | Date: ${data.date}`;

        const p = data.params;
        let pText = "";

        let days = null;
        if (p.lookback) days = p.lookback;
        else if (p.window) days = p.window;
        else if (data.strategy && data.strategy.includes("10d")) days = 10;
        else if (data.strategy && data.strategy.includes("lstm")) days = 60;
        else if (data.strategy && data.strategy.includes("20d")) days = 20; // Fallback for variants

        if (days) {
            pText = `Analyzed ${days} days of data.`;
        } else {
            // Fallback to whitelist if logic fails (or just generic text)
            pText = "Analyzed market data.";
        }

        const legend = `
        <div style="margin-top: 10px; border-top: 1px solid #444; padding-top: 5px; font-size: 0.9em; color: #ccc;">
            <strong>Signal Legend:</strong>
            <ul style="margin: 5px 0 0 20px; list-style: disc;">
                <li><strong>BULLISH (Long)</strong>: Expect price increase. Buy/Long position recommended.</li>
                <li><strong>BEARISH (Short)</strong>: Expect price decrease. Sell/Short position recommended.</li>
                <li><strong>NEUTRAL</strong>: No clear signal. Close positions or hold cash.</li>
            </ul>
        </div>
        `;

        const explainBox = document.getElementById('signal-explain');
        explainBox.innerHTML = `<strong>Strategy Parameters:</strong> ${pText}<br>${legend}`;

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

// --- Execution Tab Logic ---

let currentExecMode = 'daily';

function switchExecMode(mode) {
    currentExecMode = mode;

    // Update labels
    const titleEl = document.getElementById('config-title');
    if (titleEl) titleEl.textContent = `${mode}_config.env`;

    const logHeader = document.getElementById('log-header');
    if (logHeader) logHeader.textContent = `Execution Logs (automation/${mode}.log)`;

    // Update Run Button
    const btn = document.getElementById('btn-run-exec');
    if (btn) btn.textContent = `Run ${mode.charAt(0).toUpperCase() + mode.slice(1)} Trader`;

    // Reload data
    loadConfig();
    const logViewer = document.getElementById('exec-log-viewer');
    if (logViewer) {
        logViewer.textContent = 'Switching logs...';
        logViewer.scrollTop = 0;
    }
    pollLogs();
}

async function loadConfig() {
    try {
        const res = await fetch(`/api/config/${currentExecMode}`);
        const cfg = await res.json();

        const strat = document.getElementById('exec-strat');
        if (strat) strat.value = cfg.TRADER_STRATEGY || "momentum";

        const alloc = document.getElementById('exec-alloc');
        if (alloc) alloc.value = cfg.TRADER_ALLOCATION || "0.1";

        const maxCap = document.getElementById('exec-max-cap');
        if (maxCap) maxCap.value = cfg.TRADER_MAX_CAPITAL || "500000";

        const dailySpend = document.getElementById('exec-daily-spend');
        if (dailySpend) dailySpend.value = cfg.TRADER_MAX_DAILY_SPEND || "50000";

        const longOnly = document.getElementById('exec-long-only');
        if (longOnly) longOnly.checked = (cfg.TRADER_LONG_ONLY === 'true');

        const execute = document.getElementById('exec-execute');
        if (execute) execute.checked = (cfg.TRADER_EXECUTE === 'true');

    } catch (e) {
        console.error("Failed to load config", e);
    }
}

async function saveConfig() {
    const cfg = {
        TRADER_STRATEGY: document.getElementById('exec-strat').value,
        TRADER_ALLOCATION: document.getElementById('exec-alloc').value,
        TRADER_MAX_CAPITAL: document.getElementById('exec-max-cap').value,
        TRADER_MAX_DAILY_SPEND: document.getElementById('exec-daily-spend').value,
        TRADER_LONG_ONLY: document.getElementById('exec-long-only').checked ? 'true' : 'false',
        TRADER_EXECUTE: document.getElementById('exec-execute').checked ? 'true' : 'false'
    };

    try {
        const res = await fetch(`/api/config/${currentExecMode}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(cfg)
        });
        const data = await res.json();
        if (data.success) {
            alert(`Saved ${currentExecMode}_config.env`);
        } else {
            alert("Error saving: " + data.error);
        }
    } catch (e) {
        alert("Save failed: " + e);
    }
}

async function runScript() {
    if (!confirm(`Run ${currentExecMode} Trader script now?`)) return;

    try {
        const res = await fetch(`/api/exec/${currentExecMode}`, { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            alert(data.message);
            pollLogs();
        } else {
            alert("Error: " + data.error);
        }
    } catch (e) {
        alert("Exec failed: " + e);
    }
}

async function pollLogs() {
    if (typeof currentExecMode === 'undefined') return;
    try {
        const res = await fetch(`/api/logs/${currentExecMode}`);
        const data = await res.json();
        if (data.lines) {
            const viewer = document.getElementById('exec-log-viewer');
            if (!viewer) return;

            // Check if we are scrolled to bottom
            const isAtBottom = viewer.scrollHeight - viewer.scrollTop <= viewer.clientHeight + 50;

            viewer.textContent = data.lines.join("");

            // Auto scroll if was at bottom
            if (isAtBottom) {
                viewer.scrollTop = viewer.scrollHeight;
            }
        }
    } catch (e) {
        console.error("Log poll failed", e);
    }
}

// Init
document.addEventListener('DOMContentLoaded', () => {
    checkAuth();
    loadStrategiesAndSymbols();
    loadReportList();
    loadConfig();
    refreshBalance();

    // Poll auth every 60s
    setInterval(checkAuth, 60000);
    // Poll logs every 5s if tab is active AND auto-refresh is checked
    setInterval(() => {
        const tab = document.getElementById('Execution');
        const isTabVisible = tab && tab.style.display === 'block';
        const autoCheck = document.getElementById('auto-refresh');
        const isAuto = autoCheck && autoCheck.checked;
        if (isTabVisible && isAuto) {
            pollLogs();
        }
    }, 5000);
});
