# facturae_utils.py
import xml.etree.ElementTree as ET
from xml.dom import minidom
import streamlit as st
from firma_xades import firmar_facturae_xml
from facturae_validator import validar_facturae_completo
from certificate_manager import obtener_certificado_usuario

# Espacio de nombres oficial de FacturaE v3.2.2
NS = "http://www.facturae.gob.es/formato/Versiones/Facturaev3_2_2.xml"
ET.register_namespace("", NS)
ET.register_namespace("ds", "http://www.w3.org/2000/09/xmldsig#")

def _qn(tag):
    """Genera el Qualified Name con Namespace"""
    return f"{{{NS}}}{tag}"

def _safe_float(val, default=0.0):
    """Evita errores de float(None) o cadenas vacías"""
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default

def _safe_str(val, default=""):
    """Evita errores de conversión a string"""
    if val is None:
        return default
    return str(val).strip()

def _parse_address(address_str):
    """
    Parsea una dirección completa y extrae ciudad y provincia.
    Ejemplo: "calle san valenti 43 bajo, TERRASA (BARCELONA)"
    Retorna: (address, town, province)
    """
    if not address_str:
        return "", "Madrid", "Madrid"
    
    address_str = address_str.strip()
    town = "Madrid"
    province = "Madrid"
    address = address_str
    
    # Intentar extraer ciudad y provincia del formato "dirección, CIUDAD (PROVINCIA)"
    if "(" in address_str and ")" in address_str:
        try:
            province_part = address_str[address_str.rindex("(")+1:address_str.rindex(")")]
            province = province_part.strip().title()
            address = address_str[:address_str.rindex("(")].strip()
        except Exception:
            pass
    
    if "," in address:
        parts = address.rsplit(",", 1)
        if len(parts) == 2:
            address = parts[0].strip()
            town_candidate = parts[1].strip()
            # Si la ciudad contiene paréntesis de provincia, separar
            if "(" in town_candidate:
                town = town_candidate[:town_candidate.index("(")].strip()
            else:
                town = town_candidate
            town = town.title()
    
    return address[:100], town[:50], province[:50]

def generar_facturae_xml(invoice, client, company, lineas, user_id=None, firmar=False, certificado=None, password=None, validar=True, usar_timestamp=True):
    """
    Genera un XML compatible con FacturaE v3.2.2.
    
    SECUENCIA EXACTA SEGÚN XSD OFICIAL:
    Facturae → FileHeader → Parties → Invoices
    """
    invoice = invoice or {}
    client = client or {}
    company = company or {}
    lineas = lineas or []

    root = ET.Element(_qn("Facturae"))
    
    total_factura = _safe_float(invoice.get("total"))
    inv_num = _safe_str(invoice.get("invoice_number"), "FAC-001")
    fecha = _safe_str(invoice.get("date"), "2026-01-01")
    
    base_amt = _safe_float(invoice.get("base_amount"))
    vat_pct = _safe_float(invoice.get("vat_percentage"), 21.0)
    vat_amt = _safe_float(invoice.get("vat_amount"))
    irpf_pct = _safe_float(invoice.get("irpf_percentage"))
    irpf_amt = _safe_float(invoice.get("irpf_amount"))
    
    # ═══════════════════════════════════════════════════════
    # 1. FILE HEADER
    # Secuencia: SchemaVersion, Modality, InvoiceIssuerType, Batch
    # ═══════════════════════════════════════════════════════
    file_header = ET.SubElement(root, _qn("FileHeader"))
    ET.SubElement(file_header, _qn("SchemaVersion")).text = "3.2.2"
    ET.SubElement(file_header, _qn("Modality")).text = "I"
    ET.SubElement(file_header, _qn("InvoiceIssuerType")).text = "EM"
    
    # Batch
    batch = ET.SubElement(file_header, _qn("Batch"))
    ET.SubElement(batch, _qn("BatchIdentifier")).text = inv_num
    ET.SubElement(batch, _qn("InvoicesCount")).text = "1"
    
    tot_inv = ET.SubElement(batch, _qn("TotalInvoicesAmount"))
    ET.SubElement(tot_inv, _qn("TotalAmount")).text = f"{total_factura:.2f}"
    
    tot_out = ET.SubElement(batch, _qn("TotalOutstandingAmount"))
    ET.SubElement(tot_out, _qn("TotalAmount")).text = f"{total_factura:.2f}"
    
    tot_exe = ET.SubElement(batch, _qn("TotalExecutableAmount"))
    ET.SubElement(tot_exe, _qn("TotalAmount")).text = f"{total_factura:.2f}"
    
    ET.SubElement(batch, _qn("InvoiceCurrencyCode")).text = "EUR"
    
    # ═══════════════════════════════════════════════════════
    # 2. PARTIES
    # ═══════════════════════════════════════════════════════
    parties = ET.SubElement(root, _qn("Parties"))
    
    # --- SELLER PARTY (Emisor) ---
    seller_party = ET.SubElement(parties, _qn("SellerParty"))
    
    # TaxIdentification
    seller_tax_id = ET.SubElement(seller_party, _qn("TaxIdentification"))
    ET.SubElement(seller_tax_id, _qn("TaxIdentificationType")).text = "01"
    ET.SubElement(seller_tax_id, _qn("TaxIdentificationNumber")).text = _safe_str(
        company.get("company_tax_id") or company.get("tax_id"), "B00000000"
    ).upper()
    
    # LegalEntity
    seller_legal = ET.SubElement(seller_party, _qn("LegalEntity"))
    ET.SubElement(seller_legal, _qn("CorporateName")).text = _safe_str(
        company.get("company_name") or company.get("name"), "Empresa Emisora"
    )
    
    # Parsear dirección del emisor
    seller_full_address = _safe_str(company.get("company_address") or company.get("address"))
    seller_addr_text, seller_town, seller_province = _parse_address(seller_full_address)
    seller_postcode = _safe_str(company.get("post_code") or company.get("company_post_code"), "28001")
    
    seller_addr = ET.SubElement(seller_legal, _qn("AddressInSpain"))
    ET.SubElement(seller_addr, _qn("Address")).text = seller_addr_text or "Calle Principal 1"
    ET.SubElement(seller_addr, _qn("PostCode")).text = seller_postcode
    ET.SubElement(seller_addr, _qn("Town")).text = seller_town
    ET.SubElement(seller_addr, _qn("Province")).text = seller_province
    ET.SubElement(seller_addr, _qn("CountryCode")).text = "ESP"
    
    # --- BUYER PARTY (Receptor) ---
    buyer_party = ET.SubElement(parties, _qn("BuyerParty"))
    
    # TaxIdentification
    buyer_tax_id = ET.SubElement(buyer_party, _qn("TaxIdentification"))
    ET.SubElement(buyer_tax_id, _qn("TaxIdentificationType")).text = "01"
    ET.SubElement(buyer_tax_id, _qn("TaxIdentificationNumber")).text = _safe_str(
        client.get("tax_id"), "A00000000"
    ).upper()
    
    # LegalEntity
    buyer_legal = ET.SubElement(buyer_party, _qn("LegalEntity"))
    ET.SubElement(buyer_legal, _qn("CorporateName")).text = _safe_str(client.get("name"), "Cliente")
    
    # Parsear dirección del receptor
    buyer_full_address = _safe_str(client.get("address"))
    buyer_addr_text, buyer_town, buyer_province = _parse_address(buyer_full_address)
    buyer_postcode = _safe_str(client.get("post_code"), "28001")
    
    buyer_addr = ET.SubElement(buyer_legal, _qn("AddressInSpain"))
    ET.SubElement(buyer_addr, _qn("Address")).text = buyer_addr_text or "Calle Cliente 1"
    ET.SubElement(buyer_addr, _qn("PostCode")).text = buyer_postcode
    ET.SubElement(buyer_addr, _qn("Town")).text = buyer_town
    ET.SubElement(buyer_addr, _qn("Province")).text = buyer_province
    ET.SubElement(buyer_addr, _qn("CountryCode")).text = "ESP"
    
    # ═══════════════════════════════════════════════════════
    # 3. INVOICES
    # ═══════════════════════════════════════════════════════
    invoices = ET.SubElement(root, _qn("Invoices"))
    invoice_elem = ET.SubElement(invoices, _qn("Invoice"))
    
    # InvoiceNumber (directamente bajo Invoice)
    ET.SubElement(invoice_elem, _qn("InvoiceNumber")).text = inv_num
    
    # InvoiceHeader (solo InvoiceClass)
    invoice_header = ET.SubElement(invoice_elem, _qn("InvoiceHeader"))
    ET.SubElement(invoice_header, _qn("InvoiceClass")).text = "OR" if invoice.get("tipo") == "rectificativa" else "OO"
    
    # InvoiceIssueData
    invoice_issue = ET.SubElement(invoice_elem, _qn("InvoiceIssueData"))
    ET.SubElement(invoice_issue, _qn("IssueDate")).text = fecha
    ET.SubElement(invoice_issue, _qn("InvoiceCurrencyCode")).text = "EUR"
    ET.SubElement(invoice_issue, _qn("TaxCurrencyCode")).text = "EUR"
    ET.SubElement(invoice_issue, _qn("LanguageCode")).text = "es"
    
    # TaxesOutputs (IVA)
    taxes_outputs = ET.SubElement(invoice_elem, _qn("TaxesOutputs"))
    tax = ET.SubElement(taxes_outputs, _qn("Tax"))
    ET.SubElement(tax, _qn("TaxTypeCode")).text = "01"
    ET.SubElement(tax, _qn("TaxRate")).text = f"{vat_pct:.2f}"
    
    tx_base = ET.SubElement(tax, _qn("TaxableBase"))
    ET.SubElement(tx_base, _qn("TotalAmount")).text = f"{base_amt:.2f}"
    
    tx_amt = ET.SubElement(tax, _qn("TaxAmount"))
    ET.SubElement(tx_amt, _qn("TotalAmount")).text = f"{vat_amt:.2f}"
    
    # TaxesWithheld (IRPF) - solo si hay IRPF
    if irpf_pct > 0:
        taxes_withheld = ET.SubElement(invoice_elem, _qn("TaxesWithheld"))
        tax_w = ET.SubElement(taxes_withheld, _qn("Tax"))
        ET.SubElement(tax_w, _qn("TaxTypeCode")).text = "04"
        ET.SubElement(tax_w, _qn("TaxRate")).text = f"{irpf_pct:.2f}"
        
        tx_w_base = ET.SubElement(tax_w, _qn("TaxableBase"))
        ET.SubElement(tx_w_base, _qn("TotalAmount")).text = f"{base_amt:.2f}"
        
        tx_w_amt = ET.SubElement(tax_w, _qn("TaxAmount"))
        ET.SubElement(tx_w_amt, _qn("TotalAmount")).text = f"{irpf_amt:.2f}"
    
    # InvoiceTotals
    totals = ET.SubElement(invoice_elem, _qn("InvoiceTotals"))
    ET.SubElement(totals, _qn("TotalGrossAmount")).text = f"{base_amt:.2f}"
    ET.SubElement(totals, _qn("TotalGeneralDiscounts")).text = "0.00"
    ET.SubElement(totals, _qn("TotalGeneralSurcharges")).text = "0.00"
    ET.SubElement(totals, _qn("TotalGrossAmountBeforeTaxes")).text = f"{base_amt:.2f}"
    ET.SubElement(totals, _qn("TotalTaxOutputs")).text = f"{vat_amt:.2f}"
    
    if irpf_pct > 0:
        ET.SubElement(totals, _qn("TotalTaxesWithheld")).text = f"{irpf_amt:.2f}"
    
    ET.SubElement(totals, _qn("InvoiceTotal")).text = f"{total_factura:.2f}"
    ET.SubElement(totals, _qn("TotalOutstandingAmount")).text = f"{total_factura:.2f}"
    ET.SubElement(totals, _qn("TotalExecutableAmount")).text = f"{total_factura:.2f}"
    
    # Items
    items = ET.SubElement(invoice_elem, _qn("Items"))
    for linea in lineas:
        linea = linea or {}
        item = ET.SubElement(items, _qn("InvoiceLine"))
        ET.SubElement(item, _qn("ItemDescription")).text = _safe_str(linea.get("description"), "Servicio")
        ET.SubElement(item, _qn("Quantity")).text = f"{_safe_float(linea.get('quantity'), 1.0):.2f}"
        ET.SubElement(item, _qn("UnitPriceWithoutTax")).text = f"{_safe_float(linea.get('unit_price')):.2f}"
        
        line_base = _safe_float(linea.get("base_amount") or linea.get("total"))
        ET.SubElement(item, _qn("TotalCost")).text = f"{line_base:.2f}"
        ET.SubElement(item, _qn("GrossAmount")).text = f"{line_base:.2f}"
        
        # Impuestos por línea
        line_taxes = ET.SubElement(item, _qn("TaxesOutputs"))
        line_tax = ET.SubElement(line_taxes, _qn("Tax"))
        ET.SubElement(line_tax, _qn("TaxTypeCode")).text = "01"
        ET.SubElement(line_tax, _qn("TaxRate")).text = f"{vat_pct:.2f}"
        
        lt_base = ET.SubElement(line_tax, _qn("TaxableBase"))
        ET.SubElement(lt_base, _qn("TotalAmount")).text = f"{line_base:.2f}"
        
        lt_amt = ET.SubElement(line_tax, _qn("TaxAmount"))
        ET.SubElement(lt_amt, _qn("TotalAmount")).text = f"{(line_base * vat_pct / 100):.2f}"
    
    # PaymentDetails
    payment_details = ET.SubElement(invoice_elem, _qn("PaymentDetails"))
    installment = ET.SubElement(payment_details, _qn("Installment"))
    ET.SubElement(installment, _qn("InstallmentDueDate")).text = fecha
    ET.SubElement(installment, _qn("InstallmentAmount")).text = f"{total_factura:.2f}"
    ET.SubElement(installment, _qn("PaymentMethod")).text = "04"
    
    iban = _safe_str(company.get("company_iban")).replace(" ", "")
    if iban:
        account = ET.SubElement(installment, _qn("AccountToBeCredited"))
        ET.SubElement(account, _qn("IBAN")).text = iban

    # ═══════════════════════════════════════════════════════
    # Conversión a string
    # ═══════════════════════════════════════════════════════
    xml_bytes = ET.tostring(root, encoding="utf-8", method="xml")
    dom = minidom.parseString(xml_bytes)
    pretty_xml = "\n".join([line for line in dom.toprettyxml(indent="  ").split("\n") if line.strip()])
    
    # Validar
    if validar:
        es_valido, mensaje = validar_facturae_completo(pretty_xml)
        if not es_valido:
            st.error(f"### El XML no cumple con el esquema FacturaE v3.2.2\n\n{mensaje}")
            st.warning("Puede descargar el XML sin validar, pero no será válido oficialmente.")
        else:
            st.success("✅ XML validado correctamente contra el esquema oficial FacturaE v3.2.2")
    
    # Firmar
    if firmar:
        if certificado is None and password is None and user_id:
            certificado, password = obtener_certificado_usuario(user_id)
        if certificado and password:
            pretty_xml = firmar_facturae_xml(pretty_xml, certificado, password, usar_timestamp=usar_timestamp)
        else:
            st.warning("No se encontró certificado para firmar. El XML se generará sin firma.")
    
    return pretty_xml


def generar_facturae_xml_simplificada(invoice, client, company, lineas):
    """Genera XML FacturaE sin validación ni firma."""
    return generar_facturae_xml(invoice, client, company, lineas, firmar=False, validar=False)
