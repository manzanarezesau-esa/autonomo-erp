# modelo303_utils.py
import io
import streamlit as st
from datetime import datetime, date

def generar_pdf_303(anio, trimestre, base_ventas, iva_repercutido, base_compras, iva_soportado, irpf_retenido, beneficio_neto, pago_fraccionado, iva_ingresar):
    """
    Genera un PDF estructurado del Modelo 303 para el usuario.
    Usa WeasyPrint para crear un HTML y convertirlo a PDF.
    """
    from weasyprint import HTML
    
    # Determinar meses del trimestre
    meses_trim = {
        "1T (Ene-Mar)": "Enero - Febrero - Marzo",
        "2T (Abr-Jun)": "Abril - Mayo - Junio",
        "3T (Jul-Sep)": "Julio - Agosto - Septiembre",
        "4T (Oct-Dic)": "Octubre - Noviembre - Diciembre"
    }
    meses = meses_trim.get(trimestre, trimestre)
    
    # Determinar resultado
    resultado = iva_repercutido - iva_soportado
    if resultado > 0:
        resultado_texto = f"A INGRESAR: {resultado:,.2f} €"
        casilla = "Casilla 69"
    elif resultado < 0:
        resultado_texto = f"A COMPENSAR: {abs(resultado):,.2f} €"
        casilla = "Casilla 71"
    else:
        resultado_texto = "SIN RESULTADO (0,00 €)"
        casilla = "Casilla 69/71"
    
    html_str = f"""
    <!DOCTYPE html>
    <html lang="es">
    <head>
        <meta charset="utf-8">
        <style>
            * {{ margin: 0; padding: 0; box-sizing: border-box; }}
            body {{
                font-family: 'Segoe UI', Arial, sans-serif;
                color: #2d3748;
                margin: 1.5cm;
                font-size: 11px;
            }}
            .header {{
                display: flex;
                justify-content: space-between;
                align-items: center;
                border-bottom: 3px solid #1e3a8a;
                padding-bottom: 15px;
                margin-bottom: 25px;
            }}
            .header h1 {{
                color: #1e3a8a;
                font-size: 22px;
            }}
            .header .periodo {{
                text-align: right;
                font-size: 14px;
                color: #4a5568;
            }}
            h2 {{
                color: #1e3a8a;
                font-size: 16px;
                margin: 20px 0 10px 0;
                border-bottom: 1px solid #e2e8f0;
                padding-bottom: 5px;
            }}
            table {{
                width: 100%;
                border-collapse: collapse;
                margin: 10px 0;
                font-size: 11px;
            }}
            th {{
                background-color: #1e3a8a;
                color: white;
                padding: 8px;
                text-align: left;
                font-weight: 600;
            }}
            td {{
                padding: 8px;
                border-bottom: 1px solid #e2e8f0;
            }}
            td.amount {{ text-align: right; font-family: 'Courier New', monospace; }}
            .total-row td {{
                font-weight: bold;
                background-color: #f7fafc;
                border-top: 2px solid #1e3a8a;
            }}
            .resultado-box {{
                background-color: #ebf4ff;
                border: 2px solid #1e3a8a;
                border-radius: 8px;
                padding: 15px;
                margin: 20px 0;
                text-align: center;
            }}
            .resultado-box .importe {{
                font-size: 24px;
                font-weight: bold;
                color: #1e3a8a;
            }}
            .footer {{
                margin-top: 40px;
                font-size: 9px;
                color: #718096;
                text-align: center;
                border-top: 1px solid #e2e8f0;
                padding-top: 10px;
            }}
            .aviso {{
                background-color: #fff3cd;
                border: 1px solid #ffc107;
                padding: 10px;
                border-radius: 4px;
                margin: 15px 0;
                font-size: 10px;
            }}
        </style>
    </head>
    <body>
        <div class="header">
            <h1>MODELO 303 - IVA</h1>
            <div class="periodo">
                <strong>Período:</strong> {trimestre} {anio}<br>
                <strong>Meses:</strong> {meses}
            </div>
        </div>
        
        <div class="aviso">
            ⚠️ <strong>BORRADOR INFORMATIVO</strong> - Este documento es un resumen para tu uso personal.
            Para la presentación oficial, descarga el fichero de importación AEAT.
        </div>
        
        <h2>1. IVA DEVENGADO (Ventas)</h2>
        <table>
            <tr>
                <th>Concepto</th>
                <th>Base Imponible</th>
                <th>Tipo IVA</th>
                <th>Cuota Repercutida</th>
            </tr>
            <tr>
                <td>Régimen general</td>
                <td class="amount">{base_ventas:,.2f} €</td>
                <td>21%</td>
                <td class="amount">{iva_repercutido:,.2f} €</td>
            </tr>
            <tr class="total-row">
                <td colspan="3">TOTAL IVA DEVENGADO</td>
                <td class="amount">{iva_repercutido:,.2f} €</td>
            </tr>
        </table>
        
        <h2>2. IVA DEDUCIBLE (Compras y Gastos)</h2>
        <table>
            <tr>
                <th>Concepto</th>
                <th>Base Imponible</th>
                <th>Tipo IVA</th>
                <th>Cuota Soportada</th>
            </tr>
            <tr>
                <td>Adquisiciones corrientes</td>
                <td class="amount">{base_compras:,.2f} €</td>
                <td>21%</td>
                <td class="amount">{iva_soportado:,.2f} €</td>
            </tr>
            <tr class="total-row">
                <td colspan="3">TOTAL IVA DEDUCIBLE</td>
                <td class="amount">{iva_soportado:,.2f} €</td>
            </tr>
        </table>
        
        <h2>3. RESULTADO DE LA LIQUIDACIÓN</h2>
        <div class="resultado-box">
            <div>{casilla}</div>
            <div class="importe">{resultado_texto}</div>
        </div>
        
        <h2>4. INFORMACIÓN ADICIONAL</h2>
        <table>
            <tr>
                <th>Concepto</th>
                <th>Importe</th>
            </tr>
            <tr>
                <td>IRPF Retenciones practicadas</td>
                <td class="amount">{irpf_retenido:,.2f} €</td>
            </tr>
            <tr>
                <td>Beneficio neto estimado</td>
                <td class="amount">{beneficio_neto:,.2f} €</td>
            </tr>
            <tr>
                <td>Pago fraccionado IRPF (20%)</td>
                <td class="amount">{pago_fraccionado:,.2f} €</td>
            </tr>
        </table>
        
        <div class="footer">
            Documento generado el {datetime.now().strftime('%d/%m/%Y a las %H:%M')} ·
            Este borrador no tiene validez oficial ante la AEAT
        </div>
    </body>
    </html>
    """
    
    try:
        pdf_bytes = HTML(string=html_str).write_pdf()
        return pdf_bytes
    except Exception as e:
        st.error(f"Error al generar PDF: {str(e)}")
        return None


def generar_fichero_aeat_303(anio, trimestre, base_ventas, iva_repercutido, base_compras, iva_soportado, nif_emisor, nombre_emisor):
    """
    Genera el fichero de importación AEAT para el Modelo 303.
    
    Formato del registro tipo 1 según especificación AEAT:
    - Posiciones 1-2: Tipo de registro (01)
    - Posiciones 3-11: NIF del declarante (9 caracteres)
    - Posiciones 12-40: Apellidos y nombre (29 caracteres)
    - Posiciones 41-44: Ejercicio (4 dígitos)
    - Posiciones 45-46: Período (2 dígitos: 01, 02, 03, 04)
    - Posiciones 47-51: Espacios reservados
    - Posiciones 52-66: Casilla 01 (Base imponible - 15 caracteres)
    - Posiciones 67-81: Casilla 04 (Cuota devengada - 15 caracteres)
    - Posiciones 82-96: Casilla 19 (Base deducible - 15 caracteres)
    - Posiciones 97-111: Casilla 22 (Cuota soportada - 15 caracteres)
    - Posiciones 112-126: Casilla 69/71 (Resultado - 15 caracteres con signo)
    
    Formato del registro tipo 2 (fin):
    - Posiciones 1-2: Tipo de registro (99)
    - Posiciones 3-100: Espacios
    """
    
    # Mapear trimestre a código de período AEAT
    periodo_codigo = {
        "1T (Ene-Mar)": "01",
        "2T (Abr-Jun)": "02",
        "3T (Jul-Sep)": "03",
        "4T (Oct-Dic)": "04"
    }
    periodo = periodo_codigo.get(trimestre, "01")
    
    # Formatear NIF (9 caracteres, sin espacios, mayúsculas)
    nif_limpio = nif_emisor.strip().upper().replace(" ", "").replace("-", "")
    # Asegurar que tenga exactamente 9 caracteres
    nif_limpio = nif_limpio[:9].ljust(9)
    
    # Formatear nombre (29 caracteres)
    nombre_limpio = nombre_emisor.strip()[:29].ljust(29)
    
    # Ejercicio (4 dígitos)
    ejercicio = str(anio)[:4].rjust(4, "0")
    
    # Función para formatear importes AEAT (15 posiciones)
    # Los importes se formatean en céntimos, sin decimales
    # Los valores positivos van sin signo
    # Los valores negativos usan signo "-" al inicio
    def formatear_importe_positivo(valor):
        """Formatea importe positivo (15 posiciones, sin signo)"""
        centimos = int(round(abs(valor) * 100))
        return f"{centimos:015d}"
    
    def formatear_importe_con_signo(valor):
        """Formatea importe con signo (15 posiciones, con signo si negativo)"""
        if valor >= 0:
            centimos = int(round(valor * 100))
            return f"{centimos:015d}"
        else:
            centimos = int(round(abs(valor) * 100))
            return f"-{centimos:014d}"
    
    # Calcular resultado
    resultado = iva_repercutido - iva_soportado
    
    # Construir registro tipo 1
    # Total: 100 caracteres
    registro_1 = (
        "01" +                          # Tipo de registro (2)
        nif_limpio +                    # NIF (9) -> Posiciones 3-11
        nombre_limpio +                 # Nombre (29) -> Posiciones 12-40
        ejercicio +                     # Ejercicio (4) -> Posiciones 41-44
        periodo +                       # Período (2) -> Posiciones 45-46
        " " * 5 +                       # Espacios reservados (5) -> Posiciones 47-51
        formatear_importe_positivo(base_ventas) +      # Casilla 01 (15) -> Posiciones 52-66
        formatear_importe_positivo(iva_repercutido) +  # Casilla 04 (15) -> Posiciones 67-81
        formatear_importe_positivo(base_compras) +     # Casilla 19 (15) -> Posiciones 82-96
        formatear_importe_positivo(iva_soportado) +    # Casilla 22 (15) -> Posiciones 97-111
        formatear_importe_con_signo(resultado)         # Casilla 69/71 (15) -> Posiciones 112-126
    )
    
    # Asegurar que el registro tenga exactamente 100 caracteres
    registro_1 = registro_1[:100].ljust(100)
    
    # Construir registro de fin (tipo 99)
    registro_fin = "99" + " " * 98  # Total: 100 caracteres
    
    # Unir con CRLF (Windows) o LF (Unix)
    # La AEAT acepta ambos, pero CRLF es más seguro
    fichero_completo = registro_1 + "\r\n" + registro_fin
    
    return fichero_completo


def validar_fichero_aeat(contenido):
    """
    Valida la estructura del fichero AEAT generado.
    
    Parámetros:
    - contenido: String del fichero completo
    
    Retorna:
    - (es_valido, mensaje)
    """
    lineas = contenido.split('\r\n')
    
    if not lineas:
        return False, "El fichero está vacío"
    
    # Verificar registro inicial
    if len(lineas) < 2:
        return False, "El fichero debe tener al menos 2 registros"
    
    # Verificar primer registro
    if lineas[0][:2] != "01":
        return False, "El primer registro debe ser tipo 01"
    
    if len(lineas[0]) != 100:
        return False, f"El registro 01 debe tener 100 caracteres (tiene {len(lineas[0])})"
    
    # Verificar registro final
    if lineas[-1][:2] != "99":
        return False, "El último registro debe ser tipo 99"
    
    if len(lineas[-1]) != 100:
        return False, f"El registro 99 debe tener 100 caracteres (tiene {len(lineas[-1])})"
    
    # Verificar NIF (posiciones 3-11)
    nif = lineas[0][2:11]
    if not nif or nif.isspace():
        return False, "NIF vacío en el registro"
    
    # Verificar ejercicio (posiciones 41-44)
    ejercicio = lineas[0][40:44]
    if not ejercicio.isdigit():
        return False, "Ejercicio no numérico"
    
    # Verificar período (posiciones 45-46)
    periodo = lineas[0][44:46]
    if periodo not in ["01", "02", "03", "04"]:
        return False, "Período inválido"
    
    return True, "✅ Estructura del fichero válida"
