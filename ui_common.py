# ui_common.py
import streamlit as st
from auth_utils import logout

def render_sidebar(supabase):
    """
    Dibuja el logo, el nombre de la plataforma, el email del usuario y el botón de cierre de sesión.
    Debe llamarse después de verificar que el usuario está autenticado.
    """
    # Logo (desde settings o placeholder)
    logo_url = None
    try:
        config_res = supabase.table("settings").select("company_logo").eq("user_id", st.session_state.user_id).execute()
        if config_res.data:
            logo_url = config_res.data[0].get("company_logo")
    except Exception:
        pass

    with st.sidebar:
        if logo_url:
            st.image(logo_url, width=180)
        else:
            # Placeholder: círculo con inicial "H"
            st.markdown("""
            <div style="
                width: 80px;
                height: 80px;
                background-color: #1E3A8A;
                border-radius: 50%;
                display: flex;
                align-items: center;
                justify-content: center;
                margin: 0 auto 10px auto;
            ">
                <span style="color: white; font-size: 42px; font-weight: bold;">H</span>
            </div>
            """, unsafe_allow_html=True)

        st.markdown("""
        <h2 style='text-align: center; color: #1E3A8A; margin-top: 0;'>
            Hondureformas ERP
        </h2>
        <p style='text-align: center; color: #4a5568; font-size: 14px;'>
            Gestión contable para autónomos
        </p>
        """, unsafe_allow_html=True)

        st.markdown("---")
        st.write(f"👤 {st.session_state.user.email}")
        if st.button("🔒 Cerrar sesión"):
            logout(supabase)
            st.rerun()
