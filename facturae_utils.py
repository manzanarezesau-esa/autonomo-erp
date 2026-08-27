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
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default

def _safe_str(val, default=""):
    if val is None:
        return default
    return str(val).strip()

def generar_facturae_xml(invoice, client, company, lineas, user_id=None, firmar=False, certificado=None, password=None, validar=True, usar_timestamp=True):
    """
    Genera un XML estricto compatible con FacturaE v3.2.2.
    
    SECUENCIA EXACTA SEGÚN XSD OFICIAL:
    
    Facturae
    ├── FileHeader
    │   ├── SchemaVersion
    │   ├── Modality
    │   ├── InvoiceIssuerType
    │   └── Batch
    │       ├── BatchIdentifier
    │       ├── InvoicesCount
    │       ├── TotalInvoicesAmount
    │       │   └── TotalAmount
    │       ├── TotalOutstandingAmount
    │       │   └── TotalAmount
    │       ├── TotalExecutableAmount
    │       │   └── TotalAmount
    │       └── InvoiceCurrencyCode
    ├── Parties
    │   ├── SellerParty
    │   │   ├── TaxIdentification
    │   │   │   ├── TaxIdentificationType  ← OJO: NO PersonTypeCode
    │   │   │   └── TaxIdentificationNumber
    │   │   └── LegalEntity (o Individual)
    │   │       ├── CorporateName
    │   │       └── AddressInSpain
    │   │           ├── Address
    │   │           ├── PostCode
    │   │           ├── Town
    │   │           ├── Province
    │   │           └── CountryCode
    │   └── BuyerParty
    │       ├── TaxIdentification
    │       │   ├── TaxIdentificationType
    │       │   └── TaxIdentificationNumber
    │       └── LegalEntity (o Individual)
    │           ├── CorporateName
    │           └── AddressInSpain
    │               ├── Address
    │               ├── PostCode
    │               ├── Town
    │               ├── Province
    │               └── CountryCode
    └── Invoices
        └── Invoice
            ├── InvoiceNumber          ← DIRECTAMENTE bajo Invoice
            ├── InvoiceHeader          ← DESPUÉS de InvoiceNumber
            │   └── InvoiceClass
            ├── InvoiceIssueData
            │   ├── IssueDate
            │   ├── InvoiceCurrencyCode
            │   ├── TaxCurrencyCode
            │   └── LanguageCode
            ├── TaxesOutputs
            │   └── Tax
            │       ├── TaxTypeCode
            │       ├── TaxRate
            │       ├── TaxableBase
            │       │   └── TotalAmount
            │       └── TaxAmount
            │           └── TotalAmount
            ├── TaxesWithheld (si IRPF > 0)
            │   └── Tax
            │       ├── TaxTypeCode
            │       ├── TaxRate
            │       ├── TaxableBase
            │       │   └── TotalAmount
            │       └── TaxAmount
            │           └── TotalAmount
            ├── InvoiceTotals
            │   ├── TotalGrossAmount
            │   ├── TotalGeneralDiscounts
            │   ├── TotalGeneralSurcharges
            │   ├── TotalGrossAmountBeforeTaxes
            │   ├── TotalTaxOutputs
            │   ├── TotalTaxesWithheld (si IRPF)
            │   ├── InvoiceTotal
            │   ├── TotalOutstandingAmount
            │   └── TotalExecutableAmount
            ├── Items
            │   └── InvoiceLine
            │       ├── ItemDescription
            │       ├── Quantity
            │       ├── UnitPriceWithoutTax
            │       ├── TotalCost
            │       ├── GrossAmount
            │       └── TaxesOutputs
            │           └── Tax
            │               ├── TaxTypeCode
            │               ├── TaxRate
            │               ├── TaxableBase
            │               │   └── TotalAmount
            │               └── TaxAmount
            │                   └── TotalAmount
            └── PaymentDetails
                └── Installment
                    ├── InstallmentDueDate
                    ├── InstallmentAmount
                    ├── PaymentMethod
                    └── AccountToBeCredited (si IBAN)
                        └── IBAN
    """
    invoice = invoice or {}
    client = client or {}
    company = company or {}
    lineas = lineas or []

    root = ET.Element(_qn("Facturae"))
    
    # =====================================================
    # 1. FileHeader
    # =====================================================
    file_header = ET.SubElement(root, _qn("FileHeader"))
    ET.SubElement(file_header, _qn("SchemaVersion")).text = "3.2.2"
    ET.SubElement(file_header, _qn("Modality")).text = "I"
    ET.SubElement(file_header, _qn("InvoiceIssuerType")).text = "EM"
    
    total_factura = _safe_float(invoice.get("total"))
    inv_num = _safe_str(invoice.get("invoice_number"), "FAC-001")
    
    # Batch
    batch = ET.SubElement(file_header, _qn("Batch"))
    ET.SubElement(batch, _qn("BatchIdentifier")).text = inv_num
    ET.SubElement(batch, _qn("InvoicesCount")).text = "1"
    
    tot_inv_amt = ET.SubElement(batch, _qn("TotalInvoicesAmount"))
    ET.SubElement(tot_inv_amt, _qn("TotalAmount")).text = f"{total_factura:.2f}"
    
    tot_out_amt = ET.SubElement(batch, _qn("TotalOutstandingAmount"))
    ET.SubElement(tot_out_amt, _qn("TotalAmount")).text = f"{total_factura:.2f}"
    
    tot_exe_amt = ET.SubElement(batch, _qn("TotalExecutableAmount"))
    ET.SubElement(tot_exe_amt, _qn("TotalAmount")).text = f"{total_factura:.2f}"
    
    ET.SubElement(batch, _qn("InvoiceCurrencyCode")).text = "EUR"
    
    # =====================================================
    # 2. Parties
    # =====================================================
    parties = ET.SubElement(root, _qn("Parties"))
    
    # --- EMISOR (SellerParty) ---
    seller_party = ET.SubElement(parties, _qn("SellerParty"))
    
    # TaxIdentification - Estructura CORRECTA según XSD
    seller_tax = ET.SubElement(seller_party, _qn("TaxIdentification"))
    ET.SubElement(seller_tax, _qn("TaxIdentificationType")).text = "01"  # 01 = NIF
    ET.SubElement(seller_tax, _qn("TaxIdentificationNumber")).text = _safe_str(company.get("company_tax_id") or company.get("tax_id"), "B00000000").upper()
    
    # LegalEntity
    seller_legal = ET.SubElement(seller_party, _qn("LegalEntity"))
    ET.SubElement(seller_legal, _qn("CorporateName")).text = _safe_str(company.get("company_name") or company.get("name"), "Empresa Emisora")
    
    seller_addr = ET.SubElement(seller_legal, _qn("AddressInSpain"))
    ET.SubElement(seller_addr, _qn("Address")).text = _safe_str(company.get("company_address") or company.get("address"), "Calle Principal 1")
    ET.SubElement(seller_addr, _qn("PostCode")).text = "28001"
    ET.SubElement(seller_addr, _qn("Town")).text = "Madrid"
    ET.SubElement(seller_addr, _qn("Province")).text = "Madrid"
    ET.SubElement(seller_addr, _qn("CountryCode")).text = "ESP"
    
    # --- RECEPTOR (BuyerParty) ---
    buyer_party = ET.SubElement(parties, _qn("BuyerParty"))
    
    # TaxIdentification - Estructura CORRECTA según XSD
    buyer_tax = ET.SubElement(buyer_party, _qn("TaxIdentification"))
    ET.SubElement(buyer_tax, _qn("TaxIdentificationType")).text = "01"
    ET.SubElement(buyer_tax, _qn("TaxIdentificationNumber")).text = _safe_str(client.get("tax_id"), "A00000000").upper()
    
    # LegalEntity
    buyer_legal = ET.SubElement(buyer_party, _qn("LegalEntity"))
    ET.SubElement(buyer_legal, _qn("CorporateName")).text = _safe_str(client.get("name"), "Cliente")
    
    buyer_addr = ET.SubElement(buyer_legal, _qn("AddressInSpain"))
    ET.SubElement(buyer_addr, _qn("Address")).text = _safe_str(client.get("address"), "Calle Cliente 1")
    ET.SubElement(buyer_addr, _qn("PostCode")).text = "28001"
    ET.SubElement(buyer_addr, _qn("Town")).text = "Madrid"
    ET.SubElement(buyer_addr, _qn("Province")).text = "Madrid"
    ET.SubElement(buyer_addr, _qn("CountryCode")).text = "ESP"
    
    # =====================================================
    # 3. Invoices
    # =====================================================
    invoices = ET.SubElement(root, _qn("Invoices"))
    invoice_elem = ET.SubElement(invoices, _qn("Invoice"))
    
    # InvoiceNumber - DIRECTAMENTE bajo Invoice (PRIMERO)
    ET.SubElement(invoice_elem, _qn("InvoiceNumber")).text = inv_num
    
    # InvoiceHeader - DESPUÉS de InvoiceNumber
    invoice_header = ET.SubElement(invoice_elem, _qn("InvoiceHeader"))
    ET.SubElement(invoice_header, _qn("InvoiceClass")).text = "OR" if invoice.get("tipo") == "rectificativa" else "OO"
    
    # InvoiceIssueData
    invoice_issue = ET.SubElement(invoice_elem, _qn("InvoiceIssueData"))
    ET.SubElement(invoice_issue, _qn("IssueDate")).text = _safe_str(invoice.get("date"), "2026-01-01")
    ET.SubElement(invoice_issue, _qn("InvoiceCurrencyCode")).text = "EUR"
    ET.SubElement(invoice_issue, _qn("TaxCurrencyCode")).text = "EUR"
    ET.SubElement(invoice_issue, _qn("LanguageCode")).text = "es"
    
    base_amt = _safe_float(invoice.get("base_amount"))
    vat_pct = _safe_float(invoice.get("vat_percentage"), 21.0)
    vat_amt = _safe_float(invoice.get("vat_amount"))
    irpf_pct = _safe_float(invoice.get("irpf_percentage"))
    irpf_amt = _safe_float(invoice.get("irpf_amount"))
    
    # TaxesOutputs (IVA)
    taxes_outputs = ET.SubElement(invoice_elem, _qn("TaxesOutputs"))
    tax = ET.SubElement(taxes_outputs, _qn("Tax"))
    ET.SubElement(tax, _qn("TaxTypeCode")).text = "01"
    ET.SubElement(tax, _qn("TaxRate")).text = f"{vat_pct:.2f}"
    
    tx_base = ET.SubElement(tax, _qn("TaxableBase"))
    ET.SubElement(tx_base, _qn("TotalAmount")).text = f"{base_amt:.2f}"
    
    tx_amt = ET.SubElement(tax, _qn("TaxAmount"))
    ET.SubElement(tx_amt, _qn("TotalAmount")).text = f"{vat_amt:.2f}"
    
    # TaxesWithheld (IRPF)
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
    ET.SubElement(installment, _qn("InstallmentDueDate")).text = _safe_str(invoice.get("date"), "2026-01-01")
    ET.SubElement(installment, _qn("InstallmentAmount")).text = f"{total_factura:.2f}"
    ET.SubElement(installment, _qn("PaymentMethod")).text = "04"
    
    iban = _safe_str(company.get("company_iban")).replace(" ", "")
    if iban:
        account = ET.SubElement(installment, _qn("AccountToBeCredited"))
        ET.SubElement(account, _qn("IBAN")).text = iban

    # =====================================================
    # Conversión a string
    # =====================================================
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
    return generar_facturae_xml(invoice, client, company, lineas, firmar=False, validar=False)
