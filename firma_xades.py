# firma_xades.py
import streamlit as st
from lxml import etree
import base64
import uuid
import requests
import hashlib
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12
from signxml import XMLSigner, methods

# ============================================================
# CONFIGURACIÓN DE LA TSA (Autoridad de Sellado de Tiempo)
# ============================================================
TSA_URL_FNMT = "https://www.sede.fnmt.gob.es/tsa/tsa.php"
TSA_URL_DIGICERT = "https://timestamp.digicert.com"
TSA_URL_SECTIGO = "https://timestamp.sectigo.com"

# TSA por defecto (FNMT para España)
TSA_URL = TSA_URL_FNMT


def crear_timestamp_request(data_to_timestamp):
    """
    Crea una petición de timestamp RFC 3161.
    
    Parámetros:
    - data_to_timestamp: Datos a sellar (bytes)
    
    Retorna:
    - Petición timestamp en formato DER (bytes)
    """
    try:
        from pycryptodome.hash import SHA256
    except ImportError:
        try:
            from Crypto.Hash import SHA256
        except ImportError:
            st.error("La librería pycryptodome no está instalada. Ejecuta: pip install pycryptodome")
            return None
    
    # Calcular hash SHA-256 de los datos
    hash_obj = SHA256.new(data_to_timestamp)
    digest = hash_obj.digest()
    
    # Crear petición TimestampRequest (RFC 3161)
    # Usamos una construcción manual mínima
    from pycryptodome.asn1 import DerSequence
    
    # MessageImprint
    message_imprint = DerSequence([
        DerSequence([
            # OID para SHA-256 (2.16.840.1.101.3.4.2.1)
            b'\x06\x09\x60\x86\x48\x01\x65\x03\x04\x02\x01',
            # OCTET STRING con el hash
            b'\x04\x20' + digest
        ])
    ])
    
    # TimestampRequest (sin nonce para simplificar)
    request = DerSequence([
        b'\x30\x00',  # version
        message_imprint.encode(),
        b'\x00',  # certReq = false
    ])
    
    return request.encode()


def obtener_timestamp(data_to_timestamp, tsa_url=None):
    """
    Obtiene un sello de tiempo RFC 3161 de una TSA.
    
    Parámetros:
    - data_to_timestamp: Datos a sellar (bytes)
    - tsa_url: URL de la TSA (opcional, usa FNMT por defecto)
    
    Retorna:
    - Timestamp token (bytes) o None si falla
    """
    url = tsa_url or TSA_URL
    
    try:
        # Crear petición timestamp
        ts_request = crear_timestamp_request(data_to_timestamp)
        
        if ts_request is None:
            return None
        
        # Enviar petición a la TSA
        headers = {
            "Content-Type": "application/timestamp-query",
            "Accept": "application/timestamp-reply",
        }
        
        response = requests.post(
            url,
            data=ts_request,
            headers=headers,
            timeout=30
        )
        
        if response.status_code == 200:
            return response.content
        else:
            st.warning(f"La TSA devolvió HTTP {response.status_code}")
            return None
            
    except requests.exceptions.Timeout:
        st.warning("Timeout al conectar con la TSA. La firma se realizará sin timestamp.")
        return None
    except requests.exceptions.ConnectionError:
        st.warning("No se pudo conectar con la TSA. La firma se realizará sin timestamp.")
        return None
    except Exception as e:
        st.warning(f"Error al obtener timestamp: {str(e)}. La firma se realizará sin timestamp.")
        return None


def cargar_certificado_p12(p12_content, password_input):
    """
    Carga y valida el certificado digital PKCS12 (.p12 / .pfx).
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
        if "base64," in p12_content:
            p12_content = p12_content.split("base64,")[1]
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


def firmar_facturae_xml(xml_input, certificado_p12, password_certificado, usar_timestamp=True):
    """
    Firma un XML FacturaE con XAdES-EPES o XAdES-T (con timestamp).
    
    Parámetros:
    - xml_input: String del XML FacturaE sin firmar (str, bytes o Element)
    - certificado_p12: Bytes del certificado .p12/.pfx o Base64
    - password_certificado: Contraseña del certificado
    - usar_timestamp: Boolean para añadir timestamp (XAdES-T) o no (XAdES-EPES)
    
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
        
        # Asignar un ID único al nodo raíz
        root_id = f"Facturae-{uuid.uuid4().hex[:16]}"
        xml_root.set("Id", root_id)
        
        # Configurar firmador XAdES
        signer = XMLSigner(
            method=methods.enveloped,
            signature_algorithm="rsa-sha256",
            digest_algorithm="sha256",
            c14n_algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315"
        )
        
        # Firmar el XML
        signed_xml = signer.sign(
            xml_root,
            key=private_key_pem,
            cert=cert_pem,
            reference_uri=f"#{root_id}"
        )
        
        # Si se solicita timestamp, añadir XAdES-T
        if usar_timestamp:
            try:
                # Serializar el XML firmado para calcular el hash
                signed_data = etree.tostring(signed_xml, encoding='utf-8', method='c14n')
                
                # Obtener timestamp de la TSA
                timestamp_token = obtener_timestamp(signed_data)
                
                if timestamp_token:
                    # Añadir el timestamp al XML firmado
                    # Buscar el nodo de firma y añadir la propiedad de timestamp
                    signature_node = signed_xml.find(".//{http://www.w3.org/2000/09/xmldsig#}Signature")
                    
                    if signature_node is not None:
                        # Crear elemento para el timestamp
                        ns_xades = "http://uri.etsi.org/01903/v1.1.1#"
                        ns_ds = "http://www.w3.org/2000/09/xmldsig#"
                        
                        # Buscar o crear Object para XAdES
                        object_node = signature_node.find(f"{{{ns_ds}}}Object")
                        
                        if object_node is None:
                            object_node = etree.SubElement(signature_node, f"{{{ns_ds}}}Object")
                        
                        # Crear QualifyingProperties
                        qualifying_props = etree.SubElement(
                            object_node,
                            f"{{{ns_xades}}}QualifyingProperties",
                            Target=f"#{root_id}"
                        )
                        
                        # Crear SignedProperties
                        signed_props = etree.SubElement(
                            qualifying_props,
                            f"{{{ns_xades}}}SignedProperties"
                        )
                        
                        # Crear SignedSignatureProperties
                        signed_sig_props = etree.SubElement(
                            signed_props,
                            f"{{{ns_xades}}}SignedSignatureProperties"
                        )
                        
                        # Crear SigningTime (opcional)
                        from datetime import datetime, timezone
                        signing_time = etree.SubElement(
                            signed_sig_props,
                            f"{{{ns_xades}}}SigningTime"
                        )
                        signing_time.text = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                        
                        # Crear SignatureTimeStamp (XAdES-T)
                        sig_timestamp = etree.SubElement(
                            signed_sig_props,
                            f"{{{ns_xades}}}SignatureTimeStamp"
                        )
                        
                        # Incluir el timestamp token en base64
                        timestamp_b64 = base64.b64encode(timestamp_token).decode('utf-8')
                        
                        # Crear EncapsulatedTimeStamp
                        encapsulated_ts = etree.SubElement(
                            sig_timestamp,
                            f"{{{ns_xades}}}EncapsulatedTimeStamp"
                        )
                        encapsulated_ts.text = timestamp_b64
                        
                        st.success("✅ Firma XAdES-T con timestamp de la FNMT aplicada correctamente")
                    else:
                        st.warning("No se encontró el nodo de firma para añadir timestamp.")
                else:
                    st.warning("No se pudo obtener timestamp. La firma será XAdES-EPES (sin timestamp).")
                    
            except Exception as e:
                st.warning(f"Error al añadir timestamp: {str(e)}. La firma será XAdES-EPES (sin timestamp).")
        
        # Convertir a string
        result = etree.tostring(signed_xml, encoding='utf-8', xml_declaration=True, pretty_print=True)
        return result.decode('utf-8')
        
    except ValueError as e:
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
        cert_b64 = st.secrets.get("CERTIFICADO_P12_BASE64", "")
        password = st.secrets.get("CERTIFICADO_PASSWORD", "")
        
        if cert_b64 and password:
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
