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

def _es_persona_juridica(nif):
    """
    Determina si un NIF es de persona jurídica (empresa) o física (autónomo).
    - Letras A, B, C, D, E, F, G, H, J, N, P, Q, R, S, U, V, W = Jurídica
    - Números o letras K, L, M, X, Y, Z = Física
    """
    nif = _safe_str(nif, "").upper().strip()
    if not nif:
        return True  # Por defecto, asumir jurídica
    
    primer_caracter = nif[0]
    
    if primer_caracter.isdigit():
        return False  # DNI/NIE = Física
    
    if primer_caracter in ['K', 'L', 'M', 'X', 'Y', 'Z']:
        return False  # NIE = Física
    
    return True  # CIF = Jurídica

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
            if "(" in town_candidate:
                town = town_candidate[:town_candidate.index("(")].strip()
            else:
                town = town_candidate
            town = town.title()
    
    return address[:100], town[:50], province[:50]

def _crear_party_tax_identification(parent, nif):
    """
    Crea el bloque TaxIdentification con PersonTypeCode y ResidenceTypeCode.
    Retorna True si es persona jurídica, False si es física.
    """
    tax_id = ET.SubElement(parent, _qn("TaxIdentification"))
    
    es_juridica = _es_persona_juridica(nif)
    person_type = "J" if es_juridica else "F"
    
    ET.SubElement(tax_id, _qn("PersonTypeCode")).text = person_type
    ET.SubElement(tax_id, _qn("ResidenceTypeCode")).text = "R"
    ET.SubElement(tax_id, _qn("TaxIdentificationNumber")).text = nif
    
    return es_juridica

def _crear_party_legal_entity(parent, name, address_str, es_juridica):
    """
    Crea LegalEntity (para empresas) o Individual (para autónomos).
    FirstSurname es OBLIGATORIO en Individual según XSD.
    """
    if es_juridica:
        # Empresa - LegalEntity con CorporateName
        legal = ET.SubElement(parent, _qn("LegalEntity"))
        ET.SubElement(legal, _qn("CorporateName")).text = name
        return legal
    else:
        # Autónomo - Individual con Name y FirstSurname (OBLIGATORIO)
        individual = ET.SubElement(parent, _qn("Individual"))
        
        # Intentar separar nombre y apellido
        name_parts = name.split()
        if len(name_parts) >= 3:
            first_name = " ".join(name_parts[:2])
            first_surname = " ".join(name_parts[2:])
        elif len(name_parts) == 2:
            first_name = name_parts[0]
            first_surname = name_parts[1]
        else:
            # Una sola palabra - usar el mismo valor para ambos
            first_name = name
            first_surname = name
        
        ET.SubElement(individual, _qn("Name")).text = first_name[:40]
        # FirstSurname SIEMPRE se incluye (obligatorio)
        ET.SubElement(individual, _qn("FirstSurname")).text = (first_surname or first_name)[:40]
        
        return individual

def _crear_address_in_spanish(parent, address_str, postcode, country="ESP"):
    """
    Crea el bloque AddressInSpain con los datos parseados.
    """
    addr_text, town, province = _parse_address(address_str)
    
    addr = ET.SubElement(parent, _qn("AddressInSpain"))
    ET.SubElement(addr, _qn("Address")).text = addr_text or "Calle Principal 1"
    ET.SubElement(addr, _qn("PostCode")).text = postcode or "28001"
    ET.SubElement(addr, _qn("Town")).text = town
    ET.SubElement(addr, _qn("Province")).text = province
    ET.SubElement(addr, _qn("CountryCode")).text = country
    
    return addr

def generar_facturae_xml(invoice, client, company, lineas, user_id=None, firmar=False, certificado=None, password=None, validar=True, usar_timestamp=True):
    """
    Genera XML FacturaE v3.2.2 con estructura XSD correcta.
    
    Estructura:
    - InvoiceHeader: InvoiceNumber + InvoiceDocumentType + InvoiceClass
    - TaxIdentification: PersonTypeCode + ResidenceTypeCode + TaxIdentificationNumber
    - Individual (autónomos) o LegalEntity (empresas)
    - FirstSurname OBLIGATORIO en Individual
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
    # ═══════════════════════════════════════════════════════
    file_header = ET.SubElement(root, _qn("FileHeader"))
    ET.SubElement(file_header, _qn("SchemaVersion")).text = "3.2.2"
    ET.SubElement(file_header, _qn("Modality")).text = "I"
    ET.SubElement(file_header, _qn("InvoiceIssuerType")).text = "EM"
    
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
    
    cif_emisor = _safe_str(company.get("company_tax_id") or company.get("tax_id"), "B00000000").upper()
    es_juridica_emisor = _crear_party_tax_identification(seller_party, cif_emisor)
    
    seller_name = _safe_str(company.get("company_name") or company.get("name"), "Empresa Emisora")
    seller_address = _safe_str(company.get("company_address") or company.get("address"))
    seller_postcode = _safe_str(company.get("post_code") or company.get("company_post_code"), "28001")
    
    seller_entity = _crear_party_legal_entity(seller_party, seller_name, seller_address, es_juridica_emisor)
    _crear_address_in_spanish(seller_entity, seller_address, seller_postcode)
    
    # --- BUYER PARTY (Receptor) ---
    buyer_party = ET.SubElement(parties, _qn("BuyerParty"))
    
    cif_receptor = _safe_str(client.get("tax_id"), "A00000000").upper()
    es_juridica_receptor = _crear_party_tax_identification(buyer_party, cif_receptor)
    
    buyer_name = _safe_str(client.get("name"), "Cliente")
    buyer_address = _safe_str(client.get("address"))
    buyer_postcode = _safe_str(client.get("post_code"), "28001")
    
    buyer_entity = _crear_party_legal_entity(buyer_party, buyer_name, buyer_address, es_juridica_receptor)
    _crear_address_in_spanish(buyer_entity, buyer_address, buyer_postcode)
    
    # ═══════════════════════════════════════════════════════
    # 3. INVOICES
    # ═══════════════════════════════════════════════════════
    invoices = ET.SubElement(root, _qn("Invoices"))
    invoice_elem = ET.SubElement(invoices, _qn("Invoice"))
    
    # InvoiceHeader - InvoiceNumber DENTRO de InvoiceHeader
    invoice_header = ET.SubElement(invoice_elem, _qn("InvoiceHeader"))
    ET.SubElement(invoice_header, _qn("InvoiceNumber")).text = inv_num
    ET.SubElement(invoice_header, _qn("InvoiceDocumentType")).text = "FC"
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

    # Conversión a string
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
