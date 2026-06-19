#!/usr/bin/env python3
import os
from flask import Flask, request, jsonify, Response
import requests as req
import csv
import io

app = Flask(__name__)

YELP_API_KEY = os.environ.get(
    "YELP_API_KEY",
    "VBeaGGKDiSdCzAfbi_ouJc7HlapwrDFALu7Rjos7zCMQsJvllkb2RLYvGLtYsx5rm-KoUmBLcx9j5rzGEs56UiUIvfqdNIw2AEhczcxc01_Y85I8uumIsrrTm-E0anYx"
)



@app.route("/health")
def health():
    return jsonify({"ok": True, "key_set": bool(YELP_API_KEY)})


@app.route("/scrape", methods=["POST"])
def scrape():
    body = request.json or {}
    niche    = body.get("niche", "").strip()
    location = body.get("location", "").strip()
    if not niche or not location:
        return jsonify({"error": "niche and location required"}), 400

    try:
        r = req.get(
            "https://api.yelp.com/v3/businesses/search",
            headers={
                "Authorization": f"Bearer {YELP_API_KEY}",
                "Accept": "application/json",
            },
            params={"term": niche, "location": location, "limit": 50},
            timeout=20,
        )
    except Exception as e:
        return jsonify({"error": f"Network error: {str(e)}"}), 500

    if r.status_code != 200:
        return jsonify({"error": f"Yelp API error {r.status_code}: {r.text[:300]}"}), 500

    businesses = r.json().get("businesses", [])
    leads = []
    for b in businesses:
        leads.append({
            "Business Name": b.get("name", ""),
            "Phone":         b.get("display_phone", "") or b.get("phone", ""),
            "Address":       ", ".join(filter(None, [
                                b.get("location", {}).get("address1", ""),
                                b.get("location", {}).get("city", ""),
                                b.get("location", {}).get("state", ""),
                             ])),
            "Rating":        str(b.get("rating", "")),
            "Reviews":       str(b.get("review_count", "")),
            "Category":      ", ".join(c["title"] for c in b.get("categories", [])),
            "Website":       b.get("url", ""),
            "Source":        "Yelp",
        })

    return jsonify({"leads": leads, "total": len(leads)})


@app.route("/export-csv", methods=["POST"])
def export_csv():
    body  = request.json or {}
    leads = body.get("leads", [])
    if not leads:
        return jsonify({"error": "no data"}), 400

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=leads[0].keys())
    writer.writeheader()
    writer.writerows(leads)

    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=leads.csv"},
    )


if __name__ == "__main__":
    from flask import send_from_directory
    @app.route("/")
    def index():
        import os
        parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return send_from_directory(parent_dir, "index.html")

    app.run(port=5055, debug=False)

