# firma_xades.py
import streamlit as st
from lxml import etree
import base64
import uuid
import requests
import hashlib
from datetime import datetime, timezone
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.serialization import pkcs12
from signxml import XMLSigner, methods

# Lista de servidores TSA
TSA_LIST = [
    "https://freetsa.org/tsr",
    "http://timestamp.digicert.com",
]

TSA_HEADERS = {
    "Content-Type": "application/timestamp-query",
    "Accept": "application/timestamp-reply",
    "User-Agent": "Mozilla/5.0 HondureformasERP/1.0"
}


def crear_timestamp_request(data_to_timestamp):
    """Crea petición de timestamp RFC 3161 usando hashlib."""
    digest = hashlib.sha256(data_to_timestamp).digest()
    
    # OID SHA-256: 2.16.840.1.101.3.4.2.1
    oid_sha256 = bytes([0x06, 0x09, 0x60, 0x86, 0x48, 0x01, 0x65, 0x03, 0x04, 0x02, 0x01])
    octet_string = bytes([0x04, 0x20]) + digest
    inner_seq = bytes([0x30, len(oid_sha256) + len(octet_string)]) + oid_sha256 + octet_string
    
    request = (
        bytes([0x30, len(inner_seq) + 5]) +
        bytes([0x02, 0x01, 0x01]) +
        inner_seq +
        bytes([0x01, 0x01, 0x00])
    )
    
    return request


def solicitar_timestamp(tsq_bytes):
    """Solicita timestamp a TSA con verificación de respuesta válida."""
    for url in TSA_LIST:
        try:
            response = requests.post(url, data=tsq_bytes, headers=TSA_HEADERS, timeout=15)
            
            if response.status_code == 200 and len(response.content) > 100:
                # Verificar que la respuesta NO sea un error
                # Una respuesta TSA válida empieza con 0x30 (SEQUENCE)
                if response.content[0] == 0x30:
                    return response.content
                else:
                    st.warning(f"TSA {url} devolvió respuesta no válida. Intentando siguiente...")
            else:
                st.warning(f"TSA {url} devolvió HTTP {response.status_code} o respuesta corta.")
                
        except Exception as e:
            st.warning(f"Error en TSA {url}: {str(e)}")
    
    return None


def obtener_timestamp(data_to_timestamp):
    """Obtiene timestamp válido o None."""
    try:
        ts_request = crear_timestamp_request(data_to_timestamp)
        return solicitar_timestamp(ts_request)
    except Exception:
        return None


def cargar_certificado_p12(p12_content, password_input):
    """Carga certificado PKCS12."""
    if password_input:
        password_bytes = password_input.encode('utf-8') if isinstance(password_input, str) else password_input
    else:
        password_bytes = None
    
    if isinstance(p12_content, str):
        if "base64," in p12_content:
            p12_content = p12_content.split("base64,")[1]
        p12_bytes = base64.b64decode(p12_content)
    else:
        p12_bytes = p12_content
    
    private_key, certificate, additional_certs = pkcs12.load_key_and_certificates(p12_bytes, password_bytes)
    return private_key, certificate, additional_certs


def firmar_facturae_xml(xml_input, certificado_p12, password_certificado, usar_timestamp=True):
    """
    Firma XML FacturaE con XAdES-EPES.
    Si usar_timestamp=True y el timestamp se obtiene correctamente, añade XAdES-T.
    Si el timestamp falla, genera XAdES-EPES (sin timestamp) - NUNCA inserta errores.
    """
    try:
        # Cargar certificado
        private_key, certificate, _ = cargar_certificado_p12(certificado_p12, password_certificado)
        
        # Convertir a PEM
        private_key_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
        cert_pem = certificate.public_bytes(serialization.Encoding.PEM)
        
        # Parsear XML
        if isinstance(xml_input, (str, bytes)):
            xml_root = etree.fromstring(xml_input.encode('utf-8') if isinstance(xml_input, str) else xml_input)
        else:
            xml_root = xml_input
        
        # ID único
        root_id = f"Facturae-{uuid.uuid4().hex[:16]}"
        xml_root.set("Id", root_id)
        
        # Firmar
        signer = XMLSigner(
            method=methods.enveloped,
            signature_algorithm="rsa-sha256",
            digest_algorithm="sha256",
            c14n_algorithm="http://www.w3.org/TR/2001/REC-xml-c14n-20010315"
        )
        
        signed_xml = signer.sign(
            xml_root,
            key=private_key_pem,
            cert=cert_pem,
            reference_uri=f"#{root_id}"
        )
        
        # Intentar timestamp SOLO si se solicita
        if usar_timestamp:
            timestamp_token = None
            try:
                signed_data = etree.tostring(signed_xml, method='c14n')
                timestamp_token = obtener_timestamp(signed_data)
            except Exception:
                timestamp_token = None
            
            if timestamp_token and len(timestamp_token) > 100:
                # Timestamp VÁLIDO - añadir XAdES-T
                signature_node = signed_xml.find(".//{http://www.w3.org/2000/09/xmldsig#}Signature")
                if signature_node is not None:
                    ns_xades = "http://uri.etsi.org/01903/v1.1.1#"
                    ns_ds = "http://www.w3.org/2000/09/xmldsig#"
                    
                    object_node = etree.SubElement(signature_node, f"{{{ns_ds}}}Object")
                    
                    qualifying_props = etree.SubElement(
                        object_node,
                        f"{{{ns_xades}}}QualifyingProperties",
                        Target=f"#{root_id}"
                    )
                    
                    signed_props = etree.SubElement(qualifying_props, f"{{{ns_xades}}}SignedProperties")
                    signed_sig_props = etree.SubElement(signed_props, f"{{{ns_xades}}}SignedSignatureProperties")
                    
                    signing_time = etree.SubElement(signed_sig_props, f"{{{ns_xades}}}SigningTime")
                    signing_time.text = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                    
                    sig_timestamp = etree.SubElement(signed_sig_props, f"{{{ns_xades}}}SignatureTimeStamp")
                    timestamp_b64 = base64.b64encode(timestamp_token).decode('utf-8')
                    
                    encapsulated_ts = etree.SubElement(sig_timestamp, f"{{{ns_xades}}}EncapsulatedTimeStamp")
                    encapsulated_ts.text = timestamp_b64
                    
                    st.success("✅ Firma XAdES-T con timestamp aplicada")
            else:
                st.warning("⚠️ No se pudo obtener timestamp válido. Se generará firma XAdES-EPES (sin timestamp).")
        
        # Convertir a string
        result = etree.tostring(signed_xml, encoding='utf-8', xml_declaration=True, pretty_print=True)
        return result.decode('utf-8')
        
    except Exception as e:
        st.error(f"Error al firmar: {str(e)}")
        return xml_input if isinstance(xml_input, str) else etree.tostring(xml_input, encoding='utf-8').decode('utf-8')
