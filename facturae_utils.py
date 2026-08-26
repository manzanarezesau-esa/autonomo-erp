# facturae_utils.py
import xml.etree.ElementTree as ET
from xml.dom import minidom
import streamlit as st
from firma_xades import firmar_facturae_xml
from facturae_validator import validar_facturae_completo
from certificate_manager import obtener_certificado_usuario

# Espacio de nombres oficial de FacturaE v3.2.2
NS = "http://www.facturae.gob.es/formato/Versiones/Facturaev3_2_2.xml"
ET.register_namespace("fe", NS)
ET.register_namespace("ds", "http://www.w3.org/2000/09/xmldsig#")

def qn(tag):
    """Genera el Qualified Name correcto con Namespace para ElementTree"""
    return f"{{{NS}}}{tag}"

def generar_facturae_xml(invoice, client, company, lineas, user_id=None, firmar=False, certificado=None, password=None, validar=True, usar_timestamp=True):
    """
    Genera un XML estricto compatible con el esquema oficial FacturaE v3.2.2.
    """
    root = ET.Element(qn("Facturae"))
    
    # =====================================================
    # 1. FileHeader (Cabecera del archivo)
    # =====================================================
    file_header = ET.SubElement(root, qn("FileHeader"))
    ET.SubElement(file_header, qn("SchemaVersion")).text = "3.2.2"
    ET.SubElement(file_header, qn("Modality")).text = "I"
    ET.SubElement(file_header, qn("InvoiceIssuerType")).text = "EM"
    
    total_factura = float(invoice.get("total", 0))
    
    batch = ET.SubElement(file_header, qn("Batch"))
    ET.SubElement(batch, qn("BatchIdentifier")).text = str(invoice.get("invoice_number", "F0001"))
    ET.SubElement(batch, qn("InvoicesCount")).text = "1"
    
    tot_inv_amt = ET.SubElement(batch, qn("TotalInvoicesAmount"))
    ET.SubElement(tot_inv_amt, qn("TotalAmount")).text = f"{total_factura:.2f}"
    
    tot_out_amt = ET.SubElement(batch, qn("TotalOutstandingAmount"))
    ET.SubElement(tot_out_amt, qn("TotalAmount")).text = f"{total_factura:.2f}"
    
    tot_exe_amt = ET.SubElement(batch, qn("TotalExecutableAmount"))
    ET.SubElement(tot_exe_amt, qn("TotalAmount")).text = f"{total_factura:.2f}"
    
    ET.SubElement(batch, qn("InvoiceCurrencyCode")).text = "EUR"
    
    # =====================================================
    # 2. Parties (Emisor y Receptor)
    # =====================================================
    parties = ET.SubElement(root, qn("Parties"))
    
    # --- EMISOR ---
    seller_party = ET.SubElement(parties, qn("SellerParty"))
    seller_tax = ET.SubElement(seller_party, qn("TaxIdentification"))
    
    cif_emisor = (company.get("company_tax_id", "") or "").strip().upper()
    
    ET.SubElement(seller_tax, qn("PersonTypeCode")).text = "J"
    ET.SubElement(seller_tax, qn("ResidenceTypeCode")).text = "R"
    ET.SubElement(seller_tax, qn("TaxIdentificationNumber")).text = cif_emisor
    
    seller_legal = ET.SubElement(seller_party, qn("LegalEntity"))
    ET.SubElement(seller_legal, qn("CorporateName")).text = company.get("company_name", "Empresa Emisora")
    
    seller_addr = ET.SubElement(seller_legal, qn("AddressInSpain"))
    ET.SubElement(seller_addr, qn("Address")).text = company.get("company_address", "Calle Principal 1")
    ET.SubElement(seller_addr, qn("PostCode")).text = "28001"
    ET.SubElement(seller_addr, qn("Town")).text = "Madrid"
    ET.SubElement(seller_addr, qn("Province")).text = "Madrid"
    ET.SubElement(seller_addr, qn("CountryCode")).text = "ESP"
    
    # --- RECEPTOR ---
    buyer_party = ET.SubElement(parties, qn("BuyerParty"))
    buyer_tax = ET.SubElement(buyer_party, qn("TaxIdentification"))
    
    cif_receptor = (client.get("tax_id", "") or "").strip().upper()
    
    ET.SubElement(buyer_tax, qn("PersonTypeCode")).text = "J"
    ET.SubElement(buyer_tax, qn("ResidenceTypeCode")).text = "R"
    ET.SubElement(buyer_tax, qn("TaxIdentificationNumber")).text = cif_receptor
    
    buyer_legal = ET.SubElement(buyer_party, qn("LegalEntity"))
    ET.SubElement(buyer_legal, qn("CorporateName")).text = client.get("name", "Cliente")
    
    buyer_addr = ET.SubElement(buyer_legal, qn("AddressInSpain"))
    ET.SubElement(buyer_addr, qn("Address")).text = client.get("address", "Calle Cliente 1")
    ET.SubElement(buyer_addr, qn("PostCode")).text = "28001"
    ET.SubElement(buyer_addr, qn("Town")).text = "Madrid"
    ET.SubElement(buyer_addr, qn("Province")).text = "Madrid"
    ET.SubElement(buyer_addr, qn("CountryCode")).text = "ESP"
    
    # =====================================================
    # 3. Invoices (Cuerpo de Factura)
    # =====================================================
    invoices = ET.SubElement(root, qn("Invoices"))
    invoice_elem = ET.SubElement(invoices, qn("Invoice"))
    
    # InvoiceHeader
    invoice_header = ET.SubElement(invoice_elem, qn("InvoiceHeader"))
    ET.SubElement(invoice_header, qn("InvoiceNumber")).text = str(invoice.get("invoice_number", "FAC-01"))
    ET.SubElement(invoice_header, qn("DocumentTypeId")).text = "FC"
    ET.SubElement(invoice_header, qn("InvoiceClass")).text = "OR" if invoice.get("tipo") == "rectificativa" else "OO"
    
    # InvoiceIssueData
    invoice_issue = ET.SubElement(invoice_elem, qn("InvoiceIssueData"))
    ET.SubElement(invoice_issue, qn("IssueDate")).text = str(invoice.get("date", "2026-01-01"))
    ET.SubElement(invoice_issue, qn("InvoiceCurrencyCode")).text = "EUR"
    ET.SubElement(invoice_issue, qn("TaxCurrencyCode")).text = "EUR"
    ET.SubElement(invoice_issue, qn("LanguageCode")).text = "es"
    
    base_amt = float(invoice.get("base_amount", 0))
    vat_pct = float(invoice.get("vat_percentage", 21))
    vat_amt = float(invoice.get("vat_amount", 0))
    irpf_pct = float(invoice.get("irpf_percentage", 0))
    irpf_amt = float(invoice.get("irpf_amount", 0))
    
    # TaxesOutputs (IVA)
    taxes_outputs = ET.SubElement(invoice_elem, qn("TaxesOutputs"))
    tax = ET.SubElement(taxes_outputs, qn("Tax"))
    ET.SubElement(tax, qn("TaxTypeCode")).text = "01"
    ET.SubElement(tax, qn("TaxRate")).text = f"{vat_pct:.2f}"
    
    tx_base = ET.SubElement(tax, qn("TaxableBase"))
    ET.SubElement(tx_base, qn("TotalAmount")).text = f"{base_amt:.2f}"
    
    tx_amt = ET.SubElement(tax, qn("TaxAmount"))
    ET.SubElement(tx_amt, qn("TotalAmount")).text = f"{vat_amt:.2f}"
    
    # TaxesWithheld (IRPF)
    if irpf_pct > 0:
        taxes_withheld = ET.SubElement(invoice_elem, qn("TaxesWithheld"))
        tax_w = ET.SubElement(taxes_withheld, qn("Tax"))
        ET.SubElement(tax_w, qn("TaxTypeCode")).text = "04"
        ET.SubElement(tax_w, qn("TaxRate")).text = f"{irpf_pct:.2f}"
        
        tx_w_base = ET.SubElement(tax_w, qn("TaxableBase"))
        ET.SubElement(tx_w_base, qn("TotalAmount")).text = f"{base_amt:.2f}"
        
        tx_w_amt = ET.SubElement(tax_w, qn("TaxAmount"))
        ET.SubElement(tx_w_amt, qn("TotalAmount")).text = f"{irpf_amt:.2f}"

    # InvoiceTotals
    totals = ET.SubElement(invoice_elem, qn("InvoiceTotals"))
    ET.SubElement(totals, qn("TotalGrossAmount")).text = f"{base_amt:.2f}"
    ET.SubElement(totals, qn("TotalGeneralDiscounts")).text = "0.00"
    ET.SubElement(totals, qn("TotalGeneralSurcharges")).text = "0.00"
    ET.SubElement(totals, qn("TotalGrossAmountBeforeTaxes")).text = f"{base_amt:.2f}"
    ET.SubElement(totals, qn("TotalTaxOutputs")).text = f"{vat_amt:.2f}"
    
    if irpf_pct > 0:
        ET.SubElement(totals, qn("TotalTaxesWithheld")).text = f"{irpf_amt:.2f}"
        
    ET.SubElement(totals, qn("InvoiceTotal")).text = f"{total_factura:.2f}"
    ET.SubElement(totals, qn("TotalOutstandingAmount")).text = f"{total_factura:.2f}"
    ET.SubElement(totals, qn("TotalExecutableAmount")).text = f"{total_factura:.2f}"
    
    # Items (Líneas de factura)
    items = ET.SubElement(invoice_elem, qn("Items"))
    for linea in lineas:
        item = ET.SubElement(items, qn("InvoiceLine"))
        ET.SubElement(item, qn("ItemDescription")).text = str(linea.get("description", "Servicio"))
        ET.SubElement(item, qn("Quantity")).text = f"{float(linea.get('quantity', 1)):.2f}"
        ET.SubElement(item, qn("UnitPriceWithoutTax")).text = f"{float(linea.get('unit_price', 0)):.2f}"
        
        line_base = float(linea.get("base_amount", linea.get("total", 0)))
        ET.SubElement(item, qn("TotalCost")).text = f"{line_base:.2f}"
        ET.SubElement(item, qn("GrossAmount")).text = f"{line_base:.2f}"
        
        # Impuestos por línea (IVA)
        line_taxes = ET.SubElement(item, qn("TaxesOutputs"))
        line_tax = ET.SubElement(line_taxes, qn("Tax"))
        ET.SubElement(line_tax, qn("TaxTypeCode")).text = "01"
        ET.SubElement(line_tax, qn("TaxRate")).text = f"{vat_pct:.2f}"
        
        lt_base = ET.SubElement(line_tax, qn("TaxableBase"))
        ET.SubElement(lt_base, qn("TotalAmount")).text = f"{line_base:.2f}"
        
        lt_amt = ET.SubElement(line_tax, qn("TaxAmount"))
        ET.SubElement(lt_amt, qn("TotalAmount")).text = f"{(line_base * vat_pct / 100):.2f}"

    # PaymentDetails
    payment_details = ET.SubElement(invoice_elem, qn("PaymentDetails"))
    installment = ET.SubElement(payment_details, qn("Installment"))
    ET.SubElement(installment, qn("InstallmentDueDate")).text = str(invoice.get("date", "2026-01-01"))
    ET.SubElement(installment, qn("InstallmentAmount")).text = f"{total_factura:.2f}"
    ET.SubElement(installment, qn("PaymentMethod")).text = "04"
    
    if company.get("company_iban"):
        account = ET.SubElement(installment, qn("AccountToBeCredited"))
        ET.SubElement(account, qn("IBAN")).text = company.get("company_iban", "").replace(" ", "")

    # =====================================================
    # Conversión a string con formato indentado
    # =====================================================
    xml_bytes = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    dom = minidom.parseString(xml_bytes)
    pretty_xml = "\n".join([line for line in dom.toprettyxml(indent="  ").split("\n") if line.strip()])
    
    # Validar contra el esquema XSD
    if validar:
        es_valido, mensaje = validar_facturae_completo(pretty_xml)
        if not es_valido:
            st.error(f"### El XML no cumple con el esquema FacturaE v3.2.2\n\n{mensaje}")
            st.warning("Puede descargar el XML sin validar, pero no será válido oficialmente.")
        else:
            st.success("✅ XML validado correctamente contra el esquema oficial FacturaE v3.2.2")
            
    # Firma con XAdES-T
    if firmar:
        if certificado is None and password is None and user_id:
            certificado, password = obtener_certificado_usuario(user_id)
        if certificado and password:
            pretty_xml = firmar_facturae_xml(pretty_xml, certificado, password, usar_timestamp=usar_timestamp)
        else:
            st.warning("No se encontró certificado para firmar. El XML se generará sin firma.")
            
    return pretty_xml


def generar_facturae_xml_simplificada(invoice, client, company, lineas):
    """
    Genera XML FacturaE simplificado sin validación ni firma.
    """
    return generar_facturae_xml(invoice, client, company, lineas, firmar=False, validar=False)
