# facturae_utils.py
import xml.etree.ElementTree as ET
from xml.dom import minidom
import streamlit as st
from firma_xades import firmar_facturae_xml
from facturae_validator import validar_facturae_completo


def generar_facturae_xml(invoice, client, company, lineas, firmar=False, certificado=None, password=None, validar=True):
    """
    Genera un XML compatible con FacturaE v3.2.2.
    Opcionalmente valida y firma con XAdES-EPES.
    
    Parámetros:
    - invoice: Diccionario con datos de la factura
    - client: Diccionario con datos del cliente
    - company: Diccionario con datos de la empresa emisora
    - lineas: Lista de líneas de factura
    - firmar: Boolean para firmar o no
    - certificado: Bytes del certificado P12
    - password: Contraseña del certificado
    - validar: Boolean para validar contra XSD antes de firmar
    
    Retorna:
    - XML generado (firmado si se solicita) como string
    """
    ns = "http://www.facturae.gob.es/formato/Versiones/Facturaev3_2_2.xml"
    
    # Crear elemento raíz con namespace
    root = ET.Element("fe:Facturae", {"xmlns:fe": ns})
    
    # FileHeader
    file_header = ET.SubElement(root, "fe:FileHeader")
    schema_version = ET.SubElement(file_header, "fe:SchemaVersion")
    schema_version.text = "3.2.2"
    modality = ET.SubElement(file_header, "fe:Modality")
    modality.text = "I"
    invoice_issuer_type = ET.SubElement(file_header, "fe:InvoiceIssuerType")
    invoice_issuer_type.text = "EM"
    
    # Parties - Seller
    parties = ET.SubElement(root, "fe:Parties")
    seller_party = ET.SubElement(parties, "fe:SellerParty")
    seller_tax_id = ET.SubElement(seller_party, "fe:TaxIdentification")
    seller_tax_type = ET.SubElement(seller_tax_id, "fe:TaxIdentificationType")
    seller_tax_type.text = "01"
    seller_tax_number = ET.SubElement(seller_tax_id, "fe:TaxIdentificationNumber")
    seller_tax_number.text = company.get("company_tax_id", "")
    
    # Parties - Buyer
    buyer_party = ET.SubElement(parties, "fe:BuyerParty")
    buyer_tax_id = ET.SubElement(buyer_party, "fe:TaxIdentification")
    buyer_tax_type = ET.SubElement(buyer_tax_id, "fe:TaxIdentificationType")
    buyer_tax_type.text = "01"
    buyer_tax_number = ET.SubElement(buyer_tax_id, "fe:TaxIdentificationNumber")
    buyer_tax_number.text = client.get("tax_id", "")
    
    # Invoices
    invoices = ET.SubElement(root, "fe:Invoices")
    invoice_elem = ET.SubElement(invoices, "fe:Invoice")
    
    invoice_number = ET.SubElement(invoice_elem, "fe:InvoiceNumber")
    invoice_number.text = invoice.get("invoice_number", "")
    
    issue_date = ET.SubElement(invoice_elem, "fe:IssueDate")
    issue_date.text = invoice.get("date", "")
    
    # InvoiceTotals
    totals = ET.SubElement(invoice_elem, "fe:InvoiceTotals")
    total_gross = ET.SubElement(totals, "fe:TotalGrossAmount")
    total_gross.text = f"{invoice.get('base_amount', 0):.2f}"
    total_tax = ET.SubElement(totals, "fe:TotalTaxOutputs")
    total_tax.text = f"{invoice.get('vat_amount', 0):.2f}"
    total_invoice = ET.SubElement(totals, "fe:InvoiceTotal")
    total_invoice.text = f"{invoice.get('total', 0):.2f}"
    
    # Items
    items = ET.SubElement(invoice_elem, "fe:Items")
    for linea in lineas:
        item = ET.SubElement(items, "fe:InvoiceLine")
        item_desc = ET.SubElement(item, "fe:ItemDescription")
        item_desc.text = linea.get("description", "")
        quantity = ET.SubElement(item, "fe:Quantity")
        quantity.text = str(linea.get("quantity", 1))
        unit_price = ET.SubElement(item, "fe:UnitPriceWithoutTax")
        unit_price.text = f"{linea.get('unit_price', 0):.2f}"
        total_cost = ET.SubElement(item, "fe:TotalCost")
        total_cost.text = f"{linea.get('total', 0):.2f}"
    
    # Convertir a string con formato
    xml_str = ET.tostring(root, encoding='utf-8', method='xml')
    dom = minidom.parseString(xml_str)
    pretty_xml = dom.toprettyxml(indent="  ")
    
    # Validar contra XSD si se solicita
    if validar:
        es_valido, mensaje = validar_facturae_completo(pretty_xml)
        
        if not es_valido:
            st.error(f"### El XML no cumple con el esquema FacturaE v3.2.2\n\n{mensaje}")
            # Mostrar advertencia pero continuar (el usuario puede decidir)
            st.warning("Puede descargar el XML sin validar, pero no será válido oficialmente.")
        else:
            st.success("✅ XML validado correctamente contra el esquema oficial FacturaE v3.2.2")
    
    # Firmar si se solicita
    if firmar and certificado and password:
        pretty_xml = firmar_facturae_xml(pretty_xml, certificado, password)
    
    return pretty_xml
