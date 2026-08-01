import streamlit as st
from supabase import Client

APP_URL = st.secrets.get("APP_URL", "http://localhost:8501")

def login_user(email: str, password: str, supabase: Client) -> bool:
    try:
        res = supabase.auth.sign_in_with_password({"email": email, "password": password})
        # Autentica el cliente original (no lo reemplazamos)
        supabase.auth.set_session(res.session.access_token, res.session.refresh_token)
        user = supabase.auth.get_user()
        st.session_state.user = res.user
        st.session_state.access_token = res.session.access_token
        st.session_state.user_id = user.user.id
        return True
    except Exception as e:
        st.error(f"Error de login: {e}")
        return False

def register_user(email: str, password: str, supabase: Client) -> bool:
    try:
        res = supabase.auth.sign_up({"email": email, "password": password})
        err = getattr(res, "error", None) or getattr(res, "error_message", None)
        if err:
            st.error(f"No se pudo registrar: {err}")
            return False
        if getattr(res, "session", None):
            supabase.auth.set_session(res.session.access_token, res.session.refresh_token)
            user = supabase.auth.get_user()
            st.session_state.user = res.user
            st.session_state.access_token = res.session.access_token
            st.session_state.user_id = user.user.id
            st.success("¡Cuenta creada! Entrando...")
            return True
        else:
            st.warning("Cuenta creada. Ve a 'Iniciar Sesión' para entrar.")
            return False
    except Exception as e:
        st.error(f"No se pudo registrar: {e}")
        return False

def reset_password(email: str, supabase: Client) -> None:
    try:
        supabase.auth.reset_password_for_email(email, {"redirect_to": f"{APP_URL}/"})
        st.success("Si el email existe, recibirás un enlace para restablecer tu contraseña.")
    except Exception as e:
        st.error(f"Error al enviar el correo: {e}")

def logout(supabase: Client) -> None:
    try:
        supabase.auth.sign_out()
    except Exception:
        pass
    for key in list(st.session_state.keys()):
        del st.session_state[key]

