"""Descarga de OpenStreetMap (Overpass, ODbL) los hospitales y clínicas de Chile.

Salida: cache/osm_cl_<fecha>.json con elementos normalizados. Idempotente por día.
"""
import datetime
import json
import os
import time
import urllib.parse
import urllib.request

AQUI = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(AQUI, "cache")
RESPALDO = os.environ.get("OSM_RESPALDO")  # última descarga buena; vacío en el PC
SERVIDORES = [  # servidores Overpass públicos y gratuitos
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass-api.de/api/interpreter",
]
CONSULTA = """
[out:json][timeout:300];
area["ISO3166-1"="CL"][admin_level=2]->.cl;
(
  nwr["amenity"~"^(hospital|clinic)$"](area.cl);
  nwr["healthcare"~"^(hospital|clinic|centre)$"](area.cl);
  nwr["emergency"="yes"]["healthcare"](area.cl);
);
out center tags;
"""


def descargar():
    hoy = datetime.date.today().isoformat()
    ruta = os.path.join(CACHE, "osm_cl_" + hoy + ".json")
    if os.path.exists(ruta):
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    datos = urllib.parse.urlencode({"data": CONSULTA}).encode()
    elementos = None
    for vuelta in range(3):  # los servidores públicos se saturan seguido: 3 vueltas con pausa
        if vuelta:
            print("[OSM] Ningún servidor respondió; espero 2 minutos y reintento.")
            time.sleep(120)
        for servidor in SERVIDORES:
            req = urllib.request.Request(servidor, data=datos, headers={"User-Agent": "UrgenciaCerca/0.1 (pipeline de datos)"})
            try:
                with urllib.request.urlopen(req, timeout=400) as r:
                    elementos = json.load(r)["elements"]
                break
            except Exception as e:  # servidor público saturado: se prueba el siguiente
                print("[OSM] {} no respondió ({}); pruebo otro servidor.".format(servidor, e))
        if elementos is not None:
            break
    if elementos is None:
        # Última copia buena (en GitHub Actions, datos/osm_cl.json): así OSM caído no frena los datos del MINSAL.
        if RESPALDO and os.path.exists(RESPALDO):
            print("[OSM] Overpass no respondió; uso la última copia buena: " + RESPALDO)
            with open(RESPALDO, encoding="utf-8") as f:
                return json.load(f)
        raise SystemExit("[OSM] Ningún servidor Overpass respondió; reintentar más tarde.")
    centros = []
    for e in elementos:
        t = e.get("tags", {})
        lat = e.get("lat", e.get("center", {}).get("lat"))
        lon = e.get("lon", e.get("center", {}).get("lon"))
        nombre = (t.get("name") or "").strip()
        if lat is None or lon is None or not nombre:
            continue
        tipo = t.get("amenity") or t.get("healthcare") or ""
        centros.append({
            "osm": e["type"][0] + str(e["id"]),
            "n": nombre,
            "t": tipo,
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "emergencia": t.get("emergency") == "yes",
            "horario": t.get("opening_hours") or "",
            "tel": t.get("phone") or t.get("contact:phone") or "",
            "dir": " ".join(x for x in (t.get("addr:street"), t.get("addr:housenumber")) if x),
            "com": t.get("addr:city") or "",
        })
    os.makedirs(CACHE, exist_ok=True)
    for destino in (ruta, RESPALDO):
        if destino:
            with open(destino, "w", encoding="utf-8") as f:
                json.dump(centros, f, ensure_ascii=False)
    print("[OSM] Chile: {} centros con nombre y coordenadas.".format(len(centros)))
    return centros


if __name__ == "__main__":
    descargar()
