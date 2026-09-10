import datetime

import pytz


def is_ist_market_session_active(dt: datetime.datetime | None = None) -> bool:
    """Checks whether current or provided time falls within NSE/BSE IST market session (09:15 to 15:30 IST Mon-Fri)."""
    ist = pytz.timezone("Asia/Kolkata")
    now = dt.astimezone(ist) if dt else datetime.datetime.now(ist)
    if now.weekday() >= 5:
        return False
    market_open = now.replace(hour=9, minute=15, second=0, microsecond=0)
    market_close = now.replace(hour=15, minute=30, second=0, microsecond=0)
    return market_open <= now <= market_close


def round_to_ist_tick(price: float, tick_size: float = 0.05) -> float:
    """Rounds price to nearest NSE/BSE valid price tick (default 0.05 INR)."""
    if price <= 0:
        return 0.0
    return round(round(price / tick_size) * tick_size, 2)


import os
import threading

import psycopg2
from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_jwt_extended import JWTManager, create_access_token, get_jwt_identity, jwt_required

# Import your pipeline
from pipeline import run_analysis_for_category
from psycopg2.extras import RealDictCursor
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__)
CORS(app)  # Allows React to talk to Flask

app.config["JWT_SECRET_KEY"] = "super-secret-stock-key-that-is-very-long-12345"  # Change in production
jwt = JWTManager(app)


@app.route("/")
def home():
    return "Stock Screener API is running!"


def get_db_connection():
    return psycopg2.connect(os.environ["DATABASE_URL"], cursor_factory=RealDictCursor)


# --- 1. AUTHENTICATION ENDPOINTS ---


@app.route("/api/register", methods=["POST"])
def register():
    data = request.json
    hashed_pw = generate_password_hash(data["password"])

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO users (email, password_hash) VALUES (%s, %s) RETURNING id;", (data["email"], hashed_pw)
        )
        user_id = cur.fetchone()["id"]
        conn.commit()
        return jsonify({"message": "User created", "user_id": user_id}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 400
    finally:
        conn.close()


@app.route("/api/login", methods=["POST"])
def login():
    data = request.json
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE email = %s;", (data["email"],))
    user = cur.fetchone()
    conn.close()

    if user and check_password_hash(user["password_hash"], data["password"]):
        access_token = create_access_token(identity=str(user["id"]))
        return jsonify(access_token=access_token)
    return jsonify({"error": "Bad email or password"}), 401


# --- 2. PIPELINE TRIGGER ENDPOINT ---


def background_pipeline_task(user_id, category):
    """Runs the LLM pipeline in the background and saves to DB."""
    print(f"Starting background pipeline for {category}...")
    try:
        result = run_analysis_for_category(category)

        conn = get_db_connection()
        cur = conn.cursor()

        for pick in result["final_picks"]:
            cur.execute(
                """
                INSERT INTO stock_recommendations
                (user_id, category, ticker, entry_price, target_price, stop_loss, score, conviction, thesis)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
                (
                    user_id,
                    category,
                    pick["ticker"],
                    pick["close"],
                    pick["target"],
                    pick["stop_loss"],
                    pick["score"],
                    pick["conviction"],
                    pick["thesis"],
                ),
            )
        conn.commit()
        print("✅ Background task complete. Saved to database.")
    except Exception as e:
        print(f"❌ Background task failed: {e}")
    finally:
        if "conn" in locals():
            conn.close()


@app.route("/api/run-pipeline", methods=["POST"])
@jwt_required()
def run_pipeline():
    user_id = get_jwt_identity()
    category = request.json.get("category", "nifty_50")

    # Run in a background thread so the HTTP request doesn't time out
    thread = threading.Thread(target=background_pipeline_task, args=(user_id, category))
    thread.start()

    return jsonify({"message": f"Pipeline started for {category}. Check back in 1-2 minutes."}), 202


# --- 3. FETCH RESULTS ENDPOINT ---


@app.route("/api/recommendations/<category>", methods=["GET"])
@jwt_required()
def get_recommendations(category):
    user_id = get_jwt_identity()
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute(
        """
        SELECT * FROM stock_recommendations
        WHERE user_id = %s AND category = %s
        ORDER BY created_at DESC LIMIT 20;
    """,
        (user_id, category),
    )

    results = cur.fetchall()
    conn.close()

    return jsonify(results), 200


if __name__ == "__main__":
    app.run(debug=True, port=5000)
