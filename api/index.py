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



import concurrent.futures
import re

WEB_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

def fetch_yelp_details(biz_id):
    try:
        r = req.get(
            f"https://api.yelp.com/v3/businesses/{biz_id}",
            headers={
                "Authorization": f"Bearer {YELP_API_KEY}",
                "Accept": "application/json",
            },
            timeout=2.5
        )
        if r.status_code == 200:
            data = r.json()
            return data.get("attributes", {}).get("business_url", "")
    except Exception:
        pass
    return ""

def scrape_socials_from_url(url):
    if not url:
        return "", ""
    try:
        if not url.startswith("http"):
            url = "http://" + url
        r = req.get(url, headers=WEB_HEADERS, timeout=2.5)
        if r.status_code == 200:
            html = r.text
            urls = re.findall(r'href=["\']([^"\']+)["\']', html, re.IGNORECASE)
            fb_link = ""
            ig_link = ""
            for u in urls:
                if u.startswith("//"):
                    u = "https:" + u
                u_lower = u.lower()
                if "facebook.com" in u_lower or "fb.com" in u_lower:
                    if not any(x in u_lower for x in ["/sharer", "/share", "facebook.com/plugins", "tr?id=", "sharer.php"]):
                        if u.startswith("http"):
                            if not fb_link:
                                fb_link = u
                elif "instagram.com" in u_lower:
                    if not any(x in u_lower for x in ["/developer", "/about", "/p/"]):
                        if u.startswith("http"):
                            if not ig_link:
                                ig_link = u
            return fb_link, ig_link
    except Exception:
        pass
    return "", ""

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
            params={"term": niche, "location": location, "limit": 30},
            timeout=20,
        )
    except Exception as e:
        return jsonify({"error": f"Network error: {str(e)}"}), 500

    if r.status_code != 200:
        return jsonify({"error": f"Yelp API error {r.status_code}: {r.text[:300]}"}), 500

    businesses = r.json().get("businesses", [])
    
    # Only enrich the top 10 businesses to prevent Yelp API throttling and Vercel timeouts
    enrich_count = min(10, len(businesses))
    enrich_businesses = businesses[:enrich_count]
    
    # Fetch Yelp Details concurrently to get external websites
    biz_ids = [b.get("id") for b in enrich_businesses if b.get("id")]
    websites = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        future_to_id = {executor.submit(fetch_yelp_details, bid): bid for bid in biz_ids}
        for future in concurrent.futures.as_completed(future_to_id):
            bid = future_to_id[future]
            try:
                web_url = future.result()
                if web_url:
                    websites[bid] = web_url
            except Exception:
                pass

    # Scrape socials concurrently from websites
    socials = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        future_to_id = {executor.submit(scrape_socials_from_url, wurl): bid for bid, wurl in websites.items()}
        for future in concurrent.futures.as_completed(future_to_id):
            bid = future_to_id[future]
            try:
                fb, ig = future.result()
                socials[bid] = {"facebook": fb, "instagram": ig}
            except Exception:
                pass

    leads = []
    for b in businesses:
        bid = b.get("id")
        external_web = websites.get(bid, "")
        fb_profile = socials.get(bid, {}).get("facebook", "")
        ig_profile = socials.get(bid, {}).get("instagram", "")
        
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
            "Website":       external_web or b.get("url", ""),
            "Facebook Profile Link": fb_profile,
            "Instagram Profile Link": ig_profile,
            "Source":        "Yelp" + (" + Socials" if fb_profile or ig_profile else ""),
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

