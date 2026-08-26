# certificate_manager.py
import streamlit as st
import base64
import os
import hashlib
from datetime import datetime, timezone
from database import _get_supabase

# ============================================================
# ENCRIPTACIÓN DE CONTRASEÑAS
# ============================================================
# Usamos Fernet (AES-128-CBC + HMAC) para encriptar la contraseña
# del certificado antes de guardarla en Supabase.
# ============================================================

try:
    from cryptography.fernet import Fernet
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False
    st.warning("La librería 'cryptography' no está disponible. La contraseña se guardará sin encriptar (NO RECOMENDADO).")


def _get_encryption_key():
    """
    Obtiene o genera una clave de encriptación desde los secrets de Streamlit.
    
    La clave se deriva de SECRET_KEY usando PBKDF2 con SHA-256.
    """
    if not CRYPTO_AVAILABLE:
        return None
    
    # Obtener la clave secreta de Streamlit secrets
    secret_key = st.secrets.get("CERTIFICATE_ENCRYPTION_KEY", "")
    
    if not secret_key:
        # Fallback: usar SECRET_KEY genérica
        secret_key = st.secrets.get("SECRET_KEY", "hondureformas_default_secret_key")
    
    # Derivar clave usando PBKDF2
    salt = b"hondureformas_cert_salt_v1"
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    
    key = base64.urlsafe_b64encode(kdf.derive(secret_key.encode()))
    return key


def _encrypt_password(password: str) -> str:
    """
    Encripta la contraseña del certificado.
    
    Parámetros:
    - password: Contraseña en texto plano
    
    Retorna:
    - Contraseña encriptada en formato string (Fernet token)
    """
    if not CRYPTO_AVAILABLE:
        # Si no hay crypto, devolver la contraseña tal cual (NO RECOMENDADO)
        return password
    
    try:
        key = _get_encryption_key()
        if key is None:
            return password
        
        fernet = Fernet(key)
        encrypted = fernet.encrypt(password.encode('utf-8'))
        return encrypted.decode('utf-8')
    except Exception as e:
        st.warning(f"No se pudo encriptar la contraseña: {e}. Se guardará sin encriptar.")
        return password


def _decrypt_password(encrypted_password: str) -> str:
    """
    Desencripta la contraseña del certificado.
    
    Parámetros:
    - encrypted_password: Contraseña encriptada (Fernet token)
    
    Retorna:
    - Contraseña en texto plano
    """
    if not CRYPTO_AVAILABLE:
        return encrypted_password
    
    try:
        key = _get_encryption_key()
        if key is None:
            return encrypted_password
        
        fernet = Fernet(key)
        
        # Intentar desencriptar
        try:
            decrypted = fernet.decrypt(encrypted_password.encode('utf-8'))
            return decrypted.decode('utf-8')
        except Exception:
            # Si falla la desencriptación, puede ser que se guardó sin encriptar
            return encrypted_password
    except Exception:
        return encrypted_password


def _encrypt_certificate(cert_bytes: bytes) -> str:
    """
    Encripta el certificado P12 completo.
    
    Parámetros:
    - cert_bytes: Bytes del certificado
    
    Retorna:
    - Certificado encriptado en Base64
    """
    try:
        if CRYPTO_AVAILABLE:
            key = _get_encryption_key()
            if key:
                fernet = Fernet(key)
                encrypted = fernet.encrypt(cert_bytes)
                cert_b64 = base64.b64encode(encrypted).decode('utf-8')
                return cert_b64
    except Exception:
        pass
    
    # Fallback: solo Base64 sin encriptar
    return base64.b64encode(cert_bytes).decode('utf-8')


def _decrypt_certificate(cert_b64: str) -> bytes:
    """
    Desencripta el certificado P12.
    
    Parámetros:
    - cert_b64: Certificado en Base64 (posiblemente encriptado)
    
    Retorna:
    - Bytes del certificado
    """
    try:
        # Intentar desencriptar
        if CRYPTO_AVAILABLE:
            key = _get_encryption_key()
            if key:
                fernet = Fernet(key)
                cert_encrypted = base64.b64decode(cert_b64)
                try:
                    cert_bytes = fernet.decrypt(cert_encrypted)
                    return cert_bytes
                except Exception:
                    # Si falla, intentar como Base64 simple
                    pass
        
        # Fallback: Base64 simple
        return base64.b64decode(cert_b64)
    except Exception:
        return b""


# ============================================================
# FUNCIONES PRINCIPALES
# ============================================================

def guardar_certificado_usuario(user_id, certificado_p12_bytes, password):
    """
    Guarda el certificado P12 del usuario en Supabase con encriptación.
    
    Parámetros:
    - user_id: ID del usuario
    - certificado_p12_bytes: Bytes del certificado .p12/.pfx
    - password: Contraseña del certificado
    
    Retorna:
    - True si se guardó correctamente
    """
    try:
        supabase = _get_supabase()
        
        # Encriptar certificado
        cert_b64 = _encrypt_certificate(certificado_p12_bytes)
        
        # Encriptar contraseña
        password_encrypted = _encrypt_password(password)
        
        # Timestamp actual
        now = datetime.now(timezone.utc).isoformat()
        
        # Verificar si ya existe un certificado
        existing = supabase.table("user_certificates")\
            .select("id")\
            .eq("user_id", user_id)\
            .execute()
        
        if existing.data and len(existing.data) > 0:
            # Actualizar certificado existente
            supabase.table("user_certificates").update({
                "certificate_p12": cert_b64,
                "certificate_password": password_encrypted,
                "updated_at": now
            }).eq("user_id", user_id).execute()
        else:
            # Insertar nuevo certificado
            supabase.table("user_certificates").insert({
                "user_id": user_id,
                "certificate_p12": cert_b64,
                "certificate_password": password_encrypted,
                "created_at": now,
                "updated_at": now
            }).execute()
        
        return True
    except Exception as e:
        st.error(f"Error al guardar certificado: {str(e)}")
        return False


def obtener_certificado_usuario(user_id):
    """
    Obtiene el certificado P12 del usuario desde Supabase y lo desencripta.
    
    Parámetros:
    - user_id: ID del usuario
    
    Retorna:
    - (certificado_bytes, password) o (None, None) si no existe
    """
    try:
        supabase = _get_supabase()
        
        result = supabase.table("user_certificates")\
            .select("certificate_p12, certificate_password")\
            .eq("user_id", user_id)\
            .single()\
            .execute()
        
        if result.data:
            cert_b64 = result.data.get("certificate_p12", "")
            password_encrypted = result.data.get("certificate_password", "")
            
            if cert_b64:
                # Desencriptar certificado
                certificado_bytes = _decrypt_certificate(cert_b64)
                
                # Desencriptar contraseña
                password = _decrypt_password(password_encrypted)
                
                if certificado_bytes:
                    return certificado_bytes, password
        
        return None, None
    except Exception:
        return None, None


def eliminar_certificado_usuario(user_id):
    """
    Elimina el certificado del usuario.
    
    Parámetros:
    - user_id: ID del usuario
    
    Retorna:
    - True si se eliminó correctamente
    """
    try:
        supabase = _get_supabase()
        supabase.table("user_certificates").delete().eq("user_id", user_id).execute()
        return True
    except Exception as e:
        st.error(f"Error al eliminar certificado: {str(e)}")
        return False


def tiene_certificado(user_id):
    """
    Verifica si el usuario tiene un certificado configurado.
    
    Retorna:
    - True si tiene certificado
    """
    try:
        supabase = _get_supabase()
        result = supabase.table("user_certificates")\
            .select("id")\
            .eq("user_id", user_id)\
            .execute()
        
        return result.data is not None and len(result.data) > 0
    except Exception:
        return False
