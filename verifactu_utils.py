# verifactu_utils.py — Implementación manual con hashlib (sin dependencias externas)
import hashlib
import urllib.parse
from datetime import datetime


def generar_url_qr_verifactu(nif_emisor, num_serie_factura, fecha_expedicion, importe_total, produccion=True):
    """
    URL oficial del QR Verifactu según Orden HAC/1177/2024.
    
    - num_serie_factura: número y serie concatenados (ej: "F2026-0001")
    - fecha_expedicion: formato "DD-MM-AAAA"
    - importe_total: float (se formatea con 2 decimales)
    """
    if produccion:
        base = "https://www2.agenciatributaria.gob.es/wlpl/TIKE-CONT/ValidarQR"
    else:
        base = "https://prewww2.aeat.es/wlpl/TIKE-CONT/ValidarQR"

    nif_limpio = nif_emisor.strip().upper().replace(" ", "").replace("-", "")
    params = {
        "nif": nif_limpio,
        "numserie": num_serie_factura,
        "fecha": fecha_expedicion,
        "importe": f"{importe_total:.2f}",
    }
    return f"{base}?{urllib.parse.urlencode(params)}"


def generar_hash_verifactu(
    nif_emisor,
    num_serie_factura,
    fecha_expedicion,
    tipo_factura,
    cuota_total,
    importe_total,
    hash_anterior,
    fecha_hora_gen_registro,
):
    """
    Hash SHA-256 según especificación AEAT v0.1.2 (Orden HAC/1177/2024).
    
    Orden estricto de campos:
    1. IDEmisorFactura
    2. NumSerieFactura
    3. FechaExpedicionFactura (DD-MM-AAAA)
    4. TipoFactura (F1, F2, R1-R5, etc.)
    5. CuotaTotal
    6. ImporteTotal
    7. Huella (hash anterior, vacío si es primero)
    8. FechaHoraHusoGenRegistro (ISO-8601 con huso)
    
    Formato: nombreCampo1=valor1&nombreCampo2=valor2&...
    """
    # Limpiar NIF
    nif_limpio = nif_emisor.strip().upper().replace(" ", "").replace("-", "")

    # Formatear importes con 2 decimales (punto decimal)
    cuota_formateada = f"{float(cuota_total):.2f}"
    importe_formateado = f"{float(importe_total):.2f}"

    # Huella anterior vacía si es el primer registro
    huella_anterior = hash_anterior if hash_anterior else ""

    # Construir cadena pre-hash según orden oficial
    cadena_pre_hash = (
        f"IDEmisorFactura={nif_limpio}&"
        f"NumSerieFactura={num_serie_factura}&"
        f"FechaExpedicionFactura={fecha_expedicion}&"
        f"TipoFactura={tipo_factura}&"
        f"CuotaTotal={cuota_formateada}&"
        f"ImporteTotal={importe_formateado}&"
        f"Huella={huella_anterior}&"
        f"FechaHoraHusoGenRegistro={fecha_hora_gen_registro}"
    )

    # Calcular SHA-256
    hash_resultado = hashlib.sha256(cadena_pre_hash.encode('utf-8')).hexdigest()

    # Retornar en mayúsculas (formato oficial AEAT)
    return hash_resultado.upper()


def formatear_fecha_verifactu(fecha_iso):
    """Convierte 'YYYY-MM-DD' a 'DD-MM-AAAA' para Verifactu."""
    d = datetime.strptime(fecha_iso, "%Y-%m-%d")
    return d.strftime("%d-%m-%Y")
