import os
import json
import datetime
import uuid
import sys
from flask import Flask, request, jsonify
import firebase_admin
from firebase_admin import credentials, firestore
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # Enable CORS for all routes

# --- Firebase Initialization ---
# Reverted to use the FIREBASE_CRED_JSON environment variable as you have it configured.
try:
    cred_json_str = os.environ.get("FIREBASE_CRED_JSON")
    if not cred_json_str:
        raise RuntimeError("FIREBASE_CRED_JSON environment variable not set or empty.")
    
    cred_dict = json.loads(cred_json_str)
    cred = credentials.Certificate(cred_dict)
    firebase_admin.initialize_app(cred)
    db = firestore.client()
    print("Firebase initialized successfully from environment variable.")
except Exception as e:
    # Log a fatal error if Firebase can't be initialized
    print(f"FATAL: Error initializing Firebase: {e}", file=sys.stderr)
    sys.exit(1) # Exit if the database connection fails

# --- API Key for Admin Actions ---
# Get the API key from environment variables for security
API_KEY = os.environ.get("API_KEY", "default_api_key_for_local_testing")

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
    status = license_data.get("status")

    if status != 'active':
        return jsonify({"status": "error", "message": "License is inactive or paused"}), 403

    # Ensure the datetime object from Firestore is timezone-aware for correct comparison
    if expire_time and datetime.datetime.now(datetime.timezone.utc) > expire_time:
        return jsonify({"status": "error", "message": "License expired"}), 403

    if not bound_hwid:
        # First time this key is used, bind the HWID to it
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
    # FIX: Convert the 'days' value from the request to an integer.
    days_valid = int(data.get("days", 30))
    key = data.get("key") or str(uuid.uuid4())[:8].upper()
    
    # Use timezone-aware datetime object for consistency
    expire_time = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=days_valid)

    db.collection("licenses").document(key).set({
        "hwid": None,
        "expire_time": expire_time,
        "status": 'active'
    })

    return jsonify({"status": "success", "key": key, "expire_time": expire_time.isoformat()})

# Admin endpoint to delete a license
@app.route("/delete/<key>", methods=["POST"])
def delete_license(key):
    if request.headers.get("X-API-KEY") != API_KEY:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    db.collection("licenses").document(key).delete()
    return jsonify({"status": "success", "message": f"License {key} deleted"}), 200

# Admin endpoint to reset HWID
@app.route("/reset-hwid/<key>", methods=["POST"])
def reset_hwid(key):
    if request.headers.get("X-API-KEY") != API_KEY:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401

    doc_ref = db.collection("licenses").document(key)
    doc_ref.update({"hwid": None})
    return jsonify({"status": "success", "message": f"HWID for license {key} reset"}), 200
    
# Admin endpoint to toggle key status
@app.route("/toggle-status/<key>", methods=["POST"])
def toggle_status(key):
    if request.headers.get("X-API-KEY") != API_KEY:
        return jsonify({"status": "error", "message": "Unauthorized"}), 401
    
    doc_ref = db.collection("licenses").document(key)
    doc = doc_ref.get()
    
    if not doc.exists:
        return jsonify({"status": "error", "message": "Invalid key"}), 404
        
    license_data = doc.to_dict()
    new_status = 'paused' if license_data.get('status') == 'active' else 'active'
    
    doc_ref.update({"status": new_status})
    return jsonify({"status": "success", "message": f"License {key} status changed to {new_status}"}), 200


# Endpoint to get all licenses (for the website)
@app.route("/licenses", methods=["GET"])
def get_all_licenses():
    licenses_ref = db.collection("licenses")
    docs = licenses_ref.stream()
    licenses = []
    for doc in docs:
        data = doc.to_dict()
        # Ensure expire_time is converted to a string for JSON serialization
        if 'expire_time' in data and isinstance(data['expire_time'], datetime.datetime):
            data['expire_time'] = data['expire_time'].isoformat()
        data['id'] = doc.id
        licenses.append(data)
    return jsonify({"licenses": licenses}), 200

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
