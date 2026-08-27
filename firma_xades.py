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

# Lista de servidores TSA (incluyendo FNMT España)
TSA_LIST = [
    "http://servicios.cert.fnmt.es/tsa/postreq.aspx",  # FNMT (España)
    "https://freetsa.org/tsr",
    "http://timestamp.digicert.com",
    "http://timestamp.sectigo.com",
]

TSA_HEADERS = {
    "Content-Type": "application/timestamp-query",
    "Accept": "application/timestamp-reply",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) HondureformasERP/1.0"
}


def crear_timestamp_request(data_to_timestamp):
    """Crea petición de timestamp RFC 3161."""
    digest = hashlib.sha256(data_to_timestamp).digest()
    
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
    """Solicita timestamp a múltiples TSA."""
    for url in TSA_LIST:
        try:
            st.info(f"Intentando TSA: {url}")
            response = requests.post(
                url,
                data=tsq_bytes,
                headers=TSA_HEADERS,
                timeout=20
            )
            
            # Verificar respuesta válida
            if response.status_code == 200 and len(response.content) > 100:
                # Timestamp token válido empieza con 0x30 (SEQUENCE)
                if response.content[0] == 0x30:
                    st.success(f"✅ Timestamp obtenido de: {url}")
                    return response.content
                else:
                    st.warning(f"Respuesta no válida de {url} (no es DER)")
            else:
                st.warning(f"HTTP {response.status_code} de {url}")
                
        except requests.exceptions.Timeout:
            st.warning(f"Timeout en {url}")
        except Exception as e:
            st.warning(f"Error en {url}: {str(e)}")
    
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
    Firma XML con XAdES-EPES o XAdES-T.
    Si el timestamp falla, genera XAdES-EPES limpio.
    """
    try:
        private_key, certificate, _ = cargar_certificado_p12(certificado_p12, password_certificado)
        
        private_key_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        )
        cert_pem = certificate.public_bytes(serialization.Encoding.PEM)
        
        if isinstance(xml_input, (str, bytes)):
            xml_root = etree.fromstring(xml_input.encode('utf-8') if isinstance(xml_input, str) else xml_input)
        else:
            xml_root = xml_input
        
        root_id = f"Facturae-{uuid.uuid4().hex[:16]}"
        xml_root.set("Id", root_id)
        
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
        
        # Timestamp opcional
        if usar_timestamp:
            try:
                signed_data = etree.tostring(signed_xml, method='c14n')
                timestamp_token = solicitar_timestamp(crear_timestamp_request(signed_data))
                
                if timestamp_token and len(timestamp_token) > 100:
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
                        
                        st.success("✅ Firma XAdES-T aplicada")
                else:
                    st.warning("⚠️ No se pudo obtener timestamp. Se generó XAdES-EPES (válido sin timestamp).")
            except Exception as e:
                st.warning(f"⚠️ Error en timestamp: {str(e)}. Se generó XAdES-EPES.")
        
        result = etree.tostring(signed_xml, encoding='utf-8', xml_declaration=True, pretty_print=True)
        return result.decode('utf-8')
        
    except Exception as e:
        st.error(f"Error al firmar: {str(e)}")
        return xml_input if isinstance(xml_input, str) else etree.tostring(xml_input, encoding='utf-8').decode('utf-8')
