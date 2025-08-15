import os
import json
import datetime
import uuid
from flask import Flask, request, jsonify
import firebase_admin
from firebase_admin import credentials, firestore

app = Flask(__name__)

# Load Firebase credentials from environment variable
cred_json = os.environ.get("FIREBASE_CRED_JSON")
if not cred_json:
    raise RuntimeError("FIREBASE_CRED_JSON environment variable not set")

cred_dict = json.loads(cred_json)
cred = credentials.Certificate(cred_dict)
firebase_admin.initialize_app(cred)
db = firestore.client()

API_KEY = os.environ.get("API_KEY", "default_api_key")

# Endpoint to validate license
@app.route("/validate", methods=["POST"])
def validate_license():
    data = request.get_json()
    key = data.get("key")
    hwid = data.get("hwid")

    if not key or not hwid:
        return jsonify({"status": "error", "message": "Missing key or hwid"}), 400

    doc_ref = db.collection("licenses").document(key)
    doc = doc_ref.get()

    if not doc.exists:
        return jsonify({"status": "error", "message": "Invalid key"}), 404

    license_data = doc.to_dict()
    expire_time = license_data.get("expire_time")
    bound_hwid = license_data.get("hwid")

    # Check expiration
    if expire_time and datetime.datetime.utcnow() > expire_time.replace(tzinfo=None):
        return jsonify({"status": "error", "message": "License expired"}), 403

    # If hwid not set, bind it
    if not bound_hwid:
        doc_ref.update({"hwid": hwid})
    elif bound_hwid != hwid:
        return jsonify({"status": "error", "message": "HWID mismatch"}), 403

    return jsonify({"status": "success", "message": "License valid"}), 200

# Admin endpoint to create license
@app.route("/create", methods=["POST"])
def create_license():
    if request.headers.get("X-API-KEY") != API_KEY:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    data = request.get_json()
    days_valid = data.get("days", 30)
    key = data.get("key") or str(uuid.uuid4())[:8]
    expire_time = datetime.datetime.utcnow() + datetime.timedelta(days=days_valid)

    db.collection("licenses").document(key).set({
        "hwid": None,
        "expire_time": expire_time
    })

    return jsonify({"status": "success", "key": key, "expire_time": expire_time.isoformat()})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
