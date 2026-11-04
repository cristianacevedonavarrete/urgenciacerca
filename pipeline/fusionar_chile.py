"""Paquete oficial de Chile: MINSAL (CC0) + OpenStreetMap (ODbL).

Regla: un centro OSM a <=150 m de uno MINSAL (o a <=400 m con nombre parecido) es el mismo.
MINSAL manda; OSM solo aporta horario y teléfono que falten. Los centros OSM sin pareja se agregan.
Este es el punto de entrada del pipeline: escribe app/assets/datos/cl.json y cl.meta.json.
"""
import json
import math
import os
import unicodedata

import minsal_chile
import osm_chile

SALIDA = minsal_chile.SALIDA


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
                    if (d <= 0.15 or (d <= 0.4 and parecidos(o["n"], centros[i]["n"]))) and d < dist:
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
            centros.append({
                "n": o["n"], "t": o["t"], "u": 1 if o["emergencia"] else 0,
                "lat": o["lat"], "lon": o["lon"], "tel": tel, "dir": o["dir"], "com": o["com"],
                "pub": 0, "src": "o", "h": o["horario"],
            })
            agregados += 1

    os.makedirs(SALIDA, exist_ok=True)
    with open(os.path.join(SALIDA, "cl.json"), "w", encoding="utf-8") as f:
        json.dump(centros, f, ensure_ascii=False, separators=(",", ":"))
    meta = {
        "pais": "CL",
        "fecha_datos": fecha,
        "fuente": "MINSAL, datos.gob.cl (CC0) y © colaboradores de OpenStreetMap (ODbL)",
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
