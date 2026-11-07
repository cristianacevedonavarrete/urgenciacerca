"""Freno antes de publicar: compara el paquete nuevo con el publicado.

Uso: python revisar_datos.py <meta_publicada> <meta_nueva>
Falla (y GitHub avisa por correo) si el paquete nuevo trae muchos centros menos: suele ser una descarga cortada
del MINSAL o de OpenStreetMap, y es mejor dejar los datos de la semana anterior.
"""
import json
import sys

MINIMO = 0.9  # el nuevo debe tener al menos el 90 % de lo publicado


def main(publicada, nueva):
    with open(publicada, encoding="utf-8") as f:
        antes = json.load(f)
    with open(nueva, encoding="utf-8") as f:
        ahora = json.load(f)
    if ahora.get("esquema") != antes.get("esquema"):
        # Cambió a propósito qué entra al paquete: los totales no se pueden comparar con la versión anterior.
        print("[Revisión] Esquema nuevo ({} → {}): se publica sin comparar totales.".format(antes.get("esquema"), ahora.get("esquema")))
        return
    problemas = []
    for clave in ("total", "con_urgencia", "con_telefono"):
        if ahora[clave] < antes[clave] * MINIMO:
            problemas.append("{}: {} → {}".format(clave, antes[clave], ahora[clave]))
    if ahora["emergencia"]["ambulancia"] != antes["emergencia"]["ambulancia"]:
        problemas.append("ambulancia cambió: {} → {}".format(antes["emergencia"]["ambulancia"], ahora["emergencia"]["ambulancia"]))
    if problemas:
        sys.exit("[Revisión] No se publica: " + "; ".join(problemas))
    print("[Revisión] OK: {total} centros, {con_urgencia} con urgencia, {con_telefono} con teléfono.".format(**ahora))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
