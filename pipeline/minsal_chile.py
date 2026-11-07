"""Descarga el catastro MINSAL (datos.gob.cl, CC0) y genera el paquete de Chile para la app.

Salida: app/assets/datos/cl.json (lista compacta) + cl.meta.json (fecha, fuente, conteos).
Idempotente: si la caché cruda de hoy existe, no vuelve a descargar.
"""
import datetime
import json
import os
import re
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
        # Solo 9 dígitos que empiecen en 2-9 (formato vigente). Un número de 8 dígitos o con 0 inicial
        # es ambiguo, y en una emergencia es peor llamar a un número equivocado que no ofrecer el botón.
        if len(d) == 9 and d.startswith("800"):
            return d  # 800 gratuito: se marca sin +56, porque con prefijo internacional puede no conectar
        if len(d) == 9 and d[0] in "23456789":
            return "+56" + d
    return None


SIGLAS = {"SAPU", "SAR", "SUR", "CESFAM", "CECOSF", "COSAM", "ACHS", "IST", "UEH", "CRS", "CDT", "CRT", "PSR",
          "SAMU", "CGR", "CGU", "UC", "CAE", "II", "III", "IV", "VI", "VII", "VIII", "IX", "XI", "XII", "XIV", "XV", "XVI"}


def limpiar_nombre(nombre):
    """Quita espacios duros y dobles, y pasa a formato título los nombres escritos todo en mayúsculas."""
    s = " ".join((nombre or "").replace("\xa0", " ").split())
    if sum(ch.isalpha() for ch in s) > 3 and s == s.upper():
        s = " ".join(w if w.strip("().,-") in SIGLAS else w.capitalize() for w in s.split())
    return s


# Lugares que no atienden al público o no sirven a quien busca atención: no entran al paquete.
TIPOS_FUERA = {
    "Laboratorio Clínico", "Vacunatorio", "Sala  Externa de Toma de Muestras (SETM)", "Unidad de Procedimientos Móvil",
    "Atención Remota", "Centro de Regulación Médica de las Urgencias (SAMU)", "Centro de Diálisis",
    "Centro Corporación para la Nutrición Infantil (CONIN)", "Centro de Rehabilitación", "Hospital de Día",
    "Centro de Salud Comunitario para Personas con Demencia", "Clínica Dental",
}
NOMBRES_FUERA = re.compile(
    r"servicio m[eé]dico legal|\bSML\b|penitenciari|gendarmer|\bC\.?D\.?P\b|\bC\.?C\.?P\b|\bPRAIS\b|salud funcionari|"
    r"direcci[oó]n del servicio|actividades gestionadas|vacunatorio|sala de procedimientos|toma de muestras|"
    r"colegio|escuela|liceo|veterinari", re.IGNORECASE)

# Tipo de urgencia del MINSAL → código corto que usa la app para decidir el horario que muestra.
TIPO_URGENCIA = {
    "Urgencia Hospitalaria (UEH)": "UEH",
    "Urgencia Ambulatoria (SAPU)": "SAPU",
    "Urgencia Ambulatoria (SAR)": "SAR",
    "Urgencia Ambulatoria (SUR)": "SUR",
    "Urgencia ambulatoria privada": "PRIV",
}
# Sin urgencia general: dental, centro regulador del SAMU, oncología, institutos de especialidad.
URGENCIA_FUERA = {"SAPU Dental", "Otro", "Hospitalaria Especializada"}
CLASE_SAPU = {"Corto": "C", "Largo": "L", "Avanzado": "A", "Verano": "V", "Pendiente": "P"}
PEDIATRICO = re.compile(r"niños|niño\b|pedi[aá]tric|infantil|exequiel gonz[aá]lez", re.IGNORECASE)
NO_PEDIATRICO = re.compile(r"conin|mater|renal|materno", re.IGNORECASE)


# Urgencias vigentes que el MINSAL publica sin coordenadas (revisado el 2026-11-07). Solo se usan si siguen sin ellas.
# Se ubicaron con OpenStreetMap (Nominatim) a partir de la dirección del MINSAL:
COORDENADAS_FALTANTES = {
    "202373": (-33.019003, -71.522008),  # SAR Miraflores, Av. Padre Hurtado 2125, Viña del Mar: punto exacto en OSM
    "200765": (-34.997959, -71.387459),  # SUR Sagrada Familia: funciona en el CESFAM Sagrada Familia (punto en OSM)
    "202386": (-35.601105, -71.734146),  # SAPU San Javier, Chorrillos 1921: CESFAM San Javier, en la misma avenida (aprox.)
    "202400": (-28.572312, -70.752660),  # SAR Altiplano Norte, Lourdes 1345, Vallenar: calle Lourdes en Altiplano Norte (aprox.)
}


def transformar(registros):
    centros = []
    for r in registros:
        if not str(r.get("EstadoFuncionamiento") or "").startswith("Vigente"):
            continue
        if r.get("FechaCierre"):
            continue
        tipo = (r.get("TipoEstablecimientoGlosa") or "").strip()
        nombre = limpiar_nombre(r.get("EstablecimientoGlosa"))
        if tipo in TIPOS_FUERA or NOMBRES_FUERA.search(nombre):
            continue
        lat, lon = numero(r.get("Latitud")), numero(r.get("Longitud"))
        if (lat is None or lon is None) and str(r.get("EstablecimientoCodigo")) in COORDENADAS_FALTANTES:
            lat, lon = COORDENADAS_FALTANTES[str(r.get("EstablecimientoCodigo"))]
        # Chile continental e insular: descarta coordenadas vacías o fuera de rango
        if lat is None or lon is None or not (-56.5 < lat < -17.0) or not (-110.0 < lon < -66.0):
            if str(r.get("TieneServicioUrgencia") or "").upper() == "SI":
                print("[Pipeline] AVISO: urgencia sin coordenadas, no entra: {} ({}, código {}). "
                      "Agregarla a COORDENADAS_FALTANTES.".format(nombre, r.get("ComunaGlosa"), r.get("EstablecimientoCodigo")))
            continue
        dir_ = " ".join(x for x in (r.get("NombreVia"), r.get("Numero")) if x and x != "S/N").strip()
        tu = r.get("TipoUrgencia") or ""
        urgencia = str(r.get("TieneServicioUrgencia") or "").upper() == "SI" and tu not in URGENCIA_FUERA
        if "IST" in nombre and "Procedimientos" in nombre:
            urgencia = False
        c = {
            "n": nombre,
            "t": tipo,
            "u": 1 if urgencia else 0,
            "lat": round(lat, 6),
            "lon": round(lon, 6),
            "tel": telefono(r.get("TelefonoMovil_TelefonoFijo")),
            "dir": " ".join(dir_.split()),
            "com": (r.get("ComunaGlosa") or "").strip(),
            "pub": 1 if r.get("TipoSistemaSaludGlosa") == "Público" else 0,
        }
        if urgencia:
            c["tu"] = TIPO_URGENCIA.get(tu, "UEH" if "Hospital" in tipo else "")
            if c["tu"] == "SAPU":
                c["cs"] = CLASE_SAPU.get(r.get("ClasificacionTipoSapu") or "", "")
        if PEDIATRICO.search(nombre) and not NO_PEDIATRICO.search(nombre):
            c["ped"] = 1
        centros.append(c)
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
