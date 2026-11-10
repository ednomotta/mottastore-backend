import json
import os
import sqlite3
from flask import Flask, request, jsonify
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
import mercadopago

app = Flask(__name__)
CORS(app)

MP_ACCESS_TOKEN = os.environ.get("MP_ACCESS_TOKEN", "APP_USR-1738991350202380-110920-8485edb539259d0282b38a9d643d7e92-3346874904")
sdk = mercadopago.SDK(MP_ACCESS_TOKEN)

DB_FILE = "mottastore.db"

def get_db():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            birth TEXT NOT NULL,
            password TEXT NOT NULL
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS games (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            genre TEXT NOT NULL,
            banner TEXT NOT NULL,
            video TEXT NOT NULL,
            download_url TEXT NOT NULL,
            demo_url TEXT,
            desc TEXT NOT NULL,
            price REAL NOT NULL,
            views INTEGER DEFAULT 0,
            sales INTEGER DEFAULT 0
        )
    """)
    
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS libraries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_email TEXT NOT NULL,
            game_id TEXT NOT NULL,
            UNIQUE(user_email, game_id)
        )
    """)


    conn.commit()
    conn.close()

init_db()

@app.route("/register", methods=["POST"])
def register():
    data = request.json
    name = data.get("name")
    email = data.get("email")
    birth = data.get("birth")
    password = data.get("password")

    if not all([name, email, birth, password]):
        return jsonify({"error": "Preencha todos os campos."}), 400

    conn = get_db()
    try:
        hashed_pw = generate_password_hash(password)
        conn.execute(
            "INSERT INTO users (name, email, birth, password) VALUES (?, ?, ?, ?)",
            (name, email, birth, hashed_pw)
        )
        conn.commit()
        return jsonify({"user": {"name": name, "email": email, "birth": birth}}), 201
    except sqlite3.IntegrityError:
        return jsonify({"error": "Este e-mail já está cadastrado!"}), 409
    finally:
        conn.close()

@app.route("/login", methods=["POST"])
def login():
    data = request.json
    email = data.get("email")
    password = data.get("password")

    conn = get_db()
    user = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    conn.close()

    if user and check_password_hash(user["password"], password):
        return jsonify({
            "user": {
                "name": user["name"],
                "email": user["email"],
                "birth": user["birth"]
            }
        }), 200
    return jsonify({"error": "E-mail ou senha incorretos!"}), 401

@app.route("/games", methods=["GET"])
def get_games():
    conn = get_db()
    rows = conn.execute("SELECT * FROM games").fetchall()
    conn.close()
    games_list = [{
        "id": r["id"],
        "name": r["name"],
        "genre": r["genre"],
        "banner": r["banner"],
        "video": r["video"],
        "downloadUrl": r["download_url"],
        "demoUrl": r["demo_url"],
        "desc": r["desc"],
        "price": r["price"],
        "views": r["views"],
        "sales": r["sales"]
    } for r in rows]
    return jsonify(games_list), 200

@app.route("/games", methods=["POST"])
def add_game():
    data = request.json
    conn = get_db()
    conn.execute("""
        INSERT INTO games (id, name, genre, banner, video, download_url, demo_url, desc, price, views, sales)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0)
    """, (
        data["id"], data["name"], data["genre"], data["banner"],
        data["video"], data["downloadUrl"], data.get("demoUrl", ""),
        data["desc"], float(data["price"])
    ))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"}), 201

@app.route("/games/<game_id>", methods=["DELETE"])
def delete_game(game_id):
    conn = get_db()
    conn.execute("DELETE FROM games WHERE id = ?", (game_id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "deleted"}), 200

@app.route("/games/<game_id>/view", methods=["POST"])
def increment_view(game_id):
    conn = get_db()
    conn.execute("UPDATE games SET views = views + 1 WHERE id = ?", (game_id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "ok"}), 200

@app.route("/library/<email>", methods=["GET"])
def get_library(email):
    conn = get_db()
    rows = conn.execute("SELECT game_id FROM libraries WHERE user_email = ?", (email,)).fetchall()
    conn.close()
    return jsonify({"game_ids": [r["game_id"] for r in rows]}), 200

@app.route("/create_payment", methods=["POST"])
def create_payment():
    data = request.json
    user_email = data.get("email")
    items = data.get("items", [])

    if not user_email or not items:
        return jsonify({"error": "Dados incompletos"}), 400

    game_ids = [str(item["id"]) for item in items]
    external_ref = json.dumps({"email": user_email, "game_ids": game_ids})

    preference_data = {
        "items": [
            {
                "title": item["title"],
                "quantity": int(item.get("quantity", 1)),
                "unit_price": float(item["unit_price"]),
                "currency_id": "BRL"
            }
            for item in items
        ],
        "payer": {"email": user_email},
        "external_reference": external_ref,
        "notification_url": "https://SEU-DOMINIO.onrender.com/webhook"
    }

    try:
        preference_response = sdk.preference().create(preference_data)
        preference = preference_response["response"]
        return jsonify({"init_point": preference["init_point"], "id": preference["id"]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/webhook", methods=["POST"])
def webhook():
    topic = request.args.get("topic") or (request.json and request.json.get("type"))
    payment_id = request.args.get("id") or (request.json and request.json.get("data", {}).get("id"))

    if topic == "payment" and payment_id:
        try:
            payment_info = sdk.payment().get(payment_id)
            payment = payment_info["response"]
            if payment.get("status") == "approved":
                ref = json.loads(payment.get("external_reference", "{}"))
                user_email = ref.get("email")
                game_ids = ref.get("game_ids", [])
                if user_email and game_ids:
                    conn = get_db()
                    for gid in game_ids:
                        conn.execute(
                            "INSERT OR IGNORE INTO libraries (user_email, game_id) VALUES (?, ?)",
                            (user_email, gid)
                        )
                        conn.execute(
                            "UPDATE games SET sales = sales + 1 WHERE id = ?",
                            (gid,)
                        )
                    conn.commit()
                    conn.close()
        except Exception as e:
            print("Erro no Webhook:", e)
    return jsonify({"status": "ok"}), 200

if __name__ == "__main__":
    app.run(port=5000, debug=True)
