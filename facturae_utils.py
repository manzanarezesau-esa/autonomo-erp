import xml.etree.ElementTree as ET
from xml.dom import minidom
import streamlit as st
from firma_xades import firmar_facturae_xml
from facturae_validator import validar_facturae_completo
from certificate_manager import obtener_certificado_usuario


def generar_facturae_xml(invoice, client, company, lineas, user_id=None, firmar=False, certificado=None, password=None, validar=True, usar_timestamp=True):
    """
    Genera un XML estricto compatible con el esquema oficial FacturaE v3.2.2.
    """
    ns = "http://www.facturae.gob.es/formato/Versiones/Facturaev3_2_2.xml"
    
    # Elemento raíz con namespace oficial
    root = ET.Element(f"{{{ns}}}Facturae", {
        "xmlns:fe": ns
    })
    
    # =====================================================
    # 1. FileHeader (Cabecera del archivo)
    # =====================================================
    file_header = ET.SubElement(root, "fe:FileHeader")
    ET.SubElement(file_header, "fe:SchemaVersion").text = "3.2.2"
    ET.SubElement(file_header, "fe:Modality").text = "I"
    ET.SubElement(file_header, "fe:InvoiceIssuerType").text = "EM"
    
    total_factura = float(invoice.get("total", 0))
    batch = ET.SubElement(file_header, "fe:Batch")
    ET.SubElement(batch, "fe:BatchIdentifier").text = str(invoice.get("invoice_number", "F0001"))
    ET.SubElement(batch, "fe:InvoicesCount").text = "1"
    
    tot_inv_amt = ET.SubElement(batch, "fe:TotalInvoicesAmount")
    ET.SubElement(tot_inv_amt, "fe:TotalAmount").text = f"{total_factura:.2f}"
    
    tot_out_amt = ET.SubElement(batch, "fe:TotalOutstandingAmount")
    ET.SubElement(tot_out_amt, "fe:TotalAmount").text = f"{total_factura:.2f}"
    
    tot_exe_amt = ET.SubElement(batch, "fe:TotalExecutableAmount")
    ET.SubElement(tot_exe_amt, "fe:TotalAmount").text = f"{total_factura:.2f}"
    
    ET.SubElement(batch, "fe:InvoiceCurrencyCode").text = "EUR"
    
    # =====================================================
    # 2. Parties (Emisor y Receptor)
    # =====================================================
    parties = ET.SubElement(root, "fe:Parties")
    
    # --- EMISOR ---
    seller_party = ET.SubElement(parties, "fe:SellerParty")
    seller_tax = ET.SubElement(seller_party, "fe:TaxIdentification")
    
    cif_emisor = (company.get("company_tax_id", "") or "").strip().upper()
    es_persona_juridica = len(cif_emisor) > 0 and cif_emisor[0].isalpha()
    
    ET.SubElement(seller_tax, "fe:PersonTypeCode").text = "J" if es_persona_juridica else "F"
    ET.SubElement(seller_tax, "fe:ResidenceTypeCode").text = "R"
    ET.SubElement(seller_tax, "fe:TaxIdentificationNumber").text = cif_emisor
    
    seller_legal = ET.SubElement(seller_party, "fe:LegalEntity")
    ET.SubElement(seller_legal, "fe:CorporateName").text = company.get("company_name", "Empresa Emisora")
    
    seller_addr = ET.SubElement(seller_legal, "fe:AddressInSpain")
    ET.SubElement(seller_addr, "fe:Address").text = company.get("company_address", "Calle Principal 1")
    ET.SubElement(seller_addr, "fe:PostCode").text = "28001"
    ET.SubElement(seller_addr, "fe:Town").text = "Madrid"
    ET.SubElement(seller_addr, "fe:Province").text = "Madrid"
    ET.SubElement(seller_addr, "fe:CountryCode").text = "ESP"
    
    # --- RECEPTOR ---
    buyer_party = ET.SubElement(parties, "fe:BuyerParty")
    buyer_tax = ET.SubElement(buyer_party, "fe:TaxIdentification")
    
    cif_receptor = (client.get("tax_id", "") or "").strip().upper()
    es_cliente_juridico = len(cif_receptor) > 0 and cif_receptor[0].isalpha()
    
    ET.SubElement(buyer_tax, "fe:PersonTypeCode").text = "J" if es_cliente_juridico else "F"
    ET.SubElement(buyer_tax, "fe:ResidenceTypeCode").text = "R"
    ET.SubElement(buyer_tax, "fe:TaxIdentificationNumber").text = cif_receptor
    
    buyer_legal = ET.SubElement(buyer_party, "fe:LegalEntity")
    ET.SubElement(buyer_legal, "fe:CorporateName").text = client.get("name", "Cliente")
    
    buyer_addr = ET.SubElement(buyer_legal, "fe:AddressInSpain")
    ET.SubElement(buyer_addr, "fe:Address").text = client.get("address", "Calle Cliente 1")
    ET.SubElement(buyer_addr, "fe:PostCode").text = "28001"
    ET.SubElement(buyer_addr, "fe:Town").text = "Madrid"
    ET.SubElement(buyer_addr, "fe:Province").text = "Madrid"
    ET.SubElement(buyer_addr, "fe:CountryCode").text = "ESP"
    
    # =====================================================
    # 3. Invoices (Cuerpo de Factura)
    # =====================================================
    invoices = ET.SubElement(root, "fe:Invoices")
    invoice_elem = ET.SubElement(invoices, "fe:Invoice")
    
    # InvoiceHeader
    invoice_header = ET.SubElement(invoice_elem, "fe:InvoiceHeader")
    ET.SubElement(invoice_header, "fe:InvoiceNumber").text = str(invoice.get("invoice_number", "FAC-01"))
    ET.SubElement(invoice_header, "fe:DocumentTypeId").text = "FC"
    ET.SubElement(invoice_header, "fe:InvoiceClass").text = "OR" if invoice.get("tipo") == "rectificativa" else "OO"
    
    # InvoiceIssueData
    invoice_issue = ET.SubElement(invoice_elem, "fe:InvoiceIssueData")
    ET.SubElement(invoice_issue, "fe:IssueDate").text = str(invoice.get("date", "2026-01-01"))
    ET.SubElement(invoice_issue, "fe:InvoiceCurrencyCode").text = "EUR"
    ET.SubElement(invoice_issue, "fe:TaxCurrencyCode").text = "EUR"
    ET.SubElement(invoice_issue, "fe:LanguageCode").text = "es"
    
    base_amt = float(invoice.get("base_amount", 0))
    vat_pct = float(invoice.get("vat_percentage", 21))
    vat_amt = float(invoice.get("vat_amount", 0))
    irpf_pct = float(invoice.get("irpf_percentage", 0))
    irpf_amt = float(invoice.get("irpf_amount", 0))
    
    # TaxesOutputs (IVA)
    taxes_outputs = ET.SubElement(invoice_elem, "fe:TaxesOutputs")
    tax = ET.SubElement(taxes_outputs, "fe:Tax")
    ET.SubElement(tax, "fe:TaxTypeCode").text = "01"
    ET.SubElement(tax, "fe:TaxRate").text = f"{vat_pct:.2f}"
    
    tx_base = ET.SubElement(tax, "fe:TaxableBase")
    ET.SubElement(tx_base, "fe:TotalAmount").text = f"{base_amt:.2f}"
    
    tx_amt = ET.SubElement(tax, "fe:TaxAmount")
    ET.SubElement(tx_amt, "fe:TotalAmount").text = f"{vat_amt:.2f}"
    
    # TaxesWithheld (IRPF)
    if irpf_pct > 0:
        taxes_withheld = ET.SubElement(invoice_elem, "fe:TaxesWithheld")
        tax_w = ET.SubElement(taxes_withheld, "fe:Tax")
        ET.SubElement(tax_w, "fe:TaxTypeCode").text = "04"
        ET.SubElement(tax_w, "fe:TaxRate").text = f"{irpf_pct:.2f}"
        
        tx_w_base = ET.SubElement(tax_w, "fe:TaxableBase")
        ET.SubElement(tx_w_base, "fe:TotalAmount").text = f"{base_amt:.2f}"
        
        tx_w_amt = ET.SubElement(tax_w, "fe:TaxAmount")
        ET.SubElement(tx_w_amt, "fe:TotalAmount").text = f"{irpf_amt:.2f}"

    # InvoiceTotals
    totals = ET.SubElement(invoice_elem, "fe:InvoiceTotals")
    ET.SubElement(totals, "fe:TotalGrossAmount").text = f"{base_amt:.2f}"
    ET.SubElement(totals, "fe:TotalGeneralDiscounts").text = "0.00"
    ET.SubElement(totals, "fe:TotalGeneralSurcharges").text = "0.00"
    ET.SubElement(totals, "fe:TotalGrossAmountBeforeTaxes").text = f"{base_amt:.2f}"
    ET.SubElement(totals, "fe:TotalTaxOutputs").text = f"{vat_amt:.2f}"
    
    if irpf_pct > 0:
        ET.SubElement(totals, "fe:TotalTaxesWithheld").text = f"{irpf_amt:.2f}"
        
    ET.SubElement(totals, "fe:InvoiceTotal").text = f"{total_factura:.2f}"
    ET.SubElement(totals, "fe:TotalOutstandingAmount").text = f"{total_factura:.2f}"
    ET.SubElement(totals, "fe:TotalExecutableAmount").text = f"{total_factura:.2f}"
    
    # Items (Líneas)
    items = ET.SubElement(invoice_elem, "fe:Items")
    for linea in lineas:
        item = ET.SubElement(items, "fe:InvoiceLine")
        ET.SubElement(item, "fe:ItemDescription").text = str(linea.get("description", "Servicio"))
        ET.SubElement(item, "fe:Quantity").text = f"{float(linea.get('quantity', 1)):.2f}"
        ET.SubElement(item, "fe:UnitPriceWithoutTax").text = f"{float(linea.get('unit_price', 0)):.2f}"
        
        line_base = float(linea.get("base_amount", linea.get("total", 0)))
        ET.SubElement(item, "fe:TotalCost").text = f"{line_base:.2f}"
        ET.SubElement(item, "fe:GrossAmount").text = f"{line_base:.2f}"
        
        # Impuestos por línea
        line_taxes = ET.SubElement(item, "fe:TaxesOutputs")
        line_tax = ET.SubElement(line_taxes, "fe:Tax")
        ET.SubElement(line_tax, "fe:TaxTypeCode").text = "01"
        ET.SubElement(line_tax, "fe:TaxRate").text = f"{vat_pct:.2f}"
        
        lt_base = ET.SubElement(line_tax, "fe:TaxableBase")
        ET.SubElement(lt_base, "fe:TotalAmount").text = f"{line_base:.2f}"
        
        lt_amt = ET.SubElement(line_tax, "fe:TaxAmount")
        ET.SubElement(lt_amt, "fe:TotalAmount").text = f"{(line_base * vat_pct / 100):.2f}"

    # PaymentDetails
    payment_details = ET.SubElement(invoice_elem, "fe:PaymentDetails")
    installment = ET.SubElement(payment_details, "fe:Installment")
    ET.SubElement(installment, "fe:InstallmentDueDate").text = str(invoice.get("date", "2026-01-01"))
    ET.SubElement(installment, "fe:InstallmentAmount").text = f"{total_factura:.2f}"
    ET.SubElement(installment, "fe:PaymentMethod").text = "04"
    
    if company.get("company_iban"):
        account = ET.SubElement(installment, "fe:AccountToBeCredited")
        ET.SubElement(account, "fe:IBAN").text = company.get("company_iban", "").replace(" ", "")

    # Conversión a string con formato indentado
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
    return generar_facturae_xml(invoice, client, company, lineas, firmar=False, validar=False)
