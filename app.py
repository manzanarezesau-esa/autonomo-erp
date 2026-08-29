# app.py
import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from datetime import datetime, date, timedelta
import json
import time
import io

# Validación
from validators import validar_nif_cif, validar_iban
from formatters import money

# Módulos propios
from config import LISTA_MESES, AUTONOMO_NAME, AUTONOMO_TAX_ID, AUTONOMO_ADDRESS, AUTONOMO_IBAN, TIPOS_GASTO
from database import (
    init_supabase,
    obtener_siguiente_numero_factura, obtener_siguiente_numero_presupuesto,
    crear_factura_con_rollback, crear_gasto_con_rollback,
    auditar_factura
)
from pdf_utils import make_invoice_pdf_from_template, make_budget_pdf
from email_utils import enviar_factura_email
from banking import iniciar_conexion_gocardless, completar_importacion, obtener_token_gocardless, obtener_bancos_disponibles
from auth_utils import login_user, register_user, reset_password, logout, APP_URL
from data_service import (
    get_invoices, get_clients, get_suppliers, get_products, get_expenses,
    get_bank_transactions, get_recurring_invoices, get_budgets, get_journal_entries
)
from certificate_manager import (
    guardar_certificado_usuario, obtener_certificado_usuario,
    eliminar_certificado_usuario, tiene_certificado
)
from stripe_utils import (
    obtener_suscripcion_usuario, crear_checkout_session,
    cancelar_suscripcion, verificar_acceso, procesar_success_url,
    obtener_historial_pagos
)
from modelo303_utils import generar_pdf_303, generar_fichero_aeat_303, validar_fichero_aeat
from facturae_utils import generar_facturae_xml

st.set_page_config(page_title="Hondureformas ERP", page_icon="🏗️", layout="wide")

# Inicializar Supabase (cacheado)
if "supabase" not in st.session_state:
    st.session_state.supabase = init_supabase()
supabase = st.session_state.supabase

# Estado de sesión
if "user" not in st.session_state:
    st.session_state.user = None
    st.session_state.access_token = None
    st.session_state.user_id = None

# Intentar restaurar sesión activa
try:
    if st.session_state.user is None:
        session = supabase.auth.get_session()
        if session and getattr(session, "user", None):
            st.session_state.user = session.user
            st.session_state.access_token = session.access_token
            user_meta = supabase.auth.get_user()
            if user_meta and user_meta.user:
                st.session_state.user_id = user_meta.user.id
except Exception:
    pass

# Procesar URL de éxito de Stripe si existe
if st.session_state.user is not None and "session_id" in st.query_params:
    procesar_success_url()

# ------------------------------------------------------------
# PANTALLA DE LOGIN / REGISTRO / RECUPERACIÓN
# ------------------------------------------------------------
if st.session_state.user is None:
    query_params = st.query_params
    if ("type" in query_params and query_params["type"] == "recovery") or "access_token" in query_params:
        st.title("🔐 Establecer nueva contraseña")
        with st.form("reset_password"):
            new_password = st.text_input("Nueva contraseña", type="password")
            confirm_password = st.text_input("Confirmar nueva contraseña", type="password")
            if st.form_submit_button("Cambiar contraseña"):
                if new_password != confirm_password:
                    st.error("Las contraseñas no coinciden.")
                elif len(new_password) < 6:
                    st.error("La contraseña debe tener al menos 6 caracteres.")
                else:
                    try:
                        if "access_token" in query_params:
                            supabase.auth.set_session(
                                query_params["access_token"],
                                query_params.get("refresh_token", "")
                            )
                        supabase.auth.update_user({"password": new_password})
                        st.success("¡Contraseña actualizada! Ya puedes iniciar sesión.")
                        st.query_params.clear()
                        time.sleep(1)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error al restablecer la contraseña: {e}")
        st.stop()

    st.title("🏗️ Bienvenid@ a Hondureformas Contable")
    tab1, tab2, tab3 = st.tabs(["Iniciar Sesión", "Crear Cuenta", "Olvidé mi contraseña"])

    with tab1:
        with st.form("login"):
            email = st.text_input("Email", key="login_email")
            pwd = st.text_input("Contraseña", type="password", key="login_pwd")
            if st.form_submit_button("Entrar"):
                email = (email or "").strip()
                pwd = (pwd or "").strip()
                if not email or not pwd or "@" not in email or "." not in email:
                    st.error("Credenciales inválidas.")
                else:
                    if login_user(email, pwd, supabase):
                        st.rerun()

    with tab2:
        with st.form("register"):
            new_email = st.text_input("Email", key="register_email")
            new_pwd = st.text_input("Contraseña (mín. 6 caracteres)", type="password", key="register_pwd")
            if st.form_submit_button("Registrarse"):
                new_email = (new_email or "").strip()
                new_pwd = (new_pwd or "").strip()
                if not new_email or "@" not in new_email or "." not in new_email:
                    st.error("Email inválido.")
                elif len(new_pwd) < 6 or len(new_pwd) > 72:
                    st.error("La contraseña debe tener entre 6 y 72 caracteres.")
                else:
                    if register_user(new_email, new_pwd, supabase):
                        st.rerun()

    with tab3:
        st.subheader("Recuperar acceso")
        with st.form("forgot_password"):
            recovery_email = st.text_input("Email de la cuenta", key="recovery_email")
            if st.form_submit_button("Enviar enlace de recuperación"):
                recovery_email = (recovery_email or "").strip()
                if not recovery_email or "@" not in recovery_email:
                    st.error("Introduce un email válido.")
                else:
                    reset_password(recovery_email, supabase)
    st.stop()

# ------------------------------------------------------------
# BARRA LATERAL
# ------------------------------------------------------------
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
        st.markdown("""
        <div style="width:80px;height:80px;background-color:#1E3A8A;border-radius:50%;display:flex;align-items:center;justify-content:center;margin:0 auto 10px auto;">
            <span style="color:white;font-size:42px;font-weight:bold;">H</span>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("""
    <h2 style='text-align:center;color:#1E3A8A;margin-top:0;'>Hondureformas ERP</h2>
    <p style='text-align:center;color:#4a5568;font-size:14px;'>Gestión contable para autónomos</p>
    """, unsafe_allow_html=True)

    st.markdown("---")
    st.write(f"👤 {st.session_state.user.email}")
    
    user_id_actual = st.session_state.get("user_id")
    
    if user_id_actual:
        try:
            suscripcion = obtener_suscripcion_usuario(user_id_actual)
            plan_actual = suscripcion.get("plan", "free") if suscripcion else "free"
        except Exception:
            plan_actual = "free"
    else:
        plan_actual = "free"
    
    iconos_plan = {
        "free": "🆓 Gratis",
        "basico": "💼 Básico",
        "profesional": "⭐ Profesional",
        "gestoria": "🏢 Gestoría"
    }
    st.write(f"Plan: **{iconos_plan.get(plan_actual, plan_actual)}**")
    
    if st.button("🔒 Cerrar sesión"):
        logout(supabase)
        st.rerun()

# Menú base
opciones_menu = [
    "🏠 Salpicadero",
    "👥 Clientes",
    "🤝 Proveedores",
    "📦 Productos",
    "💰 Ventas",
    "🛒 Compras",
    "👥 Empleados",
    "🔄 Facturación recurrente",
    "📖 Libro Contable General",
    "📒 Contabilidad",
    "🏛️ Impuestos Trimestrales",
    "🏦 Conciliación Bancaria",
    "📊 Dashboards",
    "📝 Presupuestos",
    "👥 Colaboradores",
    "💳 Suscripción",
    "⚙️ Configuración"
]

# ============================================================
# VERIFICACIÓN DE ADMIN
# ============================================================
ADMIN_EMAILS = [
    "esamanzanarez@gmail.com",
    "admin@hondureformas.com",
]

user_id = st.session_state.get("user_id")
if not user_id:
    try:
        session = supabase.auth.get_session()
        if session and getattr(session, "user", None):
            st.session_state.user_id = session.user.id
            user_id = session.user.id
    except Exception:
        user_id = None

if user_id:
    try:
        email_actual = st.session_state.user.email.lower() if st.session_state.user.email else ""
        es_admin = email_actual in [e.lower() for e in ADMIN_EMAILS]
        
        if not es_admin:
            try:
                role_res = supabase.table("user_roles").select("role").eq("user_id", user_id).single().execute()
                es_admin = role_res.data.get("role") == "admin" if role_res.data else False
            except Exception:
                es_admin = False
        
        st.session_state.es_admin = es_admin
        
        if es_admin:
            opciones_menu.append("🔐 Panel Admin")
    except Exception:
        pass

menu = st.sidebar.radio("Navegación", opciones_menu)

if not user_id:
    st.error("No se pudo obtener el ID de usuario. Por favor, inicia sesión de nuevo.")
    st.stop()

# ════════════════════════════════════════════════════════════
# SALPICADERO
# ════════════════════════════════════════════════════════════
if menu == "🏠 Salpicadero":
    st.title("Panel de Control")
    st.markdown("""
    <div style="background-color: #E0E7FF; padding: 20px; border-radius: 10px; margin-bottom: 20px;">
        <h1 style="color: #1E3A8A; text-align: center; margin: 0;">Hondureformas</h1>
        <p style="text-align: center; color: #4a5568; font-size: 18px;">Resumen de tu negocio</p>
    </div>
    """, unsafe_allow_html=True)
    st.write(f"📅 Hoy es {date.today().strftime('%d/%m/%Y')}  |  Bienvenido, {st.session_state.user.email}")

    hoy = date.today()
    mes_actual = hoy.month
    anio_actual = hoy.year

    periodo = st.selectbox("📅 Período", ["Mes actual", "Trimestre actual", "Año actual", "Todo"], index=0)

    inv = get_invoices(user_id)
    exp = get_expenses(user_id)

    if not inv.empty:
        inv["date_dt"] = pd.to_datetime(inv["date"], errors="coerce")
        inv["year"] = inv["date_dt"].dt.year
    if not exp.empty:
        exp["date_dt"] = pd.to_datetime(exp["date"], errors="coerce")
        exp["year"] = exp["date_dt"].dt.year

    if periodo == "Mes actual":
        if not inv.empty:
            inv = inv[(inv["year"] == anio_actual) & (inv["month"] == LISTA_MESES[mes_actual-1])]
        if not exp.empty:
            exp = exp[(exp["year"] == anio_actual) & (exp["month"] == LISTA_MESES[mes_actual-1])]
    elif periodo == "Trimestre actual":
        if mes_actual <= 3:
            meses_trim = ["Enero", "Febrero", "Marzo"]
        elif mes_actual <= 6:
            meses_trim = ["Abril", "Mayo", "Junio"]
        elif mes_actual <= 9:
            meses_trim = ["Julio", "Agosto", "Septiembre"]
        else:
            meses_trim = ["Octubre", "Noviembre", "Diciembre"]
        if not inv.empty:
            inv = inv[(inv["year"] == anio_actual) & (inv["month"].isin(meses_trim))]
        if not exp.empty:
            exp = exp[(exp["year"] == anio_actual) & (exp["month"].isin(meses_trim))]
    elif periodo == "Año actual":
        if not inv.empty:
            inv = inv[inv["year"] == anio_actual]
        if not exp.empty:
            exp = exp[exp["year"] == anio_actual]

    bv = pd.to_numeric(inv["base_amount"], errors="coerce").sum() if not inv.empty else 0.0
    bg = pd.to_numeric(exp["base_amount"], errors="coerce").sum() if not exp.empty else 0.0
    ben = bv - bg
    iva_dev = pd.to_numeric(inv["vat_amount"], errors="coerce").sum() if not inv.empty else 0.0
    iva_sop = pd.to_numeric(exp["vat_amount"], errors="coerce").sum() if not exp.empty else 0.0
    iva_pagar = max(iva_dev - iva_sop, 0.0)
    irpf_total = pd.to_numeric(inv["irpf_amount"], errors="coerce").sum() if not inv.empty else 0.0
    pago_frac = ben * 0.20 if ben > 0 else 0.0
    neto_final = ben - iva_pagar - irpf_total - pago_frac

    c1, c2, c3 = st.columns(3)
    c1.metric("Ingresos", money(bv))
    c2.metric("Gastos", money(bg))
    c3.metric("Beneficio bruto", money(ben))
    st.markdown("---")
    c4, c5, c6 = st.columns(3)
    c4.metric("Provisión IVA", f"-{money(iva_pagar)}")
    c5.metric("IRPF (retenido)", f"-{money(irpf_total)}")
    c6.metric("Pago fraccionado IRPF (20%)", f"-{money(pago_frac)}")
    st.metric("🔥 GANANCIA NETA (después de impuestos)", money(neto_final))

    st.markdown("---")
    num_facturas = len(inv) if not inv.empty else 0
    num_gastos = len(exp) if not exp.empty else 0
    col_f1, col_f2, col_f3 = st.columns(3)
    col_f1.metric("Facturas emitidas", num_facturas)
    col_f2.metric("Gastos registrados", num_gastos)
    col_f3.metric("Promedio por factura", money(bv/num_facturas) if num_facturas > 0 else "0.00 €")

# ════════════════════════════════════════════════════════════
# CLIENTES
# ════════════════════════════════════════════════════════════
elif menu == "👥 Clientes":
    st.title("Gestión de Clientes")
    clientes_df = get_clients(user_id)

    tab_add, tab_edit, tab_del = st.tabs(["Añadir nuevo", "Editar existente", "Eliminar"])

    with tab_add:
        with st.form("add_client", clear_on_submit=True):
            n = st.text_input("Nombre")
            t = st.text_input("NIF")
            a = st.text_input("Dirección")
            tipo = st.radio("Tipo de cliente", ["Empresa (B2B)", "Particular (B2C)"], horizontal=True)
            if st.form_submit_button("Guardar cliente"):
                if n:
                    t_val = (t or "").strip()
                    if t_val and not validar_nif_cif(t_val):
                        st.error("El NIF/CIF introducido no es válido.")
                    else:
                        try:
                            supabase.table("clients_v2").insert({
                                "user_id": user_id,
                                "name": n.strip(),
                                "tax_id": t_val,
                                "address": (a or "").strip(),
                                "type": "b2b" if "B2B" in tipo else "b2c"
                            }).execute()
                            st.success("Cliente guardado correctamente")
                            get_clients.clear()
                            time.sleep(0.5)
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error al guardar cliente: {e}")
                else:
                    st.error("El nombre es obligatorio.")

    with tab_edit:
        if clientes_df.empty:
            st.info("No hay clientes registrados para editar.")
        else:
            clientes_display = clientes_df[["name", "tax_id", "address", "type"]].copy()
            clientes_display["type"] = clientes_display["type"].map({"b2b": "Empresa", "b2c": "Particular"})
            clientes_display.columns = ["Nombre", "NIF/CIF", "Dirección", "Tipo"]
            
            column_config = {
                "Nombre": st.column_config.TextColumn("Nombre", width="medium"),
                "NIF/CIF": st.column_config.TextColumn("NIF/CIF", width="small"),
                "Dirección": st.column_config.TextColumn("Dirección", width="large"),
                "Tipo": st.column_config.TextColumn("Tipo", width="small"),
            }
            
            st.markdown("**Selecciona un cliente de la tabla:**")
            event = st.dataframe(
                clientes_display,
                hide_index=True,
                use_container_width=True,
                column_config=column_config,
                selection_mode="single-row",
                on_select="rerun",
                key="clientes_edit_table"
            )
            
            if (event.selection and event.selection.rows and len(event.selection.rows) > 0):
                selected_row = event.selection.rows[0]
                if selected_row is not None and 0 <= selected_row < len(clientes_df):
                    cliente_row = clientes_df.iloc[selected_row]
                    
                    st.markdown("---")
                    st.subheader(f"Editando: **{cliente_row['name']}**")
                    
                    with st.form("edit_client_form"):
                        nuevo_nombre = st.text_input("Nombre", value=cliente_row["name"])
                        nuevo_nif = st.text_input("NIF", value=cliente_row["tax_id"])
                        nueva_direccion = st.text_input("Dirección", value=cliente_row["address"])
                        nuevo_tipo = st.radio("Tipo de cliente", ["Empresa (B2B)", "Particular (B2C)"],
                                              index=0 if cliente_row.get("type") == "b2b" else 1,
                                              horizontal=True)

                        if st.form_submit_button("Guardar cambios"):
                            nif_val = (nuevo_nif or "").strip()
                            if nif_val and not validar_nif_cif(nif_val):
                                st.error("El NIF/CIF introducido no es válido.")
                            else:
                                try:
                                    supabase.table("clients_v2").update({
                                        "name": nuevo_nombre.strip(),
                                        "tax_id": nif_val,
                                        "address": nueva_direccion.strip(),
                                        "type": "b2b" if "B2B" in nuevo_tipo else "b2c"
                                    }).eq("id", cliente_row["id"]).execute()
                                    st.success("Cliente actualizado correctamente")
                                    get_clients.clear()
                                    time.sleep(0.5)
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Error al actualizar cliente: {e}")
                else:
                    st.info("Selecciona un cliente válido de la tabla.")
            else:
                st.info("Haz clic en una fila para seleccionar un cliente.")

    with tab_del:
        if clientes_df.empty:
            st.info("No hay clientes registrados para eliminar.")
        else:
            clientes_display = clientes_df[["name", "tax_id"]].copy()
            clientes_display.columns = ["Nombre", "NIF/CIF"]
            
            column_config = {
                "Nombre": st.column_config.TextColumn("Nombre", width="large"),
                "NIF/CIF": st.column_config.TextColumn("NIF/CIF", width="small"),
            }
            
            st.markdown("**Selecciona un cliente para eliminar:**")
            event = st.dataframe(
                clientes_display,
                hide_index=True,
                use_container_width=True,
                column_config=column_config,
                selection_mode="single-row",
                on_select="rerun",
                key="clientes_del_table"
            )
            
            if (event.selection and event.selection.rows and len(event.selection.rows) > 0):
                selected_row = event.selection.rows[0]
                if selected_row is not None and 0 <= selected_row < len(clientes_df):
                    cliente_row_del = clientes_df.iloc[selected_row]
                    
                    st.warning(f"⚠️ Vas a eliminar al cliente: **{cliente_row_del['name']}**")
                    
                    confirmado = st.checkbox(
                        "Confirmo que deseo eliminar este cliente",
                        key=f"confirm_delete_client_{cliente_row_del['id']}"
                    )
                    
                    if st.button(
                        "🗑️ Eliminar definitivamente",
                        key=f"delete_client_btn_{cliente_row_del['id']}",
                        disabled=not confirmado
                    ):
                        try:
                            supabase.table("clients_v2").delete().eq("id", cliente_row_del["id"]).execute()
                            st.success("Cliente eliminado correctamente")
                            get_clients.clear()
                            time.sleep(0.5)
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error al eliminar cliente: {e}")
                    
                    if not confirmado:
                        st.caption("Debes marcar la casilla de confirmación para habilitar el botón.")
                else:
                    st.info("Selecciona un cliente válido de la tabla.")
            else:
                st.info("Haz clic en una fila para seleccionar un cliente.")

    st.markdown("---")
    st.subheader("Listado de clientes")
    if not clientes_df.empty:
        clientes_display = clientes_df[["name", "tax_id", "address", "type"]].copy()
        clientes_display["type"] = clientes_display["type"].map({"b2b": "Empresa", "b2c": "Particular"})
        clientes_display.columns = ["Nombre", "NIF/CIF", "Dirección", "Tipo"]
        st.dataframe(clientes_display, hide_index=True, use_container_width=True)
    else:
        st.info("No hay clientes registrados.")

# ════════════════════════════════════════════════════════════
# PROVEEDORES
# ════════════════════════════════════════════════════════════
elif menu == "🤝 Proveedores":
    st.title("Gestión de Proveedores")
    proveedores_df = get_suppliers(user_id)

    tab_add, tab_edit, tab_del = st.tabs(["Añadir nuevo", "Editar existente", "Eliminar"])

    with tab_add:
        with st.form("add_supplier", clear_on_submit=True):
            n = st.text_input("Nombre")
            t = st.text_input("NIF")
            a = st.text_input("Dirección")
            if st.form_submit_button("Guardar proveedor"):
                if n:
                    t_val = (t or "").strip()
                    if t_val and not validar_nif_cif(t_val):
                        st.error("El NIF/CIF del proveedor no es válido.")
                    else:
                        try:
                            supabase.table("suppliers_v2").insert({
                                "user_id": user_id,
                                "name": n.strip(),
                                "tax_id": t_val,
                                "address": (a or "").strip()
                            }).execute()
                            st.success("Proveedor guardado correctamente")
                            get_suppliers.clear()
                            time.sleep(0.5)
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error al guardar proveedor: {e}")
                else:
                    st.error("El nombre es obligatorio.")

    with tab_edit:
        if proveedores_df.empty:
            st.info("No hay proveedores registrados para editar.")
        else:
            proveedores_display = proveedores_df[["name", "tax_id", "address"]].copy()
            proveedores_display.columns = ["Nombre", "NIF/CIF", "Dirección"]
            
            column_config = {
                "Nombre": st.column_config.TextColumn("Nombre", width="medium"),
                "NIF/CIF": st.column_config.TextColumn("NIF/CIF", width="small"),
                "Dirección": st.column_config.TextColumn("Dirección", width="large"),
            }
            
            st.markdown("**Selecciona un proveedor de la tabla:**")
            event = st.dataframe(
                proveedores_display,
                hide_index=True,
                use_container_width=True,
                column_config=column_config,
                selection_mode="single-row",
                on_select="rerun",
                key="proveedores_edit_table"
            )
            
            if (event.selection and event.selection.rows and len(event.selection.rows) > 0):
                selected_row = event.selection.rows[0]
                if selected_row is not None and 0 <= selected_row < len(proveedores_df):
                    prov_row = proveedores_df.iloc[selected_row]
                    
                    st.markdown("---")
                    st.subheader(f"Editando: **{prov_row['name']}**")
                    
                    with st.form("edit_supplier_form"):
                        nuevo_nombre = st.text_input("Nombre", value=prov_row["name"])
                        nuevo_nif = st.text_input("NIF", value=prov_row["tax_id"])
                        nueva_direccion = st.text_input("Dirección", value=prov_row["address"])

                        if st.form_submit_button("Guardar cambios"):
                            nif_val = (nuevo_nif or "").strip()
                            if nif_val and not validar_nif_cif(nif_val):
                                st.error("El NIF/CIF del proveedor no es válido.")
                            else:
                                try:
                                    supabase.table("suppliers_v2").update({
                                        "name": nuevo_nombre.strip(),
                                        "tax_id": nif_val,
                                        "address": nueva_direccion.strip()
                                    }).eq("id", prov_row["id"]).execute()
                                    st.success("Proveedor actualizado correctamente")
                                    get_suppliers.clear()
                                    time.sleep(0.5)
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Error al actualizar proveedor: {e}")
                else:
                    st.info("Selecciona un proveedor válido de la tabla.")
            else:
                st.info("Haz clic en una fila para seleccionar un proveedor.")

    with tab_del:
        if proveedores_df.empty:
            st.info("No hay proveedores registrados para eliminar.")
        else:
            proveedores_display = proveedores_df[["name", "tax_id"]].copy()
            proveedores_display.columns = ["Nombre", "NIF/CIF"]
            
            column_config = {
                "Nombre": st.column_config.TextColumn("Nombre", width="large"),
                "NIF/CIF": st.column_config.TextColumn("NIF/CIF", width="small"),
            }
            
            st.markdown("**Selecciona un proveedor para eliminar:**")
            event = st.dataframe(
                proveedores_display,
                hide_index=True,
                use_container_width=True,
                column_config=column_config,
                selection_mode="single-row",
                on_select="rerun",
                key="proveedores_del_table"
            )
            
            if (event.selection and event.selection.rows and len(event.selection.rows) > 0):
                selected_row = event.selection.rows[0]
                if selected_row is not None and 0 <= selected_row < len(proveedores_df):
                    prov_row_del = proveedores_df.iloc[selected_row]
                    
                    st.warning(f"⚠️ Vas a eliminar al proveedor: **{prov_row_del['name']}**")
                    
                    confirmado = st.checkbox(
                        "Confirmo que deseo eliminar este proveedor",
                        key=f"confirm_delete_supplier_{prov_row_del['id']}"
                    )
                    
                    if st.button(
                        "🗑️ Eliminar definitivamente",
                        key=f"delete_supplier_btn_{prov_row_del['id']}",
                        disabled=not confirmado
                    ):
                        try:
                            supabase.table("suppliers_v2").delete().eq("id", prov_row_del["id"]).execute()
                            st.success("Proveedor eliminado correctamente")
                            get_suppliers.clear()
                            time.sleep(0.5)
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error al eliminar proveedor: {e}")
                    
                    if not confirmado:
                        st.caption("Debes marcar la casilla de confirmación para habilitar el botón.")
                else:
                    st.info("Selecciona un proveedor válido de la tabla.")
            else:
                st.info("Haz clic en una fila para seleccionar un proveedor.")

    st.markdown("---")
    st.subheader("Listado de proveedores")
    if not proveedores_df.empty:
        proveedores_display = proveedores_df[["name", "tax_id", "address"]].copy()
        proveedores_display.columns = ["Nombre", "NIF/CIF", "Dirección"]
        st.dataframe(proveedores_display, hide_index=True, use_container_width=True)
    else:
        st.info("No hay proveedores registrados.")

# ════════════════════════════════════════════════════════════
# PRODUCTOS
# ════════════════════════════════════════════════════════════
elif menu == "📦 Productos":
    st.title("Catálogo de Productos / Servicios")
    productos_df = get_products(user_id)

    if not productos_df.empty:
        for col in ["description", "price", "default_vat_percentage", "default_irpf_percentage"]:
            if col not in productos_df.columns:
                if col == "description":
                    productos_df[col] = ""
                else:
                    productos_df[col] = 0.0

    tab_add, tab_edit, tab_del = st.tabs(["Añadir nuevo", "Editar existente", "Eliminar"])

    with tab_add:
        with st.form("add_product", clear_on_submit=True):
            nombre = st.text_input("Nombre")
            descripcion = st.text_area("Descripción")
            precio = st.number_input("Precio unitario", min_value=0.0, step=1.0)
            vat_default = st.number_input("IVA por defecto (%)", value=21.0, step=1.0)
            irpf_default = st.number_input("IRPF por defecto (%)", value=0.0, step=1.0)
            if st.form_submit_button("Guardar nuevo producto"):
                if nombre:
                    try:
                        supabase.table("products_v2").insert({
                            "user_id": user_id,
                            "name": nombre.strip(),
                            "description": descripcion.strip(),
                            "price": precio,
                            "default_vat_percentage": vat_default,
                            "default_irpf_percentage": irpf_default
                        }).execute()
                        st.success("Producto guardado correctamente")
                        get_products.clear()
                        time.sleep(0.5)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error al guardar producto: {e}")
                else:
                    st.error("El nombre es obligatorio.")

    with tab_edit:
        if productos_df.empty:
            st.info("No hay productos registrados para editar.")
        else:
            productos_display = productos_df[["name", "description", "price", "default_vat_percentage", "default_irpf_percentage"]].copy()
            productos_display.columns = ["Nombre", "Descripción", "Precio", "IVA %", "IRPF %"]
            
            column_config = {
                "Nombre": st.column_config.TextColumn("Nombre", width="medium"),
                "Descripción": st.column_config.TextColumn("Descripción", width="large"),
                "Precio": st.column_config.NumberColumn("Precio", format="%.2f €", width="small"),
                "IVA %": st.column_config.NumberColumn("IVA %", format="%d %%", width="small"),
                "IRPF %": st.column_config.NumberColumn("IRPF %", format="%d %%", width="small"),
            }
            
            st.markdown("**Selecciona un producto de la tabla:**")
            event = st.dataframe(
                productos_display,
                hide_index=True,
                use_container_width=True,
                column_config=column_config,
                selection_mode="single-row",
                on_select="rerun",
                key="productos_edit_table"
            )
            
            if (event.selection and event.selection.rows and len(event.selection.rows) > 0):
                selected_row = event.selection.rows[0]
                if selected_row is not None and 0 <= selected_row < len(productos_df):
                    prod_row = productos_df.iloc[selected_row]
                    
                    st.markdown("---")
                    st.subheader(f"Editando: **{prod_row['name']}**")
                    
                    with st.form("edit_product_form"):
                        nuevo_nombre = st.text_input("Nombre", value=prod_row["name"])
                        nueva_descripcion = st.text_area("Descripción", value=prod_row.get("description", ""))
                        nuevo_precio = st.number_input("Precio unitario", min_value=0.0, value=float(prod_row.get("price", 0.0)), step=1.0)
                        nuevo_vat = st.number_input("IVA por defecto (%)", value=float(prod_row.get("default_vat_percentage", 21.0)), step=1.0)
                        nuevo_irpf = st.number_input("IRPF por defecto (%)", value=float(prod_row.get("default_irpf_percentage", 0.0)), step=1.0)

                        if st.form_submit_button("Guardar cambios"):
                            if nuevo_nombre:
                                try:
                                    supabase.table("products_v2").update({
                                        "name": nuevo_nombre.strip(),
                                        "description": nueva_descripcion.strip(),
                                        "price": nuevo_precio,
                                        "default_vat_percentage": nuevo_vat,
                                        "default_irpf_percentage": nuevo_irpf
                                    }).eq("id", prod_row["id"]).execute()
                                    st.success("Producto actualizado correctamente")
                                    get_products.clear()
                                    time.sleep(0.5)
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Error al actualizar producto: {e}")
                            else:
                                st.error("El nombre es obligatorio.")
                else:
                    st.info("Selecciona un producto válido de la tabla.")
            else:
                st.info("Haz clic en una fila para seleccionar un producto.")

    with tab_del:
        if productos_df.empty:
            st.info("No hay productos registrados para eliminar.")
        else:
            productos_display = productos_df[["name", "price", "default_vat_percentage"]].copy()
            productos_display.columns = ["Nombre", "Precio", "IVA %"]
            
            column_config = {
                "Nombre": st.column_config.TextColumn("Nombre", width="large"),
                "Precio": st.column_config.NumberColumn("Precio", format="%.2f €", width="small"),
                "IVA %": st.column_config.NumberColumn("IVA %", format="%d %%", width="small"),
            }
            
            st.markdown("**Selecciona un producto para eliminar:**")
            event = st.dataframe(
                productos_display,
                hide_index=True,
                use_container_width=True,
                column_config=column_config,
                selection_mode="single-row",
                on_select="rerun",
                key="productos_del_table"
            )
            
            if (event.selection and event.selection.rows and len(event.selection.rows) > 0):
                selected_row = event.selection.rows[0]
                if selected_row is not None and 0 <= selected_row < len(productos_df):
                    prod_row_del = productos_df.iloc[selected_row]
                    
                    st.warning(f"⚠️ Vas a eliminar el producto: **{prod_row_del['name']}**")
                    
                    confirmado = st.checkbox(
                        "Confirmo que deseo eliminar este producto",
                        key=f"confirm_delete_product_{prod_row_del['id']}"
                    )
                    
                    if st.button(
                        "🗑️ Eliminar definitivamente",
                        key=f"delete_product_btn_{prod_row_del['id']}",
                        disabled=not confirmado
                    ):
                        try:
                            supabase.table("products_v2").delete().eq("id", prod_row_del["id"]).execute()
                            st.success("Producto eliminado correctamente")
                            get_products.clear()
                            time.sleep(0.5)
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error al eliminar producto: {e}")
                    
                    if not confirmado:
                        st.caption("Debes marcar la casilla de confirmación para habilitar el botón.")
                else:
                    st.info("Selecciona un producto válido de la tabla.")
            else:
                st.info("Haz clic en una fila para seleccionar un producto.")

    st.markdown("---")
    st.subheader("Catálogo actual")
    if not productos_df.empty:
        productos_display = productos_df[["name", "description", "price", "default_vat_percentage", "default_irpf_percentage"]].copy()
        productos_display.columns = ["Nombre", "Descripción", "Precio", "IVA %", "IRPF %"]
        st.dataframe(productos_display, hide_index=True, use_container_width=True)
    else:
        st.info("No hay productos en el catálogo.")
# ════════════════════════════════════════════════════════════
# VENTAS
# ════════════════════════════════════════════════════════════
elif menu == "💰 Ventas":
    st.title("Facturas de Venta")
    clientes_df = get_clients(user_id)
    productos_df = get_products(user_id)

    if "modo_edicion_factura" not in st.session_state:
        st.session_state.modo_edicion_factura = False
        st.session_state.factura_editando_id = None
        st.session_state.datos_edicion = {}
    if "modo_rectificativa" not in st.session_state:
        st.session_state.modo_rectificativa = False
        st.session_state.rectificativa_original = None
        st.session_state.rectificativa_lineas = []
    if "confirmar_anulacion" not in st.session_state:
        st.session_state.confirmar_anulacion = False
        st.session_state.factura_a_anular = None

    TRANSICIONES = {
        "pendiente": ["pagada", "vencida"],
        "pagada": ["anulada"],
        "vencida": [],
        "anulada": [],
        "rectificada": [],
    }

    if clientes_df.empty:
        st.warning("Primero registra algún cliente.")
    else:
        if not st.session_state.modo_edicion_factura and not st.session_state.modo_rectificativa:
            st.subheader("Nueva factura")
            with st.form("add_invoice", clear_on_submit=True):
                num_auto = obtener_siguiente_numero_factura(user_id)
                num = st.text_input("Nº Factura", value=num_auto)
                fecha = st.date_input("Fecha", datetime.now())
                mes = LISTA_MESES[fecha.month - 1]
                st.caption(f"📅 Mes: **{mes}**")

                cli_nombre = st.selectbox("Cliente", clientes_df["name"].tolist())
                cliente_row = clientes_df[clientes_df["name"] == cli_nombre].iloc[0]
                tipo_cliente = cliente_row.get("type", "b2b")
                st.markdown("**Líneas de factura**")
                num_lineas = st.number_input("Número de líneas", min_value=1, max_value=20, value=1, step=1)
                lineas = []
                lista_productos = ["-- Manual --"]
                if not productos_df.empty and "name" in productos_df.columns:
                    lista_productos += productos_df["name"].tolist()
                for i in range(int(num_lineas)):
                    cols = st.columns([3,2,2,2])
                    with cols[0]:
                        prod_sel = st.selectbox(f"Producto {i+1}", lista_productos, key=f"prod_{i}")
                        if prod_sel == "-- Manual --":
                            desc_manual = st.text_input(f"Descripción {i+1}", value="", key=f"desc_{i}")
                        else:
                            desc_manual = prod_sel
                    with cols[1]:
                        cantidad = st.number_input(f"Cantidad {i+1}", min_value=1.0, value=1.0, step=1.0, key=f"cant_{i}")
                    with cols[2]:
                        if prod_sel != "-- Manual --" and not productos_df.empty:
                            prod_row = productos_df[productos_df["name"] == prod_sel]
                            if not prod_row.empty:
                                prod_row = prod_row.iloc[0]
                                precio = prod_row["price"]
                                vat = prod_row["default_vat_percentage"]
                                irpf = 0.0
                                st.text(f"Precio: {money(precio)}")
                            else:
                                precio = st.number_input(f"Precio {i+1}", min_value=0.0, value=0.0, step=10.0, key=f"prec_{i}")
                                vat = st.number_input(f"IVA {i+1} (%)", value=21.0, step=1.0, key=f"vat_{i}")
                                irpf = st.number_input(f"IRPF {i+1} (%)", value=0.0, step=1.0, key=f"irpf_{i}")
                        else:
                            precio = st.number_input(f"Precio {i+1}", min_value=0.0, value=0.0, step=10.0, key=f"prec_{i}")
                            vat = st.number_input(f"IVA {i+1} (%)", value=21.0, step=1.0, key=f"vat_{i}")
                            irpf = st.number_input(f"IRPF {i+1} (%)", value=0.0, step=1.0, key=f"irpf_{i}")
                    with cols[3]:
                        base_linea = cantidad * precio
                        vat_amount = base_linea * vat / 100
                        irpf_amount = base_linea * irpf / 100
                        total_linea = base_linea + vat_amount - irpf_amount
                        st.text(f"Total: {money(total_linea)}")
                    descripcion_linea = desc_manual if prod_sel == "-- Manual --" and desc_manual.strip() else (prod_sel if prod_sel != "-- Manual --" else f"Concepto manual {i+1}")
                    prod_id = None
                    if prod_sel != "-- Manual --" and not productos_df.empty:
                        matching = productos_df[productos_df["name"] == prod_sel]
                        if not matching.empty:
                            prod_id = matching.iloc[0]["id"]
                    lineas.append({
                        "product_id": prod_id,
                        "description": descripcion_linea,
                        "quantity": cantidad,
                        "unit_price": precio,
                        "base_amount": base_linea,
                        "vat_percentage": vat,
                        "vat_amount": vat_amount,
                        "irpf_percentage": irpf,
                        "irpf_amount": irpf_amount,
                        "total": total_linea
                    })
                base_total = sum(l["base_amount"] for l in lineas)
                vat_total = sum(l["vat_amount"] for l in lineas)
                irpf_total = sum(l["irpf_amount"] for l in lineas)
                total_factura = base_total + vat_total - irpf_total
                st.write(f"Base imponible: {money(base_total)} | IVA: {money(vat_total)} | IRPF: -{money(irpf_total)} | TOTAL: {money(total_factura)}")
                if st.form_submit_button("Guardar factura") and num:
                    inv_data = {
                        "user_id": user_id,
                        "invoice_number": num.strip(),
                        "date": str(fecha),
                        "month": mes,
                        "client_id": cliente_row["id"],
                        "concept": lineas[0]["description"] if len(lineas)==1 else "Varios conceptos",
                        "base_amount": base_total,
                        "vat_percentage": lineas[0]["vat_percentage"] if lineas else 21,
                        "irpf_percentage": lineas[0]["irpf_percentage"] if lineas else 0,
                        "vat_amount": vat_total,
                        "irpf_amount": irpf_total,
                        "total": total_factura,
                        "status": "pendiente",
                        "tipo": "normal"
                    }
                    with st.spinner("Guardando factura..."):
                        exito, invoice_id, mensaje = crear_factura_con_rollback(
                            inv_data, lineas, user_id, cliente_row["name"]
                        )
                    if exito:
                        st.toast("✅ Factura creada correctamente", icon="✅")
                        st.success(mensaje)
                        get_invoices.clear()
                        time.sleep(0.5)
                        st.rerun()
                    else:
                        st.error(mensaje)
        elif st.session_state.modo_rectificativa:
            st.warning("📝 Emitiendo factura rectificativa")
            original = st.session_state.rectificativa_original
            st.write(f"Factura original: **{original['invoice_number']}** de fecha {original['date']}")
            with st.form("rectificativa_form", clear_on_submit=True):
                num_auto = obtener_siguiente_numero_factura(user_id)
                num = st.text_input("Nº Factura (nuevo)", value=num_auto)
                fecha = st.date_input("Fecha", datetime.now())
                mes = LISTA_MESES[fecha.month - 1]
                st.caption(f"📅 Mes: **{mes}**")
                cliente_row = clientes_df[clientes_df["id"] == original["client_id"]].iloc[0]
                st.text(f"Cliente: {cliente_row['name']}")
                tipo_cliente = cliente_row.get("type", "b2b")
                st.markdown("**Líneas de la rectificativa**")
                lineas_original = st.session_state.rectificativa_lineas.copy()
                num_lineas = st.number_input("Número de líneas", min_value=1, max_value=20, value=len(lineas_original), step=1)
                lineas = []
                for i in range(int(num_lineas)):
                    cols = st.columns([3,2,2,2])
                    if i < len(lineas_original):
                        lin = lineas_original[i]
                        desc_val = lin["description"]
                        cant_val = float(lin["quantity"])
                        precio_val = float(lin["unit_price"])
                        vat_val = float(lin.get("vat_percentage", 21))
                        irpf_val = float(lin.get("irpf_percentage", 0))
                    else:
                        desc_val = ""
                        cant_val = 1.0
                        precio_val = 0.0
                        vat_val = 21.0
                        irpf_val = 0.0
                    with cols[0]:
                        desc = st.text_input(f"Descripción {i+1}", value=desc_val, key=f"r_desc_{i}")
                    with cols[1]:
                        cantidad = st.number_input(f"Cantidad {i+1}", min_value=1.0, value=cant_val, step=1.0, key=f"r_cant_{i}")
                    with cols[2]:
                        precio = st.number_input(f"Precio ud. {i+1}", min_value=0.0, value=precio_val, step=10.0, key=f"r_prec_{i}")
                        vat = st.number_input(f"IVA {i+1} (%)", value=vat_val, step=1.0, key=f"r_vat_{i}")
                        irpf = st.number_input(f"IRPF {i+1} (%)", value=irpf_val, step=1.0, key=f"r_irpf_{i}")
                    with cols[3]:
                        base_linea = cantidad * precio
                        vat_amount = base_linea * vat / 100
                        irpf_amount = base_linea * irpf / 100
                        total_linea = base_linea + vat_amount - irpf_amount
                        st.text(f"Total: {money(total_linea)}")
                    lineas.append({
                        "product_id": lin.get("product_id") if i < len(lineas_original) else None,
                        "description": desc,
                        "quantity": cantidad,
                        "unit_price": precio,
                        "base_amount": base_linea,
                        "vat_percentage": vat,
                        "vat_amount": vat_amount,
                        "irpf_percentage": irpf,
                        "irpf_amount": irpf_amount,
                        "total": total_linea
                    })
                base_total = sum(l["base_amount"] for l in lineas)
                vat_total = sum(l["vat_amount"] for l in lineas)
                irpf_total = sum(l["irpf_amount"] for l in lineas)
                total_factura = base_total + vat_total - irpf_total
                st.write(f"Base imponible: {money(base_total)} | IVA: {money(vat_total)} | IRPF: -{money(irpf_total)} | TOTAL: {money(total_factura)}")
                if st.form_submit_button("Guardar rectificativa") and num:
                    inv_data = {
                        "user_id": user_id,
                        "invoice_number": num.strip(),
                        "date": str(fecha),
                        "month": mes,
                        "client_id": cliente_row["id"],
                        "concept": lineas[0]["description"] if len(lineas)==1 else "Varios conceptos",
                        "base_amount": base_total,
                        "vat_percentage": lineas[0]["vat_percentage"] if lineas else 21,
                        "irpf_percentage": lineas[0]["irpf_percentage"] if lineas else 0,
                        "vat_amount": vat_total,
                        "irpf_amount": irpf_total,
                        "total": total_factura,
                        "status": "pendiente",
                        "tipo": "rectificativa",
                        "id_factura_original": original["id"]
                    }
                    with st.spinner("Guardando factura rectificativa..."):
                        exito, invoice_id, mensaje = crear_factura_con_rollback(
                            inv_data, lineas, user_id, cliente_row["name"]
                        )
                    if exito:
                        try:
                            supabase.table("invoices_v2").update({"status": "rectificada"}).eq("id", original["id"]).execute()
                            auditar_factura(original["id"], "rectificada", inv_data.get("hash", ""), user_id)
                        except Exception as e:
                            st.error(f"Error al marcar factura original como rectificada: {e}")
                        st.toast("✅ Factura rectificativa creada", icon="✅")
                        st.success(mensaje)
                        st.session_state.modo_rectificativa = False
                        get_invoices.clear()
                        time.sleep(0.5)
                        st.rerun()
                    else:
                        st.error(mensaje)
                if st.form_submit_button("Cancelar"):
                    st.session_state.modo_rectificativa = False
                    st.rerun()

    # ============ TABLA DE FACTURAS EMITIDAS ============
    inv_df = get_invoices(user_id)
    if not inv_df.empty:
        inv_display = inv_df.copy()
        if "client_name" in inv_display.columns:
            inv_display["Cliente"] = inv_display["client_name"]
        else:
            inv_display["Cliente"] = "Sin cliente"
        
        inv_display["Fecha"] = pd.to_datetime(inv_display["date"], errors="coerce")
        
        def formatear_estado(estado):
            iconos = {
                "pendiente": "🔴 Pendiente",
                "pagada": "🟢 Pagada",
                "vencida": "🟠 Vencida",
                "anulada": "⚪ Anulada",
                "rectificada": "🔵 Rectificada"
            }
            return iconos.get(estado, f"⚪ {estado}")
        
        inv_display["Estado"] = inv_display["status"].apply(formatear_estado)
        inv_display = inv_display[["invoice_number", "Fecha", "Cliente", "base_amount", "vat_amount", "total", "Estado", "status"]].copy()
        inv_display.columns = ["Nº Factura", "Fecha", "Cliente", "Base Imponible", "IVA", "Total", "Estado", "_status_raw"]
        
        st.subheader("📋 Facturas emitidas")
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            filtro_estado = st.selectbox("Filtrar por estado", ["Todas", "Solo pendientes", "Solo pagadas", "Solo vencidas", "Solo anuladas"], key="filtro_facturas")
        with col_f2:
            orden_fecha = st.selectbox("Ordenar por fecha", ["Más recientes primero", "Más antiguas primero"], key="orden_facturas")
        
        if filtro_estado == "Solo pendientes":
            inv_display = inv_display[inv_display["_status_raw"] == "pendiente"]
        elif filtro_estado == "Solo pagadas":
            inv_display = inv_display[inv_display["_status_raw"] == "pagada"]
        elif filtro_estado == "Solo vencidas":
            inv_display = inv_display[inv_display["_status_raw"] == "vencida"]
        elif filtro_estado == "Solo anuladas":
            inv_display = inv_display[inv_display["_status_raw"] == "anulada"]
        
        if orden_fecha == "Más recientes primero":
            inv_display = inv_display.sort_values("Fecha", ascending=False)
        else:
            inv_display = inv_display.sort_values("Fecha", ascending=True)
        
        inv_display = inv_display.drop(columns=["_status_raw"])
        inv_display["Fecha"] = inv_display["Fecha"].dt.strftime("%d/%m/%Y")
        
        column_config = {
            "Nº Factura": st.column_config.TextColumn("Nº Factura", width="small"),
            "Fecha": st.column_config.TextColumn("Fecha", width="small"),
            "Cliente": st.column_config.TextColumn("Cliente", width="medium"),
            "Base Imponible": st.column_config.NumberColumn("Base Imponible", format="%.2f €", width="small"),
            "IVA": st.column_config.NumberColumn("IVA", format="%.2f €", width="small"),
            "Total": st.column_config.NumberColumn("Total", format="%.2f €", width="small"),
            "Estado": st.column_config.TextColumn("Estado", width="small"),
        }
        
        event = st.dataframe(
            inv_display,
            hide_index=True,
            use_container_width=True,
            column_config=column_config,
            selection_mode="single-row",
            on_select="rerun",
            key="facturas_table"
        )
        
        if (event.selection and event.selection.rows and len(event.selection.rows) > 0):
            selected_row = event.selection.rows[0]
            if selected_row is not None and 0 <= selected_row < len(inv_display):
                factura_num = inv_display.iloc[selected_row]["Nº Factura"]
                factura_seleccionada = inv_df[inv_df["invoice_number"] == factura_num]
                
                if not factura_seleccionada.empty:
                    factura_row = factura_seleccionada.iloc[0].to_dict()
                    fact_id = factura_row["id"]
                    estado_actual = factura_row.get("status", "pendiente")
                    
                    st.markdown("---")
                    st.subheader(f"Acciones para factura {factura_row['invoice_number']}")
                    st.write(f"Estado actual: **{estado_actual}**")

                    opciones_cambio = TRANSICIONES.get(estado_actual, [])
                    if opciones_cambio:
                        with st.form("cambiar_estado"):
                            nuevo_estado = st.selectbox("Nuevo estado", opciones_cambio)
                            if st.form_submit_button("Actualizar estado"):
                                try:
                                    supabase.table("invoices_v2").update({"status": nuevo_estado}).eq("id", fact_id).execute()
                                    auditar_factura(fact_id, nuevo_estado, factura_row.get("hash", ""), user_id)
                                    st.success("Estado actualizado")
                                    get_invoices.clear()
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Error al actualizar estado: {e}")
                    else:
                        st.info("No se permiten cambios de estado para esta factura.")

                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        cliente_id = factura_row.get("client_id")
                        cliente = {"name": "", "tax_id": "", "address": ""}
                        if cliente_id:
                            try:
                                cliente_res = supabase.table("clients_v2").select("name, tax_id, address").eq("id", cliente_id).execute()
                                if cliente_res.data:
                                    cliente = cliente_res.data[0]
                            except Exception:
                                pass
                        lineas_fact_df = pd.DataFrame()
                        try:
                            lineas_fact = supabase.table("invoice_items").select("*").eq("invoice_id", fact_id).execute()
                            if lineas_fact.data:
                                lineas_fact_df = pd.DataFrame(lineas_fact.data)
                        except Exception:
                            pass
                        lineas_fact_list = lineas_fact_df.to_dict(orient="records") if not lineas_fact_df.empty else [{
                            "description": factura_row.get("concept", ""), "quantity": 1,
                            "unit_price": factura_row["base_amount"], "base_amount": factura_row["base_amount"],
                            "vat_amount": factura_row["vat_amount"], "irpf_amount": factura_row["irpf_amount"],
                            "total": factura_row["total"]
                        }]
                        try:
                            config_res = supabase.table("settings").select("*").eq("user_id", user_id).execute()
                            company_config = config_res.data[0] if config_res.data else {
                                "company_name": AUTONOMO_NAME, "company_tax_id": AUTONOMO_TAX_ID,
                                "company_address": AUTONOMO_ADDRESS, "company_iban": AUTONOMO_IBAN,
                                "company_logo": "", "codigo_html": "", "codigo_css": ""
                            }
                        except Exception:
                            company_config = {
                                "company_name": AUTONOMO_NAME, "company_tax_id": AUTONOMO_TAX_ID,
                                "company_address": AUTONOMO_ADDRESS, "company_iban": AUTONOMO_IBAN,
                                "company_logo": "", "codigo_html": "", "codigo_css": ""
                            }
                        if factura_row.get("tipo") == "rectificativa":
                            company_config["es_rectificativa"] = True
                            id_orig = factura_row.get("id_factura_original")
                            if id_orig:
                                try:
                                    orig_res = supabase.table("invoices_v2").select("invoice_number").eq("id", id_orig).single().execute()
                                    if orig_res.data:
                                        company_config["factura_original_num"] = orig_res.data["invoice_number"]
                                    else:
                                        company_config["factura_original_num"] = "desconocida"
                                except Exception:
                                    company_config["factura_original_num"] = "desconocida"
                            else:
                                company_config["factura_original_num"] = "desconocida"
                        else:
                            company_config["es_rectificativa"] = False
                            company_config["factura_original_num"] = None
                        pdf_bytes = make_invoice_pdf_from_template(factura_row, cliente, company_config, lineas_fact_list)
                        if pdf_bytes:
                            st.download_button("⬇️ Descargar PDF", pdf_bytes, f"Factura_{factura_row['invoice_number']}.pdf", mime="application/pdf")
                        
                        if st.button("📄 Descargar XML FacturaE", key=f"xml_{fact_id}"):
                            if tiene_certificado(user_id):
                                xml_str = generar_facturae_xml(
                                    factura_row, cliente, company_config, lineas_fact_list,
                                    user_id=user_id,
                                    firmar=True,
                                    validar=True,
                                    usar_timestamp=True
                                )
                                st.success("XML firmado con XAdES-T usando tu certificado")
                            else:
                                xml_str = generar_facturae_xml(
                                    factura_row, cliente, company_config, lineas_fact_list,
                                    firmar=False,
                                    validar=True
                                )
                                st.warning("XML sin firma. Configura tu certificado en Configuración.")
                            
                            st.download_button(
                                "Descargar XML",
                                xml_str.encode('utf-8'),
                                f"Factura_{factura_row['invoice_number']}.xml",
                                mime="application/xml",
                                key=f"download_xml_{fact_id}"
                            )
                    with col2:
                        destinatario = st.text_input("Email del cliente", value="cliente@example.com", key="email_fact")
                        if st.button("📧 Enviar factura por email"):
                            if pdf_bytes:
                                exito = enviar_factura_email(destinatario, f"Factura {factura_row['invoice_number']}", "Adjunto su factura.", pdf_bytes, f"Factura_{factura_row['invoice_number']}.pdf")
                                if exito:
                                    auditar_factura(fact_id, "enviada", factura_row.get("hash", ""), user_id)
                                    st.success("Factura enviada")
                                else:
                                    st.error("No se pudo enviar")
                            else:
                                st.error("Primero genera el PDF")
                    with col3:
                        if estado_actual not in ("anulada", "rectificada") and factura_row.get("tipo") != "rectificativa":
                            if st.button("📝 Emitir rectificativa"):
                                st.session_state.modo_rectificativa = True
                                st.session_state.rectificativa_original = factura_row
                                st.session_state.rectificativa_lineas = lineas_fact_list
                                st.rerun()
                    with col4:
                        if estado_actual != "anulada":
                            if not st.session_state.confirmar_anulacion or st.session_state.factura_a_anular != fact_id:
                                if st.button("🚫 Anular factura"):
                                    st.session_state.confirmar_anulacion = True
                                    st.session_state.factura_a_anular = fact_id
                                    st.rerun()
                            else:
                                st.warning("¿Estás seguro de que deseas anular esta factura?")
                                confirmado = st.checkbox("Confirmo que deseo anular esta factura")
                                col_confirm, col_cancel = st.columns(2)
                                with col_confirm:
                                    if st.button("Sí, anular definitivamente", disabled=not confirmado):
                                        try:
                                            supabase.table("invoices_v2").update({"status": "anulada"}).eq("id", fact_id).execute()
                                            auditar_factura(fact_id, "anulada", factura_row.get("hash", ""), user_id)
                                            st.success("Factura anulada correctamente")
                                            st.session_state.confirmar_anulacion = False
                                            st.session_state.factura_a_anular = None
                                            get_invoices.clear()
                                            st.rerun()
                                        except Exception as e:
                                            st.error(f"Error al anular factura: {e}")
                                with col_cancel:
                                    if st.button("Cancelar"):
                                        st.session_state.confirmar_anulacion = False
                                        st.session_state.factura_a_anular = None
                                        st.rerun()
            else:
                st.info("Selecciona una factura válida de la tabla.")
        else:
            st.info("Haz clic en una fila para seleccionar una factura.")
    else:
        st.info("No hay facturas emitidas.")

# ════════════════════════════════════════════════════════════
# COMPRAS
# ════════════════════════════════════════════════════════════
elif menu == "🛒 Compras":
    st.title("Gastos / Compras")
    proveedores_df = get_suppliers(user_id)
    if "modo_edicion_gasto" not in st.session_state:
        st.session_state.modo_edicion_gasto = False
        st.session_state.gasto_editando_id = None
        st.session_state.datos_edicion_gasto = {}
    if proveedores_df.empty:
        st.warning("Primero registra algún proveedor.")
    else:
        if not st.session_state.modo_edicion_gasto:
            with st.form("add_expense", clear_on_submit=True):
                num = st.text_input("Nº Factura Proveedor")
                fecha = st.date_input("Fecha", datetime.now())
                mes = LISTA_MESES[fecha.month - 1]
                st.caption(f"📅 Mes: **{mes}**")
                prov_nombre = st.selectbox("Proveedor", options=proveedores_df["name"].tolist())
                tipo_gasto = st.selectbox("Tipo de gasto", TIPOS_GASTO)
                concepto = st.text_input("Concepto (descripción adicional)")
                base = st.number_input("Base imponible", min_value=0.0, step=10.0)
                vat_pct = st.number_input("% IVA", value=21.0, step=1.0)
                archivo = st.file_uploader("Subir factura (PDF o imagen)", type=["pdf", "png", "jpg", "jpeg"])
                if st.form_submit_button("Guardar") and num:
                    id_prov = proveedores_df.loc[proveedores_df["name"] == prov_nombre, "id"].values[0]
                    vat_amount = base * vat_pct / 100.0
                    total = base + vat_amount
                    attachment_url = None
                    if archivo is not None:
                        file_ext = archivo.name.split(".")[-1]
                        file_path = f"{user_id}/{datetime.now().strftime('%Y%m%d%H%M%S')}_{archivo.name}"
                        try:
                            supabase.storage.from_("facturas_gastos").upload(file_path, archivo.getvalue(), {"content-type": archivo.type})
                            attachment_url = supabase.storage.from_("facturas_gastos").get_public_url(file_path)
                        except Exception as e:
                            st.error(f"Error al subir archivo: {e}")
                    expense_data = {
                        "user_id": user_id,
                        "expense_number": num.strip(),
                        "date": str(fecha),
                        "month": mes,
                        "supplier_id": id_prov,
                        "category": (concepto or "").strip(),
                        "expense_type": tipo_gasto,
                        "base_amount": base,
                        "vat_percentage": vat_pct,
                        "vat_amount": vat_amount,
                        "total": total,
                        "attachment_url": attachment_url
                    }
                    with st.spinner("Registrando gasto..."):
                        exito, expense_id, mensaje = crear_gasto_con_rollback(
                            expense_data, user_id, prov_nombre
                        )
                    if exito:
                        st.toast("✅ Gasto registrado correctamente", icon="✅")
                        st.success(mensaje)
                        get_expenses.clear()
                        time.sleep(0.5)
                        st.rerun()
                    else:
                        st.error(mensaje)
        if st.session_state.modo_edicion_gasto:
            st.warning("Editando gasto")
            datos = st.session_state.datos_edicion_gasto
            with st.form("edit_expense_form"):
                num = st.text_input("Nº Factura Proveedor", value=datos.get("expense_number", ""))
                fecha = st.date_input("Fecha", value=pd.to_datetime(datos.get("date", datetime.now())))
                mes = LISTA_MESES[fecha.month - 1]
                st.caption(f"📅 Mes: **{mes}**")
                lista_proveedores = proveedores_df["name"].tolist()
                provider_name = datos.get("provider_name", "")
                try:
                    index_prov = lista_proveedores.index(provider_name) if provider_name in lista_proveedores else 0
                except ValueError:
                    index_prov = 0
                prov_nombre = st.selectbox("Proveedor", options=lista_proveedores, index=index_prov)
                tipo_gasto = st.selectbox("Tipo de gasto", TIPOS_GASTO, index=TIPOS_GASTO.index(datos.get("expense_type", "Otros")) if datos.get("expense_type", "Otros") in TIPOS_GASTO else 0)
                concepto = st.text_input("Concepto", value=datos.get("category", ""))
                base = st.number_input("Base imponible", value=float(datos.get("base_amount", 0)), min_value=0.0, step=10.0)
                vat_pct = st.number_input("% IVA", value=float(datos.get("vat_percentage", 21)), step=1.0)
                nuevo_archivo = st.file_uploader("Cambiar archivo (dejar vacío para mantener actual)", type=["pdf", "png", "jpg", "jpeg"])
                if st.form_submit_button("Guardar cambios"):
                    vat_amount = base * vat_pct / 100.0
                    total = base + vat_amount
                    updates = {
                        "expense_number": num.strip(),
                        "date": str(fecha),
                        "month": mes,
                        "supplier_id": proveedores_df[proveedores_df["name"] == prov_nombre].iloc[0]["id"],
                        "category": concepto.strip(),
                        "expense_type": tipo_gasto,
                        "base_amount": base,
                        "vat_percentage": vat_pct,
                        "vat_amount": vat_amount,
                        "total": total
                    }
                    if nuevo_archivo is not None:
                        file_ext = nuevo_archivo.name.split(".")[-1]
                        file_path = f"{user_id}/{datetime.now().strftime('%Y%m%d%H%M%S')}_{nuevo_archivo.name}"
                        try:
                            supabase.storage.from_("facturas_gastos").upload(file_path, nuevo_archivo.getvalue(), {"content-type": nuevo_archivo.type})
                            updates["attachment_url"] = supabase.storage.from_("facturas_gastos").get_public_url(file_path)
                        except Exception as e:
                            st.error(f"Error al subir nuevo archivo: {e}")
                    try:
                        supabase.table("expenses_v2").update(updates).eq("id", st.session_state.gasto_editando_id).execute()
                        st.success("Gasto actualizado")
                        st.session_state.modo_edicion_gasto = False
                        get_expenses.clear()
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error al actualizar gasto: {e}")
                if st.form_submit_button("Cancelar edición"):
                    st.session_state.modo_edicion_gasto = False
                    st.rerun()

    exp_df = get_expenses(user_id)
    if not exp_df.empty:
        exp_display = exp_df.copy()
        if "category" in exp_display.columns:
            exp_display.rename(columns={"category": "concept"}, inplace=True)
        if "supplier_name" in exp_display.columns:
            exp_display["Proveedor"] = exp_display["supplier_name"]
        else:
            exp_display["Proveedor"] = "Sin proveedor"
        exp_display = exp_display[["expense_number", "date", "Proveedor", "expense_type", "concept", "base_amount", "total"]].copy()
        exp_display.columns = ["Nº Factura", "Fecha", "Proveedor", "Tipo Gasto", "Concepto", "Base Imponible", "Total"]
        exp_display["Fecha"] = pd.to_datetime(exp_display["Fecha"]).dt.strftime("%d/%m/%Y")
        column_config = {
            "Nº Factura": st.column_config.TextColumn("Nº Factura", width="small"),
            "Fecha": st.column_config.TextColumn("Fecha", width="small"),
            "Proveedor": st.column_config.TextColumn("Proveedor", width="medium"),
            "Tipo Gasto": st.column_config.TextColumn("Tipo Gasto", width="small"),
            "Concepto": st.column_config.TextColumn("Concepto", width="medium"),
            "Base Imponible": st.column_config.NumberColumn("Base Imponible", format="%.2f €", width="small"),
            "Total": st.column_config.NumberColumn("Total", format="%.2f €", width="small"),
        }
        st.subheader("Gastos registrados")
        event = st.dataframe(exp_display, hide_index=True, use_container_width=True, column_config=column_config, selection_mode="single-row", on_select="rerun", key="gastos_table")
        if (event.selection and event.selection.rows and len(event.selection.rows) > 0):
            selected_row = event.selection.rows[0]
            if selected_row is not None and 0 <= selected_row < len(exp_df):
                gasto_seleccionado = exp_df.iloc[selected_row]
                gasto_row = gasto_seleccionado.to_dict()
                st.markdown("---")
                st.subheader(f"Acciones para gasto {gasto_row['expense_number']}")
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("✏️ Rectificar gasto"):
                        st.session_state.modo_edicion_gasto = True
                        st.session_state.gasto_editando_id = gasto_row["id"]
                        st.session_state.datos_edicion_gasto = {
                            "expense_number": gasto_row["expense_number"],
                            "date": gasto_row["date"],
                            "month": gasto_row["month"],
                            "provider_name": gasto_row.get("Proveedor", gasto_row.get("supplier_name", "")),
                            "category": gasto_row.get("concept", gasto_row.get("category", "")),
                            "expense_type": gasto_row.get("expense_type", "Otros"),
                            "base_amount": gasto_row["base_amount"],
                            "vat_percentage": gasto_row.get("vat_percentage", 21),
                            "attachment_url": gasto_row.get("attachment_url", "")
                        }
                        st.rerun()
                with col2:
                    confirmado = st.checkbox("Confirmo que deseo eliminar este gasto", key=f"confirm_del_gasto_{gasto_row['id']}")
                    if st.button("🗑️ Eliminar gasto", key=f"del_gasto_{gasto_row['id']}", disabled=not confirmado):
                        try:
                            supabase.table("expenses_v2").delete().eq("id", gasto_row["id"]).execute()
                            st.success("Gasto eliminado")
                            get_expenses.clear()
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error: {e}")
    else:
        st.info("No hay gastos registrados.")

# ════════════════════════════════════════════════════════════
# EMPLEADOS (CON NÓMINAS Y SEGURIDAD SOCIAL)
# ════════════════════════════════════════════════════════════
elif menu == "👥 Empleados":
    st.title("👥 Gestión de Empleados y Nóminas")
    
    tab_empleados, tab_nominas, tab_ss, tab_modelo111 = st.tabs(["👥 Empleados", "💰 Nóminas", "🏥 Seguridad Social", "📄 Modelo 111"])
    
    # TAB 1: EMPLEADOS
    with tab_empleados:
        st.subheader("👥 Empleados Registrados")
        
        with st.form("add_employee", clear_on_submit=True):
            st.markdown("**➕ Añadir nuevo empleado**")
            col_e1, col_e2 = st.columns(2)
            with col_e1:
                nombre = st.text_input("Nombre completo")
                dni = st.text_input("DNI/NIE")
            with col_e2:
                nss = st.text_input("Nº Seguridad Social")
                fecha_alta = st.date_input("Fecha de alta", date.today())
            
            col_e3, col_e4 = st.columns(2)
            with col_e3:
                tipo_contrato = st.selectbox("Tipo de contrato", ["Indefinido", "Temporal", "Formación", "Prácticas"])
                salario_bruto = st.number_input("Salario bruto anual (€)", min_value=0.0, step=1000.0)
            with col_e4:
                irpf_pct = st.number_input("% IRPF", min_value=0.0, max_value=45.0, value=15.0, step=0.5)
                salario_mensual = salario_bruto / 12 if salario_bruto > 0 else 0
                st.text(f"Salario mensual: {money(salario_mensual)}")
            
            if st.form_submit_button("💾 Guardar empleado"):
                if nombre and dni and nss:
                    try:
                        ss_employee = salario_mensual * 0.0635
                        ss_company = salario_mensual * 0.2930
                        
                        supabase.table("employees").insert({
                            "user_id": user_id,
                            "full_name": nombre.strip(),
                            "dni_nie": dni.strip().upper(),
                            "social_security_number": nss.strip(),
                            "start_date": str(fecha_alta),
                            "contract_type": tipo_contrato.lower(),
                            "gross_salary": salario_mensual,
                            "irpf_percentage": irpf_pct,
                            "social_security_employee": ss_employee,
                            "social_security_company": ss_company,
                            "active": True
                        }).execute()
                        st.success("Empleado guardado correctamente")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")
                else:
                    st.error("Nombre, DNI y NSS son obligatorios.")
        
        try:
            emp_res = supabase.table("employees").select("*").eq("user_id", user_id).eq("active", True).execute()
            if emp_res.data:
                emp_df = pd.DataFrame(emp_res.data)
                emp_display = emp_df[["full_name", "dni_nie", "gross_salary", "irpf_percentage", "contract_type"]].copy()
                emp_display.columns = ["Nombre", "DNI/NIE", "Salario Mensual", "IRPF %", "Contrato"]
                st.dataframe(emp_display, hide_index=True, use_container_width=True)
            else:
                st.info("No hay empleados registrados.")
        except Exception as e:
            st.error(f"Error al cargar empleados: {e}")
    
    # TAB 2: NÓMINAS
    with tab_nominas:
        st.subheader("💰 Generar Nómina")
        
        try:
            emp_res = supabase.table("employees").select("id, full_name, gross_salary, irpf_percentage, social_security_employee, social_security_company").eq("user_id", user_id).eq("active", True).execute()
            
            if emp_res.data:
                emp_list = emp_res.data
                emp_nombres = [f"{e['full_name']} - {money(e['gross_salary'])}/mes" for e in emp_list]
                
                col_n1, col_n2 = st.columns(2)
                with col_n1:
                    emp_sel = st.selectbox("Empleado", emp_nombres)
                    emp_idx = emp_nombres.index(emp_sel)
                    empleado = emp_list[emp_idx]
                with col_n2:
                    mes_nomina = st.selectbox("Mes", LISTA_MESES, index=datetime.now().month - 1)
                
                salario = empleado["gross_salary"]
                irpf_pct = empleado["irpf_percentage"]
                ss_emp = empleado["social_security_employee"]
                ss_empresa = empleado["social_security_company"]
                
                irpf_amount = salario * irpf_pct / 100
                neto = salario - irpf_amount - ss_emp
                coste_empresa = salario + ss_empresa
                
                st.markdown("---")
                st.subheader("📊 Resumen de Nómina")
                
                col_r1, col_r2, col_r3 = st.columns(3)
                col_r1.metric("Salario Bruto", money(salario))
                col_r2.metric("IRPF Retenido", f"-{money(irpf_amount)}")
                col_r3.metric("SS Empleado", f"-{money(ss_emp)}")
                
                col_r4, col_r5, col_r6 = st.columns(3)
                col_r4.metric("💵 Salario Neto", money(neto))
                col_r5.metric("SS Empresa", money(ss_empresa))
                col_r6.metric("💰 Coste Total Empresa", money(coste_empresa))
                
                nom_existente = None
                try:
                    check_res = supabase.table("payrolls").select("id").eq("user_id", user_id).eq("employee_id", empleado["id"]).eq("month", mes_nomina).eq("year", date.today().year).execute()
                    nom_existente = check_res.data[0]["id"] if check_res.data else None
                except Exception:
                    pass
                
                if nom_existente:
                    st.warning(f"⚠️ Ya existe una nómina de {empleado['full_name']} para {mes_nomina}. Se actualizará.")
                
                if st.button("💾 Guardar nómina"):
                    try:
                        if nom_existente:
                            supabase.table("payrolls").update({
                                "gross_salary": salario,
                                "irpf_amount": irpf_amount,
                                "social_security_employee": ss_emp,
                                "social_security_company": ss_empresa,
                                "net_salary": neto,
                                "total_company_cost": coste_empresa
                            }).eq("id", nom_existente).execute()
                            st.success(f"Nómina actualizada para {mes_nomina}")
                        else:
                            supabase.table("payrolls").insert({
                                "user_id": user_id,
                                "employee_id": empleado["id"],
                                "month": mes_nomina,
                                "year": date.today().year,
                                "gross_salary": salario,
                                "irpf_amount": irpf_amount,
                                "social_security_employee": ss_emp,
                                "social_security_company": ss_empresa,
                                "net_salary": neto,
                                "total_company_cost": coste_empresa
                            }).execute()
                            
                            try:
                                expense_data = {
                                    "user_id": user_id,
                                    "expense_number": f"NOM-{mes_nomina[:3].upper()}-{date.today().year}",
                                    "date": str(date.today()),
                                    "month": mes_nomina,
                                    "supplier_id": None,
                                    "category": f"Nómina {empleado['full_name']}",
                                    "expense_type": "Nomina",
                                    "base_amount": coste_empresa,
                                    "vat_percentage": 0,
                                    "vat_amount": 0,
                                    "total": coste_empresa,
                                    "attachment_url": None
                                }
                                
                                exito_gasto, gasto_id, mensaje_gasto = crear_gasto_con_rollback(
                                    expense_data, user_id, f"Empleado: {empleado['full_name']}"
                                )
                                
                                if exito_gasto:
                                    st.success(f"Nómina guardada y gasto contabilizado: {money(coste_empresa)}")
                                else:
                                    st.warning(f"Nómina guardada pero gasto no creado: {mensaje_gasto}")
                            except Exception as e:
                                st.warning(f"Nómina guardada pero error al crear gasto: {e}")
                            
                            st.success(f"Nómina de {empleado['full_name']} guardada para {mes_nomina}")
                        
                        get_expenses.clear()
                        time.sleep(0.5)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")
            else:
                st.info("No hay empleados registrados.")
        except Exception as e:
            st.error(f"Error: {e}")
        
        st.markdown("---")
        st.subheader("📋 Historial de Nóminas")
        try:
            nom_res = supabase.table("payrolls").select("*, employees(full_name)").eq("user_id", user_id).order("created_at", desc=True).execute()
            if nom_res.data:
                nom_df = pd.DataFrame(nom_res.data)
                if "employees" in nom_df.columns:
                    nom_df["empleado"] = nom_df["employees"].apply(lambda x: x["full_name"] if isinstance(x, dict) else "")
                else:
                    nom_df["empleado"] = ""
                nom_display = nom_df[["month", "year", "empleado", "gross_salary", "net_salary", "total_company_cost"]].copy()
                nom_display.columns = ["Mes", "Año", "Empleado", "Bruto", "Neto", "Coste Empresa"]
                st.dataframe(nom_display, hide_index=True, use_container_width=True)
            else:
                st.info("No hay nóminas registradas.")
        except Exception:
            pass
    
    # TAB 3: SEGURIDAD SOCIAL
    with tab_ss:
        st.subheader("🏥 Gastos de Seguridad Social")
        
        with st.form("add_ss_expense", clear_on_submit=True):
            st.markdown("**➕ Registrar pago de Seguridad Social**")
            col_ss1, col_ss2 = st.columns(2)
            with col_ss1:
                mes_ss = st.selectbox("Mes", LISTA_MESES, index=datetime.now().month - 1)
                tipo_ss = st.selectbox("Tipo de cotización", ["Régimen General", "Autónomos (RETA)"])
            with col_ss2:
                importe_ss = st.number_input("Importe (€)", min_value=0.0, step=50.0)
                fecha_ss = st.date_input("Fecha de pago", date.today())
            
            if st.form_submit_button("💾 Guardar pago SS"):
                if importe_ss > 0:
                    try:
                        expense_data = {
                            "user_id": user_id,
                            "expense_number": f"SS-{mes_ss[:3].upper()}-{date.today().year}",
                            "date": str(fecha_ss),
                            "month": mes_ss,
                            "supplier_id": None,
                            "category": f"Seguridad Social {tipo_ss}",
                            "expense_type": "Seguridad Social",
                            "base_amount": importe_ss,
                            "vat_percentage": 0,
                            "vat_amount": 0,
                            "total": importe_ss,
                            "attachment_url": None
                        }
                        
                        exito, gasto_id, mensaje = crear_gasto_con_rollback(
                            expense_data, user_id, f"Tesorería Seguridad Social"
                        )
                        
                        if exito:
                            st.success(f"Pago de Seguridad Social registrado: {money(importe_ss)}")
                            get_expenses.clear()
                            time.sleep(0.5)
                            st.rerun()
                        else:
                            st.error(mensaje)
                    except Exception as e:
                        st.error(f"Error: {e}")
                else:
                    st.error("El importe debe ser mayor que 0.")
        
        st.markdown("---")
        st.subheader("📋 Pagos de Seguridad Social registrados")
        try:
            ss_res = supabase.table("expenses_v2").select("*").eq("user_id", user_id).eq("expense_type", "Seguridad Social").order("date", desc=True).execute()
            if ss_res.data:
                ss_df = pd.DataFrame(ss_res.data)
                ss_display = ss_df[["expense_number", "date", "month", "category", "total"]].copy()
                ss_display.columns = ["Nº", "Fecha", "Mes", "Descripción", "Importe"]
                ss_display["Fecha"] = pd.to_datetime(ss_display["Fecha"]).dt.strftime("%d/%m/%Y")
                st.dataframe(ss_display, hide_index=True, use_container_width=True)
                st.metric("Total SS registrado", money(ss_df["total"].sum()))
            else:
                st.info("No hay pagos de Seguridad Social registrados.")
        except Exception as e:
            st.info(f"Tabla de gastos no disponible: {e}")
    
    # TAB 4: MODELO 111
    with tab_modelo111:
        st.subheader("📄 Modelo 111 - Retenciones IRPF")
        
        try:
            hoy = date.today()
            if hoy.month <= 3:
                meses_trim = ["Enero", "Febrero", "Marzo"]
                trimestre = "1T"
            elif hoy.month <= 6:
                meses_trim = ["Abril", "Mayo", "Junio"]
                trimestre = "2T"
            elif hoy.month <= 9:
                meses_trim = ["Julio", "Agosto", "Septiembre"]
                trimestre = "3T"
            else:
                meses_trim = ["Octubre", "Noviembre", "Diciembre"]
                trimestre = "4T"
            
            nom_res = supabase.table("payrolls").select("*").eq("user_id", user_id).in_("month", meses_trim).execute()
            
            if nom_res.data:
                nom_df = pd.DataFrame(nom_res.data)
                total_irpf = nom_df["irpf_amount"].sum()
                num_nominas = len(nom_df)
                
                st.markdown(f"### Trimestre {trimestre} {hoy.year}")
                
                col_m1, col_m2, col_m3 = st.columns(3)
                col_m1.metric("Nº de Nóminas", num_nominas)
                col_m2.metric("Total Retenciones IRPF", money(total_irpf))
                col_m3.metric("A ingresar", money(total_irpf))
                
                st.info("📌 El Modelo 111 se presenta trimestralmente (1-20 de abril, julio, octubre, enero).")
                
                resumen_data = {
                    "Concepto": ["Nº Nóminas", "Total Retenciones IRPF"],
                    "Importe": [num_nominas, total_irpf]
                }
                resumen_df = pd.DataFrame(resumen_data)
                csv_bytes = resumen_df.to_csv(index=False, sep=';').encode('utf-8-sig')
                st.download_button(
                    "⬇️ Descargar resumen CSV",
                    csv_bytes,
                    f"Modelo_111_{trimestre}_{hoy.year}.csv",
                    mime="text/csv"
                )
            else:
                st.info(f"No hay nóminas registradas para el trimestre actual.")
        except Exception as e:
            st.error(f"Error: {e}")

# ════════════════════════════════════════════════════════════
# FACTURACIÓN RECURRENTE
# ════════════════════════════════════════════════════════════
elif menu == "🔄 Facturación recurrente":
    st.title("Facturación recurrente")
    clientes_df = get_clients(user_id)
    with st.form("add_recurring"):
        cliente = st.selectbox("Cliente", clientes_df["name"].tolist() if not clientes_df.empty else [])
        frecuencia = st.selectbox("Frecuencia", ["weekly", "monthly", "yearly"])
        proxima_fecha = st.date_input("Próxima factura", date.today() + timedelta(days=30))
        concepto = st.text_input("Concepto")
        base = st.number_input("Base imponible", min_value=0.0, step=10.0)
        vat = st.number_input("% IVA", value=21.0)
        irpf = st.number_input("% IRPF", value=0.0)
        if st.form_submit_button("Guardar recurrencia"):
            cliente_id = clientes_df[clientes_df["name"] == cliente]["id"].iloc[0]
            try:
                supabase.table("recurring_invoices").insert({
                    "user_id": user_id,
                    "client_id": cliente_id,
                    "frequency": frecuencia,
                    "next_date": str(proxima_fecha),
                    "base_amount": base,
                    "vat_percentage": vat,
                    "irpf_percentage": irpf,
                    "concept": concepto.strip(),
                    "active": True
                }).execute()
                st.success("Recurrencia guardada")
                get_recurring_invoices.clear()
                st.rerun()
            except Exception as e:
                st.error(f"Error al guardar recurrencia: {e}")
    st.subheader("Facturas recurrentes activas")
    recs = get_recurring_invoices(user_id)
    if not recs.empty:
        recs["Cliente"] = recs["client_name"] if "client_name" in recs.columns else recs.get("client_name", "")
        st.dataframe(recs, width='stretch')
    if st.button("Generar facturas pendientes hoy"):
        hoy = date.today()
        try:
            recs_to_process = supabase.table("recurring_invoices")\
                .select("*")\
                .eq("user_id", user_id)\
                .eq("active", True)\
                .lte("next_date", str(hoy))\
                .execute()
            if recs_to_process.data:
                for r in recs_to_process.data:
                    num = obtener_siguiente_numero_factura(user_id)
                    inv_data = {
                        "user_id": user_id,
                        "invoice_number": num,
                        "date": str(hoy),
                        "month": LISTA_MESES[hoy.month-1],
                        "client_id": r["client_id"],
                        "concept": r["concept"],
                        "base_amount": r["base_amount"],
                        "vat_percentage": r["vat_percentage"],
                        "irpf_percentage": r["irpf_percentage"],
                        "vat_amount": r["base_amount"] * r["vat_percentage"] / 100,
                        "irpf_amount": r["base_amount"] * r["irpf_percentage"] / 100,
                        "total": r["base_amount"] + (r["base_amount"]*r["vat_percentage"]/100) - (r["base_amount"]*r["irpf_percentage"]/100),
                        "status": "pendiente"
                    }
                    try:
                        supabase.table("invoices_v2").insert(inv_data).execute()
                    except Exception:
                        pass
                    if r["frequency"] == "weekly": next_date = hoy + timedelta(weeks=1)
                    elif r["frequency"] == "monthly": next_date = hoy + timedelta(days=30)
                    else: next_date = hoy + timedelta(days=365)
                    try:
                        supabase.table("recurring_invoices").update({"next_date": str(next_date)}).eq("id", r["id"]).execute()
                    except Exception:
                        pass
                st.success(f"Se generaron {len(recs_to_process.data)} facturas")
                get_recurring_invoices.clear()
                get_invoices.clear()
                st.rerun()
            else:
                st.info("No hay facturas pendientes para hoy")
        except Exception as e:
            st.error(f"Error al generar facturas recurrentes: {e}")

# ════════════════════════════════════════════════════════════
# LIBRO CONTABLE GENERAL (MEJORADO)
# ════════════════════════════════════════════════════════════
elif menu == "📖 Libro Contable General":
    st.title("📖 Libro Registro")
    
    inv = get_invoices(user_id)
    exp = get_expenses(user_id)
    
    if not inv.empty:
        inv["date_dt"] = pd.to_datetime(inv["date"], errors="coerce")
        inv["year"] = inv["date_dt"].dt.year
        inv["tipo"] = "Venta"
        inv.rename(columns={"invoice_number": "numero"}, inplace=True)
        if "irpf_amount" not in inv.columns:
            inv["irpf_amount"] = 0.0
    
    if not exp.empty:
        exp["date_dt"] = pd.to_datetime(exp["date"], errors="coerce")
        exp["year"] = exp["date_dt"].dt.year
        exp["tipo"] = "Gasto"
        exp.rename(columns={"expense_number": "numero"}, inplace=True)
        if "category" in exp.columns:
            exp.rename(columns={"category": "concept"}, inplace=True)
        if "irpf_amount" not in exp.columns:
            exp["irpf_amount"] = 0.0
    
    st.subheader("🔍 Filtros de Período")
    col_f1, col_f2 = st.columns(2)
    
    with col_f1:
        anios_disponibles = set()
        if not inv.empty:
            anios_disponibles.update(inv["year"].dropna().unique())
        if not exp.empty:
            anios_disponibles.update(exp["year"].dropna().unique())
        if not anios_disponibles:
            anios_disponibles = {date.today().year}
        anios_disponibles = sorted(anios_disponibles, reverse=True)
        anio_seleccionado = st.selectbox("📅 Año", anios_disponibles, index=0)
    
    with col_f2:
        mes_seleccionado = st.selectbox("📆 Mes", LISTA_MESES, index=datetime.now().month - 1)
    
    inv_filtrado = inv[(inv["year"] == anio_seleccionado) & (inv["month"] == mes_seleccionado)].copy() if not inv.empty else pd.DataFrame()
    exp_filtrado = exp[(exp["year"] == anio_seleccionado) & (exp["month"] == mes_seleccionado)].copy() if not exp.empty else pd.DataFrame()
    
    df_completo = pd.concat([inv_filtrado, exp_filtrado], ignore_index=True)
    
    if df_completo.empty:
        st.info(f"No hay movimientos en {mes_seleccionado} de {anio_seleccionado}.")
        st.stop()
    
    st.markdown("---")
    st.subheader(f"📊 Resumen de {mes_seleccionado} {anio_seleccionado}")
    
    total_base = pd.to_numeric(df_completo["base_amount"], errors="coerce").sum()
    total_iva_repercutido = pd.to_numeric(inv_filtrado["vat_amount"], errors="coerce").sum() if not inv_filtrado.empty else 0.0
    total_iva_soportado = pd.to_numeric(exp_filtrado["vat_amount"], errors="coerce").sum() if not exp_filtrado.empty else 0.0
    total_general = pd.to_numeric(df_completo["total"], errors="coerce").sum()
    num_registros = len(df_completo)
    
    col_m1, col_m2, col_m3, col_m4 = st.columns(4)
    col_m1.metric("💰 Total Base Imponible", money(total_base))
    col_m2.metric("📄 IVA Repercutido", money(total_iva_repercutido))
    col_m3.metric("🧾 IVA Soportado", money(total_iva_soportado))
    col_m4.metric("📊 Total General", money(total_general))
    
    col_m5, col_m6 = st.columns(2)
    col_m5.metric("📋 Nº de Registros", num_registros)
    col_m6.metric("IVA Neto", money(total_iva_repercutido - total_iva_soportado))
    
    st.markdown("---")
    df_display = df_completo.copy()
    columnas_mostrar = ["numero", "date_dt", "concept", "base_amount", "vat_amount", "total", "tipo"]
    for col in columnas_mostrar:
        if col not in df_display.columns:
            df_display[col] = ""
    df_display = df_display[columnas_mostrar].copy()
    df_display.columns = ["numero", "date", "concept", "base_amount", "vat_amount", "total", "tipo"]
    df_display["date"] = pd.to_datetime(df_display["date"], errors="coerce")
    
    column_config = {
        "numero": st.column_config.TextColumn("Nº Factura", width="small"),
        "date": st.column_config.DateColumn("Fecha", format="DD/MM/YYYY", width="small"),
        "concept": st.column_config.TextColumn("Concepto", width="large"),
        "base_amount": st.column_config.NumberColumn("Base Imponible", format="%.2f €"),
        "vat_amount": st.column_config.NumberColumn("Cuota IVA", format="%.2f €"),
        "total": st.column_config.NumberColumn("Total", format="%.2f €"),
        "tipo": st.column_config.TextColumn("Tipo", width="small"),
    }
    
    st.subheader("📋 Registros del Período")
    st.dataframe(df_display, hide_index=True, use_container_width=True, column_config=column_config)
    
    st.markdown("---")
    export_df = df_completo.copy()
    export_df["date"] = pd.to_datetime(export_df["date_dt"], errors="coerce").dt.strftime("%d/%m/%Y")
    columnas_export = ["numero", "date", "concept", "base_amount", "vat_amount", "total", "tipo"]
    for col in columnas_export:
        if col not in export_df.columns:
            export_df[col] = ""
    export_df = export_df[columnas_export].copy()
    export_df.columns = ["Nº Factura", "Fecha", "Concepto", "Base Imponible", "Cuota IVA", "Total", "Tipo"]
    
    csv_bytes = export_df.to_csv(index=False, sep=';').encode('utf-8-sig')
    
    st.download_button(
        "⬇️ Exportar a CSV (compatible con Excel)",
        csv_bytes,
        f"Libro_Registro_{mes_seleccionado}_{anio_seleccionado}.csv",
        mime="text/csv",
        key="descargar_csv_libro"
    )

# ════════════════════════════════════════════════════════════
# CONTABILIDAD
# ════════════════════════════════════════════════════════════
elif menu == "📒 Contabilidad":
    st.title("Contabilidad de doble partida")
    submenu = st.radio("Seleccionar", ["Libro Diario", "Mayor", "PyG y Balance"])
    if submenu == "Libro Diario":
        entries = get_journal_entries(user_id)
        if not entries.empty:
            entry_id = st.selectbox("Selecciona un asiento", entries["id"].tolist(),
                                    format_func=lambda x: entries[entries["id"]==x]["date"].values[0] + " - " + entries[entries["id"]==x]["description"].values[0])
            try:
                lineas = supabase.table("journal_entry_lines").select("*").eq("journal_entry_id", entry_id).execute()
                lineas_df = pd.DataFrame(lineas.data) if lineas.data else pd.DataFrame()
                st.dataframe(lineas_df[["account", "debit", "credit", "description"]])
            except Exception as e:
                st.error(f"Error al cargar líneas del asiento: {e}")
        else:
            st.info("Aún no hay asientos contables.")
    elif submenu == "Mayor":
        try:
            entries_user = supabase.table("journal_entries").select("id").eq("user_id", user_id).execute()
            entry_ids = [e["id"] for e in entries_user.data] if entries_user.data else []
            if entry_ids:
                cuentas = supabase.table("journal_entry_lines").select("account").in_("journal_entry_id", entry_ids).execute()
                cuentas_df = pd.DataFrame(cuentas.data) if cuentas.data else pd.DataFrame()
            else:
                cuentas_df = pd.DataFrame()
            if not cuentas_df.empty:
                cuenta_sel = st.selectbox("Selecciona cuenta", cuentas_df["account"].unique())
                movs = supabase.table("journal_entry_lines").select("*, journal_entries(date)").in_("journal_entry_id", entry_ids).eq("account", cuenta_sel).execute()
                movs_df = pd.DataFrame(movs.data) if movs.data else pd.DataFrame()
                if not movs_df.empty:
                    movs_df["date"] = movs_df["journal_entries"].apply(lambda x: x["date"] if isinstance(x, dict) else "")
                    st.dataframe(movs_df[["date", "description", "debit", "credit"]])
                    saldo = movs_df["debit"].sum() - movs_df["credit"].sum()
                    st.metric("Saldo", money(saldo))
            else:
                st.info("Sin movimientos.")
        except Exception as e:
            st.error(f"Error al cargar mayor: {e}")
    elif submenu == "PyG y Balance":
        st.subheader("📊 Cuenta de Pérdidas y Ganancias")
        inv = get_invoices(user_id)
        exp = get_expenses(user_id)
        if not inv.empty:
            inv["year"] = pd.to_datetime(inv["date"], errors="coerce").dt.year
        if not exp.empty:
            exp["year"] = pd.to_datetime(exp["date"], errors="coerce").dt.year
        anios_disponibles = set()
        if not inv.empty: anios_disponibles.update(inv["year"].dropna().unique())
        if not exp.empty: anios_disponibles.update(exp["year"].dropna().unique())
        anios_disponibles = sorted(anios_disponibles, reverse=True)
        if not anios_disponibles:
            st.info("No hay datos para mostrar.")
            st.stop()
        anio_sel = st.selectbox("Año", anios_disponibles, index=0)
        inv_f = inv[inv["year"] == anio_sel] if not inv.empty else pd.DataFrame()
        exp_f = exp[exp["year"] == anio_sel] if not exp.empty else pd.DataFrame()
        total_ingresos = inv_f["base_amount"].sum() if not inv_f.empty else 0.0
        total_gastos = exp_f["base_amount"].sum() if not exp_f.empty else 0.0
        resultado_bruto = total_ingresos - total_gastos
        if not exp_f.empty and "expense_type" in exp_f.columns:
            gastos_por_tipo = exp_f.groupby("expense_type")["base_amount"].sum()
        else:
            gastos_por_tipo = pd.Series()
        col1, col2 = st.columns(2)
        with col1:
            st.markdown("**Ingresos**")
            st.write(f"Ventas y servicios: {money(total_ingresos)}")
            st.markdown("**Gastos**")
            for tipo, importe in gastos_por_tipo.items():
                st.write(f"{tipo}: {money(importe)}")
            st.write(f"**Total Gastos:** {money(total_gastos)}")
        with col2:
            st.markdown("**Resultados**")
            st.metric("Resultado Bruto (PyG)", money(resultado_bruto))
        st.markdown("---")
        st.subheader("⚖️ Balance de Situación (resumido)")
        activo_corriente = inv_f["total"].sum() if not inv_f.empty else 0.0
        pasivo_corriente = exp_f["total"].sum() if not exp_f.empty else 0.0
        patrimonio_neto = activo_corriente - pasivo_corriente
        col_b1, col_b2, col_b3 = st.columns(3)
        col_b1.metric("Activo", money(activo_corriente))
        col_b2.metric("Pasivo", money(pasivo_corriente))
        col_b3.metric("Patrimonio Neto", money(patrimonio_neto))
        st.caption("Balance simplificado.")

# ════════════════════════════════════════════════════════════
# IMPUESTOS TRIMESTRALES
# ════════════════════════════════════════════════════════════
elif menu == "🏛️ Impuestos Trimestrales":
    st.title("Liquidación Trimestral de IVA e IRPF")
    hoy = date.today()
    anio_actual = hoy.year
    mes_actual = hoy.month
    if mes_actual <= 3: trimestre_actual = "1T (Ene-Mar)"
    elif mes_actual <= 6: trimestre_actual = "2T (Abr-Jun)"
    elif mes_actual <= 9: trimestre_actual = "3T (Jul-Sep)"
    else: trimestre_actual = "4T (Oct-Dic)"
    
    anios_disponibles = list(range(anio_actual - 5, anio_actual + 6))
    anio = st.selectbox("Año", anios_disponibles, index=5)
    
    trimestres = ["1T (Ene-Mar)","2T (Abr-Jun)","3T (Jul-Sep)","4T (Oct-Dic)"]
    trimestre = st.selectbox("Trimestre", trimestres, index=trimestres.index(trimestre_actual))
    
    meses_trim = {
        "1T (Ene-Mar)": ["Enero","Febrero","Marzo"],
        "2T (Abr-Jun)": ["Abril","Mayo","Junio"],
        "3T (Jul-Sep)": ["Julio","Agosto","Septiembre"],
        "4T (Oct-Dic)": ["Octubre","Noviembre","Diciembre"]
    }
    meses = meses_trim[trimestre]
    inv = get_invoices(user_id)
    exp = get_expenses(user_id)
    if not inv.empty:
        inv["date_dt"] = pd.to_datetime(inv["date"], errors="coerce")
        inv["year"] = inv["date_dt"].dt.year
        inv = inv[(inv["year"] == anio) & (inv["month"].isin(meses))]
    if not exp.empty:
        exp["date_dt"] = pd.to_datetime(exp["date"], errors="coerce")
        exp["year"] = exp["date_dt"].dt.year
        exp = exp[(exp["year"] == anio) & (exp["month"].isin(meses))]
    base_ventas = inv["base_amount"].sum() if not inv.empty else 0.0
    iva_repercutido = inv["vat_amount"].sum() if not inv.empty else 0.0
    base_compras = exp["base_amount"].sum() if not exp.empty else 0.0
    iva_soportado = exp["vat_amount"].sum() if not exp.empty else 0.0
    irpf_retenido = inv["irpf_amount"].sum() if not inv.empty else 0.0
    beneficio_neto = base_ventas - base_compras
    pago_fraccionado = beneficio_neto * 0.20
    if pago_fraccionado < 0: pago_fraccionado = 0.0
    iva_ingresar = max(iva_repercutido - iva_soportado, 0)
    
    st.subheader(f"Resumen {trimestre} {anio}")
    col1,col2,col3 = st.columns(3)
    col1.metric("Ventas (base)", money(base_ventas))
    col2.metric("IVA repercutido", money(iva_repercutido))
    col3.metric("IRPF retenido", money(irpf_retenido))
    col4,col5,col6 = st.columns(3)
    col4.metric("Compras (base)", money(base_compras))
    col5.metric("IVA soportado", money(iva_soportado))
    col6.metric("IVA a ingresar", money(iva_ingresar))
    st.markdown("---")
    st.subheader("Pago fraccionado IRPF")
    col7,col8,col9 = st.columns(3)
    col7.metric("Beneficio neto", money(beneficio_neto))
    col8.metric("% aplicado", "20 %")
    col9.metric("💶 Pago fraccionado", money(pago_fraccionado))
    
    st.markdown("---")
    st.subheader("📄 Modelo 303")
    
    if st.button("Generar Modelo 303"):
        try:
            config_res = supabase.table("settings").select("company_tax_id, company_name").eq("user_id", user_id).execute()
            if config_res.data:
                nif_emisor = config_res.data[0].get("company_tax_id", "")
                nombre_emisor = config_res.data[0].get("company_name", "")
            else:
                nif_emisor = AUTONOMO_TAX_ID
                nombre_emisor = AUTONOMO_NAME
        except Exception:
            nif_emisor = AUTONOMO_TAX_ID
            nombre_emisor = AUTONOMO_NAME
        
        st.markdown("### Opciones de descarga")
        col_desc1, col_desc2 = st.columns(2)
        
        with col_desc1:
            st.markdown("**📄 Borrador PDF**")
            try:
                pdf_bytes_303 = generar_pdf_303(
                    anio, trimestre, base_ventas, iva_repercutido,
                    base_compras, iva_soportado, irpf_retenido,
                    beneficio_neto, pago_fraccionado, iva_ingresar
                )
                if pdf_bytes_303:
                    st.download_button("⬇️ Descargar PDF", pdf_bytes_303, f"Modelo_303_{anio}_{trimestre.replace(' ','')}.pdf", mime="application/pdf", key="descargar_pdf_303")
            except Exception as e:
                st.error(f"Error: {e}")
        
        with col_desc2:
            st.markdown("**💻 Fichero AEAT**")
            try:
                fichero_completo = generar_fichero_aeat_303(
                    anio, trimestre, base_ventas, iva_repercutido,
                    base_compras, iva_soportado, nif_emisor, nombre_emisor
                )
                st.download_button("⬇️ Descargar fichero", fichero_completo.encode('utf-8'), f"303_{anio}_{trimestre.replace(' ','')}.txt", mime="text/plain", key="descargar_fichero_303")
                es_valido, mensaje = validar_fichero_aeat(fichero_completo)
                if es_valido:
                    st.success(mensaje)
                else:
                    st.warning(mensaje)
            except Exception as e:
                st.error(f"Error: {e}")

# ════════════════════════════════════════════════════════════
# CONCILIACIÓN BANCARIA
# ════════════════════════════════════════════════════════════
elif menu == "🏦 Conciliación Bancaria":
    st.title("Conciliación Bancaria")
    tab1, tab2 = st.tabs(["Cargar CSV", "GoCardless"])
    with tab1:
        st.subheader("Cargar extracto bancario (CSV)")
        archivo_csv = st.file_uploader("Selecciona archivo CSV", type="csv")
        if archivo_csv:
            try:
                df_banco = pd.read_csv(archivo_csv)
                st.write("Vista previa:"); st.dataframe(df_banco.head(10))
                if st.button("Importar movimientos (CSV)"):
                    for _, row in df_banco.iterrows():
                        try:
                            supabase.table("bank_transactions").insert({
                                "user_id": user_id,
                                "date": str(row.get("date", "")),
                                "description": str(row.get("description", "")),
                                "amount": float(row.get("amount", 0))
                            }).execute()
                        except Exception as e:
                            st.error(f"Error: {e}")
                    st.success("Movimientos importados.")
                    get_bank_transactions.clear()
                    st.rerun()
            except Exception as e:
                st.error(f"Error al leer CSV: {e}")
    with tab2:
        st.subheader("Importar desde GoCardless")
        token_bancos = obtener_token_gocardless()
        if token_bancos:
            try:
                bancos = obtener_bancos_disponibles(token_bancos, "ES")
            except Exception:
                bancos = []
            if bancos:
                banco_dict = {b.get("name", "Desconocido"): b.get("id", "") for b in bancos}
                banco_seleccionado = st.selectbox("🏦 Selecciona tu banco", options=list(banco_dict.keys()))
                if "gocardless_step" not in st.session_state:
                    st.session_state.gocardless_step = "idle"
                if st.session_state.gocardless_step == "idle":
                    if st.button("🔌 Conectar con banco"):
                        institution_id = banco_dict[banco_seleccionado]
                        exito, link, req_id = iniciar_conexion_gocardless(institution_id)
                        if exito:
                            st.session_state.gocardless_link = link
                            st.session_state.gocardless_req_id = req_id
                            st.session_state.gocardless_step = "waiting_auth"
                            st.rerun()
                        else:
                            st.error(link)
                elif st.session_state.gocardless_step == "waiting_auth":
                    link = st.session_state.get("gocardless_link", "#")
                    st.info(f"🔗 [Abrir enlace de autorización]({link})")
                    if st.button("✅ He autorizado la cuenta"):
                        exito, mensaje, df = completar_importacion(user_id, supabase)
                        if exito:
                            st.success(mensaje)
                            if df is not None and not df.empty:
                                st.dataframe(df.head(10))
                            st.session_state.gocardless_step = "idle"
                            get_bank_transactions.clear()
                        else:
                            st.error(mensaje)
                        st.rerun()
            else:
                st.info("No se pudieron cargar los bancos.")
        else:
            st.error("No se pudo autenticar con GoCardless.")
    
    st.subheader("Movimientos sin conciliar")
    transacciones = get_bank_transactions(user_id)
    if not transacciones.empty:
        for idx, mov in transacciones.iterrows():
            with st.expander(f"{mov['date']} - {mov['description']} - {money(mov['amount'])}"):
                col1, col2 = st.columns(2)
                with col1:
                    with st.form(key=f"form_fact_{idx}"):
                        facturas = get_invoices(user_id)
                        factura_seleccionada = st.selectbox("Emparejar con factura", ["Ninguna"] + (facturas["invoice_number"].tolist() if not facturas.empty else []), key=f"fact_{idx}")
                        if st.form_submit_button("Vincular factura"):
                            if factura_seleccionada != "Ninguna":
                                id_factura = facturas.loc[facturas["invoice_number"] == factura_seleccionada, "id"].values[0]
                                try:
                                    supabase.table("bank_transactions").update({"matched_invoice_id": id_factura}).eq("id", mov["id"]).execute()
                                    st.success("Factura vinculada")
                                    get_bank_transactions.clear()
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Error: {e}")
                with col2:
                    with st.form(key=f"form_gasto_{idx}"):
                        gastos = get_expenses(user_id)
                        gasto_seleccionado = st.selectbox("Emparejar con gasto", ["Ninguno"] + (gastos["expense_number"].tolist() if not gastos.empty else []), key=f"gasto_{idx}")
                        if st.form_submit_button("Vincular gasto"):
                            if gasto_seleccionado != "Ninguno":
                                id_gasto = gastos.loc[gastos["expense_number"] == gasto_seleccionado, "id"].values[0]
                                try:
                                    supabase.table("bank_transactions").update({"matched_expense_id": id_gasto}).eq("id", mov["id"]).execute()
                                    st.success("Gasto vinculado")
                                    get_bank_transactions.clear()
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Error: {e}")
    else:
        st.info("No hay movimientos bancarios.")

# ════════════════════════════════════════════════════════════
# DASHBOARDS MEJORADO
# ════════════════════════════════════════════════════════════
elif menu == "📊 Dashboards":
    st.title("📊 Dashboards de Facturación")
    
    invoices = get_invoices(user_id)
    expenses = get_expenses(user_id)
    
    if invoices.empty and expenses.empty:
        st.info("No hay datos para mostrar.")
        st.stop()
    
    if not invoices.empty:
        invoices["date_dt"] = pd.to_datetime(invoices["date"], errors="coerce")
        invoices["year"] = invoices["date_dt"].dt.year
        invoices["month_name"] = invoices["date_dt"].dt.month.apply(lambda x: LISTA_MESES[x-1] if 1 <= x <= 12 else "Desconocido")
        invoices["month_num"] = invoices["date_dt"].dt.month
    
    if not expenses.empty:
        expenses["date_dt"] = pd.to_datetime(expenses["date"], errors="coerce")
        expenses["year"] = expenses["date_dt"].dt.year
        expenses["month_name"] = expenses["date_dt"].dt.month.apply(lambda x: LISTA_MESES[x-1] if 1 <= x <= 12 else "Desconocido")
        expenses["month_num"] = expenses["date_dt"].dt.month
    
    st.subheader("🔍 Filtros")
    col_f1, col_f2, col_f3 = st.columns(3)
    with col_f1:
        anios_disponibles = set()
        if not invoices.empty: anios_disponibles.update(invoices["year"].dropna().unique())
        if not expenses.empty: anios_disponibles.update(expenses["year"].dropna().unique())
        anios_disponibles = sorted(anios_disponibles, reverse=True)
        year_seleccionado = st.selectbox("📅 Año", anios_disponibles, index=0 if anios_disponibles else 0)
    with col_f2:
        opciones_meses = ["Todos"] + LISTA_MESES
        mes_seleccionado = st.selectbox("📆 Mes", opciones_meses, index=0)
    with col_f3:
        tipo_grafico = st.selectbox("📈 Tipo", ["Barras", "Líneas", "Área"], index=0)
    
    data_inv = invoices[invoices["year"] == year_seleccionado].copy() if not invoices.empty else pd.DataFrame()
    data_exp = expenses[expenses["year"] == year_seleccionado].copy() if not expenses.empty else pd.DataFrame()
    
    if mes_seleccionado != "Todos":
        if not data_inv.empty: data_inv = data_inv[data_inv["month_name"] == mes_seleccionado]
        if not data_exp.empty: data_exp = data_exp[data_exp["month_name"] == mes_seleccionado]
    
    if data_inv.empty and data_exp.empty:
        st.warning("No hay datos en el período.")
        st.stop()
    
    st.markdown("---")
    st.subheader("📊 Indicadores Clave")
    
    total_ingresos = data_inv["total"].sum() if not data_inv.empty else 0.0
    total_gastos = data_exp["total"].sum() if not data_exp.empty else 0.0
    num_facturas = len(data_inv) if not data_inv.empty else 0
    beneficio = total_ingresos - total_gastos
    promedio_factura = total_ingresos / num_facturas if num_facturas > 0 else 0
    iva_repercutido = data_inv["vat_amount"].sum() if not data_inv.empty else 0.0
    iva_soportado = data_exp["vat_amount"].sum() if not data_exp.empty else 0.0
    
    kpi1, kpi2, kpi3, kpi4 = st.columns(4)
    kpi1.metric("💰 Ingresos", money(total_ingresos))
    kpi2.metric("📄 Facturas", num_facturas)
    kpi3.metric("🧾 Gastos", money(total_gastos))
    kpi4.metric("📊 Promedio", money(promedio_factura))
    
    kpi5, kpi6, kpi7, kpi8 = st.columns(4)
    kpi5.metric("🔥 Beneficio", money(beneficio))
    kpi6.metric("IVA Repercutido", money(iva_repercutido))
    kpi7.metric("IVA Soportado", money(iva_soportado))
    kpi8.metric("IVA Neto", money(iva_repercutido - iva_soportado))
    
    st.markdown("---")
    st.subheader("📈 Ingresos vs Gastos")
    
    if mes_seleccionado == "Todos":
        ing_mensual = data_inv.groupby(["month_num", "month_name"])["total"].sum().reset_index().sort_values("month_num") if not data_inv.empty else pd.DataFrame(columns=["month_num", "month_name", "total"])
        gas_mensual = data_exp.groupby(["month_num", "month_name"])["total"].sum().reset_index().sort_values("month_num") if not data_exp.empty else pd.DataFrame(columns=["month_num", "month_name", "total"])
        meses_todos = pd.DataFrame({"month_num": range(1, 13), "month_name": LISTA_MESES})
        df_grafico = meses_todos.merge(ing_mensual[["month_num", "total"]].rename(columns={"total": "ingresos"}), on="month_num", how="left").merge(gas_mensual[["month_num", "total"]].rename(columns={"total": "gastos"}), on="month_num", how="left").fillna(0)
        x_labels = df_grafico["month_name"].tolist()
        titulo = f"Ingresos vs Gastos {year_seleccionado}"
    else:
        if not data_inv.empty:
            data_inv["day"] = data_inv["date_dt"].dt.day
            ing_diario = data_inv.groupby("day")["total"].sum().reset_index()
        else:
            ing_diario = pd.DataFrame(columns=["day", "total"])
        if not data_exp.empty:
            data_exp["day"] = data_exp["date_dt"].dt.day
            gas_diario = data_exp.groupby("day")["total"].sum().reset_index()
        else:
            gas_diario = pd.DataFrame(columns=["day", "total"])
        dias_todos = pd.DataFrame({"day": range(1, 32)})
        df_grafico = dias_todos.merge(ing_diario.rename(columns={"total": "ingresos"}), on="day", how="left").merge(gas_diario.rename(columns={"total": "gastos"}), on="day", how="left").fillna(0)
        x_labels = [str(d) for d in df_grafico["day"]]
        titulo = f"Ingresos vs Gastos {mes_seleccionado} {year_seleccionado}"
    
    if not df_grafico.empty:
        fig, ax = plt.subplots(figsize=(12, 6))
        x_pos = range(len(x_labels))
        width = 0.35
        if tipo_grafico == "Barras":
            ax.bar([p - width/2 for p in x_pos], df_grafico["ingresos"], width, label="Ingresos", color="#10B981")
            ax.bar([p + width/2 for p in x_pos], df_grafico["gastos"], width, label="Gastos", color="#EF4444")
        elif tipo_grafico == "Líneas":
            ax.plot(x_pos, df_grafico["ingresos"], marker="o", label="Ingresos", color="#10B981", linewidth=2)
            ax.plot(x_pos, df_grafico["gastos"], marker="s", label="Gastos", color="#EF4444", linewidth=2)
        else:
            ax.fill_between(x_pos, df_grafico["ingresos"], alpha=0.5, label="Ingresos", color="#10B981")
            ax.fill_between(x_pos, df_grafico["gastos"], alpha=0.5, label="Gastos", color="#EF4444")
        ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f} €"))
        ax.set_xticks(x_pos)
        ax.set_xticklabels(x_labels, rotation=45, ha="right")
        ax.set_title(titulo, fontweight="bold")
        ax.legend()
        ax.grid(axis="y", linestyle="--", alpha=0.7)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        fig.tight_layout()
        st.pyplot(fig)
    
    st.markdown("---")
    col_g1, col_g2 = st.columns(2)
    with col_g1:
        st.subheader("🏆 Top Clientes")
        if not data_inv.empty and "client_name" in data_inv.columns:
            top_clientes = data_inv.groupby("client_name")["total"].sum().sort_values(ascending=False).head(5)
            if not top_clientes.empty:
                fig2, ax2 = plt.subplots(figsize=(8, 5))
                ax2.barh(range(len(top_clientes)), top_clientes.values, color="#1E3A8A")
                ax2.set_yticks(range(len(top_clientes)))
                ax2.set_yticklabels(top_clientes.index, fontsize=10)
                ax2.invert_yaxis()
                ax2.set_title("Top 5 Clientes", fontweight="bold")
                fig2.tight_layout()
                st.pyplot(fig2)
    with col_g2:
        st.subheader("📊 Estados de Facturas")
        if not data_inv.empty and "status" in data_inv.columns:
            estados = data_inv["status"].value_counts()
            if not estados.empty:
                fig3, ax3 = plt.subplots(figsize=(8, 5))
                colores = {"pendiente": "#F59E0B", "pagada": "#10B981", "vencida": "#EF4444", "anulada": "#6B7280", "rectificada": "#3B82F6"}
                colors_list = [colores.get(e, "#6B7280") for e in estados.index]
                ax3.pie(estados.values, labels=estados.index, autopct='%1.1f%%', colors=colors_list, startangle=90)
                ax3.set_title("Estado de Facturas", fontweight="bold")
                fig3.tight_layout()
                st.pyplot(fig3)
                

 
# ════════════════════════════════════════════════════════════
# PRESUPUESTOS (Edición funcional + Vista previa profesional + PDF correcto)
# ════════════════════════════════════════════════════════════
import io
import json
import time
from datetime import date, datetime
import pandas as pd
import streamlit as st
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm

# ============================================================
# FUNCIÓN GENERADORA DE PDF DE PRESUPUESTO
# ============================================================
def make_budget_pdf(empresa, cliente, lineas, base_total, vat_total, total, vat_pct=21.0, budget_number="P-0000"):
    buffer = io.BytesIO()
    
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=1.5 * cm,
        rightMargin=1.5 * cm,
        topMargin=1.5 * cm,
        bottomMargin=1.5 * cm
    )
    
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Heading1'],
        fontSize=14,
        leading=16,
        textColor=colors.HexColor("#1A365D"),
        spaceAfter=4
    )
    
    body_style = ParagraphStyle(
        'DocBody',
        parent=styles['Normal'],
        fontSize=8.5,
        leading=11,
        textColor=colors.HexColor("#2D3748")
    )
    
    bold_style = ParagraphStyle(
        'DocBold',
        parent=body_style,
        fontName='Helvetica-Bold'
    )
    
    desc_style = ParagraphStyle(
        'DescStyle',
        parent=body_style,
        fontSize=8,
        leading=10,
        textColor=colors.HexColor("#2D3748")
    )
    
    table_header_style = ParagraphStyle(
        'TableHeader',
        parent=body_style,
        fontName='Helvetica-Bold',
        textColor=colors.white,
        fontSize=8.5,
        leading=10
    )

    story = []

    # 1. Cabecera (Empresa y Cliente)
    empresa_info = f"""
    <b>{empresa.get('company_name', 'Empresa')}</b><br/>
    NIF/CIF: {empresa.get('company_tax_id', '')}<br/>
    {empresa.get('company_address', '')}<br/>
    {f"Tel: {empresa.get('company_phone', '')}<br/>" if empresa.get('company_phone') else ''}
    {f"Email: {empresa.get('company_email', '')}" if empresa.get('company_email') else ''}
    """
    
    cliente_info = f"""
    <b>DATOS DEL CLIENTE:</b><br/>
    <b>{cliente.get('name', 'Cliente')}</b><br/>
    NIF/CIF: {cliente.get('tax_id', '')}<br/>
    {cliente.get('address', '')}
    """
    
    header_table = Table(
        [[Paragraph(empresa_info.strip(), body_style), Paragraph(cliente_info.strip(), body_style)]],
        colWidths=[255, 255]
    )
    header_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
        ('TOPPADDING', (0, 0), (-1, -1), 0),
    ]))
    
    story.append(header_table)
    story.append(Spacer(1, 10))

    # 2. Datos del Presupuesto
    fecha_str = date.today().strftime("%d/%m/%Y")
    story.append(Paragraph(f"<b>PRESUPUESTO {budget_number}</b>", title_style))
    story.append(Paragraph(f"<b>Fecha de emisión:</b> {fecha_str}", body_style))
    story.append(Spacer(1, 10))

    # 3. Tabla de Líneas
    table_data = [
        [
            Paragraph("Descripción / Concepto", table_header_style),
            Paragraph("Cant.", table_header_style),
            Paragraph("Precio Ud.", table_header_style),
            Paragraph("Total", table_header_style)
        ]
    ]

    for item in lineas:
        desc_formatted = str(item.get("description", "")).replace("\n", "<br/>")
        cant_val = float(item.get("quantity", 1))
        precio_val = float(item.get("unit_price", 0))
        total_val = float(item.get("total", cant_val * precio_val))

        table_data.append([
            Paragraph(desc_formatted, desc_style),
            Paragraph(f"{cant_val:,.2f}".replace(",", "@").replace(".", ",").replace("@", "."), body_style),
            Paragraph(f"{precio_val:,.2f} €".replace(",", "@").replace(".", ",").replace("@", "."), body_style),
            Paragraph(f"{total_val:,.2f} €".replace(",", "@").replace(".", ",").replace("@", "."), body_style)
        ])

    items_table = Table(table_data, colWidths=[310, 45, 75, 80])
    items_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#1A365D")),
        ('ALIGN', (1, 0), (-1, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E0")),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
    ]))
    
    story.append(items_table)
    story.append(Spacer(1, 10))

    # 4. Resumen de Totales
    def fmt_money(val):
        return f"{float(val):,.2f} €".replace(",", "@").replace(".", ",").replace("@", ".")

    totales_data = [
        [Paragraph("Base Imponible:", body_style), Paragraph(fmt_money(base_total), body_style)],
        [Paragraph(f"IVA ({vat_pct:.2f}%):", body_style), Paragraph(fmt_money(vat_total), body_style)]
    ]
    
    irpf_val = sum(float(l.get("irpf_amount", 0)) for l in lineas) if lineas else 0.0
    if irpf_val > 0:
        totales_data.append([Paragraph("Retención IRPF:", body_style), Paragraph(f"-{fmt_money(irpf_val)}", body_style)])

    totales_data.append([Paragraph("<b>TOTAL:</b>", bold_style), Paragraph(f"<b>{fmt_money(total)}</b>", bold_style)])

    totales_table = Table(totales_data, colWidths=[120, 80])
    totales_table.setStyle(TableStyle([
        ('ALIGN', (0, 0), (-1, -1), 'RIGHT'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('LINEABOVE', (0, -1), (-1, -1), 1, colors.HexColor("#1A365D")),
    ]))

    wrapper_table = Table([["", totales_table]], colWidths=[310, 200])
    wrapper_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('LEFTPADDING', (0, 0), (-1, -1), 0),
        ('RIGHTPADDING', (0, 0), (-1, -1), 0),
    ]))

    story.append(KeepTogether([wrapper_table]))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


# ============================================================
# MÓDULO PRESUPUESTOS (STREAMLIT)
# ============================================================
elif menu == "📝 Presupuestos":
    st.title("📝 Presupuestos")
    
    try:
        config_res = supabase.table("settings").select("*").eq("user_id", user_id).execute()
        if config_res.data:
            empresa = config_res.data[0]
            if "user_id" not in empresa:
                empresa["user_id"] = user_id
        else:
            empresa = {"user_id": user_id, "company_name": AUTONOMO_NAME, "company_tax_id": AUTONOMO_TAX_ID, "company_address": AUTONOMO_ADDRESS, "company_iban": AUTONOMO_IBAN, "company_phone": "", "company_email": "", "company_logo": ""}
    except Exception:
        empresa = {"user_id": user_id, "company_name": AUTONOMO_NAME, "company_tax_id": AUTONOMO_TAX_ID, "company_address": AUTONOMO_ADDRESS, "company_iban": AUTONOMO_IBAN, "company_phone": "", "company_email": "", "company_logo": ""}

    if "editing_budget_id" not in st.session_state:
        st.session_state.editing_budget_id = None
    if "edit_budget_data" not in st.session_state:
        st.session_state.edit_budget_data = None
    if "budget_number_editing" not in st.session_state:
        st.session_state.budget_number_editing = None

    def limpiar_estado_edicion():
        st.session_state.editing_budget_id = None
        st.session_state.edit_budget_data = None
        st.session_state.budget_number_editing = None

    tab_nuevo, tab_historial = st.tabs(["Nuevo / Editar presupuesto", "Historial de presupuestos"])

    with tab_nuevo:
        clientes_df = get_clients(user_id)
        productos_df = get_products(user_id)
        if not productos_df.empty:
            for col in ["description", "price", "default_vat_percentage", "default_irpf_percentage"]:
                if col not in productos_df.columns:
                    productos_df[col] = "" if col == "description" else 0.0

        if st.session_state.editing_budget_id and st.session_state.edit_budget_data:
            st.warning(f"✏️ **Editando presupuesto {st.session_state.budget_number_editing}** - Modifica los campos y guarda los cambios.")
            if st.button("❌ Cancelar edición", key="cancel_edit_btn"):
                limpiar_estado_edicion()
                st.rerun()
        else:
            st.info("➕ Creando nuevo presupuesto")

        if st.session_state.editing_budget_id and st.session_state.edit_budget_data:
            budget_data = st.session_state.edit_budget_data
            cliente_pre = {
                "name": budget_data.get("client_name", ""),
                "tax_id": budget_data.get("client_tax_id", ""),
                "address": budget_data.get("client_address", "")
            }
            lineas_pre = json.loads(budget_data.get("lines", "[]")) if budget_data.get("lines") else []
            fecha_pre = budget_data.get("date", str(date.today()))
            try:
                fecha_pre_dt = datetime.strptime(fecha_pre, "%Y-%m-%d").date()
            except:
                fecha_pre_dt = date.today()
            vat_pct_pre = float(budget_data.get("vat_pct", 21.0))
            irpf_pct_pre = float(budget_data.get("irpf_pct", 0.0))
        else:
            cliente_pre = {"name": "", "tax_id": "", "address": ""}
            lineas_pre = []
            fecha_pre_dt = date.today()
            vat_pct_pre = 21.0
            irpf_pct_pre = 0.0

        st.markdown("---")
        st.subheader("Datos del cliente")
        
        modo_cliente = st.radio(
            "Seleccionar cliente",
            ["Existente", "Nuevo (manual)"],
            horizontal=True,
            key="modo_cliente"
        )
        
        if modo_cliente == "Existente":
            if clientes_df.empty:
                cliente = {"name": "", "tax_id": "", "address": ""}
            else:
                cliente_sel = st.selectbox(
                    "Cliente",
                    clientes_df["name"].tolist(),
                    key="cliente_select_presupuesto"
                )
                cliente_row = clientes_df[clientes_df["name"] == cliente_sel].iloc[0]
                cliente = {
                    "name": cliente_row["name"],
                    "tax_id": cliente_row["tax_id"],
                    "address": cliente_row["address"]
                }
        else:
            cliente = {
                "name": st.text_input("Nombre/Razón Social", value=cliente_pre["name"], key="manual_name_budget"),
                "tax_id": st.text_input("RTN / NIF", value=cliente_pre["tax_id"], key="manual_taxid_budget"),
                "address": st.text_input("Dirección", value=cliente_pre["address"], key="manual_address_budget")
            }

        fecha = st.date_input("Fecha del presupuesto", value=fecha_pre_dt, key="fecha_presupuesto_edit")
        
        st.markdown("---")
        st.subheader("Líneas del presupuesto")
        
        num_lineas = st.number_input(
            "Número de líneas",
            min_value=1,
            max_value=20,
            value=max(len(lineas_pre), 1),
            key="num_lineas_budget"
        )
        
        lista_productos = ["-- Manual --"]
        if not productos_df.empty:
            lista_productos += productos_df["name"].tolist()
        
        lineas = []
        for i in range(int(num_lineas)):
            lin_pre = lineas_pre[i] if i < len(lineas_pre) else None
            
            cols = st.columns([3, 2, 2, 2])
            
            with cols[0]:
                prod_default = "-- Manual --"
                if lin_pre and lin_pre.get("description"):
                    desc = lin_pre.get("description", "")
                    for p in lista_productos:
                        if p != "-- Manual --" and p in desc:
                            prod_default = p
                            break
                
                prod_sel = st.selectbox(
                    f"Producto {i+1}",
                    lista_productos,
                    key=f"bud_prod_edit_{i}",
                    index=lista_productos.index(prod_default) if prod_default in lista_productos else 0
                )
                
                if prod_sel == "-- Manual --":
                    desc_manual = st.text_input(
                        f"Descripción {i+1}",
                        value=lin_pre.get("description", "") if lin_pre else "",
                        key=f"bud_desc_edit_{i}"
                    )
                else:
                    prod_info = productos_df[productos_df["name"] == prod_sel]
                    descripcion_producto = prod_info.iloc[0].get("description", "") if not prod_info.empty else ""
                    desc_manual = st.text_area(
                        f"Descripción {i+1} (editable)",
                        value=lin_pre.get("description", "") if lin_pre else descripcion_producto,
                        key=f"bud_desc_edit_{i}",
                        height=80
                    )
            
            with cols[1]:
                cantidad = st.number_input(
                    f"Cantidad {i+1}",
                    min_value=1.0,
                    value=float(lin_pre["quantity"]) if lin_pre else 1.0,
                    key=f"bud_qty_edit_{i}"
                )
            
            with cols[2]:
                if prod_sel != "-- Manual --" and not productos_df.empty:
                    prod_row = productos_df[productos_df["name"] == prod_sel]
                    if not prod_row.empty:
                        precio_default = prod_row.iloc[0]["price"]
                        vat_default = prod_row.iloc[0]["default_vat_percentage"]
                        irpf_default = 0.0
                    else:
                        precio_default = float(lin_pre["unit_price"]) if lin_pre else 0.0
                        vat_default = float(lin_pre.get("vat_percentage", 21)) if lin_pre else 21.0
                        irpf_default = float(lin_pre.get("irpf_percentage", 0)) if lin_pre else 0.0
                else:
                    precio_default = float(lin_pre["unit_price"]) if lin_pre else 0.0
                    vat_default = float(lin_pre.get("vat_percentage", vat_pct_pre)) if lin_pre else vat_pct_pre
                    irpf_default = float(lin_pre.get("irpf_percentage", irpf_pct_pre)) if lin_pre else irpf_pct_pre
                
                precio = st.number_input(
                    f"Precio ud. {i+1}",
                    min_value=0.0,
                    value=precio_default,
                    key=f"bud_price_edit_{i}"
                )
                vat = st.number_input(f"IVA % {i+1}", value=vat_default, key=f"bud_vat_edit_{i}")
                irpf = st.number_input(f"IRPF % {i+1}", value=irpf_default, key=f"bud_irpf_edit_{i}")
            
            with cols[3]:
                base_linea = cantidad * precio
                vat_amount = base_linea * vat / 100
                irpf_amount = base_linea * irpf / 100
                total_linea = base_linea + vat_amount - irpf_amount
                st.text(f"Total: {money(total_linea)}")
            
            descripcion_linea = (
                f"{prod_sel}\n{desc_manual.strip()}" if prod_sel != "-- Manual --" and desc_manual.strip()
                else (desc_manual.strip() if desc_manual.strip() else prod_sel)
            )
            
            lineas.append({
                "description": descripcion_linea,
                "quantity": cantidad,
                "unit_price": precio,
                "base_amount": base_linea,
                "vat_percentage": vat,
                "vat_amount": vat_amount,
                "irpf_percentage": irpf,
                "irpf_amount": irpf_amount,
                "total": total_linea
            })

        if lineas:
            base_total = sum(l["base_amount"] for l in lineas)
            vat_total = sum(l["vat_amount"] for l in lineas)
            irpf_total = sum(l["irpf_amount"] for l in lineas)
            total = base_total + vat_total - irpf_total
        else:
            base_total = vat_total = irpf_total = total = 0.0

        st.markdown("---")
        st.subheader("🔍 Vista previa del presupuesto")
        
        with st.container(border=True):
            col_empresa, col_cliente = st.columns(2)
            
            with col_empresa:
                st.markdown(f"### 📋 {empresa.get('company_name', 'Empresa')}")
                st.markdown(f"**NIF:** {empresa.get('company_tax_id', '')}")
                st.markdown(f"**Dirección:** {empresa.get('company_address', '')}")
                if empresa.get('company_email'):
                    st.markdown(f"**Email:** {empresa.get('company_email', '')}")
                if empresa.get('company_phone'):
                    st.markdown(f"**Tel:** {empresa.get('company_phone', '')}")
            
            with col_cliente:
                st.markdown(f"### 👤 {cliente.get('name', 'Cliente')}")
                st.markdown(f"**Dirección:** {cliente.get('address', '')}")
                st.markdown(f"**Fecha:** {fecha.strftime('%d/%m/%Y')}")
                numero_mostrar = st.session_state.budget_number_editing or obtener_siguiente_numero_presupuesto(user_id)
                st.markdown(f"**Nº Presupuesto:** {numero_mostrar}")
            
            st.markdown("---")
            
            if lineas:
                lineas_df = pd.DataFrame(lineas)
                vista_df = lineas_df[["description", "quantity", "unit_price", "vat_percentage", "vat_amount", "total"]].copy()
                vista_df.columns = ["Descripción", "Cant.", "Precio ud.", "IVA %", "IVA €", "Total"]
                vista_df["Precio ud."] = vista_df["Precio ud."].apply(lambda x: f"{x:,.2f} €")
                vista_df["IVA €"] = vista_df["IVA €"].apply(lambda x: f"{x:,.2f} €")
                vista_df["Total"] = vista_df["Total"].apply(lambda x: f"{x:,.2f} €")
                
                column_config_preview = {
                    "Descripción": st.column_config.TextColumn("Descripción", width="large"),
                    "Cant.": st.column_config.NumberColumn("Cant.", width="small"),
                    "Precio ud.": st.column_config.TextColumn("Precio ud.", width="small"),
                    "IVA %": st.column_config.NumberColumn("IVA %", width="small"),
                    "IVA €": st.column_config.TextColumn("IVA €", width="small"),
                    "Total": st.column_config.TextColumn("Total", width="small"),
                }
                
                st.dataframe(
                    vista_df,
                    hide_index=True,
                    use_container_width=True,
                    column_config=column_config_preview
                )
            
            st.markdown("---")
            
            col_tot1, col_tot2 = st.columns([2, 1])
            
            with col_tot2:
                st.markdown("### Resumen")
                st.markdown(f"**Base imponible:** {money(base_total)}")
                st.markdown(f"**IVA ({lineas[0]['vat_percentage'] if lineas else 0:.2f}%):** {money(vat_total)}")
                if irpf_total > 0:
                    st.markdown(f"**IRPF ({lineas[0]['irpf_percentage'] if lineas else 0:.2f}%):** -{money(irpf_total)}")
                st.markdown("---")
                st.markdown(f"## **TOTAL: {money(total)}**")

        st.markdown("---")
        
        col_acc1, col_acc2 = st.columns(2)
        
        with col_acc1:
            if st.button("💾 Guardar presupuesto", key="guardar_presupuesto_edit"):
                if not validar_nif_cif(cliente.get("tax_id", "")):
                    st.error("El NIF del cliente no es válido.")
                else:
                    if st.session_state.editing_budget_id:
                        try:
                            supabase.table("budgets").update({
                                "date": str(fecha),
                                "client_name": cliente.get("name", ""),
                                "client_tax_id": cliente.get("tax_id", ""),
                                "client_address": cliente.get("address", ""),
                                "lines": json.dumps(lineas),
                                "base_total": base_total,
                                "vat_total": vat_total,
                                "irpf_total": irpf_total,
                                "total": total,
                                "vat_pct": lineas[0]["vat_percentage"] if lineas else 21,
                                "irpf_pct": lineas[0]["irpf_percentage"] if lineas else 0,
                            }).eq("id", st.session_state.editing_budget_id).execute()
                            
                            st.success(f"Presupuesto {st.session_state.budget_number_editing} actualizado correctamente.")
                            limpiar_estado_edicion()
                            get_budgets.clear()
                            time.sleep(0.5)
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error al actualizar: {e}")
                    else:
                        budget_number = obtener_siguiente_numero_presupuesto(user_id)
                        data = {
                            "user_id": user_id,
                            "budget_number": budget_number,
                            "date": str(fecha),
                            "client_name": cliente.get("name", ""),
                            "client_tax_id": cliente.get("tax_id", ""),
                            "client_address": cliente.get("address", ""),
                            "lines": json.dumps(lineas),
                            "base_total": base_total,
                            "vat_total": vat_total,
                            "irpf_total": irpf_total,
                            "total": total,
                            "vat_pct": lineas[0]["vat_percentage"] if lineas else 21,
                            "irpf_pct": lineas[0]["irpf_percentage"] if lineas else 0,
                            "status": "pendiente"
                        }
                        try:
                            supabase.table("budgets").insert(data).execute()
                            st.success(f"Presupuesto {budget_number} guardado correctamente.")
                            get_budgets.clear()
                            time.sleep(0.5)
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error al guardar: {e}")
        
        with col_acc2:
            if st.button("📄 Generar PDF del presupuesto", key="pdf_presupuesto_edit"):
                if not validar_nif_cif(cliente.get("tax_id", "")):
                    st.error("El NIF del cliente no es válido.")
                else:
                    empresa["user_id"] = user_id
                    vat_pct = lineas[0]["vat_percentage"] if lineas else 21
                    
                    if st.session_state.editing_budget_id and st.session_state.budget_number_editing:
                        numero_pdf = st.session_state.budget_number_editing
                    else:
                        numero_pdf = obtener_siguiente_numero_presupuesto(user_id)
                    
                    cliente_pdf = {
                        "name": cliente.get("name", ""),
                        "tax_id": cliente.get("tax_id", ""),
                        "address": cliente.get("address", "")
                    }
                    
                    if empresa and cliente_pdf and lineas:
                        pdf_bytes = make_budget_pdf(
                            empresa, cliente_pdf, lineas,
                            base_total, vat_total, total,
                            vat_pct, budget_number=numero_pdf
                        )
                        if pdf_bytes:
                            st.download_button(
                                "⬇️ Descargar PDF",
                                pdf_bytes,
                                f"Presupuesto_{numero_pdf}.pdf",
                                mime="application/pdf",
                                key="download_pdf_edit"
                            )
                            destinatario = st.text_input(
                                "Email para enviar presupuesto",
                                key="email_presupuesto_edit",
                                placeholder="cliente@ejemplo.com"
                            )
                            if st.button("📧 Enviar por email", key="send_budget_email_edit"):
                                if not destinatario or "@" not in destinatario:
                                    st.error("Introduce un email válido.")
                                else:
                                    with st.spinner("Enviando..."):
                                        exito = enviar_factura_email(
                                            destinatario,
                                            f"Presupuesto {numero_pdf}",
                                            "Adjunto le enviamos el presupuesto.",
                                            pdf_bytes,
                                            f"Presupuesto_{numero_pdf}.pdf"
                                        )
                                    if exito:
                                        st.success("Presupuesto enviado correctamente")
                                    else:
                                        st.error("No se pudo enviar el email")

    with tab_historial:
        st.subheader("Presupuestos guardados")
        budgets_df = get_budgets(user_id)
        
        if not budgets_df.empty:
            budgets_display = budgets_df[["budget_number", "date", "client_name", "total", "status"]].copy()
            budgets_display.columns = ["Nº Presupuesto", "Fecha", "Cliente", "Total", "Estado"]
            budgets_display["Fecha"] = pd.to_datetime(budgets_display["Fecha"]).dt.strftime("%d/%m/%Y")
            
            column_config = {
                "Nº Presupuesto": st.column_config.TextColumn("Nº Presupuesto", width="small"),
                "Fecha": st.column_config.TextColumn("Fecha", width="small"),
                "Cliente": st.column_config.TextColumn("Cliente", width="medium"),
                "Total": st.column_config.NumberColumn("Total", format="%.2f €", width="small"),
                "Estado": st.column_config.TextColumn("Estado", width="small"),
            }
            
            event = st.dataframe(
                budgets_display,
                hide_index=True,
                use_container_width=True,
                column_config=column_config,
                selection_mode="single-row",
                on_select="rerun",
                key="budgets_table_historial"
            )
            
            if (event.selection and event.selection.rows and len(event.selection.rows) > 0):
                selected_row = event.selection.rows[0]
                if selected_row is not None and 0 <= selected_row < len(budgets_df):
                    budget_row = budgets_df.iloc[selected_row]
                    budget_id = budget_row["id"]
                    budget_number_sel = budget_row["budget_number"]
                    
                    try:
                        resp = supabase.table("budgets").select("*").eq("id", budget_id).single().execute()
                        budget_data = resp.data if resp.data else budget_row.to_dict()
                    except Exception:
                        budget_data = budget_row.to_dict()
                    
                    st.markdown("---")
                    
                    with st.container(border=True):
                        col_info1, col_info2 = st.columns(2)
                        
                        with col_info1:
                            st.markdown(f"### 📄 Presupuesto {budget_number_sel}")
                            st.markdown(f"**Fecha:** {pd.to_datetime(budget_data.get('date', '')).strftime('%d/%m/%Y') if budget_data.get('date') else 'N/A'}")
                            st.markdown(f"**Estado:** {budget_data.get('status', 'pendiente')}")
                        
                        with col_info2:
                            st.markdown(f"**Cliente:** {budget_data.get('client_name', 'N/A')}")
                            st.markdown(f"**NIF/CIF:** {budget_data.get('client_tax_id', 'N/A')}")
                            st.markdown(f"**Dirección:** {budget_data.get('client_address', 'N/A')}")
                        
                        st.markdown("---")
                        
                        try:
                            lineas_db = json.loads(budget_data.get("lines", "[]"))
                            if lineas_db:
                                lineas_hist_df = pd.DataFrame(lineas_db)
                                
                                columnas_necesarias = ["description", "quantity", "unit_price", "total"]
                                for col in columnas_necesarias:
                                    if col not in lineas_hist_df.columns:
                                        lineas_hist_df[col] = 0 if col != "description" else ""
                                
                                hist_display = lineas_hist_df[columnas_necesarias].copy()
                                hist_display.columns = ["Descripción", "Cant.", "Precio ud.", "Total"]
                                hist_display["Precio ud."] = hist_display["Precio ud."].apply(lambda x: f"{float(x):,.2f} €")
                                hist_display["Total"] = hist_display["Total"].apply(lambda x: f"{float(x):,.2f} €")
                                
                                column_config_hist = {
                                    "Descripción": st.column_config.TextColumn("Descripción", width="large"),
                                    "Cant.": st.column_config.NumberColumn("Cant.", width="small"),
                                    "Precio ud.": st.column_config.TextColumn("Precio ud.", width="small"),
                                    "Total": st.column_config.TextColumn("Total", width="small"),
                                }
                                
                                st.dataframe(
                                    hist_display,
                                    hide_index=True,
                                    use_container_width=True,
                                    column_config=column_config_hist
                                )
                            
                            st.markdown("---")
                            col_tot_hist1, col_tot_hist2 = st.columns([2, 1])
                            
                            with col_tot_hist2:
                                st.markdown("### Resumen")
                                st.markdown(f"**Base imponible:** {money(budget_data.get('base_total', 0))}")
                                st.markdown(f"**IVA ({budget_data.get('vat_pct', 21):.2f}%):** {money(budget_data.get('vat_total', 0))}")
                                irpf_hist = budget_data.get('irpf_total', 0)
                                if irpf_hist and irpf_hist > 0:
                                    st.markdown(f"**IRPF:** -{money(irpf_hist)}")
                                st.markdown("---")
                                st.markdown(f"## **TOTAL: {money(budget_data.get('total', 0))}**")
                        except Exception as e:
                            st.warning(f"No se pudieron cargar las líneas del presupuesto: {e}")
                    
                    st.markdown("---")
                    
                    col1, col2, col3 = st.columns(3)
                    
                    with col1:
                        if st.button("✏️ Editar", key=f"edit_btn_{budget_id}"):
                            st.session_state.editing_budget_id = budget_id
                            st.session_state.edit_budget_data = budget_data
                            st.session_state.budget_number_editing = budget_number_sel
                            st.rerun()
                    
                    with col2:
                        confirmado = st.checkbox("Confirmar eliminación", key=f"confirm_del_btn_{budget_id}")
                        if st.button("🗑️ Eliminar", key=f"del_btn_{budget_id}", disabled=not confirmado):
                            try:
                                supabase.table("budgets").delete().eq("id", budget_id).execute()
                                st.success("Presupuesto eliminado.")
                                get_budgets.clear()
                                time.sleep(0.5)
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error: {e}")
                    
                    with col3:
                        try:
                            cliente_pdf = {
                                "name": budget_data.get("client_name", ""),
                                "tax_id": budget_data.get("client_tax_id", ""),
                                "address": budget_data.get("client_address", "")
                            }
                            lineas_pdf = json.loads(budget_data.get("lines", "[]"))
                            
                            if st.button("📄 Descargar PDF", key=f"pdf_btn_{budget_id}"):
                                pdf_bytes = make_budget_pdf(
                                    empresa,
                                    cliente_pdf,
                                    lineas_pdf,
                                    budget_data.get("base_total", 0),
                                    budget_data.get("vat_total", 0),
                                    budget_data.get("total", 0),
                                    budget_data.get("vat_pct", 21),
                                    budget_number=budget_number_sel
                                )
                                if pdf_bytes:
                                    st.download_button(
                                        "⬇️ Descargar",
                                        pdf_bytes,
                                        f"Presupuesto_{budget_number_sel}.pdf",
                                        mime="application/pdf",
                                        key=f"download_hist_{budget_id}"
                                    )
                        except Exception as e:
                            st.error(f"Error al generar PDF: {e}")
        else:
            st.info("No hay presupuestos guardados aún.")
# ════════════════════════════════════════════════════════════
# COLABORADORES
# ════════════════════════════════════════════════════════════
elif menu == "👥 Colaboradores":
    st.title("Colaboradores")
    st.info("Funcionalidad en desarrollo.")

# ════════════════════════════════════════════════════════════
# PANEL DE ADMINISTRACIÓN (CORREGIDO)
# ════════════════════════════════════════════════════════════
elif menu == "🔐 Panel Admin":
    st.title("🔐 Panel de Administración")
    
    ADMIN_EMAILS = ["esamanzanarez@gmail.com", "admin@hondureformas.com"]
    
    es_admin = False
    try:
        email_actual = st.session_state.user.email.lower() if st.session_state.user.email else ""
        es_admin = email_actual in [e.lower() for e in ADMIN_EMAILS]
        if not es_admin:
            try:
                role_res = supabase.table("user_roles").select("role").eq("user_id", user_id).single().execute()
                es_admin = role_res.data.get("role") == "admin" if role_res.data else False
            except Exception:
                es_admin = False
    except Exception:
        es_admin = False
    
    if not es_admin:
        st.error("❌ No tienes permisos para acceder a esta sección.")
        st.stop()
    
    st.success(f"✅ Acceso concedido como administrador: {st.session_state.user.email}")
    
    from supabase import create_client
    
    def get_admin_client():
        try:
            SUPABASE_URL = st.secrets["SUPABASE_URL"]
            SERVICE_ROLE_KEY = st.secrets["SUPABASE_SERVICE_ROLE_KEY"]
            return create_client(SUPABASE_URL, SERVICE_ROLE_KEY)
        except Exception:
            return supabase
    
    admin_client = get_admin_client()
    
    PRECIOS_PLANES = {"free": 0, "basico": 15, "profesional": 30, "gestoria": 60}
    
    def registrar_accion_admin(accion, user_id_afectado, detalles=""):
        try:
            admin_client.table("admin_actions").insert({
                "admin_id": user_id,
                "user_id": user_id_afectado,
                "action_type": accion,
                "action_details": detalles
            }).execute()
        except Exception:
            pass
    
    tab_resumen, tab_usuarios, tab_suscripciones, tab_logs = st.tabs(["📊 Resumen", "👥 Usuarios", "💳 Suscripciones", "⚠️ Logs"])
    
    # TAB RESUMEN
    with tab_resumen:
        st.subheader("📊 Visión General")
        mrr = 0
        usuarios_activos = 0
        try:
            subs_res = admin_client.table("subscriptions").select("plan, status").execute()
            if subs_res.data:
                for s in subs_res.data:
                    if s["status"] == "active" and s["plan"] in PRECIOS_PLANES:
                        mrr += PRECIOS_PLANES[s["plan"]]
                    if s["status"] == "active":
                        usuarios_activos += 1
        except Exception:
            pass
        
        mes_actual_nombre = LISTA_MESES[date.today().month - 1]
        try:
            facturas_mes = admin_client.table("invoices_v2").select("id").eq("month", mes_actual_nombre).execute()
            num_facturas_mes = len(facturas_mes.data) if facturas_mes.data else 0
        except Exception:
            num_facturas_mes = 0
        
        col_k1, col_k2, col_k3 = st.columns(3)
        col_k1.metric("💰 MRR", f"{mrr:,.0f} €/mes")
        col_k2.metric("👥 Usuarios Activos", usuarios_activos)
        col_k3.metric("📄 Facturas este mes", num_facturas_mes)
    
    # TAB USUARIOS (LEFT JOIN)
    with tab_usuarios:
        st.subheader("👥 Gestión de Usuarios")
        try:
            usuarios = []
            try:
                users_view_res = admin_client.table("users_view").select("*").execute()
                users_view_data = users_view_res.data if users_view_res.data else []
            except Exception:
                users_view_data = []
            
            try:
                roles_res = admin_client.table("user_roles").select("user_id, role").execute()
                roles_dict = {r["user_id"]: r["role"] for r in roles_res.data} if roles_res.data else {}
            except Exception:
                roles_dict = {}
            
            try:
                subs_res = admin_client.table("subscriptions").select("user_id, plan, status").execute()
                subs_dict = {s["user_id"]: {"plan": s["plan"], "status": s["status"]} for s in subs_res.data} if subs_res.data else {}
            except Exception:
                subs_dict = {}
            
            try:
                settings_res = admin_client.table("settings").select("user_id, company_name, company_tax_id, company_email").execute()
                settings_dict = {s["user_id"]: {"company_name": s.get("company_name", ""), "company_tax_id": s.get("company_tax_id", ""), "company_email": s.get("company_email", "")} for s in settings_res.data} if settings_res.data else {}
            except Exception:
                settings_dict = {}
            
            if users_view_data:
                for u in users_view_data:
                    uid = u.get("id", "")
                    email = u.get("email", "")
                    role = roles_dict.get(uid, "cliente")
                    sub_info = subs_dict.get(uid, {"plan": "free", "status": "active"})
                    setting_info = settings_dict.get(uid, {"company_name": "", "company_tax_id": "", "company_email": email})
                    usuarios.append({
                        "id": uid,
                        "email": setting_info.get("company_email", "") or email,
                        "company_name": setting_info.get("company_name", ""),
                        "company_tax_id": setting_info.get("company_tax_id", ""),
                        "role": role,
                        "plan": sub_info.get("plan", "free"),
                        "status": sub_info.get("status", "active"),
                    })
            else:
                all_user_ids = set()
                all_user_ids.update(roles_dict.keys())
                all_user_ids.update(subs_dict.keys())
                all_user_ids.update(settings_dict.keys())
                for uid in all_user_ids:
                    setting_info = settings_dict.get(uid, {"company_name": "", "company_tax_id": "", "company_email": ""})
                    sub_info = subs_dict.get(uid, {"plan": "free", "status": "active"})
                    usuarios.append({
                        "id": uid,
                        "email": setting_info.get("company_email", ""),
                        "company_name": setting_info.get("company_name", ""),
                        "company_tax_id": setting_info.get("company_tax_id", ""),
                        "role": roles_dict.get(uid, "cliente"),
                        "plan": sub_info.get("plan", "free"),
                        "status": sub_info.get("status", "active"),
                    })
            
            if usuarios:
                st.success(f"✅ Se encontraron {len(usuarios)} usuarios")
                busqueda = st.text_input("🔍 Buscar por email, nombre o CIF", key="busqueda_admin_usuarios")
                usuarios_filtrados = usuarios
                if busqueda:
                    bl = busqueda.lower()
                    usuarios_filtrados = [u for u in usuarios if bl in (u["email"] or "").lower() or bl in (u["company_name"] or "").lower() or bl in (u["company_tax_id"] or "").lower()]
                
                usuarios_df = pd.DataFrame(usuarios_filtrados)
                st.dataframe(usuarios_df[["email", "company_name", "company_tax_id", "plan", "role", "status"]], hide_index=True, use_container_width=True)
                
                if usuarios_filtrados:
                    email_sel = st.selectbox("Selecciona usuario", [u["email"] or u["company_name"] or str(u["id"])[:8] for u in usuarios_filtrados], key="select_usuario_admin")
                    usuario_sel = next((u for u in usuarios_filtrados if (u["email"] or u["company_name"] or str(u["id"])[:8]) == email_sel), None)
                    
                    if usuario_sel:
                        user_id_sel = usuario_sel["id"]
                        st.markdown("---")
                        st.subheader(f"Gestionar: {usuario_sel['email'] or usuario_sel['company_name']}")
                        
                        col_a1, col_a2, col_a3 = st.columns(3)
                        with col_a1:
                            nuevo_rol = st.selectbox("Rol", ["cliente", "admin"], index=0 if usuario_sel["role"] != "admin" else 1, key=f"rol_{user_id_sel}")
                            if st.button("🔄 Cambiar rol", key=f"btn_rol_{user_id_sel}"):
                                admin_client.table("user_roles").upsert({"user_id": user_id_sel, "role": nuevo_rol}, on_conflict="user_id").execute()
                                registrar_accion_admin("cambiar_rol", user_id_sel, nuevo_rol)
                                st.success("Rol actualizado")
                                st.rerun()
                        with col_a2:
                            dias_prueba = st.number_input("Días prueba", 0, 30, 7, key=f"dias_{user_id_sel}")
                            if st.button("🎁 Conceder prueba", key=f"btn_prueba_{user_id_sel}"):
                                fecha_fin = date.today() + timedelta(days=int(dias_prueba))
                                admin_client.table("subscriptions").upsert({"user_id": user_id_sel, "plan": "profesional", "status": "trialing", "trial_end": str(fecha_fin)}, on_conflict="user_id").execute()
                                registrar_accion_admin("conceder_prueba", user_id_sel, f"{dias_prueba} días")
                                st.success(f"Prueba hasta {fecha_fin}")
                                st.rerun()
                        with col_a3:
                            if usuario_sel["status"] == "inactive":
                                if st.button("✅ Habilitar", key=f"btn_hab_{user_id_sel}"):
                                    admin_client.table("subscriptions").update({"status": "active"}).eq("user_id", user_id_sel).execute()
                                    registrar_accion_admin("habilitar", user_id_sel)
                                    st.success("Habilitado")
                                    st.rerun()
                            else:
                                if st.button("🚫 Deshabilitar", key=f"btn_des_{user_id_sel}"):
                                    admin_client.table("subscriptions").update({"status": "inactive"}).eq("user_id", user_id_sel).execute()
                                    registrar_accion_admin("deshabilitar", user_id_sel)
                                    st.success("Deshabilitado")
                                    st.rerun()
        except Exception as e:
            st.error(f"Error al cargar usuarios: {e}")
    
    # TAB SUSCRIPCIONES (MAPEO EMAIL)
    with tab_suscripciones:
        st.subheader("💳 Control de Suscripciones")
        try:
            subs_res = admin_client.table("subscriptions").select("*").execute()
            if subs_res.data:
                subs_df = pd.DataFrame(subs_res.data)
                
                mapping_dict = {}
                try:
                    users_view_res = admin_client.table("users_view").select("id, email").execute()
                    if users_view_res.data:
                        for u in users_view_res.data:
                            mapping_dict[u["id"]] = {"email": u.get("email", ""), "nombre": ""}
                except Exception:
                    pass
                
                try:
                    settings_res = admin_client.table("settings").select("user_id, company_email, company_name").execute()
                    if settings_res.data:
                        for s in settings_res.data:
                            uid = s["user_id"]
                            if uid not in mapping_dict:
                                mapping_dict[uid] = {"email": "", "nombre": ""}
                            if not mapping_dict[uid].get("email"):
                                mapping_dict[uid]["email"] = s.get("company_email", "")
                            mapping_dict[uid]["nombre"] = s.get("company_name", "")
                except Exception:
                    pass
                
                def get_email(uid):
                    info = mapping_dict.get(uid, {})
                    email = info.get("email", "")
                    return email if email else "Sin email"
                
                def get_nombre(uid):
                    info = mapping_dict.get(uid, {})
                    nombre = info.get("nombre", "")
                    return nombre if nombre else "Sin nombre"
                
                subs_df["email"] = subs_df["user_id"].apply(get_email)
                subs_df["nombre"] = subs_df["user_id"].apply(get_nombre)
                
                total_activas = len(subs_df[subs_df["status"] == "active"])
                total_trialing = len(subs_df[subs_df["status"] == "trialing"])
                total_past_due = len(subs_df[subs_df["status"] == "past_due"])
                
                col_s1, col_s2, col_s3 = st.columns(3)
                col_s1.metric("✅ Activas", total_activas)
                col_s2.metric("🎁 Prueba", total_trialing)
                col_s3.metric("⚠️ Atrasadas", total_past_due)
                
                if total_past_due > 0:
                    st.error(f"🚨 {total_past_due} usuarios con pagos atrasados")
                
                st.markdown("---")
                subs_display = subs_df[["email", "nombre", "plan", "status"]].copy()
                subs_display.columns = ["Email", "Nombre", "Plan", "Estado"]
                subs_display = subs_display.sort_values("Email")
                st.dataframe(subs_display, hide_index=True, use_container_width=True)
                
                sin_email = len(subs_df[subs_df["email"] == "Sin email"])
                if sin_email > 0:
                    st.info(f"ℹ️ {sin_email} suscripciones sin email asociado.")
        except Exception as e:
            st.error(f"Error al cargar suscripciones: {e}")
    
    # TAB LOGS
    with tab_logs:
        st.subheader("⚠️ Monitor de Logs")
        col_l1, col_l2 = st.columns(2)
        with col_l1:
            st.markdown("### Errores FacturaE")
            try:
                logs_res = admin_client.table("error_logs").select("*").order("created_at", desc=True).limit(50).execute()
                if logs_res.data:
                    logs_df = pd.DataFrame(logs_res.data)
                    logs_df["created_at"] = pd.to_datetime(logs_df["created_at"]).dt.strftime("%d/%m/%Y %H:%M")
                    st.dataframe(logs_df[["created_at", "user_id", "invoice_number", "error_message"]], hide_index=True, use_container_width=True)
                else:
                    st.info("Sin errores registrados.")
            except Exception as e:
                st.error(f"Error al cargar error_logs: {e}")
        with col_l2:
            st.markdown("### Auditoría Admin")
            try:
                audit_res = admin_client.table("admin_actions").select("*").order("created_at", desc=True).limit(50).execute()
                if audit_res.data:
                    audit_df = pd.DataFrame(audit_res.data)
                    audit_df["created_at"] = pd.to_datetime(audit_df["created_at"]).dt.strftime("%d/%m/%Y %H:%M")
                    st.dataframe(audit_df[["created_at", "admin_id", "user_id", "action_type", "action_details"]], hide_index=True, use_container_width=True)
                else:
                    st.info("Sin acciones registradas.")
            except Exception as e:
                st.error(f"Error al cargar admin_actions: {e}")

# ════════════════════════════════════════════════════════════
# SUSCRIPCIÓN (COMPLETA)
# ════════════════════════════════════════════════════════════
elif menu == "💳 Suscripción":
    st.title("💳 Planes de Suscripción")
    
    if not user_id:
        st.error("No se pudo obtener tu ID de usuario. Inicia sesión de nuevo.")
        st.stop()
    
    try:
        suscripcion = obtener_suscripcion_usuario(user_id)
        plan_actual = suscripcion.get("plan", "free") if suscripcion else "free"
    except Exception:
        plan_actual = "free"
    
    iconos_plan = {"free": "🆓 Gratis", "basico": "💼 Básico", "profesional": "⭐ Profesional", "gestoria": "🏢 Gestoría"}
    st.markdown(f"### Tu plan actual: **{iconos_plan.get(plan_actual, plan_actual)}**")
    
    try:
        pagos = obtener_historial_pagos(user_id)
        if pagos:
            st.markdown("---")
            st.subheader("📜 Historial de pagos")
            pagos_df = pd.DataFrame(pagos)
            if not pagos_df.empty:
                pagos_df["Fecha"] = pd.to_datetime(pagos_df["created_at"]).dt.strftime("%d/%m/%Y")
                pagos_df["Importe"] = pagos_df["amount"].apply(lambda x: f"{float(x):,.2f} €")
                pagos_df["Plan"] = pagos_df["plan"]
                pagos_df["Estado"] = pagos_df["status"]
                st.dataframe(pagos_df[["Fecha", "Importe", "Plan", "Estado"]], hide_index=True, use_container_width=True)
    except Exception:
        pass
    
    st.markdown("---")
    st.markdown("### Planes disponibles")
    
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.markdown("### 🆓 Gratis")
        st.markdown("**0 €/mes**")
        st.markdown("---")
        st.markdown("✔️ 3 facturas/mes")
        st.markdown("✔️ PDF básico sin QR")
        st.markdown("✔️ Clientes y productos")
        st.markdown("❌ Sin firma electrónica")
        st.markdown("❌ Sin Veri*Factu")
        st.markdown("❌ Sin XML FacturaE")
        st.markdown("---")
        if plan_actual == "free":
            st.success("✅ Plan actual")
        else:
            if st.button("⬇️ Cambiar a Gratis", key="btn_free", use_container_width=True):
                if cancelar_suscripcion(user_id):
                    st.success("Suscripción cancelada. Plan cambiado a Gratis.")
                    time.sleep(1)
                    st.rerun()
    
    with col2:
        st.markdown("### 💼 Básico")
        st.markdown("**15 €/mes**")
        st.markdown("---")
        st.markdown("✔️ Facturas ilimitadas")
        st.markdown("✔️ PDF con QR Veri*Factu")
        st.markdown("✔️ Envío por email")
        st.markdown("✔️ Clientes y productos")
        st.markdown("✔️ Presupuestos")
        st.markdown("❌ Sin firma XAdES-T")
        st.markdown("❌ Sin XML FacturaE")
        st.markdown("---")
        if plan_actual == "basico":
            st.success("✅ Plan actual")
        else:
            if st.button("🚀 Contratar Básico", key="btn_basico", use_container_width=True):
                url = crear_checkout_session(user_id, st.session_state.user.email, "basico")
                if url:
                    st.markdown(f"[🔗 Ir a la página de pago]({url})")
                    st.info("Serás redirigido a Stripe para completar el pago.")
    
    with col3:
        st.markdown("### ⭐ Profesional")
        st.markdown("**30 €/mes**")
        st.markdown("---")
        st.markdown("✔️ Todo lo del plan Básico")
        st.markdown("✔️ **Veri*Factu completo**")
        st.markdown("✔️ **FacturaE XML firmado XAdES-T**")
        st.markdown("✔️ Hash encadenado SHA-256")
        st.markdown("✔️ QR verificable AEAT")
        st.markdown("✔️ Contabilidad")
        st.markdown("✔️ Modelo 303")
        st.markdown("---")
        if plan_actual == "profesional":
            st.success("✅ Plan actual")
        else:
            if st.button("🌟 Contratar Profesional", key="btn_profesional", use_container_width=True):
                url = crear_checkout_session(user_id, st.session_state.user.email, "profesional")
                if url:
                    st.markdown(f"[🔗 Ir a la página de pago]({url})")
                    st.info("Serás redirigido a Stripe para completar el pago.")
    
    with col4:
        st.markdown("### 🏢 Gestoría")
        st.markdown("**60 €/mes**")
        st.markdown("---")
        st.markdown("✔️ Todo lo del plan Profesional")
        st.markdown("✔️ **Multi-usuario**")
        st.markdown("✔️ **API REST**")
        st.markdown("✔️ Soporte prioritario")
        st.markdown("✔️ Informes avanzados")
        st.markdown("✔️ Exportación a Excel")
        st.markdown("✔️ Personalización completa")
        st.markdown("---")
        if plan_actual == "gestoria":
            st.success("✅ Plan actual")
        else:
            if st.button("🏢 Contratar Gestoría", key="btn_gestoria", use_container_width=True):
                url = crear_checkout_session(user_id, st.session_state.user.email, "gestoria")
                if url:
                    st.markdown(f"[🔗 Ir a la página de pago]({url})")
                    st.info("Serás redirigido a Stripe para completar el pago.")
    
    st.markdown("---")
    st.caption("Los pagos se procesan de forma segura a través de Stripe. Puedes cancelar en cualquier momento.")

# ════════════════════════════════════════════════════════════
# CONFIGURACIÓN (COMPLETA)
# ════════════════════════════════════════════════════════════
elif menu == "⚙️ Configuración":
    st.title("Configuración de empresa y plantillas")
    try:
        config_res = supabase.table("settings").select("*").eq("user_id", user_id).execute()
        settings = config_res.data[0] if config_res.data else {}
    except Exception:
        settings = {}
    company_name = settings.get("company_name") or AUTONOMO_NAME
    tax_id = settings.get("company_tax_id") or AUTONOMO_TAX_ID
    address = settings.get("company_address") or AUTONOMO_ADDRESS
    iban = settings.get("company_iban") or AUTONOMO_IBAN
    company_logo = settings.get("company_logo") or ""
    company_phone = settings.get("company_phone") or ""
    company_email = settings.get("company_email") or ""
    nombre_plantilla = settings.get("nombre_plantilla") or "default"
    template_html = settings.get("codigo_html") or ""
    template_css = settings.get("codigo_css") or ""
    budget_html = settings.get("budget_html") or ""
    budget_css = settings.get("budget_css") or ""

    with st.form("config_form"):
        company_name = st.text_input("Nombre de la empresa / autónomo", value=company_name)
        tax_id = st.text_input("NIF/CIF", value=tax_id)
        address = st.text_area("Dirección fiscal", value=address)
        iban = st.text_input("IBAN", value=iban)
        company_phone = st.text_input("Teléfono", value=company_phone)
        company_email = st.text_input("Correo electrónico", value=company_email)
        company_logo = st.text_input("URL del logo (opcional)", value=company_logo)
        st.markdown("---")
        st.subheader("Plantilla de factura")
        nombre_plantilla = st.text_input("Nombre de la plantilla", value=nombre_plantilla)
        template_html = st.text_area("Código HTML (codigo_html)", value=template_html, height=300)
        template_css = st.text_area("Código CSS (codigo_css) - opcional", value=template_css, height=100)
        st.markdown("---")
        st.subheader("Plantilla de presupuesto")
        budget_html = st.text_area("Código HTML (budget_html)", value=budget_html, height=300)
        budget_css = st.text_area("Código CSS (budget_css) - opcional", value=budget_css, height=100)
        if st.form_submit_button("Guardar datos fiscales"):
            tax_val = (tax_id or "").strip()
            if tax_val and not validar_nif_cif(tax_val):
                st.error("El NIF/CIF no es válido.")
            else:
                iban_val = (iban or "").strip()
                if iban_val and not validar_iban(iban_val):
                    st.error("El IBAN no es válido.")
                else:
                    data = {
                        "user_id": user_id, "company_name": company_name.strip(),
                        "company_tax_id": tax_val, "company_address": address.strip(),
                        "company_iban": iban_val, "company_phone": company_phone.strip(),
                        "company_email": company_email.strip(), "company_logo": company_logo.strip(),
                        "nombre_plantilla": nombre_plantilla.strip(), "codigo_html": template_html,
                        "codigo_css": template_css, "budget_html": budget_html, "budget_css": budget_css,
                    }
                    try:
                        supabase.table("settings").upsert(data, on_conflict="user_id").execute()
                        st.success("Datos fiscales actualizados correctamente")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")

    st.markdown("---")
    st.subheader("🔐 Certificado Digital para Firma Electrónica")
    
    tiene_cert = tiene_certificado(user_id)
    
    if tiene_cert:
        st.success("✅ Tienes un certificado configurado")
        if st.button("🗑️ Eliminar certificado actual"):
            confirmado = st.checkbox("Confirmo que deseo eliminar mi certificado")
            if confirmado:
                if eliminar_certificado_usuario(user_id):
                    st.success("Certificado eliminado correctamente")
                    st.rerun()
    
    st.markdown("**Subir certificado (.p12 o .pfx)**")
    archivo_cert = st.file_uploader("Archivo del certificado", type=["p12", "pfx"])
    password_cert = st.text_input("Contraseña del certificado", type="password")
    
    if st.button("💾 Guardar certificado"):
        if archivo_cert is None:
            st.error("Debes subir un archivo de certificado.")
        elif not password_cert:
            st.error("Debes introducir la contraseña del certificado.")
        else:
            try:
                certificado_bytes = archivo_cert.getvalue()
                from firma_xades import cargar_certificado_p12
                try:
                    cargar_certificado_p12(certificado_bytes, password_cert)
                except Exception as e:
                    st.error(f"El certificado no es válido: {str(e)}")
                    st.stop()
                if guardar_certificado_usuario(user_id, certificado_bytes, password_cert):
                    st.success("Certificado guardado correctamente")
                    st.rerun()
            except Exception as e:
                st.error(f"Error al guardar certificado: {str(e)}")

    st.markdown("---")
    if st.button("Probar plantilla factura"):
        ejemplo_invoice = {"invoice_number": "F2024-001", "date": "2024-01-15", "month": "Enero", "concept": "Desarrollo web", "base_amount": 1000.0, "vat_percentage": 21, "vat_amount": 210.0, "irpf_percentage": 0, "irpf_amount": 0.0, "total": 1210.0}
        ejemplo_client = {"name": "Cliente Ejemplo", "tax_id": "B12345678", "address": "Calle Falsa 123"}
        ejemplo_lineas = [{"description": "Desarrollo web", "quantity": 1, "unit_price": 1000.0, "base_amount": 1000.0, "vat_amount": 210.0, "irpf_amount": 0.0, "total": 1210.0}]
        ejemplo_company = {"company_name": company_name, "company_tax_id": tax_id, "company_address": address, "company_iban": iban, "company_logo": company_logo, "company_phone": company_phone, "company_email": company_email, "codigo_html": template_html, "codigo_css": template_css}
        pdf_bytes = make_invoice_pdf_from_template(ejemplo_invoice, ejemplo_client, ejemplo_company, ejemplo_lineas)
        if pdf_bytes:
            st.download_button("Descargar factura de prueba", pdf_bytes, "prueba_factura.pdf", "application/pdf")
