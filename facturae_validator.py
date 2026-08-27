# facturae_validator.py
import streamlit as st
from lxml import etree

# ============================================================
# VALIDACIÓN SIMPLIFICADA DE FACTURAE v3.2.2
# ============================================================
# NOTA: El XSD completo de FacturaE v3.2.2 es muy extenso.
# Por ahora usamos una validación manual de campos obligatorios.
# Para validación oficial completa, usar la sede electrónica de la AEAT.
# ============================================================

def validar_facturae_completo(xml_str):
    """
    Valida un XML FacturaE con validación manual de campos obligatorios.
    
    Retorna:
    - (es_valido, mensaje)
    """
    campos_faltantes = []
    errores = []
    
    try:
        xml_doc = etree.fromstring(xml_str.encode('utf-8'))
        
        # Namespace de FacturaE
        ns = "{http://www.facturae.gob.es/formato/Versiones/Facturaev3_2_2.xml}"
        
        # Campos obligatorios a comprobar
        campos_obligatorios = {
            "SchemaVersion": "Versión del esquema",
            "Modality": "Modalidad",
            "InvoiceIssuerType": "Tipo de emisor",
            "BatchIdentifier": "Identificador del lote",
            "InvoicesCount": "Número de facturas",
            "InvoiceCurrencyCode": "Código de moneda",
            "TaxIdentificationType": "Tipo de identificación fiscal",
            "TaxIdentificationNumber": "Número de identificación fiscal",
            "InvoiceNumber": "Número de factura",
            "InvoiceClass": "Clase de factura",
            "IssueDate": "Fecha de expedición",
            "TotalGrossAmount": "Base imponible",
            "TotalTaxOutputs": "IVA repercutido",
            "InvoiceTotal": "Total de la factura",
            "ItemDescription": "Descripción de línea",
            "Quantity": "Cantidad",
            "UnitPriceWithoutTax": "Precio unitario sin impuestos",
            "TotalCost": "Coste total de línea",
        }
        
        for campo, descripcion in campos_obligatorios.items():
            elemento = xml_doc.find(f".//{ns}{campo}")
            if elemento is None or not elemento.text or not elemento.text.strip():
                campos_faltantes.append(f"{descripcion} ({campo})")
        
        # Verificar estructura básica
        file_header = xml_doc.find(f".//{ns}FileHeader")
        if file_header is None:
            errores.append("Falta el bloque FileHeader")
        
        parties = xml_doc.find(f".//{ns}Parties")
        if parties is None:
            errores.append("Falta el bloque Parties")
        
        invoices = xml_doc.find(f".//{ns}Invoices")
        if invoices is None:
            errores.append("Falta el bloque Invoices")
        
        # Verificar TaxIdentification en Seller y Buyer
        seller_tax = xml_doc.find(f".//{ns}SellerParty/{ns}TaxIdentification")
        if seller_tax is None:
            errores.append("Falta TaxIdentification del emisor")
        
        buyer_tax = xml_doc.find(f".//{ns}BuyerParty/{ns}TaxIdentification")
        if buyer_tax is None:
            errores.append("Falta TaxIdentification del receptor")
        
        # Verificar que hay al menos 1 línea de factura
        invoice_lines = xml_doc.findall(f".//{ns}InvoiceLine")
        if len(invoice_lines) == 0:
            errores.append("No hay líneas de factura")
        
        # Construir mensaje
        mensajes = []
        
        if campos_faltantes:
            mensajes.append("**Campos obligatorios faltantes:**")
            for campo in campos_faltantes:
                mensajes.append(f"  • {campo}")
        
        if errores:
            mensajes.append("**Errores de estructura:**")
            for error in errores:
                mensajes.append(f"  • {error}")
        
        if not mensajes:
            return True, "✅ XML válido según validación manual de campos obligatorios FacturaE v3.2.2"
        
        return False, "\n".join(mensajes)
        
    except etree.XMLSyntaxError as e:
        return False, f"Error de sintaxis XML: {str(e)}"
    except Exception as e:
        return False, f"Error al validar XML: {str(e)}"
