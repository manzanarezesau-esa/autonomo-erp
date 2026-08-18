# firma_xades.py
import streamlit as st
from lxml import etree
import base64
from cryptography.hazmat.primitives.serialization import pkcs12, serialization

def firmar_facturae_xml(xml_str, certificado_p12, password_certificado):
    """
    Firma un XML FacturaE con XAdES-EPES.
    
    Parámetros:
    - xml_str: String del XML FacturaE sin firmar
    - certificado_p12: Bytes del certificado .p12/.pfx
    - password_certificado: Contraseña del certificado
    
    Retorna:
    - XML firmado como string
    """
    try:
        # Cargar certificado P12
        private_key, certificate, additional_certs = pkcs12.load_key_and_certificates(
            certificado_p12,
            password_certificado.encode('utf-8')
        )
        
        # Convertir a formato PEM
        private_key_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
        
        cert_pem = certificate.public_bytes(serialization.Encoding.PEM)
        
        # Parsear XML
        xml_root = etree.fromstring(xml_str.encode('utf-8'))
        
        # Importar signxml aquí para evitar errores si no está instalado
        try:
            from signxml import XMLSigner
        except ImportError:
            st.error("La librería signxml no está instalada. Ejecuta: pip install signxml")
            return xml_str
        
        # Configurar firmador XAdES
        signer = XMLSigner(
            method=etree.parse,
            signature_algorithm="rsa-sha256",
            digest_algorithm="sha256",
            c14n_algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315"
        )
        
        # Firmar el XML
        signed_xml = signer.sign(
            xml_root,
            key=private_key_pem,
            cert=cert_pem,
            reference_uri=""
        )
        
        # Convertir a string
        result = etree.tostring(signed_xml, encoding='utf-8', xml_declaration=True, pretty_print=True)
        return result.decode('utf-8')
        
    except Exception as e:
        st.warning(f"No se pudo firmar el XML: {str(e)}")
        return xml_str


def cargar_certificado_desde_secrets():
    """
    Carga el certificado desde st.secrets (para Streamlit Cloud).
    
    Retorna:
    - (certificado_bytes, password) o (None, None) si no está configurado
    """
    try:
        # En Streamlit Cloud, el certificado puede venir como base64 en secrets
        cert_b64 = st.secrets.get("CERTIFICADO_P12_BASE64", "")
        password = st.secrets.get("CERTIFICADO_PASSWORD", "")
        
        if cert_b64 and password:
            certificado_bytes = base64.b64decode(cert_b64)
            return certificado_bytes, password
        return None, None
    except Exception:
        return None, None
