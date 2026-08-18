import xml.etree.ElementTree as ET
from xml.dom import minidom

def generar_facturae_xml(invoice, client, company, lineas):
    """
    Genera un archivo XML FacturaE v3.2.2 conforme al esquema oficial
    del Ministerio de Hacienda / AEAT (España).
    """
    NS_FE = "http://www.facturae.es/Facturae/2014/v3.2.2/Facturae"
    
    # Registrar namespace para prefijos en la salida XML
    ET.register_namespace("fe", NS_FE)
    
    def fe(tag):
        return f"{{{NS_FE}}}{tag}"
    
    root = ET.Element(fe("Facturae"))
    
    total_val = float(invoice.get("total", 0.0) or 0.0)
    base_val = float(invoice.get("base_amount", 0.0) or 0.0)
    vat_pct = float(invoice.get("vat_percentage", 21.0) or 21.0)
    vat_amt = float(invoice.get("vat_amount", 0.0) or 0.0)

    # -------------------------------------------------------------
    # 1. FILE HEADER (Cabecera del fichero)
    # -------------------------------------------------------------
    file_header = ET.SubElement(root, fe("FileHeader"))
    ET.SubElement(file_header, fe("SchemaVersion")).text = "3.2.2"
    ET.SubElement(file_header, fe("Modality")).text = "I"  # Individual
    ET.SubElement(file_header, fe("InvoiceIssuerType")).text = "EM"  # Emisor
    
    batch = ET.SubElement(file_header, fe("Batch"))
    ET.SubElement(batch, fe("BatchIdentifier")).text = str(invoice.get("invoice_number", ""))
    ET.SubElement(batch, fe("InvoicesCount")).text = "1"
    
    tot_inv = ET.SubElement(batch, fe("TotalInvoicesAmount"))
    ET.SubElement(tot_inv, fe("TotalAmount")).text = f"{total_val:.2f}"
    
    tot_out = ET.SubElement(batch, fe("TotalOutstandingAmount"))
    ET.SubElement(tot_out, fe("TotalAmount")).text = f"{total_val:.2f}"
    
    tot_exe = ET.SubElement(batch, fe("TotalExecutableAmount"))
    ET.SubElement(tot_exe, fe("TotalAmount")).text = f"{total_val:.2f}"
    
    ET.SubElement(batch, fe("InvoiceCurrencyCode")).text = "EUR"

    # -------------------------------------------------------------
    # 2. PARTIES (Emisor y Comprador)
    # -------------------------------------------------------------
    parties = ET.SubElement(root, fe("Parties"))
    
    # Emisor / Vendedor
    seller = ET.SubElement(parties, fe("SellerParty"))
    tax_id_s = ET.SubElement(seller, fe("TaxIdentification"))
    nif_emisor = str(company.get("company_tax_id", "")).upper().strip()
    es_fisica_s = len(nif_emisor) == 9 and nif_emisor[0].isdigit()
    
    ET.SubElement(tax_id_s, fe("PersonTypeCode")).text = "F" if es_fisica_s else "J"
    ET.SubElement(tax_id_s, fe("ResidenceTypeCode")).text = "R"
    ET.SubElement(tax_id_s, fe("TaxIdentificationNumber")).text = nif_emisor
    
    seller_entity = ET.SubElement(seller, fe("Individual" if es_fisica_s else "LegalEntity"))
    if es_fisica_s:
        ET.SubElement(seller_entity, fe("Name")).text = str(company.get("company_name", ""))
        ET.SubElement(seller_entity, fe("FirstSurname")).text = "."
    else:
        ET.SubElement(seller_entity, fe("CorporateName")).text = str(company.get("company_name", ""))

    # Comprador / Cliente
    buyer = ET.SubElement(parties, fe("BuyerParty"))
    tax_id_b = ET.SubElement(buyer, fe("TaxIdentification"))
    nif_cliente = str(client.get("tax_id", "")).upper().strip()
    es_fisica_b = len(nif_cliente) == 9 and (nif_cliente[0].isdigit() or nif_cliente[0] in "XYZ")
    
    ET.SubElement(tax_id_b, fe("PersonTypeCode")).text = "F" if es_fisica_b else "J"
    ET.SubElement(tax_id_b, fe("ResidenceTypeCode")).text = "R"
    ET.SubElement(tax_id_b, fe("TaxIdentificationNumber")).text = nif_cliente
    
    buyer_entity = ET.SubElement(buyer, fe("Individual" if es_fisica_b else "LegalEntity"))
    if es_fisica_b:
        ET.SubElement(buyer_entity, fe("Name")).text = str(client.get("name", ""))
        ET.SubElement(buyer_entity, fe("FirstSurname")).text = "."
    else:
        ET.SubElement(buyer_entity, fe("CorporateName")).text = str(client.get("name", ""))

    # -------------------------------------------------------------
    # 3. INVOICES (Detalle de la factura)
    # -------------------------------------------------------------
    invoices = ET.SubElement(root, fe("Invoices"))
    inv = ET.SubElement(invoices, fe("Invoice"))
    
    # Encabezado
    header = ET.SubElement(inv, fe("InvoiceHeader"))
    ET.SubElement(header, fe("InvoiceNumber")).text = str(invoice.get("invoice_number", ""))
    ET.SubElement(header, fe("InvoiceDocumentType")).text = "FC"  # Factura Completa
    ET.SubElement(header, fe("InvoiceClass")).text = "OO"  # Original
    ET.SubElement(header, fe("IssueDate")).text = str(invoice.get("date", ""))
    
    # Líneas
    items_elem = ET.SubElement(inv, fe("Items"))
    for line in lineas:
        line_elem = ET.SubElement(items_elem, fe("InvoiceLine"))
        ET.SubElement(line_elem, fe("ItemDescription")).text = str(line.get("description", ""))
        ET.SubElement(line_elem, fe("Quantity")).text = f"{float(line.get('quantity', 1)):.2f}"
        ET.SubElement(line_elem, fe("UnitPriceWithoutTax")).text = f"{float(line.get('unit_price', 0)):.2f}"
        ET.SubElement(line_elem, fe("TotalAmount")).text = f"{float(line.get('base_amount', 0)):.2f}"

    # Impuestos REPERCUTIDOS (IVA)
    taxes_outputs = ET.SubElement(inv, fe("TaxesOutputs"))
    tax = ET.SubElement(taxes_outputs, fe("Tax"))
    ET.SubElement(tax, fe("TaxTypeCode")).text = "01"  # IVA
    ET.SubElement(tax, fe("TaxRate")).text = f"{vat_pct:.2f}"
    
    taxable_base = ET.SubElement(tax, fe("TaxableBase"))
    ET.SubElement(taxable_base, fe("TotalAmount")).text = f"{base_val:.2f}"
    
    tax_amt = ET.SubElement(tax, fe("TaxAmount"))
    ET.SubElement(tax_amt, fe("TotalAmount")).text = f"{vat_amt:.2f}"
    
    # Totales de la factura
    inv_totals = ET.SubElement(inv, fe("InvoiceTotals"))
    ET.SubElement(inv_totals, fe("TotalGrossAmount")).text = f"{base_val:.2f}"
    ET.SubElement(inv_totals, fe("TotalGrossAmountBeforeTaxes")).text = f"{base_val:.2f}"
    ET.SubElement(inv_totals, fe("TotalTaxOutputs")).text = f"{vat_amt:.2f}"
    ET.SubElement(inv_totals, fe("TotalTaxesWithheld")).text = "0.00"
    ET.SubElement(inv_totals, fe("InvoiceTotal")).text = f"{total_val:.2f}"

    # Formateo legible (al quitar encoding="utf-8" devuelve 'str' en lugar de 'bytes')
    xml_raw = ET.tostring(root, encoding="utf-8")
    parsed = minidom.parseString(xml_raw)
    return parsed.toprettyxml(indent="  ")
