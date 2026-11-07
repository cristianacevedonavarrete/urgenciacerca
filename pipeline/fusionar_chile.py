"""Paquete de Chile: MINSAL (CC0) + OpenStreetMap (ODbL).

Regla: un centro OSM a <=150 m de uno MINSAL (o a <=1 km con nombre parecido) es el mismo.
MINSAL manda; OSM solo aporta horario y teléfono que falten. Los centros OSM sin pareja se agregan, siempre sin urgencia.
Este es el punto de entrada del pipeline: escribe app/assets/datos/cl.json y cl.meta.json.
"""
import json
import math
import os
import unicodedata

import minsal_chile
import osm_chile

SALIDA = minsal_chile.SALIDA
# Coordenadas del MINSAL en otra región (auditoría del 2026-11-07): fuera hasta que el MINSAL las corrija.
MAL_UBICADOS = {"Clinica Red Medical", "Clínica Red Medical"}


def km(a, b):
    r = 6371.0
    p1, p2 = math.radians(a["lat"]), math.radians(b["lat"])
    dp, dl = p2 - p1, math.radians(b["lon"] - a["lon"])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def palabras(nombre):
    s = unicodedata.normalize("NFKD", nombre.lower())
    s = "".join(ch for ch in s if ch.isascii() and (ch.isalnum() or ch == " "))
    vacias = {"de", "del", "la", "el", "los", "las", "y", "centro", "salud", "hospital", "clinica", "cesfam", "dr", "doctor"}
    return {w for w in s.split() if len(w) > 2 and w not in vacias}


def parecidos(a, b):
    pa, pb = palabras(a), palabras(b)
    return bool(pa and pb) and len(pa & pb) / min(len(pa), len(pb)) >= 0.5


def celda(lat, lon):
    return (int(lat * 100), int(lon * 100))  # ~1 km


def main():
    registros, fecha = minsal_chile.descargar()
    centros = minsal_chile.transformar(registros)
    for c in centros:
        c["src"] = "m"
        c["h"] = ""
    rejilla = {}
    for i, c in enumerate(centros):
        rejilla.setdefault(celda(c["lat"], c["lon"]), []).append(i)

    osm = osm_chile.descargar()
    unidos = agregados = 0
    for o in osm:
        ci, cj = celda(o["lat"], o["lon"])
        mejor, dist = None, 9.9
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                for i in rejilla.get((ci + di, cj + dj), []):
                    d = km(o, centros[i])
                    if (d <= 0.15 or (d <= 1.0 and parecidos(o["n"], centros[i]["n"]))) and d < dist:
                        mejor, dist = i, d
        tel = minsal_chile.telefono(o["tel"])
        if mejor is not None:
            c = centros[mejor]
            if not c["h"] and o["horario"]:
                c["h"] = o["horario"]
            if not c["tel"] and tel:
                c["tel"] = tel
            unidos += 1
        else:
            nombre = minsal_chile.limpiar_nombre(o["n"])
            if minsal_chile.NOMBRES_FUERA.search(nombre) or len(palabras(nombre)) == 0:
                continue  # colegios, veterinarias o nombres sin contenido («SAPU»)
            # La urgencia la decide solo el MINSAL: emergency=yes de OSM suele estar mal puesta.
            nuevo = {
                "n": nombre, "t": o["t"], "u": 0,
                "lat": o["lat"], "lon": o["lon"], "tel": tel, "dir": " ".join(o["dir"].split()),
                "com": "", "pub": 0, "src": "o", "h": o["horario"],
            }
            if minsal_chile.PEDIATRICO.search(nombre) and not minsal_chile.NO_PEDIATRICO.search(nombre):
                nuevo["ped"] = 1
            centros.append(nuevo)
            agregados += 1

    # Comuna de los centros OSM: la del centro MINSAL más cercano (el texto libre de OSM no sirve para elegir comuna).
    minsal = [c for c in centros if c["src"] == "m"]
    for c in centros:
        if c["src"] == "o":
            c["com"] = min(minsal, key=lambda m: (m["lat"] - c["lat"]) ** 2 + (m["lon"] - c["lon"]) ** 2)["com"]

    # Coordenadas absurdas. Una urgencia a más de 150 km de la mediana de su comuna se deja fuera; los demás solo se
    # avisan, porque hay comunas enormes con postas legítimas muy lejos (Puerto Edén, en Natales).
    por_comuna = {}
    for c in minsal:
        por_comuna.setdefault(c["com"], []).append(c)
    medianas = {}
    for com, cs in por_comuna.items():
        lats, lons = sorted(x["lat"] for x in cs), sorted(x["lon"] for x in cs)
        medianas[com] = {"lat": lats[len(lats) // 2], "lon": lons[len(lons) // 2]}
    lejos = []
    for c in centros:
        if c["n"] in MAL_UBICADOS:
            lejos.append(c)
        elif c["com"] in medianas and km(c, medianas[c["com"]]) > 150:
            print("[Fusión] {}: {} ({}) queda a más de 150 km del centro de su comuna.".format(
                "Fuera, es urgencia" if c["u"] else "Aviso", c["n"], c["com"]))
            if c["u"]:
                lejos.append(c)
    centros = [c for c in centros if c not in lejos]

    os.makedirs(SALIDA, exist_ok=True)
    with open(os.path.join(SALIDA, "cl.json"), "w", encoding="utf-8") as f:
        json.dump(centros, f, ensure_ascii=False, separators=(",", ":"))
    meta = {
        "pais": "CL",
        "esquema": 2,  # 2 (2026-11-07): campos tu, cs y ped; solo el MINSAL decide la urgencia
        "fecha_datos": fecha,
        "fuente": "MINSAL, datos.gob.cl (CC0) y © colaboradores de OpenStreetMap (ODbL)",
        "licencia": "ODbL 1.0 (https://opendatacommons.org/licenses/odbl/1-0/); ver datos/LICENCIA.md",
        "emergencia": {"ambulancia": "131", "bomberos": "132", "carabineros": "133"},
        "total": len(centros),
        "con_urgencia": sum(c["u"] for c in centros),
        "con_telefono": sum(1 for c in centros if c["tel"]),
        "con_horario_osm": sum(1 for c in centros if c["h"]),
        "osm_unidos": unidos,
        "osm_agregados": agregados,
    }
    with open(os.path.join(SALIDA, "cl.meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    print("[Fusión] Chile: {total} centros; OSM unidos {osm_unidos}, agregados {osm_agregados}; "
          "con teléfono {con_telefono}; con horario OSM {con_horario_osm}.".format(**meta))


if __name__ == "__main__":
    main()
