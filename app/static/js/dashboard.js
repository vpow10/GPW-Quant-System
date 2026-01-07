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

async function loadAnalyzedStrategies() {
    try {
        const res = await fetch('/api/analysis/list');
        const strats = await res.json();

        const sel = document.getElementById('sel-strat-analysis');
        if (!sel) return;

        sel.innerHTML = '';
        strats.forEach(s => {
            const opt = document.createElement('option');
            opt.value = s;
            opt.textContent = s;
            sel.appendChild(opt);
        });
    } catch (e) {
        console.error("Failed to load analyzed strategies", e);
    }
}

async function loadAnalysisPlots() {
    const strat = document.getElementById('sel-strat-analysis').value;
    const container = document.getElementById('analysis-plots');
    const title = document.getElementById('report-title');
    if (title) title.textContent = `Analysis: ${strat}`;

    if (!strat) return alert("No strategy selected");

    container.innerHTML = 'Loading plots...';

    // Plot descriptions (Polish)
    const descriptions = {
        "equity_curves.png": "<strong>Krzywe kapitału (Equity Curves):</strong> Przedstawiają skumulowany wynik inwestycji w czasie, startując od poziomu 1.0 (100%).<br>• <strong>Strategy (net):</strong> Wynik wybranej strategii po uwzględnieniu kosztów transakcyjnych i poślizgów cenowych.<br>• <strong>Benchmark (B&H):</strong> Wynik strategii 'Kup i Trzymaj' dla indeksu odniesienia (WIG20).<br>• <strong>Active:</strong> 'Aktywny zwrot', czyli różnica między wynikiem strategii a benchmarkiem. Pokazuje wartość dodaną (alpha).",

        "regime_bar_ann_return.png": "<strong>Zannualizowana stopa zwrotu (CAGR):</strong> Wynik w podziale na fazy rynku (Reżimy).<br>• <strong>Regime (Reżim):</strong> Kondycja rynku określana na podstawie średniej ruchomej. <em>BULL</em> (Hossa - cena rośnie), <em>BEAR</em> (Bessa - cena spada), <em>NORMAL</em> (Konsolidacja).<br>• Wykres pokazuje, jak strategia radzi sobie w trudnych (Bessa) i dobrych (Hossa) okresach.",

        "regime_bar_sharpe_info.png": "<strong>Efektywność skorygowana o ryzyko:</strong><br>• <strong>Sharpe Ratio:</strong> Miarodajna ocena zysku w relacji do ryzyka (zmienności) dla Strategii i Benchmarku. Wyższe wartości oznaczają lepszy, stabilniejszy wynik.<br>• <strong>Information Ratio:</strong> Mierzy stabilność generowania nadwyżki nad benchmarkiem (dla Active Return).",

        "regime_bar_turnover_leverage.png": "<strong>Ekspozycja i obrót portfela:</strong><br>• <strong>Avg Gross Leverage:</strong> Średnie zaangażowanie kapitału. Wartość 1.0 to 100% w akcjach. Wartości bliskie 0 oznaczają ucieczkę do gotówki (Cash) w danym reżimie.<br>• <strong>Avg Turnover:</strong> Średni obrót portfela. Wysoki słupek oznacza częste zmiany pozycji (i wyższe koszty)."
    };

    try {
        const res = await fetch(`/api/analysis/plots/${strat}`);
        const files = await res.json();

        if (files.error) {
            container.textContent = `Error: ${files.error}`;
            return;
        }

        if (!files || files.length === 0) {
            container.textContent = "No plots found for this strategy.";
            return;
        }

        container.innerHTML = '';
        files.forEach(f => {
            // Create wrapper for plot
            const div = document.createElement('div');
            div.className = "plot-wrapper";
            div.style = "background: #252526; padding: 10px; border-radius: 5px;";

            // Plot title from filename
            const title = document.createElement('h4');
            title.textContent = f.replace('.png', '').replace(/_/g, ' ');
            title.style = "margin-top: 0; color: #ccc; margin-bottom: 5px;";

            // Description
            const desc = document.createElement('p');
            desc.style = "font-size: 0.9em; color: #aaa; margin-bottom: 10px; font-style: normal; line-height: 1.4;";
            desc.innerHTML = descriptions[f] || "";

            // Image
            const img = document.createElement('img');
            img.src = `/api/analysis/image/${strat}/${f}`;
            img.style = "max-width: 100%; height: auto; border: 1px solid #444;";

            div.appendChild(title);
            div.appendChild(desc);
            div.appendChild(img);
            container.appendChild(div);
        });

    } catch (e) {
        container.textContent = `Error loading plots: ${e}`;
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
    loadAnalyzedStrategies();
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
