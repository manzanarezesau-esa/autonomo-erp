# facturae_validator.py
import streamlit as st
from lxml import etree
from schema_facturae import XSD_SCHEMA_TEXT

# Caché del esquema para no recargarlo cada vez
_xsd_cache = {}


def obtener_esquema_xsd():
    """
    Carga el esquema XSD desde el string embebido en schema_facturae.py.
    
    Retorna:
    - Objeto XMLSchema de lxml o None si no se pudo cargar
    """
    if "schema" in _xsd_cache:
        return _xsd_cache["schema"]
    
    try:
        # Parsear el XSD desde el string embebido
        schema_doc = etree.fromstring(XSD_SCHEMA_TEXT.encode('utf-8'))
        schema = etree.XMLSchema(schema_doc)
        
        # Guardar en caché
        _xsd_cache["schema"] = schema
        return schema
        
    except etree.XMLSchemaParseError as e:
        st.error(f"Error al parsear el esquema XSD embebido: {str(e)}")
        return None
    except Exception as e:
        st.error(f"Error inesperado al cargar el esquema XSD: {str(e)}")
        return None


def validar_xml_facturae(xml_str):
    """
    Valida un XML FacturaE contra el esquema XSD embebido v3.2.2.
    
    Parámetros:
    - xml_str: String del XML a validar
    
    Retorna:
    - Tupla (es_valido, lista_errores, lista_avisos)
    """
    schema = obtener_esquema_xsd()
    
    if schema is None:
        return False, ["No se pudo cargar el esquema XSD embebido."], []
    
    try:
        # Parsear el XML
        xml_doc = etree.fromstring(xml_str.encode('utf-8'))
        
        # Validar contra el esquema
        es_valido = schema.validate(xml_doc)
        
        # Obtener errores detallados
        errores = []
        avisos = []
        
        for error in schema.error_log:
            if error.level == etree.ErrorLevels.ERROR:
                errores.append(f"Línea {error.line}: {error.message}")
            elif error.level == etree.ErrorLevels.WARNING:
                avisos.append(f"Línea {error.line}: {error.message}")
        
        return es_valido, errores, avisos
        
    except etree.XMLSyntaxError as e:
        return False, [f"Error de sintaxis XML: {str(e)}"], []
    except Exception as e:
        return False, [f"Error inesperado durante la validación: {str(e)}"], []


def validacion_manual_rapida(xml_str):
    """
    Validación manual de campos obligatorios si el XSD no está disponible.
    
    Comprueba los campos mínimos requeridos por FacturaE v3.2.2.
    
    Retorna:
    - Lista de campos faltantes (vacía si todo correcto)
    """
    campos_faltantes = []
    
    try:
        xml_doc = etree.fromstring(xml_str.encode('utf-8'))
        
        # Namespace de FacturaE
        ns = "{http://www.facturae.gob.es/formato/Versiones/Facturaev3_2_2.xml}"
        
        # Campos obligatorios a comprobar
        campos_obligatorios = {
            "SchemaVersion": "Versión del esquema",
            "Modality": "Modalidad",
            "InvoiceIssuerType": "Tipo de emisor",
            "TaxIdentificationNumber": "NIF del emisor",
            "InvoiceNumber": "Número de factura",
            "IssueDate": "Fecha de expedición",
            "TotalGrossAmount": "Base imponible",
            "TotalTaxOutputs": "IVA repercutido",
            "InvoiceTotal": "Total de la factura",
        }
        
        for campo, descripcion in campos_obligatorios.items():
            elemento = xml_doc.find(f".//{ns}{campo}")
            if elemento is None or not elemento.text or not elemento.text.strip():
                campos_faltantes.append(f"{descripcion} ({campo})")
        
        return campos_faltantes
        
    except Exception as e:
        return [f"Error al parsear XML: {str(e)}"]


def validar_facturae_completo(xml_str):
    """
    Valida el XML FacturaE con XSD embebido y validación manual de respaldo.
    
    Parámetros:
    - xml_str: String del XML a validar
    
    Retorna:
    - (es_valido, mensaje_resultado)
    """
    # 1. Intentar validación con XSD embebido
    es_valido_xsd, errores_xsd, avisos_xsd = validar_xml_facturae(xml_str)
    
    if es_valido_xsd:
        return True, "✅ XML válido según el esquema oficial FacturaE v3.2.2"
    
    # 2. Si falló el XSD, hacer validación manual
    campos_faltantes = validacion_manual_rapida(xml_str)
    
    mensajes = []
    
    if errores_xsd:
        mensajes.append("**Errores de validación XSD:**")
        for error in errores_xsd[:10]:
            mensajes.append(f"  • {error}")
        if len(errores_xsd) > 10:
            mensajes.append(f"  • ... y {len(errores_xsd) - 10} errores más")
    
    if campos_faltantes:
        mensajes.append("**Campos obligatorios faltantes:**")
        for campo in campos_faltantes:
            mensajes.append(f"  • {campo}")
    
    if avisos_xsd:
        mensajes.append("**Advertencias:**")
        for aviso in avisos_xsd[:5]:
            mensajes.append(f"  • {aviso}")
    
    if not mensajes:
        mensajes.append("El XML no cumple con el esquema FacturaE v3.2.2")
    
    return False, "\n".join(mensajes)
