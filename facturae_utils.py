# facturae_utils.py
import xml.etree.ElementTree as ET
from xml.dom import minidom
import streamlit as st
from firma_xades import firmar_facturae_xml
from facturae_validator import validar_facturae_completo
from certificate_manager import obtener_certificado_usuario


def generar_facturae_xml(invoice, client, company, lineas, user_id=None, firmar=False, certificado=None, password=None, validar=True, usar_timestamp=True):
    """
    Genera un XML compatible con FacturaE v3.2.2.
    Opcionalmente valida y firma con XAdES-EPES o XAdES-T.
    
    Parámetros:
    - invoice: Diccionario con datos de la factura
    - client: Diccionario con datos del cliente
    - company: Diccionario con datos de la empresa emisora
    - lineas: Lista de líneas de factura
    - user_id: ID del usuario (para obtener su certificado automáticamente)
    - firmar: Boolean para firmar o no
    - certificado: Bytes del certificado P12 (opcional si user_id proporcionado)
    - password: Contraseña del certificado (opcional si user_id proporcionado)
    - validar: Boolean para validar contra XSD antes de firmar
    - usar_timestamp: Boolean para añadir timestamp XAdES-T
    
    Retorna:
    - XML generado (firmado si se solicita) como string
    """
    ns = "http://www.facturae.gob.es/formato/Versiones/Facturaev3_2_2.xml"
    
    # Crear elemento raíz con namespace
    root = ET.Element("fe:Facturae", {"xmlns:fe": ns})
    
    # =====================================================
    # FileHeader
    # =====================================================
    file_header = ET.SubElement(root, "fe:FileHeader")
    schema_version = ET.SubElement(file_header, "fe:SchemaVersion")
    schema_version.text = "3.2.2"
    modality = ET.SubElement(file_header, "fe:Modality")
    modality.text = "I"
    invoice_issuer_type = ET.SubElement(file_header, "fe:InvoiceIssuerType")
    invoice_issuer_type.text = "EM"
    
    # Batch (opcional)
    batch = ET.SubElement(file_header, "fe:Batch")
    batch_identifier = ET.SubElement(batch, "fe:BatchIdentifier")
    batch_identifier.text = invoice.get("invoice_number", "F0001")
    invoices_count = ET.SubElement(batch, "fe:InvoicesCount")
    invoices_count.text = "1"
    
    # =====================================================
    # Parties - SellerParty (Emisor)
    # =====================================================
    parties = ET.SubElement(root, "fe:Parties")
    
    seller_party = ET.SubElement(parties, "fe:SellerParty")
    
    # TaxIdentification del vendedor
    seller_tax_id = ET.SubElement(seller_party, "fe:TaxIdentification")
    seller_tax_type = ET.SubElement(seller_tax_id, "fe:TaxIdentificationType")
    seller_tax_type.text = "01"  # 01 = NIF, 02 = CIF, 03 = NIE
    seller_tax_number = ET.SubElement(seller_tax_id, "fe:TaxIdentificationNumber")
    seller_tax_number.text = (company.get("company_tax_id", "") or "").strip().upper()
    
    # LegalEntity del vendedor
    seller_legal = ET.SubElement(seller_party, "fe:LegalEntity")
    seller_name = ET.SubElement(seller_legal, "fe:CorporateName")
    seller_name.text = company.get("company_name", "")
    
    seller_address = ET.SubElement(seller_legal, "fe:Address")
    seller_addr = ET.SubElement(seller_address, "fe:Address")
    seller_addr.text = company.get("company_address", "")
    seller_postcode = ET.SubElement(seller_address, "fe:PostCode")
    seller_postcode.text = "28001"
    seller_town = ET.SubElement(seller_address, "fe:Town")
    seller_town.text = "Madrid"
    seller_province = ET.SubElement(seller_address, "fe:Province")
    seller_province.text = "Madrid"
    seller_country = ET.SubElement(seller_address, "fe:CountryCode")
    seller_country.text = "ESP"
    
    # Contacto del vendedor
    if company.get("company_phone") or company.get("company_email"):
        seller_contact = ET.SubElement(seller_party, "fe:ContactDetails")
        if company.get("company_phone"):
            seller_phone = ET.SubElement(seller_contact, "fe:Telephone")
            seller_phone.text = company.get("company_phone", "")
        if company.get("company_email"):
            seller_email = ET.SubElement(seller_contact, "fe:ElectronicMail")
            seller_email.text = company.get("company_email", "")
    
    # =====================================================
    # Parties - BuyerParty (Cliente)
    # =====================================================
    buyer_party = ET.SubElement(parties, "fe:BuyerParty")
    
    # TaxIdentification del comprador
    buyer_tax_id = ET.SubElement(buyer_party, "fe:TaxIdentification")
    buyer_tax_type = ET.SubElement(buyer_tax_id, "fe:TaxIdentificationType")
    buyer_tax_type.text = "01"
    buyer_tax_number = ET.SubElement(buyer_tax_id, "fe:TaxIdentificationNumber")
    buyer_tax_number.text = (client.get("tax_id", "") or "").strip().upper()
    
    # LegalEntity del comprador
    buyer_legal = ET.SubElement(buyer_party, "fe:LegalEntity")
    buyer_name = ET.SubElement(buyer_legal, "fe:CorporateName")
    buyer_name.text = client.get("name", "")
    
    buyer_address = ET.SubElement(buyer_legal, "fe:Address")
    buyer_addr = ET.SubElement(buyer_address, "fe:Address")
    buyer_addr.text = client.get("address", "")
    buyer_postcode = ET.SubElement(buyer_address, "fe:PostCode")
    buyer_postcode.text = "28001"
    buyer_town = ET.SubElement(buyer_address, "fe:Town")
    buyer_town.text = "Madrid"
    buyer_province = ET.SubElement(buyer_address, "fe:Province")
    buyer_province.text = "Madrid"
    buyer_country = ET.SubElement(buyer_address, "fe:CountryCode")
    buyer_country.text = "ESP"
    
    # =====================================================
    # Invoices
    # =====================================================
    invoices = ET.SubElement(root, "fe:Invoices")
    invoice_elem = ET.SubElement(invoices, "fe:Invoice")
    
    # InvoiceHeader
    invoice_header = ET.SubElement(invoice_elem, "fe:InvoiceHeader")
    invoice_number = ET.SubElement(invoice_header, "fe:InvoiceNumber")
    invoice_number.text = invoice.get("invoice_number", "")
    
    # InvoiceClass (OO = Original, OR = Rectificativa)
    invoice_class = ET.SubElement(invoice_header, "fe:InvoiceClass")
    if invoice.get("tipo") == "rectificativa":
        invoice_class.text = "OR"
    else:
        invoice_class.text = "OO"
    
    # InvoiceIssueData
    invoice_issue = ET.SubElement(invoice_elem, "fe:InvoiceIssueData")
    issue_date = ET.SubElement(invoice_issue, "fe:IssueDate")
    issue_date.text = invoice.get("date", "")
    
    operation_date = ET.SubElement(invoice_issue, "fe:OperationDate")
    operation_date.text = invoice.get("date", "")
    
    # PlaceOfIssue (opcional)
    place_issue = ET.SubElement(invoice_issue, "fe:PlaceOfIssue")
    place_issue.text = "Madrid"
    
    # =====================================================
    # TaxesOutputs (Impuestos repercutidos)
    # =====================================================
    taxes_outputs = ET.SubElement(invoice_elem, "fe:TaxesOutputs")
    
    # IVA
    iva_tax = ET.SubElement(taxes_outputs, "fe:Tax")
    iva_type = ET.SubElement(iva_tax, "fe:TaxTypeCode")
    iva_type.text = "01"  # 01 = IVA
    iva_rate = ET.SubElement(iva_tax, "fe:TaxRate")
    iva_rate.text = f"{invoice.get('vat_percentage', 21):.2f}"
    iva_base = ET.SubElement(iva_tax, "fe:TaxableBase")
    iva_base.text = f"{invoice.get('base_amount', 0):.2f}"
    iva_amount = ET.SubElement(iva_tax, "fe:TaxAmount")
    iva_amount.text = f"{invoice.get('vat_amount', 0):.2f}"
    
    # IRPF (si existe)
    if invoice.get("irpf_percentage", 0) > 0:
        irpf_tax = ET.SubElement(taxes_outputs, "fe:Tax")
        irpf_type = ET.SubElement(irpf_tax, "fe:TaxTypeCode")
        irpf_type.text = "04"  # 04 = IRPF
        irpf_rate = ET.SubElement(irpf_tax, "fe:TaxRate")
        irpf_rate.text = f"{invoice.get('irpf_percentage', 0):.2f}"
        irpf_base = ET.SubElement(irpf_tax, "fe:TaxableBase")
        irpf_base.text = f"{invoice.get('base_amount', 0):.2f}"
        irpf_amount = ET.SubElement(irpf_tax, "fe:TaxAmount")
        irpf_amount.text = f"{invoice.get('irpf_amount', 0):.2f}"
    
    # =====================================================
    # InvoiceTotals
    # =====================================================
    totals = ET.SubElement(invoice_elem, "fe:InvoiceTotals")
    
    total_gross = ET.SubElement(totals, "fe:TotalGrossAmount")
    total_gross.text = f"{invoice.get('base_amount', 0):.2f}"
    
    # TotalGeneralDiscounts (si hay descuentos, aquí 0)
    total_discounts = ET.SubElement(totals, "fe:TotalGeneralDiscounts")
    total_discounts.text = "0.00"
    
    # TotalTaxOutputs (suma de impuestos repercutidos)
    total_tax_outputs = ET.SubElement(totals, "fe:TotalTaxOutputs")
    vat_total = invoice.get('vat_amount', 0)
    irpf_total = invoice.get('irpf_amount', 0) if invoice.get('irpf_percentage', 0) > 0 else 0
    total_tax_outputs.text = f"{vat_total:.2f}"
    
    # InvoiceTotal
    invoice_total = ET.SubElement(totals, "fe:InvoiceTotal")
    invoice_total.text = f"{invoice.get('total', 0):.2f}"
    
    # =====================================================
    # Items (Líneas de factura)
    # =====================================================
    items = ET.SubElement(invoice_elem, "fe:Items")
    
    for linea in lineas:
        item = ET.SubElement(items, "fe:InvoiceLine")
        
        # ItemDescription
        item_desc = ET.SubElement(item, "fe:ItemDescription")
        item_desc.text = linea.get("description", "")
        
        # Quantity
        quantity = ET.SubElement(item, "fe:Quantity")
        quantity.text = str(linea.get("quantity", 1))
        
        # UnitPriceWithoutTax
        unit_price = ET.SubElement(item, "fe:UnitPriceWithoutTax")
        unit_price.text = f"{linea.get('unit_price', 0):.2f}"
        
        # TotalCost
        total_cost = ET.SubElement(item, "fe:TotalCost")
        total_cost.text = f"{linea.get('base_amount', linea.get('total', 0)):.2f}"
        
        # GrossAmount (Base imponible de la línea)
        gross_amount = ET.SubElement(item, "fe:GrossAmount")
        gross_amount.text = f"{linea.get('base_amount', 0):.2f}"
    
    # =====================================================
    # PaymentDetails (opcional pero recomendado)
    # =====================================================
    payment_details = ET.SubElement(invoice_elem, "fe:PaymentDetails")
    installment = ET.SubElement(payment_details, "fe:Installment")
    installment_duedate = ET.SubElement(installment, "fe:InstallmentDueDate")
    installment_duedate.text = invoice.get("date", "")
    installment_amount = ET.SubElement(installment, "fe:InstallmentAmount")
    installment_amount.text = f"{invoice.get('total', 0):.2f}"
    
    payment_method = ET.SubElement(installment, "fe:PaymentMethod")
    payment_method.text = "04"  # 04 = Transferencia
    
    # IBAN si existe
    if company.get("company_iban"):
        account = ET.SubElement(installment, "fe:AccountToBeCredited")
        iban_code = ET.SubElement(account, "fe:IBAN")
        iban_code.text = company.get("company_iban", "").replace(" ", "")
    
    # =====================================================
    # Convertir a string con formato
    # =====================================================
    xml_str = ET.tostring(root, encoding='utf-8', method='xml')
    dom = minidom.parseString(xml_str)
    pretty_xml = dom.toprettyxml(indent="  ")
    
    # Validar contra XSD si se solicita
    if validar:
        es_valido, mensaje = validar_facturae_completo(pretty_xml)
        
        if not es_valido:
            st.error(f"### El XML no cumple con el esquema FacturaE v3.2.2\n\n{mensaje}")
            st.warning("Puede descargar el XML sin validar, pero no será válido oficialmente.")
        else:
            st.success("✅ XML validado correctamente contra el esquema oficial FacturaE v3.2.2")
    
    # Firmar si se solicita
    if firmar:
        # Si no se proporcionó certificado directamente, obtener del usuario
        if certificado is None and password is None and user_id:
            certificado, password = obtener_certificado_usuario(user_id)
        
        if certificado and password:
            pretty_xml = firmar_facturae_xml(
                pretty_xml,
                certificado,
                password,
                usar_timestamp=usar_timestamp
            )
        else:
            st.warning("No se encontró certificado para firmar. El XML se generará sin firma.")
    
    return pretty_xml


def generar_facturae_xml_simplificada(invoice, client, company, lineas):
    """
    Genera un XML FacturaE simplificado (sin datos de dirección completos).
    Útil para facturas simplificadas.
    """
    # Para facturas simplificadas, se puede reutilizar la función principal
    # pero con datos mínimos
    return generar_facturae_xml(
        invoice, client, company, lineas,
        firmar=False, validar=False
    )
