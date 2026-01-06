import datetime
import threading
import time

from flask import Flask, jsonify, render_template, request

from app.engine import LiveTrader
from app.sync import sync_gpw_data
from data.scripts.saxo_auth import TokenStore
from data.scripts.saxo_auth import login as saxo_login

app = Flask(__name__)
trader = LiveTrader()


def to_dict_safe(obj):
    return str(obj)


@app.route("/")
def index():
    return render_template("dashboard.html")


@app.route("/api/balance")
def get_balance():
    try:
        res = trader.get_wallet()
        # engine.get_wallet returns a simplified dict, not raw Saxo response directly
        if "error" in res:
            return jsonify({"success": False, "error": res["error"], "raw": res.get("raw")})

        # It returns keys: Currency, TotalValue, CashAvailableForTrading, raw
        return jsonify(
            {
                "success": True,
                "total_value": res.get("TotalValue"),
                "currency": res.get("Currency"),
                "cash_available": res.get("CashAvailableForTrading"),
                "raw": res.get("raw"),
            }
        )
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/auth/status")
def auth_status():
    try:
        store = TokenStore()
        tokens = store.load()
        if not tokens:
            return jsonify({"authenticated": False, "message": "No tokens found"})

        now = time.time()
        is_valid = now < tokens.access_exp

        return jsonify(
            {
                "authenticated": is_valid,
                "access_exp": tokens.access_exp,
                "expires_in": int(tokens.access_exp - now) if is_valid else 0,
            }
        )
    except Exception as e:
        return jsonify({"authenticated": False, "error": str(e)})


@app.route("/api/auth/login", methods=["POST"])
def run_login():
    try:
        status = {"success": False, "message": ""}

        def safe_login():
            try:
                # Assuming default port 8765 is free
                saxo_login(port=8765)
                status["success"] = True
                status["message"] = "Login successful"
            except SystemExit as e:
                status["message"] = f"Login failed (SystemExit): {e}"
            except Exception as e:
                status["message"] = f"Login failed: {e}"

        safe_login()

        if status["success"]:
            return jsonify(status)
        else:
            return jsonify(status), 400

    except Exception as e:
        return jsonify({"success": False, "error": str(e)}), 500


@app.route("/api/sync", methods=["POST"])
def run_sync():
    try:
        logs = sync_gpw_data()
        return jsonify({"success": True, "logs": logs})
    except Exception as e:
        return jsonify({"success": False, "error": str(e)})


@app.route("/api/strategies")
def list_strategies():
    strats = trader.list_strategies()
    return jsonify(strats)


@app.route("/api/symbols")
def list_symbols():
    syms = trader.list_symbols()
    return jsonify([{"name": s[0], "uic": s[1]} for s in syms])


@app.route("/api/analyze", methods=["POST"])
def analyze():
    data = request.json
    strategy = data.get("strategy")
    uic = data.get("uic")

    if not strategy or not uic:
        return jsonify({"error": "Missing strategy or uic"}), 400

    try:
        # generate_signal signature: strategy_name: str, uic: int
        res = trader.generate_signal(str(strategy), int(uic))
        return jsonify(res)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/trade", methods=["POST"])
def trade():
    data = request.json
    uic = data.get("uic")
    side = data.get("side")
    amount = data.get("amount")
    order_type = data.get("type", "Market")
    price = data.get("price")

    if not uic or not side or not amount:
        return jsonify({"error": "Missing trade params"}), 400

    try:
        res = trader.execute_trade(
            int(uic),
            side,
            int(amount) if str(amount).isdigit() else float(amount),
            order_type,
            float(price) if price else None,
        )
        return jsonify({"result": res})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/reports")
def list_reports():
    import os

    reports_dir = os.path.join("data", "backtests")
    try:
        files = [f for f in os.listdir(reports_dir) if f.endswith(".csv")]
        return jsonify(sorted(files))
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/reports/<filename>")
def get_report(filename):
    import csv
    import os

    if not filename.endswith(".csv"):
        return jsonify({"error": "Invalid file type"}), 400

    if ".." in filename or "/" in filename:
        return jsonify({"error": "Invalid filename"}), 400

    path = os.path.join("data", "backtests", filename)
    try:
        with open(path, "r") as f:
            reader = csv.reader(f)
            data = list(reader)
        return jsonify({"filename": filename, "data": data})
    except Exception as e:
        return jsonify({"error": str(e)}), 404


def keep_alive_loop():
    from data.scripts.saxo_auth import force_refresh

    print("[KeepAlive] Background thread started.")
    while True:
        time.sleep(15 * 60)
        try:
            print(f"[KeepAlive] Refreshing token at {datetime.datetime.now()}...")
            force_refresh()
        except Exception as e:
            print(f"[KeepAlive] Error: {e}")


if __name__ == "__main__":
    # Start background thread
    # Daemon=True ensures it dies when main process dies
    t = threading.Thread(target=keep_alive_loop, daemon=True)
    t.start()
    app.run(debug=True, port=5000)
