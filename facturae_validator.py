# facturae_validator.py
import streamlit as st
from lxml import etree

# ============================================================
# VALIDACIÓN SIMPLIFICADA DE FACTURAE v3.2.2
# ============================================================
# Valida campos obligatorios según la estructura CORRECTA del XSD.
# Ya NO usa TaxIdentificationType - usa PersonTypeCode y ResidenceTypeCode.
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
        
        # ============================================================
        # CAMPOS OBLIGATORIOS - ESTRUCTURA CORRECTA según XSD
        # ============================================================
        campos_obligatorios = {
            # FileHeader
            "SchemaVersion": "Versión del esquema",
            "Modality": "Modalidad",
            "InvoiceIssuerType": "Tipo de emisor",
            "BatchIdentifier": "Identificador del lote",
            "InvoicesCount": "Número de facturas",
            "InvoiceCurrencyCode": "Código de moneda",
            
            # TaxIdentification - CORREGIDO
            "PersonTypeCode": "Tipo de persona (F/J)",
            "ResidenceTypeCode": "Código de residencia",
            "TaxIdentificationNumber": "Número de identificación fiscal",
            
            # InvoiceHeader
            "InvoiceNumber": "Número de factura",
            "InvoiceDocumentType": "Tipo de documento",
            "InvoiceClass": "Clase de factura",
            
            # InvoiceIssueData
            "IssueDate": "Fecha de expedición",
            "LanguageCode": "Código de idioma",
            
            # InvoiceTotals
            "TotalGrossAmount": "Base imponible",
            "TotalTaxOutputs": "IVA repercutido",
            "InvoiceTotal": "Total de la factura",
            
            # Items
            "ItemDescription": "Descripción de línea",
            "Quantity": "Cantidad",
            "UnitPriceWithoutTax": "Precio unitario sin impuestos",
            "TotalCost": "Coste total de línea",
        }
        
        for campo, descripcion in campos_obligatorios.items():
            elemento = xml_doc.find(f".//{ns}{campo}")
            if elemento is None or not elemento.text or not elemento.text.strip():
                campos_faltantes.append(f"{descripcion} ({campo})")
        
        # ============================================================
        # VERIFICACIÓN DE ESTRUCTURA
        # ============================================================
        
        # FileHeader
        file_header = xml_doc.find(f".//{ns}FileHeader")
        if file_header is None:
            errores.append("Falta el bloque FileHeader")
        
        # Batch
        batch = xml_doc.find(f".//{ns}FileHeader/{ns}Batch")
        if batch is None:
            errores.append("Falta el bloque Batch dentro de FileHeader")
        
        # Parties
        parties = xml_doc.find(f".//{ns}Parties")
        if parties is None:
            errores.append("Falta el bloque Parties")
        
        # Invoices
        invoices = xml_doc.find(f".//{ns}Invoices")
        if invoices is None:
            errores.append("Falta el bloque Invoices")
        
        # ============================================================
        # VERIFICACIÓN DE TAX IDENTIFICATION EN SELLER Y BUYER
        # ============================================================
        
        # Seller Party
        seller_party = xml_doc.find(f".//{ns}SellerParty")
        if seller_party is None:
            errores.append("Falta SellerParty")
        else:
            seller_tax = seller_party.find(f"{ns}TaxIdentification")
            if seller_tax is None:
                errores.append("Falta TaxIdentification del emisor")
            else:
                # Verificar PersonTypeCode
                person_type = seller_tax.find(f"{ns}PersonTypeCode")
                if person_type is None or not person_type.text:
                    errores.append("Falta PersonTypeCode del emisor")
                
                # Verificar ResidenceTypeCode
                residence_type = seller_tax.find(f"{ns}ResidenceTypeCode")
                if residence_type is None or not residence_type.text:
                    errores.append("Falta ResidenceTypeCode del emisor")
                
                # Verificar TaxIdentificationNumber
                tax_number = seller_tax.find(f"{ns}TaxIdentificationNumber")
                if tax_number is None or not tax_number.text:
                    errores.append("Falta TaxIdentificationNumber del emisor")
            
            # Verificar que tenga Individual o LegalEntity
            seller_individual = seller_party.find(f"{ns}Individual")
            seller_legal = seller_party.find(f"{ns}LegalEntity")
            if seller_individual is None and seller_legal is None:
                errores.append("El emisor debe tener Individual o LegalEntity")
            
            # Si es Individual, verificar FirstSurname
            if seller_individual is not None:
                seller_first_surname = seller_individual.find(f"{ns}FirstSurname")
                if seller_first_surname is None or not seller_first_surname.text:
                    errores.append("Falta FirstSurname en Individual del emisor")
        
        # Buyer Party
        buyer_party = xml_doc.find(f".//{ns}BuyerParty")
        if buyer_party is None:
            errores.append("Falta BuyerParty")
        else:
            buyer_tax = buyer_party.find(f"{ns}TaxIdentification")
            if buyer_tax is None:
                errores.append("Falta TaxIdentification del receptor")
            else:
                person_type = buyer_tax.find(f"{ns}PersonTypeCode")
                if person_type is None or not person_type.text:
                    errores.append("Falta PersonTypeCode del receptor")
                
                residence_type = buyer_tax.find(f"{ns}ResidenceTypeCode")
                if residence_type is None or not residence_type.text:
                    errores.append("Falta ResidenceTypeCode del receptor")
                
                tax_number = buyer_tax.find(f"{ns}TaxIdentificationNumber")
                if tax_number is None or not tax_number.text:
                    errores.append("Falta TaxIdentificationNumber del receptor")
            
            buyer_individual = buyer_party.find(f"{ns}Individual")
            buyer_legal = buyer_party.find(f"{ns}LegalEntity")
            if buyer_individual is None and buyer_legal is None:
                errores.append("El receptor debe tener Individual o LegalEntity")
            
            if buyer_individual is not None:
                buyer_first_surname = buyer_individual.find(f"{ns}FirstSurname")
                if buyer_first_surname is None or not buyer_first_surname.text:
                    errores.append("Falta FirstSurname en Individual del receptor")
        
        # ============================================================
        # VERIFICACIÓN DE INVOICE HEADER
        # ============================================================
        
        invoice = xml_doc.find(f".//{ns}Invoice")
        if invoice is not None:
            # InvoiceHeader
            invoice_header = invoice.find(f"{ns}InvoiceHeader")
            if invoice_header is None:
                errores.append("Falta InvoiceHeader")
            else:
                # InvoiceNumber dentro de InvoiceHeader
                invoice_number = invoice_header.find(f"{ns}InvoiceNumber")
                if invoice_number is None or not invoice_number.text:
                    errores.append("Falta InvoiceNumber dentro de InvoiceHeader")
                
                # InvoiceDocumentType
                doc_type = invoice_header.find(f"{ns}InvoiceDocumentType")
                if doc_type is None or not doc_type.text:
                    errores.append("Falta InvoiceDocumentType dentro de InvoiceHeader")
                
                # InvoiceClass
                invoice_class = invoice_header.find(f"{ns}InvoiceClass")
                if invoice_class is None or not invoice_class.text:
                    errores.append("Falta InvoiceClass dentro de InvoiceHeader")
        
        # ============================================================
        # VERIFICACIÓN DE LÍNEAS DE FACTURA
        # ============================================================
        invoice_lines = xml_doc.findall(f".//{ns}InvoiceLine")
        if len(invoice_lines) == 0:
            errores.append("No hay líneas de factura")
        
        # ============================================================
        # CONSTRUIR MENSAJE DE RESULTADO
        # ============================================================
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
            return True, "✅ XML válido según validación de campos obligatorios FacturaE v3.2.2"
        
        return False, "\n".join(mensajes)
        
    except etree.XMLSyntaxError as e:
        return False, f"Error de sintaxis XML: {str(e)}"
    except Exception as e:
        return False, f"Error al validar XML: {str(e)}"
