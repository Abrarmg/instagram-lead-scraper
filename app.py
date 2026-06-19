#!/usr/bin/env python3
import os
from flask import Flask, request, jsonify, send_from_directory, Response
import requests as req
import re
import csv
import io

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=BASE_DIR, static_url_path="")

YELP_API_KEY = os.environ.get("YELP_API_KEY", "VBeaGGKDiSdCzAfbi_ouJc7HlapwrDFALu7Rjos7zCMQsJvllkb2RLYvGLtYsx5rm-KoUmBLcx9j5rzGEs56UiUIvfqdNIw2AEhczcxc01_Y85I8uumIsrrTm-E0anYx")
YELP_HEADERS = {
    "Authorization": f"Bearer {YELP_API_KEY}",
    "Accept": "application/json",
}


def yelp_search(niche, location, limit=50):
    businesses = []
    try:
        r = req.get(
            "https://api.yelp.com/v3/businesses/search",
            headers=YELP_HEADERS,
            params={"term": niche, "location": location, "limit": limit},
            timeout=15,
        )
        if r.status_code != 200:
            return businesses, f"Yelp API error {r.status_code}: {r.text[:200]}"
        for b in r.json().get("businesses", []):
            ig_url = ""
            ig_username = ""
            # Some Yelp listings include Instagram in their social links
            for attr in b.get("attributes", {}).values():
                if isinstance(attr, str) and "instagram.com" in attr:
                    m = re.search(r'instagram\.com/([A-Za-z0-9._]{2,40})', attr)
                    if m:
                        ig_username = m.group(1)
                        ig_url = f"https://www.instagram.com/{ig_username}/"
            businesses.append({
                "Business Name":  b.get("name", ""),
                "Username":       ig_username,
                "Instagram URL":  ig_url,
                "Followers":      "N/A",
                "Phone":          b.get("display_phone", "") or b.get("phone", ""),
                "Email":          "",
                "Website":        b.get("url", ""),
                "Category":       ", ".join(c["title"] for c in b.get("categories", [])),
                "Rating":         str(b.get("rating", "")),
                "Reviews":        str(b.get("review_count", "")),
                "Address":        ", ".join(filter(None, [
                    b.get("location", {}).get("address1", ""),
                    b.get("location", {}).get("city", ""),
                    b.get("location", {}).get("state", ""),
                ])),
                "Source":         "Yelp",
            })
    except Exception as e:
        return businesses, str(e)
    return businesses, None


@app.route("/")
def index():
    resp = send_from_directory(BASE_DIR, "dashboard.html")
    resp.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    resp.headers["Pragma"] = "no-cache"
    return resp


@app.route("/scrape", methods=["POST"])
def scrape():
    body = request.json or {}
    niche    = body.get("niche", "").strip()
    location = body.get("location", "").strip()
    if not niche or not location:
        return jsonify({"error": "niche and location required"}), 400

    leads, error = yelp_search(niche, location, limit=50)
    if error and not leads:
        return jsonify({"error": error}), 500

    return jsonify({"leads": leads, "total": len(leads)})


@app.route("/export-csv", methods=["POST"])
def export_csv():
    body = request.json or {}
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
    app.run(port=5055, debug=False)
