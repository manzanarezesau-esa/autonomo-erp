# verifactu_utils.py — REESCRITO SEGÚN ORDEN HAC/1177/2024
import urllib.parse
from datetime import datetime
from kreyo_verifactu_hash_calculator import (
    compute_registro_alta,
    RegistroAltaInput,
)


def generar_url_qr_verifactu(nif_emisor, num_serie_factura, fecha_expedicion, importe_total, produccion=True):
    """
    URL oficial del QR Verifactu.
    
    - num_serie_factura: concatenación "SERIE-NUMERO" (ej: "F2026-0001")
    - fecha_expedicion: formato "DD-MM-AAAA"
    - importe_total: float (se formatea con punto decimal)
    """
    if produccion:
        base = "https://www2.agenciatributaria.gob.es/wlpl/TIKE-CONT/ValidarQR"
    else:
        base = "https://prewww2.aeat.es/wlpl/TIKE-CONT/ValidarQR"

    nif_limpio = nif_emisor.strip().upper().replace(" ", "").replace("-", "")
    params = {
        "nif": nif_limpio,
        "numserie": num_serie_factura,
        "fecha": fecha_expedicion,  # Ya debe venir en DD-MM-AAAA
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
    Hash SHA-256 según especificación AEAT v0.1.2.
    Usa librería de referencia que pasa los vectores oficiales.
    
    - num_serie_factura: "SERIE-NUMERO" concatenado
    - fecha_expedicion: "DD-MM-AAAA"
    - tipo_factura: "F1", "F2", "R1", etc.
    - cuota_total: string con coma decimal (ej: "12,35")
    - importe_total: string con coma decimal (ej: "123,45")
    - hash_anterior: None si es la primera factura
    - fecha_hora_gen_registro: ISO 8601 con timezone
    """
    input_data = RegistroAltaInput(
        id_emisor_factura=nif_emisor.strip().upper(),
        num_serie_factura=num_serie_factura,
        fecha_expedicion_factura=fecha_expedicion,
        tipo_factura=tipo_factura,
        cuota_total=str(cuota_total).replace(".", ","),
        importe_total=str(importe_total).replace(".", ","),
        huella_anterior=hash_anterior,
        fecha_hora_huso_gen_registro=fecha_hora_gen_registro,
    )
    return compute_registro_alta(input_data)


def formatear_fecha_verifactu(fecha_iso):
    """Convierte 'YYYY-MM-DD' a 'DD-MM-AAAA' para Verifactu."""
    d = datetime.strptime(fecha_iso, "%Y-%m-%d")
    return d.strftime("%d-%m-%Y")
