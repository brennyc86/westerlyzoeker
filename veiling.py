#!/usr/bin/env python3
"""Snelle controle van veilingen vlak voor het einde. Veilingen verlengen hun eindtijd bij een laat bod (soft close),
dus zolang een veiling binnen ~30 minuten eindigt (of net is geëindigd) vragen we elke 45 seconden de stand op.
Draait ≤ 14 minuten per aanroep; de workflow start dit elke 15 minuten."""
import datetime, sys, time
import westerly as w

LOOKAHEAD_MIN = 35       # vanaf zoveel minuten voor het einde intensief volgen
NAGLOEI_MIN = 12         # zoveel minuten na het (laatste) eindtijdstip nog blijven volgen i.v.m. verlenging
MAX_RUN_S = 13 * 60
PAUZE_S = 45


def parse(t):
    return datetime.datetime.fromisoformat(t.replace("Z", "+00:00"))


def relevant(boten, nu):
    uit = []
    for b in boten.values():
        v = b.get("veiling")
        if not v or not v.get("einde") or not b.get("online", True) and v.get("definitief"):
            continue
        einde = parse(v["einde"])
        if v.get("definitief"):
            continue
        if einde - datetime.timedelta(minutes=LOOKAHEAD_MIN) <= nu <= einde + datetime.timedelta(minutes=NAGLOEI_MIN):
            uit.append(b)
    return uit


def ververs(b):
    if b["bron"] == "troostwijk":
        return w.tw_ververs(b)
    if b["bron"] == "boatauction":
        return w.ba_ververs(b)
    return False


def sluit_af(boten, nu):
    """Veilingen waarvan het einde meer dan NAGLOEI_MIN geleden is en die gesloten zijn, definitief maken."""
    for b in boten.values():
        v = b.get("veiling")
        if v and v.get("einde") and not v.get("definitief") and nu > parse(v["einde"]) + datetime.timedelta(minutes=NAGLOEI_MIN):
            if v.get("gesloten") or nu > parse(v["einde"]) + datetime.timedelta(hours=2):
                v["definitief"] = True
                b["status"] = "veiling gesloten"
                b["online"], b["offline_sinds"] = False, v["einde"]
                if not any(e["t"] == "veiling gesloten" for e in b["gebeurtenissen"]):
                    b["gebeurtenissen"].append({"d": v["einde"], "t": "veiling gesloten", "eindbod": v.get("huidig_bod")})


def main():
    oud = w.laad()
    nu = datetime.datetime.now(datetime.timezone.utc)
    if not relevant(oud, nu):
        print("geen veilingen in de eindfase")
        return 0
    start = time.time()
    rondes = 0
    while time.time() - start < MAX_RUN_S:
        nu = datetime.datetime.now(datetime.timezone.utc)
        lijst = relevant(oud, nu)
        if not lijst:
            break
        for b in lijst:
            ververs(b)
        rondes += 1
        time.sleep(PAUZE_S)
    nu = datetime.datetime.now(datetime.timezone.utc)
    sluit_af(oud, nu)
    stamp = w.nu_iso()
    try:
        import json
        bronstatus = json.load(open(w.DATA / "boten.json")).get("bronnen", {})
    except Exception:
        bronstatus = {}
    w.schrijf(oud, stamp, bronstatus)
    print(f"{rondes} controle-rondes")
    return rondes


if __name__ == "__main__":
    main()
