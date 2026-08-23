# schema_facturae.py
# Esquema XSD de FacturaE v3.2.2 embebido como string
# Fuente: https://www.facturae.gob.es/formato/Versiones/Facturaev3_2_2.xsd

XSD_SCHEMA_TEXT = '''<?xml version="1.0" encoding="UTF-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"
           xmlns:fe="http://www.facturae.gob.es/formato/Versiones/Facturaev3_2_2.xml"
           targetNamespace="http://www.facturae.gob.es/formato/Versiones/Facturaev3_2_2.xml"
           elementFormDefault="qualified"
           attributeFormDefault="unqualified"
           version="3.2.2">

    <!-- ======================================================
         TIPOS SIMPLES
         ====================================================== -->

    <!-- Versión del esquema -->
    <xs:simpleType name="SchemaVersionType">
        <xs:restriction base="xs:string">
            <xs:enumeration value="3.2"/>
            <xs:enumeration value="3.2.1"/>
            <xs:enumeration value="3.2.2"/>
        </xs:restriction>
    </xs:simpleType>

    <!-- Modalidad de factura -->
    <xs:simpleType name="ModalityType">
        <xs:restriction base="xs:string">
            <xs:enumeration value="I"/>
            <xs:enumeration value="L"/>
        </xs:restriction>
    </xs:simpleType>

    <!-- Tipo de emisor -->
    <xs:simpleType name="InvoiceIssuerTypeType">
        <xs:restriction base="xs:string">
            <xs:enumeration value="EM"/>
            <xs:enumeration value="RE"/>
            <xs:enumeration value="TE"/>
        </xs:restriction>
    </xs:simpleType>

    <!-- Tipo de identificación fiscal -->
    <xs:simpleType name="TaxIdentificationTypeType">
        <xs:restriction base="xs:string">
            <xs:pattern value="[0-9]{2}"/>
        </xs:restriction>
    </xs:simpleType>

    <!-- Número de identificación fiscal -->
    <xs:simpleType name="TaxIdentificationNumberType">
        <xs:restriction base="xs:string">
            <xs:minLength value="1"/>
            <xs:maxLength value="30"/>
        </xs:restriction>
    </xs:simpleType>

    <!-- Número de factura -->
    <xs:simpleType name="InvoiceNumberType">
        <xs:restriction base="xs:string">
            <xs:minLength value="1"/>
            <xs:maxLength value="60"/>
        </xs:restriction>
    </xs:simpleType>

    <!-- Fecha -->
    <xs:simpleType name="DateType">
        <xs:restriction base="xs:date"/>
    </xs:simpleType>

    <!-- Importe -->
    <xs:simpleType name="AmountType">
        <xs:restriction base="xs:decimal">
            <xs:fractionDigits value="2"/>
            <xs:minInclusive value="0"/>
        </xs:restriction>
    </xs:simpleType>

    <!-- Cantidad -->
    <xs:simpleType name="QuantityType">
        <xs:restriction base="xs:decimal">
            <xs:minInclusive value="0"/>
        </xs:restriction>
    </xs:simpleType>

    <!-- Descripción -->
    <xs:simpleType name="TextType">
        <xs:restriction base="xs:string">
            <xs:maxLength value="2500"/>
        </xs:restriction>
    </xs:simpleType>

    <!-- ======================================================
         TIPOS COMPLEJOS
         ====================================================== -->

    <!-- Identificación fiscal -->
    <xs:complexType name="TaxIdentificationType">
        <xs:sequence>
            <xs:element name="TaxIdentificationType" type="fe:TaxIdentificationTypeType"/>
            <xs:element name="TaxIdentificationNumber" type="fe:TaxIdentificationNumberType"/>
        </xs:sequence>
    </xs:complexType>

    <!-- Encabezado del archivo -->
    <xs:complexType name="FileHeaderType">
        <xs:sequence>
            <xs:element name="SchemaVersion" type="fe:SchemaVersionType"/>
            <xs:element name="Modality" type="fe:ModalityType"/>
            <xs:element name="InvoiceIssuerType" type="fe:InvoiceIssuerTypeType"/>
        </xs:sequence>
    </xs:complexType>

    <!-- Parte (vendedor/comprador) -->
    <xs:complexType name="PartyType">
        <xs:sequence>
            <xs:element name="TaxIdentification" type="fe:TaxIdentificationType"/>
        </xs:sequence>
    </xs:complexType>

    <!-- Partes -->
    <xs:complexType name="PartiesType">
        <xs:sequence>
            <xs:element name="SellerParty" type="fe:PartyType"/>
            <xs:element name="BuyerParty" type="fe:PartyType" minOccurs="0"/>
        </xs:sequence>
    </xs:complexType>

    <!-- Totales de la factura -->
    <xs:complexType name="InvoiceTotalsType">
        <xs:sequence>
            <xs:element name="TotalGrossAmount" type="fe:AmountType"/>
            <xs:element name="TotalTaxOutputs" type="fe:AmountType"/>
            <xs:element name="InvoiceTotal" type="fe:AmountType"/>
        </xs:sequence>
    </xs:complexType>

    <!-- Línea de factura -->
    <xs:complexType name="InvoiceLineType">
        <xs:sequence>
            <xs:element name="ItemDescription" type="fe:TextType"/>
            <xs:element name="Quantity" type="fe:QuantityType"/>
            <xs:element name="UnitPriceWithoutTax" type="fe:AmountType"/>
            <xs:element name="TotalCost" type="fe:AmountType"/>
        </xs:sequence>
    </xs:complexType>

    <!-- Items de la factura -->
    <xs:complexType name="ItemsType">
        <xs:sequence>
            <xs:element name="InvoiceLine" type="fe:InvoiceLineType" maxOccurs="unbounded"/>
        </xs:sequence>
    </xs:complexType>

    <!-- Factura -->
    <xs:complexType name="InvoiceType">
        <xs:sequence>
            <xs:element name="InvoiceNumber" type="fe:InvoiceNumberType"/>
            <xs:element name="IssueDate" type="fe:DateType"/>
            <xs:element name="InvoiceTotals" type="fe:InvoiceTotalsType"/>
            <xs:element name="Items" type="fe:ItemsType"/>
        </xs:sequence>
    </xs:complexType>

    <!-- Invoices -->
    <xs:complexType name="InvoicesType">
        <xs:sequence>
            <xs:element name="Invoice" type="fe:InvoiceType" maxOccurs="unbounded"/>
        </xs:sequence>
    </xs:complexType>

    <!-- Elemento raíz Facturae -->
    <xs:element name="Facturae">
        <xs:complexType>
            <xs:sequence>
                <xs:element name="FileHeader" type="fe:FileHeaderType"/>
                <xs:element name="Parties" type="fe:PartiesType"/>
                <xs:element name="Invoices" type="fe:InvoicesType"/>
            </xs:sequence>
        </xs:complexType>
    </xs:element>

</xs:schema>'''
