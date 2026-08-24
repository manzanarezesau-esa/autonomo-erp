# modelo303_utils.py
import io
import streamlit as st
from datetime import datetime, date

def generar_pdf_303(anio, trimestre, base_ventas, iva_repercutido, base_compras, iva_soportado, irpf_retenido, beneficio_neto, pago_fraccionado, iva_ingresar):
    """
    Genera un PDF estructurado del Modelo 303 para el usuario.
    Usa WeasyPrint (ya instalado) para crear un HTML y convertirlo a PDF.
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
    Sigue el diseño de registro oficial de la AEAT (Registro tipo 1).
    
    Formato del registro tipo 1 (Modelo 303):
    Posiciones 1-2: Tipo de registro (01 para registro de datos)
    Posiciones 3-11: NIF del declarante (9 caracteres)
    Posiciones 12-40: Apellidos y nombre (29 caracteres)
    Posiciones 41-45: Ejercicio (4 caracteres + 1 espacio)
    Posiciones 46-50: Período (2 caracteres + 3 espacios)
    Posiciones 51-65: Casilla 01 (Base imponible - 15 caracteres con signo)
    Posiciones 66-80: Casilla 04 (Cuota devengada - 15 caracteres)
    ... (continúa con todas las casillas)
    
    NOTA: Esta es una versión simplificada. El formato exacto debe validarse
    con el diseño oficial de la AEAT antes de usar.
    """
    
    # Mapear trimestre a código de período AEAT
    periodo_codigo = {
        "1T (Ene-Mar)": "01",
        "2T (Abr-Jun)": "02",
        "3T (Jul-Sep)": "03",
        "4T (Oct-Dic)": "04"
    }
    periodo = periodo_codigo.get(trimestre, "01")
    
    # Formatear NIF (9 caracteres, sin espacios)
    nif_limpio = nif_emisor.strip().upper().replace(" ", "")[:9].ljust(9)
    
    # Formatear nombre (29 caracteres)
    nombre_limpio = nombre_emisor.strip()[:29].ljust(29)
    
    # Formatear ejercicio (4 dígitos)
    ejercicio = str(anio)[:4]
    
    # Función para formatear importes (15 posiciones, 2 decimales, sin punto)
    def formatear_importe(valor):
        # Convertir a céntimos y formatear a 15 caracteres con ceros a la izquierda
        centimos = int(round(valor * 100))
        if centimos < 0:
            # Negativo: usar complemento a 10 o formato especial
            return f"-{abs(centimos):013d}"
        return f"{centimos:015d}"
    
    # Construir el registro tipo 1
    registro = (
        "01" +                     # Tipo de registro
        nif_limpio +               # NIF declarante
        nombre_limpio +            # Nombre
        ejercicio + " " +          # Ejercicio
        periodo + "   " +          # Período
        formatear_importe(base_ventas) +       # Casilla 01: Base imponible
        formatear_importe(iva_repercutido) +   # Casilla 04: Cuota devengada
        formatear_importe(base_compras) +      # Casilla 19: Base deducible
        formatear_importe(iva_soportado) +     # Casilla 22: Cuota soportada
        formatear_importe(iva_repercutido - iva_soportado)  # Casilla 69/71: Resultado
    )
    
    # Añadir registro de fin de archivo (tipo 99)
    registro_fin = "99" + " " * 98  # Registro de fin con espacios
    
    return registro + "\r\n" + registro_fin
