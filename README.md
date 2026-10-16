# Westerly zoeker

Volgt Westerly-zeilboten die in Nederland (en daarbuiten) te koop of op veiling staan: prijzen, prijsverloop, biedingen,
wanneer een boot online kwam en verkocht/offline ging. Dashboard: zie GitHub Pages van deze repo.

* `westerly.py` – verzamelt alle bronnen (elk uur) en schrijft `docs/data/boten.json` + CSV's
* `veiling.py` – volgt veilingen in de laatste 35 minuten elke 45 seconden (soft close: eindtijd verlengt bij laat bod)
* `docs/index.html` – dashboard, boten, veilingen, beoordelingen (1–5 sterren, export/import)
* `docs/data/` – `boten.json` (alles), `boten.csv`, `prijzen.csv`, `biedingen.csv`
