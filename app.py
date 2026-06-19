#!/usr/bin/env python3
import os
from flask import Flask, request, jsonify, send_from_directory, Response
import requests as req
import re
import csv
import io
import time
import random

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=BASE_DIR, static_url_path="")

YELP_API_KEY = os.environ.get("YELP_API_KEY", "")
YELP_HEADERS = {
    "Authorization": f"Bearer {YELP_API_KEY}",
    "Accept": "application/json",
}

WEB_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

IG_SKIP = {
    'p','explore','accounts','stories','reels','tv','reel','login','signup',
    'about','press','api','legal','privacy','_n_','direct','null','sharer',
    'intent','share','hashtag','tagged','mentions','feed','home','search','reel',
}


# ─────────────────────────────────────────────
# STAGE 1: Yelp Fusion API → businesses
# ─────────────────────────────────────────────
def yelp_search(niche, location, session, limit=50):
    businesses = []
    try:
        r = session.get(
            "https://api.yelp.com/v3/businesses/search",
            headers=YELP_HEADERS,
            params={"term": niche, "location": location, "limit": limit},
            timeout=15,
        )
        if r.status_code != 200:
            return businesses
        for b in r.json().get("businesses", []):
            businesses.append({
                "name":               b.get("name", ""),
                "yelp_id":            b.get("id", ""),
                "yelp_url":           b.get("url", ""),
                "phone":              b.get("display_phone", "") or b.get("phone", ""),
                "website":            "",
                "instagram_username": "",
                "category":           ", ".join(c["title"] for c in b.get("categories", [])),
            })
    except Exception:
        pass
    return businesses


# ─────────────────────────────────────────────
# STAGE 2: Yelp business detail API → website
# ─────────────────────────────────────────────
def yelp_biz_detail(biz, session):
    if not biz.get("yelp_id"):
        return biz
    try:
        r = session.get(
            f"https://api.yelp.com/v3/businesses/{biz['yelp_id']}",
            headers=YELP_HEADERS,
            timeout=10,
        )
        if r.status_code == 200:
            data = r.json()
            biz["website"] = data.get("url", "")  # external website if available
            # Some responses include hours/attributes but not always a website
            # Use the Yelp URL as fallback website
            if not biz["website"]:
                biz["website"] = biz.get("yelp_url", "")
    except Exception:
        pass
    return biz


# ─────────────────────────────────────────────
# STAGE 3: Business website → Instagram username
# ─────────────────────────────────────────────
def find_ig_on_website(website_url, session):
    if not website_url:
        return None
    try:
        time.sleep(random.uniform(0.5, 1.5))
        r = session.get(website_url, headers=HEADERS, timeout=10, allow_redirects=True)
        if r.status_code != 200:
            return None
        ig = re.findall(r'instagram\.com/([A-Za-z0-9._]{2,40})', r.text)
        clean = [u for u in ig if u.lower() not in IG_SKIP]
        return clean[0] if clean else None
    except Exception:
        return None


# ─────────────────────────────────────────────
# STAGE 4: Instagram profile data
# ─────────────────────────────────────────────
def extract_contact(text):
    phone_patterns = [
        r'wa\.me/(\+?[\d]{7,15})',
        r'\+1[\s\-.]?\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4}',
        r'\+44[\s\-.]?\d{2,4}[\s\-.]?\d{3,4}[\s\-.]?\d{3,4}',
        r'\+92[\s\-.]?\d{3}[\s\-.]?\d{7}',
        r'\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4}',
    ]
    found = []
    for p in phone_patterns:
        found.extend(re.findall(p, text))
    nums = [re.sub(r'[^\d+]', '', m) for m in found if len(re.sub(r'\D', '', m)) >= 7]
    phone = list(dict.fromkeys(nums))[0] if nums else ""

    em = re.search(r'[\w\.\+\-]+@[\w\.-]+\.\w{2,}', text)
    email = em.group() if em else ""
    return phone, email


def fetch_ig_profile(username, session):
    data = {
        "full_name": "", "bio": "", "followers": "N/A",
        "whatsapp": "", "email": "", "ig_website": "",
        "is_business": False, "category": "",
    }
    try:
        time.sleep(random.uniform(1, 2.5))
        r = session.get(
            f"https://www.instagram.com/{username}/",
            headers={
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept": "text/html,application/xhtml+xml",
            },
            timeout=12,
        )
        if r.status_code != 200:
            return data

        text = r.text
        for pat, key in [
            (r'"edge_followed_by":\{"count":(\d+)\}', "followers"),
            (r'"follower_count":(\d+)', "followers"),
            (r'"full_name":"([^"]+)"', "full_name"),
            (r'"biography":"([^"]*)"', "bio"),
            (r'"external_url":"([^"]*)"', "ig_website"),
            (r'"is_business_account":(true|false)', "is_business"),
            (r'"is_professional_account":(true|false)', "is_business"),
            (r'"category_name":"([^"]*)"', "category"),
        ]:
            if key in data and data[key] not in ("", "N/A", False):
                continue
            m = re.search(pat, text)
            if m:
                val = m.group(1)
                if key == "followers":
                    try: val = int(val)
                    except: continue
                elif key == "is_business":
                    val = (val == "true")
                elif key == "bio":
                    val = (val.replace('\\n', ' ')
                              .replace('\\u0040', '@')
                              .replace('\\"', '"')
                              .replace('\\u2019', "'"))
                data[key] = val

        wa, em = extract_contact(data.get("bio", ""))
        data["whatsapp"] = wa
        data["email"] = em

    except Exception:
        pass
    return data


# ─────────────────────────────────────────────
# FLASK ROUTES
# ─────────────────────────────────────────────
@app.route("/")
def index():
    return send_from_directory(BASE_DIR, "dashboard.html")


@app.route("/scrape", methods=["POST"])
def scrape():
    body = request.json or {}
    niche    = body.get("niche", "").strip()
    location = body.get("location", "").strip()
    if not niche or not location:
        return jsonify({"error": "niche and location required"}), 400

    session = req.Session()
    session.headers.update({"Accept-Encoding": "gzip, deflate"})

    # Stage 1 — Yelp Fusion API search
    businesses = yelp_search(niche, location, session, limit=50)

    leads = []
    for biz in businesses[:50]:
        # Stage 2 — Yelp business detail for website
        biz = yelp_biz_detail(biz, session)

        ig_username = biz.get("instagram_username")

        # Stage 3 — Website → Instagram
        if not ig_username and biz.get("website"):
            ig_username = find_ig_on_website(biz["website"], session)

        if ig_username:
            # Stage 4 — Instagram profile
            ig = fetch_ig_profile(ig_username, session)
            leads.append({
                "Business Name":  ig.get("full_name") or biz["name"],
                "Username":       ig_username,
                "Instagram URL":  f"https://www.instagram.com/{ig_username}/",
                "Followers":      ig.get("followers", "N/A"),
                "Bio":            ig.get("bio", "")[:160],
                "WhatsApp":       ig.get("whatsapp") or biz.get("phone", ""),
                "Email":          ig.get("email", ""),
                "Website":        ig.get("ig_website") or biz.get("website", ""),
                "Category":       ig.get("category", ""),
                "Is Business":    "Yes" if ig.get("is_business") else "—",
                "Phone":          biz.get("phone", ""),
                "Source":         "Yelp + Instagram",
                "Yelp URL":       biz.get("yelp_url", ""),
            })
        else:
            # No Instagram found — still a useful lead with phone/website
            leads.append({
                "Business Name":  biz["name"],
                "Username":       "",
                "Instagram URL":  "",
                "Followers":      "N/A",
                "Bio":            "",
                "WhatsApp":       "",
                "Email":          "",
                "Website":        biz.get("website", ""),
                "Category":       "",
                "Is Business":    "Yes",
                "Phone":          biz.get("phone", ""),
                "Source":         "Yelp",
                "Yelp URL":       biz.get("yelp_url", ""),
            })

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
        headers={"Content-Disposition": "attachment; filename=instagram_leads.csv"},
    )


@app.route("/push-to-sheets", methods=["POST"])
def push_to_sheets():
    """Forward leads to a Google Apps Script web app URL."""
    body = request.json or {}
    script_url = body.get("script_url", "").strip()
    leads = body.get("leads", [])

    if not script_url:
        return jsonify({"error": "script_url required"}), 400
    if not leads:
        return jsonify({"error": "no leads to push"}), 400

    try:
        r = req.post(
            script_url,
            json={"leads": leads},
            headers={"Content-Type": "application/json"},
            timeout=30,
        )
        return jsonify({"ok": True, "status": r.status_code, "response": r.text[:200]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    app.run(port=5055, debug=False)
