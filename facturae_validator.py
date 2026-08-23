# facturae_validator.py
import streamlit as st
from lxml import etree
import os
import requests
import tempfile

# URL del esquema XSD oficial de FacturaE v3.2.2
XSD_URL = "https://www.facturae.gob.es/formato/Versiones/Facturaev3_2_2.xsd"

# Caché del esquema para no descargarlo cada vez
_xsd_cache = {}


def obtener_esquema_xsd():
    """
    Descarga y cachea el esquema XSD oficial de FacturaE v3.2.2.
    
    Retorna:
    - Objeto XMLSchema de lxml o None si no se pudo descargar
    """
    if "schema" in _xsd_cache:
        return _xsd_cache["schema"]
    
    try:
        # Intentar descargar el XSD
        response = requests.get(XSD_URL, timeout=30)
        if response.status_code == 200:
            xsd_content = response.content
            
            # Guardar temporalmente para lxml
            with tempfile.NamedTemporaryFile(suffix=".xsd", delete=False) as temp_file:
                temp_file.write(xsd_content)
                temp_path = temp_file.name
            
            try:
                # Crear schema desde el archivo temporal
                with open(temp_path, 'rb') as f:
                    schema_doc = etree.parse(f)
                schema = etree.XMLSchema(schema_doc)
                
                # Guardar en caché
                _xsd_cache["schema"] = schema
                return schema
            finally:
                # Limpiar archivo temporal
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
        else:
            st.warning(f"No se pudo descargar el esquema XSD (HTTP {response.status_code})")
            return None
    except Exception as e:
        st.warning(f"Error al descargar el esquema XSD: {str(e)}")
        return None


def validar_xml_facturae(xml_str):
    """
    Valida un XML FacturaE contra el esquema XSD oficial v3.2.2.
    
    Parámetros:
    - xml_str: String del XML a validar
    
    Retorna:
    - Tupla (es_valido, lista_errores, lista_avisos)
      - es_valido: True si cumple el esquema
      - lista_errores: Lista de errores de validación
      - lista_avisos: Lista de advertencias
    """
    schema = obtener_esquema_xsd()
    
    if schema is None:
        return False, ["No se pudo obtener el esquema XSD para validar."], []
    
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
    Valida el XML FacturaE con XSD y validación manual de respaldo.
    
    Parámetros:
    - xml_str: String del XML a validar
    
    Retorna:
    - (es_valido, mensaje_resultado)
    """
    # 1. Intentar validación con XSD oficial
    es_valido_xsd, errores_xsd, avisos_xsd = validar_xml_facturae(xml_str)
    
    if es_valido_xsd:
        return True, "✅ XML válido según el esquema oficial FacturaE v3.2.2"
    
    # 2. Si falló el XSD, hacer validación manual
    campos_faltantes = validacion_manual_rapida(xml_str)
    
    mensajes = []
    
    if errores_xsd:
        mensajes.append("**Errores de validación XSD:**")
        for error in errores_xsd[:10]:  # Mostrar máximo 10 errores
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
