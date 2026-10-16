#!/usr/bin/env python3
"""Westerly-zoeker: verzamelt Westerly-zeilboten die in Nederland (en daarbuiten) te koop of op veiling staan,
bewaart prijs- en biedhistorie en schrijft docs/data/*.json|csv. Alleen standaardbibliotheek."""
import csv, datetime, html, json, pathlib, re, sys, time, urllib.parse, urllib.request, urllib.error

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
      "Accept-Language": "nl-NL,nl;q=0.9,en;q=0.5"}
ROOT = pathlib.Path(__file__).parent
DATA = ROOT / "docs" / "data"
CFG = json.load(open(ROOT / "config.json"))
GQL = "https://storefront.tbauctions.com/storefront/graphql"
M2FT = 3.28084

# model -> (zoekpatroon, standaardlengte in voet; None = onbekend). Alleen modellen waarvan de lengte zeker is.
MODELLEN = [
    ("Centaur", r"centaur", 26), ("Konsort", r"konsort", 29), ("Griffon", r"griffon", 26), ("Fulmar", r"fulmar", 32),
    ("Storm", r"storm\b|seastorm", 33), ("Pentland", r"pentland", 36), ("Tiger", r"tiger", 25), ("Typhoon", r"typhoon", 37),
    ("Berwick", r"berwick", 24), ("Longbow", r"longbow", 35), ("Seahawk", r"seahawk", 35), ("Conway", r"conway", 36),
    ("Corsair", r"corsair", 36), ("Oceanmaster", r"ocean ?master", 48), ("Oceanranger", r"ocean ?ranger", 38),
    ("Oceanlord", r"ocean ?lord", 41), ("Renown", r"renown", 38), ("Merlin", r"merlin", 25), ("Falcon", r"falcon", None),
    ("Chieftain", r"chieftain", None), ("Sealord", r"sea ?lord", None), ("Footloose", r"footloose", None),
    ("Nomad", r"nomad", None), ("Pageant", r"pageant", None), ("Cirrus", r"cirrus", None), ("Rapier", r"rapier", None),
    ("Vulcan", r"vulcan", None), ("Teal", r"\bteal\b", None), ("Windrush", r"windrush", None), ("Sirocco", r"sirocco", None),
    ("Regatta", r"regatta", None), ("Kestrel", r"kestrel", None), ("Discus", r"discus", None), ("Tempest", r"tempest", None),
    ("Jouster", r"jouster", None), ("Highlander", r"highlander", None), ("Oceanquest", r"ocean ?quest", 35),
    ("Ocean 33", r"ocean 33|33 ocean", 33), ("Humphreys HOD 35", r"humphreys|hod 35", 35),
]
NIET_WESTERLY_ONDERDEEL = re.compile(r"zeil(en)?\b.*\b(set|los)|onderdel|reserve|motor |buitenboord|gitaar|guild|jeans|trailer|kuiptent|patrijspoort|mast, giek|rolgrootzeil|cover|hoes", re.I)


def nu_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="minutes")


def haal(url, tries=3, data=None, headers=None, tekst=True):
    h = dict(UA)
    h.update(headers or {})
    for i in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data, headers=h), timeout=30) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as e:
            if i == tries - 1:
                print("FOUT", url[:90], e, file=sys.stderr)
                return ""
            time.sleep(10 if "403" in str(e) or "429" in str(e) else 2)


def getal(s):
    """'€ 34.500' / '£ 14.000' / '12,5' -> float."""
    s = re.sub(r"[^\d,.]", "", s or "")
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".") if len(s.split(",")[-1]) <= 2 else s.replace(",", "")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")
    try:
        return float(s)
    except ValueError:
        return None


def herken_model(tekst):
    t = (tekst or "").lower()
    for naam, pat, ft in MODELLEN:
        if re.search(pat, t):
            return naam, ft
    m = re.search(r"westerly\s*(\d{2})\b", t)
    if m:
        return "Westerly " + m.group(1), int(m.group(1))
    return "Westerly (overig)", None


def lengte_ft(titel, tekst, lengte_m=None, model_ft=None):
    """Lengte in voet zoals eigenaren die noemen (nominaal: 'Konsort 29', 'Westerly 33'); gemeten lengte is vaak iets korter."""
    t = (titel or "")
    m = re.search(r"westerly\s*(\d{2})\b(?!\s?(?:cm|m\b))", t, re.I) or re.search(r"\b(?:" + "|".join(p for _, p, _ in MODELLEN) + r")\s*(\d{2})\b", t, re.I)
    if m and 18 <= int(m.group(1)) <= 60:
        return float(m.group(1)), "modelnaam"
    m = re.search(r"\b(\d{2})\s?(?:ft|feet|foot|voet|'|’)", t + " " + (tekst or ""), re.I)
    if m and 15 <= int(m.group(1)) <= 60:
        return float(m.group(1)), "advertentie"
    if model_ft:
        return float(model_ft), "modeltabel (indicatief)"
    if lengte_m and 5 < lengte_m < 25:
        return round(lengte_m * M2FT, 1), "gemeten (m→ft)"
    return None, ""


def bouwjaar(*teksten):
    for t in teksten:
        m = re.search(r"\b(19[6-9]\d|200[0-2])\b", t or "")
        if m:
            return int(m.group(1))
    return None


def maak(bron, extid, url, titel, tekst="", prijs=None, valuta="EUR", jaar=None, lengte_m=None, land="", plaats="", foto="", **extra):
    model, mft = herken_model(titel + " " + (tekst or "")[:300])
    ft, ftbron = lengte_ft(titel, tekst, lengte_m, mft)
    r = {"id": f"{bron}-{extid}", "bron": bron, "url": url, "titel": re.sub(r"\s+", " ", titel).strip(), "type": model,
         "lengte_ft": ft, "lengte_bron": ftbron, "lengte_m": round(lengte_m, 2) if lengte_m and 5 < lengte_m < 25 else None, "bouwjaar": jaar or bouwjaar(titel, tekst), "land": land, "plaats": plaats,
         "valuta": valuta, "prijs": prijs, "foto": foto, "tekst": re.sub(r"\s+", " ", tekst or "")[:300],
         "verkocht_bron": False, "biedingen": [], "veiling": None}
    r.update(extra)
    return r


# ---------------------------------------------------------------- Marktplaats
def attr(l, key):
    for a in l.get("attributes", []) + l.get("extendedAttributes", []):
        if a["key"] == key:
            return a.get("value", "")
    return ""


def marktplaats():
    uit, gezien = [], set()
    for woord in CFG["mp_zoekwoorden"]:
        for off in (0, 100):
            q = urllib.parse.urlencode({"query": woord, "limit": 100, "offset": off, "l1CategoryId": 976})
            txt = haal("https://www.marktplaats.nl/lrp/api/search?" + q)
            if not txt:
                break
            d = json.loads(txt)
            for l in d.get("listings", []):
                if l["itemId"] in gezien:
                    continue
                url = "https://www.marktplaats.nl" + l.get("vipUrl", "")
                if "kajuitzeilboten" not in url and "open-zeilboten" not in url and "overige" not in url and "motorboten" not in url and "zeilboten" not in url:
                    continue
                tekst = l["title"] + " " + l.get("description", "") + " " + attr(l, "brandCabinSailboatsYachts")
                if "westerly" not in l["title"].lower() and attr(l, "brandCabinSailboatsYachts").lower() != "westerly":
                    continue
                if re.search(r"/(zeilen-en-zeiltoebehoren|bootonderdelen|accessoires|hengelsport|motoren)", url):
                    continue
                gezien.add(l["itemId"])
                p = l["priceInfo"].get("priceCents", 0) / 100
                pt = l["priceInfo"].get("priceType", "")
                loc = l.get("location", {})
                r = maak("marktplaats", l["itemId"], url, l["title"], l.get("description", ""), p if p >= 100 else None, "EUR",
                         None, None, "NL" if not loc.get("abroad") else "buitenland", loc.get("cityName", ""),
                         ("https:" + l["imageUrls"][0]) if l.get("imageUrls") else "", prijstype=pt.lower(),
                         geplaatst=l.get("date", ""), lat=loc.get("latitude"), lon=loc.get("longitude"))
                uit.append(r)
            if not d.get("listings") or len(d["listings"]) < 100:
                break
        time.sleep(0.5)
    return uit


def mp_detail(r):
    """Biedingen + extra velden uit de advertentiepagina."""
    time.sleep(0.6)
    h = haal(r["url"], tries=3)
    if not h:
        return False
    if r["id"].split("-", 1)[1] not in h:
        return False
    i = h.find('"bidsInfo":')
    if i >= 0:
        try:
            info, _ = json.JSONDecoder().raw_decode(h[i + len('"bidsInfo":'):])
        except Exception:
            info = {}
        bieden = [{"d": b["date"], "bedrag": round(b["value"] / 100), "naam": (b.get("user") or {}).get("nickname", "")}
                  for b in info.get("bids", []) if b["value"] / 100 <= 5_000_000]
        r["biedingen_actief"] = bool(info.get("isBiddingEnabled"))
        voeg_biedingen_toe(r, bieden)
    m = re.search(r'"(?:lengte|length)"[^}]{0,80}"value":"([\d.,]+)"', h)
    return True


def voeg_biedingen_toe(r, nieuw):
    bekend = {(b["d"], b["bedrag"]) for b in r["biedingen"]}
    for b in nieuw:
        if (b["d"], b["bedrag"]) not in bekend:
            r["biedingen"].append(b)
    r["biedingen"].sort(key=lambda b: b["d"])


# ---------------------------------------------------------------- Boten-jachten.nl (aggregator)
def botenjachten():
    uit, gezien = [], set()
    for pag in range(1, 8):
        h = haal(f"https://www.boten-jachten.nl/nl/verkoop/westerly?page={pag}")
        if not h:
            break
        h = re.sub(r"<svg.*?</svg>", "", h, flags=re.S)
        kaarten = re.split(r'<div class="cards cards--two\s*">', h)[1:]
        nieuw = 0
        for k in kaarten:
            m = re.search(r'href="(https://www\.boten-jachten\.nl/nl/[^"]*-s(\d+))"[^>]*title="([^"]+)"', k)
            if not m or m.group(2) in gezien:
                continue
            gezien.add(m.group(2))
            nieuw += 1
            tekst = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", k))
            titel = re.sub(r"\s*\(\d{4}\)\s*$", "", m.group(3))
            if "westerly" not in titel.lower():
                continue
            lm = re.search(r"Lengte.{0,12}?:\s*([\d,.]+)\s*m", tekst)
            jr = re.search(r"bouwj\.?:\s*(\d{4})", tekst)
            prijsm = re.search(r"([€£$])\s*([\d.,]+)", tekst)
            loc = re.search(r"(Nederland|Verenigd Koninkrijk|Duitsland|Frankrijk|België|Spanje|Denemarken|Zweden|Noorwegen|Italië|Griekenland|Portugal|Kroatië|Ierland)[^<]{0,60}?(?=\d+ (?:dag|week|maand|jaar|uur)|\Z)", tekst)
            img = re.search(r'<img src="([^"]+)"', k)
            land = loc.group(1) if loc else ""
            uit.append(maak("botenjachten", m.group(2), m.group(1), titel, tekst, getal(prijsm.group(2)) if prijsm else None,
                            {"€": "EUR", "£": "GBP", "$": "USD"}.get(prijsm.group(1), "EUR") if prijsm else "EUR",
                            int(jr.group(1)) if jr else None, getal(lm.group(1)) if lm else None,
                            "NL" if land == "Nederland" else land, re.sub(r"\s*\d+\s+(?:dag|week|weken|maand|maanden|jaar|uur).*$", "", loc.group(0).replace(land, "")).strip(", ") if loc else "",
                            img.group(1) if img else "", verkocht_bron=("verkocht" in tekst.lower() and "te koop" not in tekst.lower())))
        if not nieuw:
            break
        time.sleep(0.7)
    return uit


# ---------------------------------------------------------------- De Valk Yacht Brokers (met 'Verkocht!')
def devalk():
    uit = []
    h = haal("https://www.devalk.nl/nl/merk/westerly.html")
    links = sorted(set(re.findall(r'href="(https://www\.devalk\.nl/nl/model/westerly/[^"]+)"', h)))
    for ml in links:
        mh = haal(ml)
        for u in sorted(set(re.findall(r'href="(https://www\.devalk\.nl/nl/jachtmakelaardij/(\d+)/[^"]+)"', mh))):
            dh = haal(u[0])
            if not dh:
                continue
            t = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"<(script|style|svg)[^>]*>.*?</\1>", "", dh, flags=re.S))))
            titel = re.search(r"<title>([^<|]+?)(?: zeiljacht)? te koop", dh)
            titel = html.unescape(titel.group(1)).strip() if titel else "Westerly"
            verkocht = "is verkocht" in t.lower()
            if verkocht:       # bovenaan staan alternatieven; de eigen gegevens staan achter 'Toon allen'
                i = t.rfind(titel + " Afmetingen")
                seg = t[i:i + 700] if i >= 0 else ""
            else:
                i = t.find("Vraagprijs")
                seg = t[max(0, i - 300):i + 120]
            jr = re.search(r"Bouwjaar (\d{4})", seg)
            af = re.search(r"Afmetingen ([\d.]+) x", seg)
            pr = re.search(r"Vraagprijs\s*€?\s*([\d.]+)", seg)
            lig = re.search(r"Ligplaats bij (.{3,50}?)(?: Brandstof| Motor| Prijs| Vraagprijs|$)", seg)
            img = re.search(r'property="og:image" content="([^"]+)"', dh)
            uit.append(maak("devalk", u[1], u[0], titel, seg, getal(pr.group(1)) if pr and not verkocht else None, "EUR",
                            int(jr.group(1)) if jr else None, float(af.group(1)) if af else None, "", lig.group(1) if lig else "",
                            img.group(1) if img else "", verkocht_bron=verkocht))
        time.sleep(0.5)
    return uit


# ---------------------------------------------------------------- Doeve Makelaars
def doeve():
    uit = []
    h = haal("https://www.doevemakelaar.nl/nl/schepen-op-merknaam/westerly")
    for path, sid, slug in sorted(set(re.findall(r'href="(/nl/schip/(\d+)/([^"]*westerly[^"]*))"', h))):
        u = "https://www.doevemakelaar.nl" + path
        dh = haal(u)
        if not dh:
            continue
        t = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"<(script|style|svg)[^>]*>.*?</\1>", "", dh, flags=re.S)))
        titel = slug.replace("-", " ").title()
        pr = re.search(r"(?:Vraagprijs|Prijs)[^\d]{0,15}([\d.]+(?:,\d+)?)", t)
        jr = re.search(r"Bouwjaar[^\d]{0,10}(\d{4})", t)
        lm = re.search(r"Lengte[^\d]{0,15}([\d,.]+)\s*m", t)
        img = re.search(r'property="og:image" content="([^"]+)"', dh)
        uit.append(maak("doeve", sid, u, titel, t[:600], getal(pr.group(1)) if pr else None, "EUR", int(jr.group(1)) if jr else None,
                        getal(lm.group(1)) if lm else None, "NL", "", img.group(1) if img else "", verkocht_bron="verkocht" in t.lower()[:400]))
    return uit


# ---------------------------------------------------------------- Boatauction.com
OUD = {}      # vorige stand; wordt in main() gezet zodat afgesloten veilingen niet opnieuw worden opgehaald


def boatauction():
    uit = []
    h = haal("https://boatauction.com/nl/brands/westerly", tries=3) or ""
    links = sorted(set(re.findall(r'(https://boatauction\.com/nl/boat-selling/(\d+)/sailboat/westerly/[a-z0-9-]+)', h)), key=lambda x: int(x[1]))
    for u, bid in links:
        o = OUD.get("boatauction-" + bid)
        if o and (o.get("veiling") or {}).get("definitief"):
            continue
        r = ba_detail(u, bid)
        if r:
            uit.append(r)
        time.sleep(0.4)
    return uit


def ba_parse(h):
    """(huidig_bod, aantal, einde_iso, gesloten) uit een Boatauction-pagina."""
    t = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", re.sub(r"<(script|style|svg)[^>]*>.*?</\1>", "", h, flags=re.S))))
    bod = re.search(r"Huidig bod:?\s*€\s*([\d.,]+)|Current bid:?\s*€\s*([\d.,]+)", t)
    aant = re.search(r"Biedingen:\s*(\d+)|Bids:\s*(\d+)", t)
    ts = re.search(r'class="countdown"[^>]*data-time="(\d+)"', h)
    gesloten = bool(re.search(r"niet meer mogelijk|no longer possible to bid", t, re.I))
    einde = datetime.datetime.fromtimestamp(int(ts.group(1)), datetime.timezone.utc).isoformat(timespec="seconds") if ts else None
    return (getal((bod.group(1) or bod.group(2))) if bod else None), (int(aant.group(1) or aant.group(2)) if aant else None), einde, gesloten, t


def ba_detail(u, bid):
    h = haal(u)
    if not h:
        return None
    bod, aantal, einde, gesloten, t = ba_parse(h)
    titel = re.search(r"<title>([^<]+?)(?: te koop| for sale)", h)
    titel = html.unescape(titel.group(1)).strip() if titel else "Westerly"
    jr = re.search(r"Bouwjaar:\s*(\d{4})|Year of construction:\s*(\d{4})", t)
    ln = re.search(r"Lengte:\s*(\d+)\s*cm|Length:\s*(\d+)\s*cm", t)
    pl = re.search(r"Ligplaats:\s*([^,]+),\s*(\w+)", t)
    img = re.search(r'property="og:image" content="([^"]+)"', h)
    i = t.find("Omschrijving kavel")
    omschr = t[i:i + 500] if i >= 0 else t[t.find("Basisgegevens"):][:500]
    jaar = int(jr.group(1) or jr.group(2)) if jr else None
    r = maak("boatauction", bid, u, titel, omschr, None, "EUR", jaar if jaar and jaar >= 1950 else None,
             (int(ln.group(1) or ln.group(2)) / 100) if ln else None, pl.group(2) if pl else "NL", pl.group(1) if pl else "",
             img.group(1) if img else "")
    r["veiling"] = {"platform": "boatauction", "gesloten": gesloten, "einde": einde, "huidig_bod": bod, "bieden_aantal": aantal}
    if bod:
        r["biedingen"] = [{"d": nu_iso(), "bedrag": round(bod), "naam": "", "aantal": aantal}]
    return r


def ba_ververs(r):
    h = haal(r["url"], tries=2)
    if not h:
        return False
    bod, aantal, einde, gesloten, _ = ba_parse(h)
    zet_veiling(r, einde, bod, aantal, gesloten)
    return True


# ---------------------------------------------------------------- Troostwijk / Vavato / BVA (GraphQL + categoriepagina's)
def gql(q, v=None):
    t = haal(GQL, data=json.dumps({"query": q, "variables": v or {}}).encode(), headers={"content-type": "application/json"}, tries=2)
    try:
        return json.loads(t)
    except Exception:
        return {}


TW_DOMEINEN = [("troostwijkauctions.com", "TWK"), ("vavato.com", "VAVATO"), ("bva-auctions.com", "BVA")]
TW_CATS = ["f23077a9-2f49-4129-891f-a9948ad47f0e", "4ab7e7d7-5d11-4c61-a49e-b1c4dc766a7f"]


def veilingen_tw():
    uit, gezien = [], set()
    for dom, plat in TW_DOMEINEN:
        for cat, lvl in (("f23077a9-2f49-4129-891f-a9948ad47f0e", "boats-yachts/sailing-boats"), ("4ab7e7d7-5d11-4c61-a49e-b1c4dc766a7f", "boats-yachts")):
            for pag in range(1, 4):
                h = haal(f"https://www.{dom}/nl/c/{lvl}/{cat}?page={pag}", tries=2)
                m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', h or "", re.S)
                if not m:
                    break
                try:
                    pp = json.loads(m.group(1))["props"]["pageProps"]
                    res = (pp.get("lotsData") or {}).get("results") or []
                except Exception:
                    break
                for l in res:
                    if l["displayId"] in gezien or not re.search(r"westerly|" + "|".join(p for _, p, _ in MODELLEN[:12]), (l.get("title") or "") + " " + (l.get("description") or ""), re.I):
                        continue
                    if "westerly" not in ((l.get("title") or "") + " " + (l.get("description") or "")).lower():
                        continue
                    gezien.add(l["displayId"])
                    uit.append(tw_record(l, dom, plat))
                if len(res) < 48:
                    break
            time.sleep(0.5)
    return uit


def tw_record(l, dom, plat):
    loc = l.get("location") or {}
    cur = (l.get("currentBidAmount") or {})
    r = maak("troostwijk", l["displayId"], f"https://www.{dom}/nl/l/{l.get('urlSlug')}", l.get("title") or "", l.get("description") or "",
             None, cur.get("currency", "EUR"), None, None, (loc.get("countryCode") or "").upper(), loc.get("city", ""),
             (l.get("image") or {}).get("url", ""))
    r["veiling"] = {"platform": l.get("platform") or plat, "domein": dom, "gesloten": l.get("biddingStatus") == "BIDDING_CLOSED",
                    "einde": datetime.datetime.fromtimestamp(l["endDate"], datetime.timezone.utc).isoformat(timespec="seconds") if l.get("endDate") else None,
                    "huidig_bod": (cur.get("cents") or 0) / 100 if cur.get("cents") else None, "bieden_aantal": l.get("bidsCount")}
    if cur.get("cents"):
        r["biedingen"] = [{"d": nu_iso(), "bedrag": round(cur["cents"] / 100), "naam": "", "aantal": l.get("bidsCount")}]
    return r


def tw_ververs(r):
    """Actuele stand van een Troostwijk-lot."""
    v = r["veiling"]
    q = '''query($d:String!,$p:Platform!){lotDetails(displayId:$d,locale:"nl",platform:$p){lot{biddingStatus bidsCount endDate currentBidAmount{cents currency}}}}'''
    res = gql(q, {"d": r["id"].split("-", 1)[1], "p": v["platform"]})
    lot = ((res.get("data") or {}).get("lotDetails") or {}).get("lot")
    if not lot:
        return False
    nieuw_einde = datetime.datetime.fromtimestamp(lot["endDate"], datetime.timezone.utc).isoformat(timespec="seconds") if lot.get("endDate") else v.get("einde")
    zet_veiling(r, nieuw_einde, (lot.get("currentBidAmount") or {}).get("cents", 0) / 100 or None, lot.get("bidsCount"),
                lot.get("biddingStatus") == "BIDDING_CLOSED")
    return True


def zet_veiling(r, einde, bod, aantal, gesloten):
    """Werkt veilingstand bij; registreert verlenging van de eindtijd (soft close) en nieuwe biedingen."""
    v = r["veiling"]
    nu = nu_iso()
    if einde and v.get("einde") and einde != v["einde"]:
        v.setdefault("verlengingen", []).append({"d": nu, "van": v["einde"], "naar": einde})
    if einde:
        v["einde"] = einde
    if bod and (bod != v.get("huidig_bod") or (aantal or 0) != (v.get("bieden_aantal") or 0)):
        if not r["biedingen"] or r["biedingen"][-1]["bedrag"] != bod:
            r["biedingen"].append({"d": nu, "bedrag": round(bod), "naam": "", "aantal": aantal})
    v["huidig_bod"], v["bieden_aantal"], v["gesloten"], v["laatste_check"] = bod or v.get("huidig_bod"), aantal, gesloten, nu


# ---------------------------------------------------------------- samenvoegen en bewaren
def eur(r, prijs):
    if prijs is None:
        return None
    return round(prijs * (CFG["gbp_eur"] if r.get("valuta") == "GBP" else 1))


def laad():
    try:
        return {a["id"]: a for a in json.load(open(DATA / "boten.json"))["boten"]}
    except Exception:
        return {}


def probe(r):
    try:
        with urllib.request.urlopen(urllib.request.Request(r["url"], headers=UA), timeout=25) as x:
            body = x.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return "weg" if e.code in (404, 410) else "?"
    except Exception:
        return "?"
    ext = r["id"].split("-", 1)[1]
    return "online" if ext in body else "weg"


def werk_bij(oud, nieuw, bronnen_ok, nu):
    """Voegt nieuwe scrape samen met historie. nieuw: lijst records; bronnen_ok: set bronnen die geslaagd zijn."""
    uit = {}
    for r in nieuw:
        o = oud.get(r["id"])
        prijs_eur = eur(r, r["prijs"])
        r["prijs_eur"] = prijs_eur
        if o:
            r["eerst_gezien"] = o["eerst_gezien"]
            r["gebeurtenissen"] = list(o.get("gebeurtenissen", []))
            r["prijshistorie"] = list(o.get("prijshistorie", []))
            r["biedingen"] = r["biedingen"] if r["biedingen"] else []
            voeg_biedingen_toe(r, o.get("biedingen", []))
            if o.get("veiling") and r.get("veiling"):
                r["veiling"]["verlengingen"] = o["veiling"].get("verlengingen", [])
                if o["veiling"].get("einde") and r["veiling"].get("einde") and o["veiling"]["einde"] != r["veiling"]["einde"]:
                    r["veiling"]["verlengingen"].append({"d": nu, "van": o["veiling"]["einde"], "naar": r["veiling"]["einde"]})
            elif o.get("veiling"):
                r["veiling"] = o["veiling"]
            for k in ("kwaliteit", "notitie", "historisch"):
                if k in o:
                    r[k] = o[k]
            if not o.get("online", True):
                r["gebeurtenissen"].append({"d": nu, "t": "weer online"})
        else:
            r["eerst_gezien"] = nu
            r["historisch"] = bool(r.get("verkocht_bron") or (r.get("veiling") or {}).get("gesloten"))   # bij eerste controle al afgelopen: datums onbekend
            r["gebeurtenissen"] = [{"d": nu, "t": "verkocht (bij eerste controle al verkocht)" if r.get("verkocht_bron") else "online"}]
            r["prijshistorie"] = []
        r.setdefault("kwaliteit", None)
        r.setdefault("notitie", "")
        ph = r["prijshistorie"]
        if prijs_eur is not None and (not ph or ph[-1]["p"] != prijs_eur):
            ph.append({"d": nu, "p": prijs_eur, "valuta": r["valuta"], "orig": r["prijs"]})
        r["online"], r["gemist"], r["laatst_gezien"], r["offline_sinds"] = True, 0, nu, None
        if r.get("verkocht_bron"):
            r["status"] = "verkocht"
            if not any(e["t"].startswith("verkocht") for e in r["gebeurtenissen"]):
                r["gebeurtenissen"].append({"d": nu, "t": "verkocht"})
                r["offline_sinds"] = nu
            r["online"] = False
            r["offline_sinds"] = r["offline_sinds"] or nu
        elif r.get("veiling"):
            v = r["veiling"]
            if v.get("gesloten"):
                r["status"], r["online"] = "veiling gesloten", False
                r["offline_sinds"] = r["offline_sinds"] or v.get("einde") or nu
                v["definitief"] = True
                if not any(e["t"] == "veiling gesloten" for e in r["gebeurtenissen"]):
                    r["gebeurtenissen"].append({"d": r["offline_sinds"], "t": "veiling gesloten", "eindbod": v.get("huidig_bod")})
            else:
                r["status"] = "veiling actief"
        else:
            r["status"] = "te koop"
        uit[r["id"]] = r
    for oid, o in oud.items():
        if oid in uit:
            continue
        o = dict(o)
        if (o.get("veiling") or {}).get("definitief"):
            uit[oid] = o
            continue
        if o.get("online", True) and o["bron"] in bronnen_ok:
            o["gemist"] = o.get("gemist", 0) + 1
            if o["gemist"] >= 2:
                st = probe(o)
                if st == "weg":
                    o["online"], o["offline_sinds"] = False, nu
                    o["status"] = "veiling gesloten" if o.get("veiling") else ("verkocht" if o.get("verkocht_bron") else "offline (verkocht of ingetrokken)")
                    o["gebeurtenissen"] = o["gebeurtenissen"] + [{"d": nu, "t": "offline"}]
                elif st == "online":
                    o["gemist"] = 0
        uit[oid] = o
    return uit


def groepeer(boten):
    """Dezelfde boot op meerdere sites: zelfde model + bouwjaar + (prijs binnen 5% of dezelfde plaats). Markeert 'zelfde_als'."""
    lijst = sorted(boten.values(), key=lambda b: b["eerst_gezien"])
    for b in lijst:
        b.pop("zelfde_als", None)
    for i, b in enumerate(lijst):
        if b.get("zelfde_als") or not b.get("bouwjaar"):
            continue
        for c in lijst[i + 1:]:
            if c["bron"] == b["bron"] or c.get("zelfde_als") or c.get("bouwjaar") != b["bouwjaar"] or c["type"] != b["type"] or c["type"].endswith("(overig)"):
                continue
            pb, pc = b.get("prijs_eur"), c.get("prijs_eur")
            if (pb and pc and abs(pb - pc) / max(pb, pc) <= 0.05) or (b.get("plaats") and b["plaats"] == c.get("plaats")):
                c["zelfde_als"] = b["id"]


def schrijf(boten, nu, bronstatus):
    DATA.mkdir(parents=True, exist_ok=True)
    groepeer(boten)
    lijst = sorted(boten.values(), key=lambda b: (b.get("type", ""), b.get("prijs_eur") or 0))
    out = {"bijgewerkt": nu, "bronnen": bronstatus, "boten": lijst}
    (DATA / "boten.json").write_text(json.dumps(out, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    with open(DATA / "boten.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id", "website", "url", "titel", "type", "lengte_voet", "bouwjaar", "land", "plaats", "status", "eerst_gezien", "offline_sinds",
                    "huidige_prijs", "valuta", "aantal_prijzen", "aantal_biedingen", "hoogste_bod", "kwaliteit"])
        for b in lijst:
            w.writerow([b["id"], b["bron"], b["url"], b["titel"], b["type"], b.get("lengte_ft"), b.get("bouwjaar"), b.get("land"), b.get("plaats"),
                        b.get("status"), b["eerst_gezien"], b.get("offline_sinds") or "", b.get("prijs") or "", b.get("valuta"),
                        len(b["prijshistorie"]), len(b["biedingen"]), max([x["bedrag"] for x in b["biedingen"]] or [""]), b.get("kwaliteit") or ""])
    with open(DATA / "prijzen.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["boot_id", "website", "type", "lengte_voet", "datum_ingegaan", "prijs_eur", "oorspronkelijke_valuta", "oorspronkelijke_prijs"])
        for b in lijst:
            for p in b["prijshistorie"]:
                w.writerow([b["id"], b["bron"], b["type"], b.get("lengte_ft"), p["d"], p["p"], p.get("valuta"), p.get("orig")])
    with open(DATA / "biedingen.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["boot_id", "website", "type", "tijdstip_bod", "bedrag_eur", "bieder"])
        for b in lijst:
            for x in b["biedingen"]:
                w.writerow([b["id"], b["bron"], b["type"], x["d"], x["bedrag"], x.get("naam", "")])


def main():
    oud = laad()
    OUD.update(oud)
    nu = nu_iso()
    bronnen = [("marktplaats", marktplaats), ("botenjachten", botenjachten), ("devalk", devalk), ("doeve", doeve),
               ("boatauction", boatauction), ("troostwijk", veilingen_tw)]
    nieuw, ok, status = [], set(), {}
    for naam, fn in bronnen:
        try:
            res = fn()
            nieuw += res
            status[naam] = len(res)
            if res or naam in ("troostwijk", "boatauction", "doeve"):   # geen resultaat is voor deze bronnen normaal
                ok.add(naam)
        except Exception as e:
            print("FOUT bron", naam, e, file=sys.stderr)
            status[naam] = -1
    # details: biedingen van Marktplaats, actuele stand van veilingen
    for r in nieuw:
        if r["bron"] == "marktplaats":
            o = oud.get(r["id"]) or {}
            if r.get("prijstype") in ("min_bid", "fast_bid") or o.get("biedingen_actief") or not o:
                mp_detail(r)
        elif r["bron"] == "troostwijk":
            tw_ververs(r)
        elif r["bron"] == "boatauction":
            ba_ververs(r)
    boten = werk_bij(oud, nieuw, ok, nu)
    schrijf(boten, nu, status)
    actief = sum(b.get("online", True) for b in boten.values())
    print(f"{actief} online, {len(boten) - actief} offline/verkocht, bronnen: {status}")


if __name__ == "__main__":
    main()
