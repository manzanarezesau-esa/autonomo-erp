# verifactu_utils.py
import hashlib
import urllib.parse

def generar_qr_verifactu(nif_emisor, numero_factura, serie, fecha_expedicion, importe_total, hash_factura):
    """
    Genera la URL del QR según especificación Veri*Factu de la AEAT.
    
    Parámetros:
    - nif_emisor: NIF del emisor (ej: "12345678Z")
    - numero_factura: Número de factura (ej: "0001")
    - serie: Serie de la factura (ej: "F2024" o "0")
    - fecha_expedicion: Fecha en formato "YYYY-MM-DD"
    - importe_total: Importe total (float)
    - hash_factura: Huella SHA-256 (64 caracteres hex)
    
    Retorna:
    - URL completa para el QR
    """
    base_url = "https://www.agenciatributaria.gob.es/Verifactu"
    
    # Limpiar NIF (sin espacios, guiones, etc.)
    nif_limpio = nif_emisor.strip().upper().replace(" ", "").replace("-", "")
    
    # Formatear importe con 2 decimales usando punto
    importe_formateado = f"{importe_total:.2f}"
    
    # Construir parámetros
    params = {
        "nif": nif_limpio,
        "num": numero_factura,
        "serie": serie if serie else "0",
        "fecha": fecha_expedicion,
        "importe": importe_formateado,
        "hash": hash_factura
    }
    
    # Codificar URL
    query_string = urllib.parse.urlencode(params)
    url_completa = f"{base_url}?{query_string}"
    
    return url_completa


def generar_hash_verifactu(nif_emisor, numero_factura, serie, fecha_expedicion, importe_total, hash_anterior=""):
    """
    Genera la huella SHA-256 según especificación Veri*Factu.
    
    El orden de concatenación es:
    NIF + NúmeroFactura + Serie + FechaExpedicion + ImporteTotal + HashAnterior
    
    Parámetros:
    - nif_emisor: NIF del emisor
    - numero_factura: Número de factura
    - serie: Serie de la factura
    - fecha_expedicion: Fecha en formato "YYYY-MM-DD"
    - importe_total: Importe total (float)
    - hash_anterior: Hash de la factura anterior (cadena vacía si es la primera)
    
    Retorna:
    - Hash SHA-256 en hexadecimal (64 caracteres)
    """
    # Limpiar NIF
    nif_limpio = nif_emisor.strip().upper().replace(" ", "").replace("-", "")
    
    # Formatear importe
    importe_formateado = f"{importe_total:.2f}"
    
    # Construir cadena a hashear
    cadena = (
        f"{nif_limpio}|"
        f"{numero_factura}|"
        f"{serie if serie else '0'}|"
        f"{fecha_expedicion}|"
        f"{importe_formateado}|"
        f"{hash_anterior}"
    )
    
    # Generar hash SHA-256
    hash_resultado = hashlib.sha256(cadena.encode('utf-8')).hexdigest()
    
    return hash_resultado
