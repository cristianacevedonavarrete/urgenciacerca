"""Hospitales y clínicas de Chile desde OpenStreetMap (ODbL), con el extracto de Geofabrik.

Antes se usaban servidores Overpass públicos. Se dejaron el 2026-11-07: private.coffee prohíbe
usarlo donde un dato incorrecto pueda tener consecuencias graves, y overpass-api.de pide que las
apps para el público usen su propia instancia. Geofabrik publica un extracto diario y gratuito.

Salida: cache/osm_cl_<fecha>.json con elementos normalizados (mismo formato que antes). Idempotente por día.
Requiere: pip install osmium shapely
"""
import datetime
import json
import os
import urllib.request

import osmium
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union
from shapely.prepared import prep

AQUI = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(AQUI, "cache")
RESPALDO = os.environ.get("OSM_RESPALDO")  # última descarga buena; vacío en el PC
EXTRACTO = "https://download.geofabrik.de/south-america/chile-latest.osm.pbf"
AGENTE = "UrgenciaCerca-pipeline/0.2 (+https://github.com/cristianacevedonavarrete/urgenciacerca)"
CHILE = 167454  # relación del límite nacional (admin_level=2) en OpenStreetMap


def es_salud(t):
    """Mismo criterio que la consulta Overpass anterior."""
    return (t.get("amenity") in ("hospital", "clinic")
            or t.get("healthcare") in ("hospital", "clinic", "centre")
            or (t.get("emergency") == "yes" and "healthcare" in t))


def bajar_extracto(hoy):
    ruta = os.path.join(CACHE, "geofabrik", "chile-" + hoy + ".osm.pbf")
    if os.path.exists(ruta):
        return ruta
    os.makedirs(os.path.dirname(ruta), exist_ok=True)
    req = urllib.request.Request(EXTRACTO, headers={"User-Agent": AGENTE})
    with urllib.request.urlopen(req, timeout=900) as r, open(ruta + ".parcial", "wb") as f:
        while True:
            trozo = r.read(1 << 20)
            if not trozo:
                break
            f.write(trozo)
    os.replace(ruta + ".parcial", ruta)
    print("[OSM] Extracto de Geofabrik descargado: {:.0f} MB.".format(os.path.getsize(ruta) / 1e6))
    return ruta


def anillo(r):
    return [(n.lon, n.lat) for n in r]


def leer(pbf):
    """Devuelve (elementos de salud, polígono de Chile o None)."""
    candidatos, chile = [], []
    fp = (osmium.FileProcessor(pbf)
          .with_locations()
          .with_areas(osmium.filter.IdFilter([CHILE]))
          .with_filter(osmium.filter.KeyFilter("amenity", "healthcare", "emergency", "boundary")))
    for o in fp:
        if o.is_area():
            if o.orig_id() == CHILE and o.from_way() is False:
                for ext in o.outer_rings():
                    chile.append(Polygon(anillo(ext), [anillo(i) for i in o.inner_rings(ext)]))
            continue
        t = dict(o.tags)
        if not es_salud(t):
            continue
        if o.is_node():
            lat, lon, tipo = o.location.lat, o.location.lon, "node"
        elif o.is_way():
            pts = [(n.lat, n.lon) for n in o.nodes if n.location.valid()]
            if not pts:
                continue
            lat = (min(p[0] for p in pts) + max(p[0] for p in pts)) / 2  # centro del recuadro, como Overpass
            lon = (min(p[1] for p in pts) + max(p[1] for p in pts)) / 2
            tipo = "way"
        else:
            continue  # las relaciones se resuelven con sus áreas, abajo
        candidatos.append((tipo, o.id, t, lat, lon))
    return candidatos, chile


def areas_de_relaciones(pbf):
    """Relaciones de salud (multipolígonos): centro del recuadro de sus anillos externos."""
    salida = []
    fp = (osmium.FileProcessor(pbf)
          .with_areas(osmium.filter.KeyFilter("amenity", "healthcare", "emergency"))
          .with_filter(osmium.filter.EntityFilter(osmium.osm.AREA)))
    for a in fp:
        if a.from_way():
            continue
        t = dict(a.tags)
        if not es_salud(t):
            continue
        pts = [(n.lat, n.lon) for ext in a.outer_rings() for n in ext]
        if pts:
            salida.append(("relation", a.orig_id(), t,
                           (min(p[0] for p in pts) + max(p[0] for p in pts)) / 2,
                           (min(p[1] for p in pts) + max(p[1] for p in pts)) / 2))
    return salida


def descargar():
    hoy = datetime.date.today().isoformat()
    ruta = os.path.join(CACHE, "osm_cl_" + hoy + ".json")
    if os.path.exists(ruta):
        with open(ruta, encoding="utf-8") as f:
            return json.load(f)
    try:
        pbf = bajar_extracto(hoy)
        candidatos, chile = leer(pbf)
        candidatos += areas_de_relaciones(pbf)
    except Exception as e:
        # Última copia buena (en GitHub Actions, datos/osm_cl.json): así OSM caído no frena los datos del MINSAL.
        if RESPALDO and os.path.exists(RESPALDO):
            print("[OSM] Geofabrik falló ({}); uso la última copia buena: {}".format(e, RESPALDO))
            with open(RESPALDO, encoding="utf-8") as f:
                return json.load(f)
        raise SystemExit("[OSM] No se pudo leer el extracto de Geofabrik: {}".format(e))
    if not chile:
        raise SystemExit("[OSM] No se pudo armar el límite de Chile; no se publica nada.")
    dentro = prep(unary_union(chile))
    centros, fuera = [], 0
    for tipo, ident, t, lat, lon in candidatos:
        nombre = (t.get("name") or "").strip()
        if not nombre:
            continue
        if not dentro.contains(Point(lon, lat)):
            fuera += 1  # el extracto trae un margen de los países vecinos
            continue
        centros.append({
            "osm": tipo[0] + str(ident),
            "n": nombre,
            "t": t.get("amenity") or t.get("healthcare") or "",
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "emergencia": t.get("emergency") == "yes",
            "horario": t.get("opening_hours") or "",
            "tel": t.get("phone") or t.get("contact:phone") or "",
            "dir": " ".join(x for x in (t.get("addr:street"), t.get("addr:housenumber")) if x),
            "com": t.get("addr:city") or "",
        })
    centros.sort(key=lambda c: c["osm"])
    os.makedirs(CACHE, exist_ok=True)
    for destino in (ruta, RESPALDO):
        if destino:
            with open(destino, "w", encoding="utf-8") as f:
                json.dump(centros, f, ensure_ascii=False)
    print("[OSM] Chile: {} centros con nombre y coordenadas ({} fuera del límite descartados).".format(len(centros), fuera))
    return centros


if __name__ == "__main__":
    descargar()
