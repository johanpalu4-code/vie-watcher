"""
VIE Watcher : surveille les nouvelles offres VIE (Mon VIE via Business France)
et n'envoie sur ton webhook Discord que celles qui correspondent a tes domaines :
admin systeme / reseau, cybersecurite, developpement web.

Installation :  pip install requests
Lancement local  :  python vie_watcher.py          (boucle toutes les 2 min)
Lancement GitHub :  RUN_ONCE=1 python vie_watcher.py (une seule verification)

Le webhook et la cle API sont lus dans les variables d'environnement
WEBHOOK_URL et API_KEY (secrets GitHub). Ne les ecris jamais dans ce fichier.
"""

import json
import os
import re
import time
import unicodedata

import requests

# ---------------- CONFIGURATION ----------------
API_URL = "https://civiweb-api-prd.azurewebsites.net/api/Offers/search"
OFFER_URL = "https://mon-vie-via.businessfrance.fr/offres/{id}"
WEBHOOK_URL = os.environ.get("WEBHOOK_URL", "")
API_KEY = os.environ.get("API_KEY", "")   # valeur de X-Api-Key vue dans DevTools
RUN_ONCE = os.environ.get("RUN_ONCE") == "1"
SEEN_FILE = "seen_offers.json"
POLL_SECONDS = 120          # toutes les 2 minutes, inutile de spammer l'API
FETCH_LIMIT = 50            # nombre d'offres recentes recuperees a chaque passage

# Mots-cles cherches dans le TITRE de l'offre (match large)
TITLE_KEYWORDS = [
    # Systeme / reseau / infra
    "administrateur systeme", "admin sys", "sysadmin", "system administrator",
    "systems engineer", "ingenieur systeme", "reseau", "network", "infrastructure",
    "infra", "it support", "support informatique", "helpdesk", "help desk",
    "technicien informatique", "it technician", "it engineer", "it officer",
    "it project", "it manager", "informatique", "cloud", "devops", "sre",
    "telecom", "it specialist", "it consultant", "it analyst",
    # Cyber
    "cyber", "cybersecurite", "cybersecurity", "securite informatique",
    "securite des systemes", "information security", "infosec", "it security",
    "soc", "pentest", "pentester", "grc", "iam", "rssi", "ciso",
    # Dev web
    "developpeur", "developer", "developpement web", "web developer",
    "full stack", "fullstack", "front end", "frontend", "front-end",
    "back end", "backend", "back-end", "software engineer", "ingenieur logiciel",
    "php", "javascript", "react", "angular", "symfony", "laravel", "node",
]

# Mots-cles "forts" cherches aussi dans la DESCRIPTION (peu de faux positifs)
DESCRIPTION_KEYWORDS = [
    "active directory", "entra id", "azure ad", "microsoft 365", "office 365",
    "fortinet", "fortigate", "pare-feu", "firewall", "vmware", "hyper-v",
    "powershell", "cybersecurite", "cybersecurity", "siem", "soc analyst",
    "developpeur web", "web developer", "full stack", "fullstack",
    "administrateur systeme", "administrateur reseau", "system administrator",
    "network administrator",
]

# Si un de ces mots est dans le titre, on ignore l'offre (ajuste a ton gout)
TITLE_EXCLUDE = [
    "sales", "commercial", "vente", "marketing", "comptab", "finance",
    "achat", "purchas", "supply chain", "rh ", "human resources",
]
# ------------------------------------------------


def normalize(text):
    """Minuscules + suppression des accents pour comparer proprement."""
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text.lower()


def contains_any(text, keywords):
    text = normalize(text)
    for kw in keywords:
        pattern = r"(?<![a-z0-9])" + re.escape(normalize(kw)) + r"(?![a-z0-9])"
        if re.search(pattern, text):
            return kw
    return None


def pick(offer, *keys, default=""):
    """Recupere le premier champ existant (les noms de champs de l'API peuvent varier)."""
    for k in keys:
        v = offer.get(k)
        if v not in (None, "", []):
            return v
    return default


def fetch_offers():
    payload = {
        "limit": FETCH_LIMIT,
        "skip": 0,
        "query": None,
        "activitySectorId": [],
        "missionsTypesIds": [],
        "missionsDurations": [],
        "gerographicZones": [],
        "countriesIds": [],
        "studiesLevelId": [],
        "companiesSizes": [],
        "specializationsIds": [],
        "entreprisesIds": [0],
        "missionStartDate": None,
    }
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Content-Type": "application/json",
        "Origin": "https://mon-vie-via.businessfrance.fr",
        "Referer": "https://mon-vie-via.businessfrance.fr/",
        "X-Api-Key": API_KEY,
    }
    r = requests.post(API_URL, json=payload, timeout=30, headers=headers)
    r.raise_for_status()
    data = r.json()
    return data.get("result", data if isinstance(data, list) else [])


def is_relevant(offer):
    title = pick(offer, "missionTitle", "title")
    description = pick(offer, "missionDescription", "description")
    if contains_any(title, TITLE_EXCLUDE):
        return None
    return contains_any(title, TITLE_KEYWORDS) or contains_any(description, DESCRIPTION_KEYWORDS)


def notify(offer, matched_kw):
    oid = pick(offer, "id")
    title = pick(offer, "missionTitle", "title", default="Offre VIE")
    org = pick(offer, "organizationName", "companyName", default="?")
    country = pick(offer, "countryNameEn", "countryName", default="?")
    city = pick(offer, "cityNameEn", "cityName", "city", default="")
    duration = pick(offer, "missionDuration", default="?")
    salary = pick(offer, "indemnite", "salary", default="?")
    start = str(pick(offer, "missionStartDate", default="?"))[:10]

    embed = {
        "title": title[:250],
        "url": OFFER_URL.format(id=oid),
        "color": 0x2ECC71,
        "fields": [
            {"name": "Entreprise", "value": str(org), "inline": True},
            {"name": "Lieu", "value": f"{city}, {country}".strip(", "), "inline": True},
            {"name": "Duree", "value": f"{duration} mois", "inline": True},
            {"name": "Indemnite", "value": f"{salary} EUR", "inline": True},
            {"name": "Debut", "value": start, "inline": True},
            {"name": "Mot-cle", "value": matched_kw, "inline": True},
        ],
    }
    r = requests.post(WEBHOOK_URL, json={"embeds": [embed]}, timeout=15)
    if r.status_code == 429:  # rate limit Discord
        time.sleep(r.json().get("retry_after", 2))
        requests.post(WEBHOOK_URL, json={"embeds": [embed]}, timeout=15)


def load_seen():
    if os.path.exists(SEEN_FILE):
        with open(SEEN_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    return None


def save_seen(seen):
    with open(SEEN_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(seen)[-5000:], f)


def check_once(seen):
    for offer in reversed(fetch_offers()):
        oid = str(pick(offer, "id"))
        if not oid or oid in seen:
            continue
        seen.add(oid)
        kw = is_relevant(offer)
        title = pick(offer, "missionTitle", "title")
        if kw:
            print(f"[MATCH] {title} ({kw})")
            notify(offer, kw)
        else:
            print(f"[skip]  {title}")
    save_seen(seen)


def main():
    if not WEBHOOK_URL or not API_KEY:
        raise SystemExit("WEBHOOK_URL ou API_KEY manquant (variables d'environnement).")

    seen = load_seen()
    if seen is None:
        # Premier lancement : on memorise l'existant sans notifier (evite le flood)
        offers = fetch_offers()
        seen = {str(pick(o, "id")) for o in offers}
        save_seen(seen)
        print(f"Init OK, {len(seen)} offres existantes ignorees.")
        if RUN_ONCE:
            return

    if RUN_ONCE:
        check_once(seen)
        return

    print("Surveillance lancee.")
    while True:
        try:
            check_once(seen)
        except Exception as e:
            print(f"Erreur : {e}")
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
