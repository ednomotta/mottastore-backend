import json
import os
from flask import Flask, request, jsonify
from flask_cors import CORS
import mercadopago

app = Flask(__name__)
CORS(app)

MP_ACCESS_TOKEN = os.environ.get("MP_ACCESS_TOKEN", "APP_USR-1738991350202380-110920-8485edb539259d0282b38a9d643d7e92-3346874904")
sdk = mercadopago.SDK(MP_ACCESS_TOKEN)

DB_FILE = "db.json"

def load_db():
    if not os.path.exists(DB_FILE):
        return {"libraries": {}}
    with open(DB_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

def save_db(data):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

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
                    db = load_db()
                    user_lib = db["libraries"].get(user_email, [])
                    for gid in game_ids:
                        if gid not in user_lib:
                            user_lib.append(gid)
                    db["libraries"][user_email] = user_lib
                    save_db(db)
        except Exception as e:
            print("Erro:", e)
    return jsonify({"status": "ok"}), 200

@app.route("/library/<email>", methods=["GET"])
def get_library(email):
    db = load_db()
    return jsonify({"game_ids": db["libraries"].get(email, [])})

if __name__ == "__main__":
    app.run(port=5000, debug=True)
