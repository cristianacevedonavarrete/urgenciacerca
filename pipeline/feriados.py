"""Festivos nacionales de Chile, año en curso y siguiente, para que la app use el horario de fin de semana.

Pedido de Cristián (2026-11-07): «El sistema debe actualizar los datos año a año».
Se cruzan dos fuentes y solo entra una fecha si ambas la confirman. Un festivo de más haría que la app
diera por abierto de día un SAPU cerrado; uno de menos solo lo da por cerrado (más prudente).
- boostr.cl: https://api.boostr.cl/holidays/<año>.json
- Nager.Date: https://date.nager.at/api/v3/PublicHolidays/<año>/CL (solo los nacionales, global=true)
Los festivos regionales (por ejemplo, Arica el 7 de junio) no se incluyen todavía.
"""
import datetime
import json
import urllib.request

AGENTE = {"User-Agent": "UrgenciaCerca-pipeline (+https://github.com/cristianacevedonavarrete/urgenciacerca)"}


def _leer(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=AGENTE), timeout=60) as r:
        return json.load(r)


def del_anio(anio):
    boostr = {f["date"] for f in _leer("https://api.boostr.cl/holidays/{}.json".format(anio))["data"]}
    nager = {f["date"] for f in _leer("https://date.nager.at/api/v3/PublicHolidays/{}/CL".format(anio)) if f.get("global")}
    solo_uno = sorted(boostr ^ nager)
    if solo_uno:
        print("[Feriados] {}: fechas que solo una fuente trae, no se usan: {}".format(anio, ", ".join(solo_uno)))
    return sorted(boostr & nager)


def lista():
    """Festivos de este año y el siguiente. Si una fuente falla, devuelve lo que se pudo (la app tiene respaldo)."""
    hoy = datetime.date.today()
    fechas = []
    for anio in (hoy.year, hoy.year + 1):
        try:
            fechas += del_anio(anio)
        except Exception as e:
            print("[Feriados] No se pudo leer {}: {}".format(anio, e))
    print("[Feriados] {} festivos nacionales confirmados por ambas fuentes.".format(len(fechas)))
    return fechas


if __name__ == "__main__":
    print(lista())
