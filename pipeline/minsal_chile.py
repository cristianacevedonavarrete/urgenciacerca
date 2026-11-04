"""Descarga el catastro MINSAL (datos.gob.cl, CC0) y genera el paquete de Chile para la app.

Salida: app/assets/datos/cl.json (lista compacta) + cl.meta.json (fecha, fuente, conteos).
Idempotente: si la caché cruda de hoy existe, no vuelve a descargar.
"""
import datetime
import json
import os
import urllib.request

RECURSO = "2c44d782-3365-44e3-aefb-2c8b8363a1bc"
URL = "https://datos.gob.cl/api/3/action/datastore_search?resource_id={}&limit=1000&offset={}"
AQUI = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(AQUI, "cache")
# En GitHub Actions la salida es la carpeta `datos/` del repositorio público (variable SALIDA_DATOS).
SALIDA = os.environ.get("SALIDA_DATOS") or os.path.join(AQUI, "..", "..", "Android", "SaludCerca", "app", "assets", "datos")


def descargar():
    hoy = datetime.date.today().isoformat()
    crudo = os.path.join(CACHE, "minsal_" + hoy + ".json")
    if os.path.exists(crudo):
        with open(crudo, encoding="utf-8") as f:
            return json.load(f), hoy
    registros, offset = [], 0
    while True:
        with urllib.request.urlopen(URL.format(RECURSO, offset), timeout=60) as r:
            res = json.load(r)["result"]
        registros += res["records"]
        offset += 1000
        if offset >= res["total"]:
            break
    os.makedirs(CACHE, exist_ok=True)
    with open(crudo, "w", encoding="utf-8") as f:
        json.dump(registros, f, ensure_ascii=False)
    print("[Pipeline] MINSAL descargado: {} registros.".format(len(registros)))
    return registros, hoy


def numero(texto):
    try:
        v = float(str(texto).replace(",", "."))
    except (TypeError, ValueError):
        return None
    return v if v == v and abs(v) != float("inf") else None


def telefono(texto):
    """Primer número usable, en formato +56XXXXXXXXX; None si no hay."""
    if not texto:
        return None
    for parte in str(texto).replace("/", ";").replace(",", ";").split(";"):
        d = "".join(ch for ch in parte if ch in "0123456789")
        if d.startswith("56"):
            d = d[2:]
        # Solo 9 dígitos (formato vigente). Un número de 8 dígitos es ambiguo y en una emergencia
        # es peor llamar a un número equivocado que no ofrecer el botón.
        if len(d) == 9:
            return "+56" + d
    return None


def transformar(registros):
    centros = []
    for r in registros:
        if not str(r.get("EstadoFuncionamiento") or "").startswith("Vigente"):
            continue
        if r.get("FechaCierre"):
            continue
        lat, lon = numero(r.get("Latitud")), numero(r.get("Longitud"))
        # Chile continental e insular: descarta coordenadas vacías o fuera de rango
        if lat is None or lon is None or not (-56.5 < lat < -17.0) or not (-110.0 < lon < -66.0):
            continue
        dir_ = " ".join(x for x in (r.get("NombreVia"), r.get("Numero")) if x and x != "S/N").strip()
        centros.append({
            "n": (r.get("EstablecimientoGlosa") or "").strip(),
            "t": (r.get("TipoEstablecimientoGlosa") or "").strip(),
            "u": 1 if str(r.get("TieneServicioUrgencia") or "").upper() == "SI" else 0,
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "tel": telefono(r.get("TelefonoMovil_TelefonoFijo")),
            "dir": dir_,
            "com": (r.get("ComunaGlosa") or "").strip(),
            "pub": 1 if r.get("TipoSistemaSaludGlosa") == "Público" else 0,
        })
    return centros


def main():
    registros, fecha = descargar()
    centros = transformar(registros)
    os.makedirs(SALIDA, exist_ok=True)
    with open(os.path.join(SALIDA, "cl.json"), "w", encoding="utf-8") as f:
        json.dump(centros, f, ensure_ascii=False, separators=(",", ":"))
    meta = {
        "pais": "CL",
        "fecha_datos": fecha,
        "fuente": "MINSAL, datos.gob.cl (CC0)",
        "emergencia": {"ambulancia": "131", "bomberos": "132", "carabineros": "133"},
        "total": len(centros),
        "con_urgencia": sum(c["u"] for c in centros),
        "con_telefono": sum(1 for c in centros if c["tel"]),
    }
    with open(os.path.join(SALIDA, "cl.meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    print("[Pipeline] Paquete Chile listo: {} centros, {} con urgencia, {} con teléfono.".format(
        meta["total"], meta["con_urgencia"], meta["con_telefono"]))


if __name__ == "__main__":
    main()
