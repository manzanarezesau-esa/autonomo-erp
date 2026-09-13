# verifactu_utils.py — Implementación completa Verifactu (Orden HAC/1177/2024)
import hashlib
import urllib.parse
from datetime import datetime


# ════════════════════════════════════════════════════════════
# URL OFICIAL DEL QR (Orden HAC/1177/2024)
# ════════════════════════════════════════════════════════════
def generar_url_qr_verifactu(nif_emisor, num_serie_factura, fecha_expedicion, importe_total, produccion=True):
    """
    URL oficial del QR Verifactu.

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


# ════════════════════════════════════════════════════════════
# HASH SHA-256 OFICIAL (Orden HAC/1177/2024)
# ════════════════════════════════════════════════════════════
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

    Orden ESTRICTO de campos (no se puede alterar):
    1. IDEmisorFactura
    2. NumSerieFactura
    3. FechaExpedicionFactura (DD-MM-AAAA)
    4. TipoFactura (F1, F2, R1-R5)
    5. CuotaTotal (IVA)
    6. ImporteTotal
    7. Huella (hash anterior, vacío si es el primero)
    8. FechaHoraHusoGenRegistro (ISO-8601 con huso)

    Formato: nombreCampo1=valor1&nombreCampo2=valor2&...
    """
    nif_limpio = (nif_emisor or "").strip().upper().replace(" ", "").replace("-", "")
    cuota_fmt = f"{float(cuota_total):.2f}"
    importe_fmt = f"{float(importe_total):.2f}"
    huella = hash_anterior if hash_anterior else ""

    cadena = (
        f"IDEmisorFactura={nif_limpio}&"
        f"NumSerieFactura={num_serie_factura}&"
        f"FechaExpedicionFactura={fecha_expedicion}&"
        f"TipoFactura={tipo_factura}&"
        f"CuotaTotal={cuota_fmt}&"
        f"ImporteTotal={importe_fmt}&"
        f"Huella={huella}&"
        f"FechaHoraHusoGenRegistro={fecha_hora_gen_registro}"
    )

    return hashlib.sha256(cadena.encode("utf-8")).hexdigest().upper()


def formatear_fecha_verifactu(fecha_iso):
    """Convierte 'YYYY-MM-DD' a 'DD-MM-AAAA' para Verifactu."""
    d = datetime.strptime(fecha_iso, "%Y-%m-%d")
    return d.strftime("%d-%m-%Y")


# ════════════════════════════════════════════════════════════
# SISTEMA INFORMÁTICO (SIF) — Identificación del software
# ════════════════════════════════════════════════════════════
def get_sistema_informatico(nif_emisor: str = "") -> dict:
    """
    Devuelve los datos identificativos del Sistema Informático de Facturación
    (SIF) que genera los registros, según la Orden HAC/1177/2024.

    Estos datos son obligatorios en cada registro de facturación (registro de alta).
    """
    return {
        "NombreRazon": "Hondureformas",
        "NIF": nif_emisor or "",  # se rellena con el NIF del usuario desde settings
        "NombreSistemaInformatico": "Hondureformas ERP",
        "IdSistemaInformatico": "HF",
        "Version": "1.0.0",
        "NumeroInstalacion": "00001",
        "TipoUsoPosibleSoloVerifactu": "S",
        "TipoUsoPosibleMultiOT": "S",
        "IndicadorMultiplesOT": "S",
    }


def get_bloque_sistema_informatico_xml(nif_emisor: str) -> str:
    """
    Devuelve el bloque XML <SistemaInformatico> listo para insertar
    en el registro de alta de Verifactu.
    """
    sif = get_sistema_informatico(nif_emisor)
    return (
        "<SistemaInformatico>"
        f"<NombreRazon>{sif['NombreRazon']}</NombreRazon>"
        f"<NIF>{sif['NIF']}</NIF>"
        f"<NombreSistemaInformatico>{sif['NombreSistemaInformatico']}</NombreSistemaInformatico>"
        f"<IdSistemaInformatico>{sif['IdSistemaInformatico']}</IdSistemaInformatico>"
        f"<Version>{sif['Version']}</Version>"
        f"<NumeroInstalacion>{sif['NumeroInstalacion']}</NumeroInstalacion>"
        f"<TipoUsoPosibleSoloVerifactu>{sif['TipoUsoPosibleSoloVerifactu']}</TipoUsoPosibleSoloVerifactu>"
        f"<TipoUsoPosibleMultiOT>{sif['TipoUsoPosibleMultiOT']}</TipoUsoPosibleMultiOT>"
        f"<IndicadorMultiplesOT>{sif['IndicadorMultiplesOT']}</IndicadorMultiplesOT>"
        "</SistemaInformatico>"
    )
