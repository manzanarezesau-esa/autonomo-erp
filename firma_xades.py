# firma_xades.py
import streamlit as st
from lxml import etree
import base64
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12
from signxml import XMLSigner, methods


def cargar_certificado_p12(p12_content, password_input):
    """
    Carga y valida el certificado digital PKCS12 (.p12 / .pfx).
    
    Parámetros:
    - p12_content: Contenido del certificado (bytes, str base64, o str con Data URI)
    - password_input: Contraseña del certificado (str o bytes)
    
    Retorna:
    - Tupla (private_key, certificate, additional_certificates)
    
    Lanza:
    - ValueError si el contenido o la contraseña son incorrectos
    """
    # 1. Asegurar que la contraseña sea bytes o None
    if password_input:
        if isinstance(password_input, str):
            password_bytes = password_input.encode('utf-8')
        else:
            password_bytes = password_input
    else:
        password_bytes = None
    
    # 2. Asegurar que los datos del certificado sean bytes binarios
    if isinstance(p12_content, str):
        # Si viene como Base64 con encabezado Data URI
        if "base64," in p12_content:
            p12_content = p12_content.split("base64,")[1]
        # Decodificar Base64 a bytes
        try:
            p12_bytes = base64.b64decode(p12_content)
        except Exception as e:
            raise ValueError(
                "El contenido Base64 del certificado no es válido. "
                "Verifique que el certificado esté correctamente codificado en Base64."
            ) from e
    elif isinstance(p12_content, bytes):
        p12_bytes = p12_content
    else:
        raise ValueError("El contenido del certificado debe ser bytes o una cadena Base64.")
    
    # 3. Intentar deserializar
    try:
        private_key, certificate, additional_certs = pkcs12.load_key_and_certificates(
            p12_bytes,
            password_bytes
        )
        return private_key, certificate, additional_certs
    except ValueError as e:
        raise ValueError(
            "No se pudo desencriptar el certificado. Verifique que la contraseña sea correcta "
            "y que el archivo cargado sea un certificado válido (.p12 / .pfx)."
        ) from e
    except Exception as e:
        raise ValueError(
            f"Error inesperado al cargar el certificado: {str(e)}"
        ) from e


def firmar_facturae_xml(xml_input, certificado_p12, password_certificado):
    """
    Firma un XML FacturaE con XAdES-EPES.
    
    Parámetros:
    - xml_input: String del XML FacturaE sin firmar (str, bytes o Element)
    - certificado_p12: Bytes del certificado .p12/.pfx o Base64
    - password_certificado: Contraseña del certificado
    
    Retorna:
    - XML firmado como string
    """
    try:
        # Cargar y validar el certificado P12
        private_key, certificate, additional_certs = cargar_certificado_p12(
            certificado_p12,
            password_certificado
        )
        
        # Convertir a formato PEM para signxml
        private_key_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
        
        cert_pem = certificate.public_bytes(serialization.Encoding.PEM)
        
        # Asegurar que tenemos un Element XML (no string)
        if isinstance(xml_input, (str, bytes)):
            xml_root = etree.fromstring(xml_input.encode('utf-8') if isinstance(xml_input, str) else xml_input)
        else:
            xml_root = xml_input
        
        # Configurar firmador XAdES con el método correcto
        # ✅ CORRECTO: Usar el enum methods.enveloped de la librería signxml
        signer = XMLSigner(
            method=methods.enveloped,  # Método enveloped signature (estándar para XAdES)
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
        
    except ValueError as e:
        # Error específico de certificado (contraseña incorrecta, archivo inválido)
        st.error(f"Error de certificado: {str(e)}")
        return xml_input if isinstance(xml_input, str) else etree.tostring(xml_input, encoding='utf-8').decode('utf-8')
    except ImportError as e:
        st.error(f"Librería no instalada: {str(e)}")
        return xml_input if isinstance(xml_input, str) else etree.tostring(xml_input, encoding='utf-8').decode('utf-8')
    except Exception as e:
        st.warning(f"No se pudo firmar el XML: {str(e)}")
        return xml_input if isinstance(xml_input, str) else etree.tostring(xml_input, encoding='utf-8').decode('utf-8')


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
            # El certificado está en Base64 en secrets
            try:
                certificado_bytes = base64.b64decode(cert_b64)
                return certificado_bytes, password
            except Exception:
                st.error("El Base64 del certificado en secrets no es válido.")
                return None, None
        elif cert_b64 and not password:
            st.warning("Certificado configurado pero falta la contraseña (CERTIFICADO_PASSWORD).")
            return None, None
        return None, None
    except Exception as e:
        st.error(f"Error al cargar certificado desde secrets: {str(e)}")
        return None, None
