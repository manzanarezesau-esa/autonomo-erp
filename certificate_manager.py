# certificate_manager.py
import streamlit as st
import base64
from database import _get_supabase


def guardar_certificado_usuario(user_id, certificado_p12_bytes, password):
    """
    Guarda el certificado P12 del usuario en Supabase.
    
    Parámetros:
    - user_id: ID del usuario
    - certificado_p12_bytes: Bytes del certificado .p12/.pfx
    - password: Contraseña del certificado
    
    Retorna:
    - True si se guardó correctamente
    """
    try:
        supabase = _get_supabase()
        
        # Convertir certificado a Base64
        cert_b64 = base64.b64encode(certificado_p12_bytes).decode('utf-8')
        
        # Verificar si ya existe un certificado
        existing = supabase.table("user_certificates")\
            .select("id")\
            .eq("user_id", user_id)\
            .execute()
        
        if existing.data and len(existing.data) > 0:
            # Actualizar certificado existente
            supabase.table("user_certificates").update({
                "certificate_p12": cert_b64,
                "certificate_password": password,
                "updated_at": "now()"
            }).eq("user_id", user_id).execute()
        else:
            # Insertar nuevo certificado
            supabase.table("user_certificates").insert({
                "user_id": user_id,
                "certificate_p12": cert_b64,
                "certificate_password": password,
                "created_at": "now()",
                "updated_at": "now()"
            }).execute()
        
        return True
    except Exception as e:
        st.error(f"Error al guardar certificado: {str(e)}")
        return False


def obtener_certificado_usuario(user_id):
    """
    Obtiene el certificado P12 del usuario desde Supabase.
    
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
            password = result.data.get("certificate_password", "")
            
            if cert_b64:
                certificado_bytes = base64.b64decode(cert_b64)
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
