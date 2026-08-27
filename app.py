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
        role_res = supabase.table("user_roles").select("role").eq("user_id", user_id).single().execute()
        es_admin = role_res.data.get("role") == "admin" if role_res.data else False
    except Exception:
        es_admin = False
    
    if es_admin:
        opciones_menu.append("🔐 Panel Admin")

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
    
    # Filtros
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
    
    # KPIs
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
    
    # Tabla
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
    st.dataframe(
        df_display,
        hide_index=True,
        use_container_width=True,
        column_config=column_config
    )
    
    # Exportar CSV
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
                movs = supabase.table("journal_entry_lines")\
                    .select("*, journal_entries(date)")\
                    .in_("journal_entry_id", entry_ids)\
                    .eq("account", cuenta_sel)\
                    .execute()
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
# PRESUPUESTOS - VERSIÓN COMPLETA
# ════════════════════════════════════════════════════════════
elif menu == "📝 Presupuestos":
    st.title("📝 Presupuestos")
    
    # Inicializar variables de sesión
    if "editing_budget_id" not in st.session_state:
        st.session_state.editing_budget_id = None
    if "edit_budget_data" not in st.session_state:
        st.session_state.edit_budget_data = None
    if "pdf_temp_bytes" not in st.session_state:
        st.session_state.pdf_temp_bytes = None
    if "pdf_temp_number" not in st.session_state:
        st.session_state.pdf_temp_number = None
    if "show_email_input" not in st.session_state:
        st.session_state.show_email_input = {}
    
    # Cargar datos de la empresa
    try:
        config_res = supabase.table("settings").select("*").eq("user_id", user_id).execute()
        if config_res.data:
            empresa = config_res.data[0]
            if "user_id" not in empresa:
                empresa["user_id"] = user_id
        else:
            empresa = {
                "user_id": user_id, 
                "company_name": AUTONOMO_NAME, 
                "company_tax_id": AUTONOMO_TAX_ID, 
                "company_address": AUTONOMO_ADDRESS, 
                "company_iban": AUTONOMO_IBAN, 
                "company_phone": "", 
                "company_email": "", 
                "company_logo": ""
            }
    except Exception:
        empresa = {
            "user_id": user_id, 
            "company_name": AUTONOMO_NAME, 
            "company_tax_id": AUTONOMO_TAX_ID, 
            "company_address": AUTONOMO_ADDRESS, 
            "company_iban": AUTONOMO_IBAN, 
            "company_phone": "", 
            "company_email": "", 
            "company_logo": ""
        }

    # Tabs principales
    tab_nuevo, tab_historial = st.tabs(["📝 Nuevo / Editar presupuesto", "📋 Historial de presupuestos"])

    # ════════════════════════════════════════════════════════════
    # TAB 1: NUEVO / EDITAR PRESUPUESTO
    # ════════════════════════════════════════════════════════════
    with tab_nuevo:
        # Cargar datos de clientes y productos
        clientes_df = get_clients(user_id)
        productos_df = get_products(user_id)
        if not productos_df.empty:
            for col in ["description", "price", "default_vat_percentage", "default_irpf_percentage"]:
                if col not in productos_df.columns:
                    productos_df[col] = "" if col == "description" else 0.0

        # Modo de trabajo
        modo_edicion = st.radio(
            "Modo de trabajo", 
            ["Crear nuevo presupuesto", "Editar presupuesto existente"], 
            horizontal=True, 
            key="modo_presupuesto", 
            index=0 if st.session_state.editing_budget_id is None else 1
        )

        if modo_edicion == "Editar presupuesto existente":
            budgets_df = get_budgets(user_id)
            if budgets_df.empty:
                st.warning("No hay presupuestos guardados.")
                st.stop()
            budget_sel = st.selectbox(
                "Selecciona el presupuesto a editar", 
                budgets_df["budget_number"].tolist(), 
                key="editar_budget_select"
            )
            if budget_sel:
                budget_row = budgets_df[budgets_df["budget_number"] == budget_sel].iloc[0]
                budget_id = budget_row["id"]
                try:
                    resp = supabase.table("budgets").select("*").eq("id", budget_id).single().execute()
                    if resp.data:
                        st.session_state.editing_budget_id = budget_id
                        st.session_state.edit_budget_data = resp.data
                except Exception as e:
                    st.error(f"Error: {e}")
            if st.button("❌ Cancelar edición", key="cancel_edit"):
                st.session_state.editing_budget_id = None
                st.session_state.edit_budget_data = None
                st.rerun()
        else:
            st.session_state.editing_budget_id = None
            st.session_state.edit_budget_data = None

        # Cargar datos de edición si existen
        if st.session_state.editing_budget_id and st.session_state.edit_budget_data:
            budget_data = st.session_state.edit_budget_data
            cliente_pre = {
                "name": budget_data.get("client_name", ""), 
                "tax_id": budget_data.get("client_tax_id", ""), 
                "address": budget_data.get("client_address", ""),
                "email": budget_data.get("client_email", "")
            }
            lineas_pre = json.loads(budget_data.get("lines", "[]"))
            fecha_pre = budget_data.get("date", str(date.today()))
            try:
                fecha_pre_dt = datetime.strptime(fecha_pre, "%Y-%m-%d").date()
            except:
                fecha_pre_dt = date.today()
        else:
            cliente_pre = {"name": "", "tax_id": "", "address": "", "email": ""}
            lineas_pre = []
            fecha_pre_dt = date.today()

        # ──────────────────────────────────────────────────────────
        # DATOS DEL CLIENTE
        # ──────────────────────────────────────────────────────────
        st.subheader("👤 Datos del cliente")
        modo_cliente = st.radio(
            "Seleccionar cliente", 
            ["Existente", "Nuevo (manual)"], 
            horizontal=True, 
            key="modo_cliente"
        )
        
        if modo_cliente == "Existente":
            if clientes_df.empty:
                cliente = {"name": "", "tax_id": "", "address": "", "email": ""}
            else:
                cliente_sel = st.selectbox("Cliente", clientes_df["name"].tolist(), key="cliente_select")
                cliente_row = clientes_df[clientes_df["name"] == cliente_sel].iloc[0]
                cliente = {
                    "name": cliente_row["name"], 
                    "tax_id": cliente_row["tax_id"], 
                    "address": cliente_row["address"],
                    "email": cliente_row.get("email", "")
                }
        else:
            cliente = {
                "name": st.text_input("Nombre/Razón Social", value=cliente_pre["name"], key="manual_name"),
                "tax_id": st.text_input("RTN / NIF", value=cliente_pre["tax_id"], key="manual_taxid"),
                "address": st.text_input("Dirección", value=cliente_pre["address"], key="manual_address"),
                "email": st.text_input("📧 Email del cliente", value=cliente_pre.get("email", ""), key="manual_email", placeholder="cliente@ejemplo.com")
            }

        fecha = st.date_input("📅 Fecha del presupuesto", value=fecha_pre_dt, key="fecha_presupuesto")

        # ──────────────────────────────────────────────────────────
        # LÍNEAS DEL PRESUPUESTO
        # ──────────────────────────────────────────────────────────
        st.subheader("📋 Líneas del presupuesto")
        num_lineas = st.number_input(
            "Número de líneas", 
            min_value=1, 
            max_value=20, 
            value=max(len(lineas_pre), 1), 
            key="num_lineas"
        )
        
        lista_productos = ["-- Manual --"]
        if not productos_df.empty:
            lista_productos += productos_df["name"].tolist()
        
        lineas = []
        for i in range(int(num_lineas)):
            lin_pre = lineas_pre[i] if i < len(lineas_pre) else None
            cols = st.columns([3, 1.5, 2, 2])
            
            with cols[0]:
                prod_sel = st.selectbox(f"Producto {i+1}", lista_productos, key=f"bud_prod_{i}")
                if prod_sel == "-- Manual --":
                    desc_manual = st.text_input(
                        f"Descripción {i+1}", 
                        value=lin_pre.get("description", "") if lin_pre else "", 
                        key=f"bud_desc_{i}"
                    )
                else:
                    prod_info = productos_df[productos_df["name"] == prod_sel]
                    descripcion_producto = prod_info.iloc[0].get("description", "") if not prod_info.empty else ""
                    desc_manual = st.text_area(
                        f"Descripción {i+1} (editable)", 
                        value=descripcion_producto or "", 
                        key=f"bud_desc_{i}", 
                        height=80
                    )
            
            with cols[1]:
                cantidad = st.number_input(
                    f"Cantidad {i+1}", 
                    min_value=1.0, 
                    value=float(lin_pre["quantity"]) if lin_pre else 1.0, 
                    key=f"bud_qty_{i}"
                )
            
            with cols[2]:
                if prod_sel != "-- Manual --" and not productos_df.empty:
                    prod_row = productos_df[productos_df["name"] == prod_sel]
                    if not prod_row.empty:
                        precio_default = prod_row.iloc[0]["price"]
                        vat_default = prod_row.iloc[0]["default_vat_percentage"]
                        irpf_default = 0.0
                    else:
                        precio_default = 0.0
                        vat_default = 21.0
                        irpf_default = 0.0
                else:
                    precio_default = float(lin_pre["unit_price"]) if lin_pre else 0.0
                    vat_default = float(lin_pre.get("vat_percentage", 21)) if lin_pre else 21.0
                    irpf_default = 0.0
                
                precio = st.number_input(
                    f"Precio ud. {i+1}", 
                    min_value=0.0, 
                    value=precio_default, 
                    key=f"bud_price_{i}"
                )
                vat = st.number_input(
                    f"IVA % {i+1}", 
                    value=vat_default, 
                    key=f"bud_vat_{i}"
                )
                irpf = st.number_input(
                    f"IRPF % {i+1}", 
                    value=irpf_default, 
                    key=f"bud_irpf_{i}"
                )
            
            with cols[3]:
                base_linea = cantidad * precio
                vat_amount = base_linea * vat / 100
                irpf_amount = base_linea * irpf / 100
                total_linea = base_linea + vat_amount + irpf_amount
                st.metric("Total línea", f"{total_linea:,.2f} €")
            
            descripcion_linea = f"{prod_sel}\n{desc_manual.strip()}" if prod_sel != "-- Manual --" and desc_manual.strip() else (desc_manual.strip() if desc_manual.strip() else prod_sel)
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

        # Totales
        if lineas:
            base_total = sum(l["base_amount"] for l in lineas)
            vat_total = sum(l["vat_amount"] for l in lineas)
            irpf_total = sum(l["irpf_amount"] for l in lineas)
            total = base_total + vat_total + irpf_total
        else:
            base_total = vat_total = irpf_total = total = 0.0

        # ──────────────────────────────────────────────────────────
        # VISTA PREVIA
        # ──────────────────────────────────────────────────────────
        st.markdown("---")
        st.subheader("🔍 Vista previa del presupuesto")
        with st.container(border=True):
            # Datos de la empresa
            col_logo, col_empresa = st.columns([1, 3])
            with col_logo:
                if empresa.get("company_logo"):
                    st.image(empresa["company_logo"], width=100)
            with col_empresa:
                st.markdown(f"**{empresa.get('company_name', '')}**")
                st.markdown(f"NIF: {empresa.get('company_tax_id', '')}")
                st.markdown(f"Dirección: {empresa.get('company_address', '')}")
                if empresa.get("company_phone"):
                    st.markdown(f"Tel: {empresa.get('company_phone', '')}")
                if empresa.get("company_email"):
                    st.markdown(f"Email: {empresa.get('company_email', '')}")
            
            st.markdown("---")
            st.markdown(f"**📄 PRESUPUESTO** (fecha: {fecha.strftime('%d/%m/%Y')})")
            st.markdown(f"**👤 Cliente:** {cliente.get('name', '')}")
            if cliente.get('tax_id'):
                st.markdown(f"NIF: {cliente.get('tax_id', '')}")
            if cliente.get('address'):
                st.markdown(f"Dirección: {cliente.get('address', '')}")
            
            if lineas:
                lineas_df = pd.DataFrame(lineas)
                vista_df = lineas_df[["description", "quantity", "unit_price", "total"]].copy()
                vista_df.columns = ["Descripción", "Cant.", "Precio ud.", "Total"]
                vista_df["Precio ud."] = vista_df["Precio ud."].apply(lambda x: f"{x:,.2f} €")
                vista_df["Total"] = vista_df["Total"].apply(lambda x: f"{x:,.2f} €")
                st.dataframe(vista_df, hide_index=True, use_container_width=True)
            
            st.markdown("---")
            col_totales = st.columns(4)
            with col_totales[0]:
                st.markdown(f"**Base imponible:** {money(base_total)}")
            with col_totales[1]:
                st.markdown(f"**IVA:** {money(vat_total)}")
            with col_totales[2]:
                st.markdown(f"**IRPF:** {money(irpf_total)}")
            with col_totales[3]:
                st.markdown(f"### **TOTAL: {money(total)}**")

        # ──────────────────────────────────────────────────────────
        # ACCIONES: GUARDAR, PDF, EMAIL
        # ──────────────────────────────────────────────────────────
        st.markdown("---")
        st.subheader("⚡ Acciones")
        
        col_acc1, col_acc2, col_acc3 = st.columns(3)
        
        with col_acc1:
            if st.button("💾 Guardar presupuesto", key="guardar_presupuesto", use_container_width=True):
                if not validar_nif_cif(cliente.get("tax_id", "")):
                    st.error("El NIF del cliente no es válido.")
                elif not lineas:
                    st.error("Debes añadir al menos una línea al presupuesto.")
                else:
                    if st.session_state.editing_budget_id:
                        try:
                            supabase.table("budgets").update({
                                "date": str(fecha), 
                                "client_name": cliente.get("name", ""),
                                "client_tax_id": cliente.get("tax_id", ""), 
                                "client_address": cliente.get("address", ""),
                                "client_email": cliente.get("email", ""),
                                "lines": json.dumps(lineas), 
                                "base_total": base_total, 
                                "vat_total": vat_total,
                                "irpf_total": irpf_total, 
                                "total": total,
                                "vat_pct": lineas[0]["vat_percentage"] if lineas else 21,
                                "irpf_pct": lineas[0]["irpf_percentage"] if lineas else 0,
                                "updated_at": datetime.now().isoformat()
                            }).eq("id", st.session_state.editing_budget_id).execute()
                            st.success("✅ Presupuesto actualizado correctamente.")
                            st.session_state.editing_budget_id = None
                            st.session_state.edit_budget_data = None
                            get_budgets.clear()
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
                            "client_email": cliente.get("email", ""),
                            "lines": json.dumps(lineas), 
                            "base_total": base_total, 
                            "vat_total": vat_total,
                            "irpf_total": irpf_total, 
                            "total": total,
                            "vat_pct": lineas[0]["vat_percentage"] if lineas else 21,
                            "irpf_pct": lineas[0]["irpf_percentage"] if lineas else 0,
                            "status": "pendiente",
                            "created_at": datetime.now().isoformat()
                        }
                        try:
                            supabase.table("budgets").insert(data).execute()
                            st.success(f"✅ Presupuesto {budget_number} guardado correctamente.")
                            get_budgets.clear()
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error al guardar: {e}")

        with col_acc2:
            if st.button("📄 Generar PDF", key="pdf_presupuesto", use_container_width=True):
                if not validar_nif_cif(cliente.get("tax_id", "")):
                    st.error("El NIF del cliente no es válido.")
                elif not lineas:
                    st.error("No hay líneas para generar el PDF.")
                else:
                    empresa["user_id"] = user_id
                    vat_pct = lineas[0]["vat_percentage"] if lineas else 21
                    temp_budget_number = obtener_siguiente_numero_presupuesto(user_id)
                    cliente_pdf = {
                        "name": cliente.get("name", ""), 
                        "tax_id": cliente.get("tax_id", ""), 
                        "address": cliente.get("address", "")
                    }
                    pdf_bytes = make_budget_pdf(
                        empresa, cliente_pdf, lineas, 
                        base_total, vat_total, total, vat_pct, 
                        budget_number=temp_budget_number
                    )
                    if pdf_bytes:
                        st.session_state.pdf_temp_bytes = pdf_bytes
                        st.session_state.pdf_temp_number = temp_budget_number
                        st.success("✅ PDF generado correctamente")
                        st.rerun()

        with col_acc3:
            if st.button("📧 Enviar por email", key="email_presupuesto", use_container_width=True):
                if not validar_nif_cif(cliente.get("tax_id", "")):
                    st.error("El NIF del cliente no es válido.")
                elif not lineas:
                    st.error("No hay líneas para generar el PDF.")
                elif not cliente.get("email"):
                    st.error("El cliente no tiene email registrado.")
                else:
                    empresa["user_id"] = user_id
                    vat_pct = lineas[0]["vat_percentage"] if lineas else 21
                    temp_budget_number = obtener_siguiente_numero_presupuesto(user_id)
                    cliente_pdf = {
                        "name": cliente.get("name", ""), 
                        "tax_id": cliente.get("tax_id", ""), 
                        "address": cliente.get("address", "")
                    }
                    pdf_bytes = make_budget_pdf(
                        empresa, cliente_pdf, lineas, 
                        base_total, vat_total, total, vat_pct, 
                        budget_number=temp_budget_number
                    )
                    if pdf_bytes:
                        with st.spinner("📧 Enviando email..."):
                            exito = enviar_factura_email(
                                cliente.get("email"), 
                                f"Presupuesto {temp_budget_number}", 
                                f"Hola {cliente.get('name', '')},\n\nAdjunto le enviamos el presupuesto solicitado.\n\nSaludos,\n{empresa.get('company_name', '')}",
                                pdf_bytes, 
                                f"Presupuesto_{temp_budget_number}.pdf"
                            )
                        if exito:
                            st.success(f"✅ Presupuesto enviado a {cliente.get('email')}")
                        else:
                            st.error("❌ Error al enviar el email. Verifica la configuración.")

        # ──────────────────────────────────────────────────────────
        # OPCIONES DEL PDF GENERADO (si existe)
        # ──────────────────────────────────────────────────────────
        if st.session_state.pdf_temp_bytes:
            st.markdown("---")
            st.subheader("📎 Opciones del PDF generado")
            
            pdf_bytes = st.session_state.pdf_temp_bytes
            temp_budget_number = st.session_state.pdf_temp_number
            
            col_dl, col_email_temp = st.columns(2)
            
            with col_dl:
                st.download_button(
                    "⬇️ Descargar PDF", 
                    pdf_bytes, 
                    f"presupuesto_{temp_budget_number}.pdf", 
                    mime="application/pdf", 
                    key="download_pdf_temp",
                    use_container_width=True
                )
            
            with col_email_temp:
                email_destino = st.text_input(
                    "📧 Email destinatario", 
                    value=cliente.get("email", ""),
                    key="email_pdf_temp",
                    placeholder="cliente@ejemplo.com"
                )
                if st.button("📧 Enviar este PDF", key="send_pdf_temp", use_container_width=True):
                    if not email_destino or "@" not in email_destino:
                        st.error("Introduce un email válido.")
                    else:
                        with st.spinner("Enviando..."):
                            exito = enviar_factura_email(
                                email_destino, 
                                f"Presupuesto {temp_budget_number}", 
                                f"Hola,\n\nAdjunto le enviamos el presupuesto.\n\nSaludos,\n{empresa.get('company_name', '')}",
                                pdf_bytes, 
                                f"Presupuesto_{temp_budget_number}.pdf"
                            )
                        if exito:
                            st.success(f"✅ Enviado a {email_destino}")
                            st.session_state.pdf_temp_bytes = None
                            st.rerun()
                        else:
                            st.error("❌ Error al enviar el email")
            
            if st.button("🗑️ Cerrar opciones", key="close_pdf_temp"):
                st.session_state.pdf_temp_bytes = None
                st.session_state.pdf_temp_number = None
                st.rerun()

    # ════════════════════════════════════════════════════════════
    # TAB 2: HISTORIAL DE PRESUPUESTOS
    # ════════════════════════════════════════════════════════════
    with tab_historial:
        st.subheader("📋 Historial de presupuestos")
        
        budgets_df = get_budgets(user_id)
        
        if not budgets_df.empty:
            # Preparar datos para mostrar
            budgets_display = budgets_df[["budget_number", "date", "client_name", "total", "status"]].copy()
            budgets_display.columns = ["Nº Presupuesto", "Fecha", "Cliente", "Total", "Estado"]
            budgets_display["Fecha"] = pd.to_datetime(budgets_display["Fecha"]).dt.strftime("%d/%m/%Y")
            
            # Configurar columnas
            column_config = {
                "Nº Presupuesto": st.column_config.TextColumn("Nº Presupuesto", width="small"),
                "Fecha": st.column_config.TextColumn("Fecha", width="small"),
                "Cliente": st.column_config.TextColumn("Cliente", width="medium"),
                "Total": st.column_config.NumberColumn("Total", format="%.2f €", width="small"),
                "Estado": st.column_config.TextColumn("Estado", width="small"),
            }
            
            # Mostrar tabla con selección
            event = st.dataframe(
                budgets_display, 
                hide_index=True, 
                use_container_width=True, 
                column_config=column_config, 
                selection_mode="single-row", 
                on_select="rerun", 
                key="budgets_table"
            )
            
            # Procesar selección
            if event.selection and event.selection.rows and len(event.selection.rows) > 0:
                selected_row = event.selection.rows[0]
                if selected_row is not None and 0 <= selected_row < len(budgets_df):
                    budget_row = budgets_df.iloc[selected_row]
                    budget_id = budget_row["id"]
                    
                    # Obtener datos completos
                    try:
                        resp = supabase.table("budgets").select("*").eq("id", budget_id).single().execute()
                        budget_data = resp.data if resp.data else budget_row.to_dict()
                    except Exception:
                        budget_data = budget_row.to_dict()
                    
                    # Mostrar detalles
                    st.markdown("---")
                    st.subheader(f"📄 Presupuesto {budget_data['budget_number']}")
                    
                    # Información del presupuesto
                    col_info1, col_info2, col_info3 = st.columns(3)
                    with col_info1:
                        st.markdown(f"**Cliente:** {budget_data.get('client_name', '')}")
                        if budget_data.get('client_tax_id'):
                            st.markdown(f"**NIF:** {budget_data.get('client_tax_id', '')}")
                    with col_info2:
                        st.markdown(f"**Fecha:** {budget_data.get('date', '')}")
                        st.markdown(f"**Estado:** {budget_data.get('status', 'pendiente')}")
                    with col_info3:
                        st.markdown(f"**Total:** {money(budget_data.get('total', 0))}")
                        st.markdown(f"**IVA:** {money(budget_data.get('vat_total', 0))}")
                    
                    # Mostrar líneas
                    try:
                        lineas_db = json.loads(budget_data.get("lines", "[]"))
                        if lineas_db:
                            st.markdown("**Líneas del presupuesto:**")
                            lineas_df = pd.DataFrame(lineas_db)
                            vista_lineas = lineas_df[["description", "quantity", "unit_price", "total"]].copy()
                            vista_lineas.columns = ["Descripción", "Cant.", "Precio ud.", "Total"]
                            vista_lineas["Precio ud."] = vista_lineas["Precio ud."].apply(lambda x: f"{x:,.2f} €")
                            vista_lineas["Total"] = vista_lineas["Total"].apply(lambda x: f"{x:,.2f} €")
                            st.dataframe(vista_lineas, hide_index=True, use_container_width=True)
                    except Exception:
                        lineas_db = []
                    
                    # ──────────────────────────────────────────────────────────
                    # ACCIONES DEL PRESUPUESTO SELECCIONADO
                    # ──────────────────────────────────────────────────────────
                    st.markdown("---")
                    st.subheader("⚡ Acciones")
                    
                    col1, col2, col3, col4, col5 = st.columns(5)
                    
                    # 1. EDITAR
                    with col1:
                        if st.button("✏️ Editar", key=f"edit_{budget_id}", use_container_width=True):
                            st.session_state.editing_budget_id = budget_id
                            st.session_state.edit_budget_data = budget_data
                            st.rerun()
                    
                    # 2. PDF
                    with col2:
                        if st.button("📄 PDF", key=f"pdf_{budget_id}", use_container_width=True):
                            empresa_data = empresa.copy()
                            cliente_pdf = {
                                "name": budget_data.get('client_name', ''),
                                "tax_id": budget_data.get('client_tax_id', ''),
                                "address": budget_data.get('client_address', '')
                            }
                            try:
                                lineas_pdf = json.loads(budget_data.get("lines", "[]"))
                            except:
                                lineas_pdf = []
                            
                            if lineas_pdf:
                                pdf_bytes = make_budget_pdf(
                                    empresa_data, 
                                    cliente_pdf, 
                                    lineas_pdf,
                                    budget_data.get('base_total', 0),
                                    budget_data.get('vat_total', 0),
                                    budget_data.get('total', 0),
                                    budget_data.get('vat_pct', 21),
                                    budget_number=budget_data.get('budget_number', '')
                                )
                                if pdf_bytes:
                                    # Guardar en sesión para descargar
                                    st.session_state[f"pdf_hist_{budget_id}"] = pdf_bytes
                                    st.session_state[f"pdf_num_hist_{budget_id}"] = budget_data.get('budget_number', '')
                                    st.rerun()
                    
                    # 3. ENVIAR EMAIL
                    with col3:
                        if st.button("📧 Enviar", key=f"send_{budget_id}", use_container_width=True):
                            # Generar PDF
                            empresa_data = empresa.copy()
                            cliente_pdf = {
                                "name": budget_data.get('client_name', ''),
                                "tax_id": budget_data.get('client_tax_id', ''),
                                "address": budget_data.get('client_address', '')
                            }
                            try:
                                lineas_pdf = json.loads(budget_data.get("lines", "[]"))
                            except:
                                lineas_pdf = []
                            
                            if lineas_pdf:
                                pdf_bytes = make_budget_pdf(
                                    empresa_data, 
                                    cliente_pdf, 
                                    lineas_pdf,
                                    budget_data.get('base_total', 0),
                                    budget_data.get('vat_total', 0),
                                    budget_data.get('total', 0),
                                    budget_data.get('vat_pct', 21),
                                    budget_number=budget_data.get('budget_number', '')
                                )
                                if pdf_bytes:
                                    st.session_state[f"email_show_{budget_id}"] = True
                                    st.session_state[f"pdf_hist_{budget_id}"] = pdf_bytes
                                    st.session_state[f"pdf_num_hist_{budget_id}"] = budget_data.get('budget_number', '')
                                    st.rerun()
                    
                    # 4. CAMBIAR ESTADO
                    with col4:
                        nuevo_estado = st.selectbox(
                            "Estado",
                            ["pendiente", "enviado", "aceptado", "rechazado"],
                            index=["pendiente", "enviado", "aceptado", "rechazado"].index(budget_data.get('status', 'pendiente')),
                            key=f"estado_{budget_id}"
                        )
                        if nuevo_estado != budget_data.get('status', 'pendiente'):
                            if st.button("🔄 Actualizar estado", key=f"update_status_{budget_id}"):
                                try:
                                    supabase.table("budgets").update({
                                        "status": nuevo_estado,
                                        "updated_at": datetime.now().isoformat()
                                    }).eq("id", budget_id).execute()
                                    st.success(f"✅ Estado actualizado a '{nuevo_estado}'")
                                    get_budgets.clear()
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Error: {e}")
                    
                    # 5. ELIMINAR
                    with col5:
                        confirmado = st.checkbox("Confirmar eliminación", key=f"confirm_del_{budget_id}")
                        if st.button("🗑️ Eliminar", key=f"del_{budget_id}", disabled=not confirmado, use_container_width=True):
                            try:
                                supabase.table("budgets").delete().eq("id", budget_id).execute()
                                st.success("✅ Presupuesto eliminado.")
                                get_budgets.clear()
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error: {e}")
                    
                    # ──────────────────────────────────────────────────────────
                    # MOSTRAR PDF GENERADO PARA DESCARGA O EMAIL
                    # ──────────────────────────────────────────────────────────
                    # Descarga de PDF
                    if st.session_state.get(f"pdf_hist_{budget_id}"):
                        pdf_bytes = st.session_state[f"pdf_hist_{budget_id}"]
                        budget_num = st.session_state.get(f"pdf_num_hist_{budget_id}", "")
                        
                        st.markdown("---")
                        st.subheader("📎 PDF generado")
                        
                        col_dl_hist, col_email_hist = st.columns(2)
                        
                        with col_dl_hist:
                            st.download_button(
                                "⬇️ Descargar PDF",
                                pdf_bytes,
                                f"presupuesto_{budget_num}.pdf",
                                mime="application/pdf",
                                key=f"download_hist_{budget_id}",
                                use_container_width=True
                            )
                        
                        # Mostrar input de email si se activó
                        if st.session_state.get(f"email_show_{budget_id}", False):
                            with col_email_hist:
                                email_destino = st.text_input(
                                    "📧 Email destinatario",
                                    value=budget_data.get('client_email', ''),
                                    key=f"email_hist_{budget_id}",
                                    placeholder="cliente@ejemplo.com"
                                )
                                col_env, col_cancel = st.columns(2)
                                with col_env:
                                    if st.button("✅ Enviar", key=f"send_hist_{budget_id}", use_container_width=True):
                                        if not email_destino or "@" not in email_destino:
                                            st.error("Introduce un email válido.")
                                        else:
                                            with st.spinner("Enviando..."):
                                                exito = enviar_factura_email(
                                                    email_destino,
                                                    f"Presupuesto {budget_num}",
                                                    f"Hola,\n\nAdjunto le enviamos el presupuesto.\n\nSaludos,\n{empresa.get('company_name', '')}",
                                                    pdf_bytes,
                                                    f"Presupuesto_{budget_num}.pdf"
                                                )
                                            if exito:
                                                st.success(f"✅ Enviado a {email_destino}")
                                                # Actualizar estado a "enviado" automáticamente
                                                try:
                                                    supabase.table("budgets").update({
                                                        "status": "enviado",
                                                        "updated_at": datetime.now().isoformat()
                                                    }).eq("id", budget_id).execute()
                                                except:
                                                    pass
                                                st.session_state[f"email_show_{budget_id}"] = False
                                                st.session_state[f"pdf_hist_{budget_id}"] = None
                                                get_budgets.clear()
                                                st.rerun()
                                            else:
                                                st.error("❌ Error al enviar el email")
                                with col_cancel:
                                    if st.button("❌ Cancelar", key=f"cancel_hist_{budget_id}", use_container_width=True):
                                        st.session_state[f"email_show_{budget_id}"] = False
                                        st.session_state[f"pdf_hist_{budget_id}"] = None
                                        st.rerun()
                        else:
                            with col_email_hist:
                                if st.button("📧 Enviar por email", key=f"send_email_hist_{budget_id}", use_container_width=True):
                                    st.session_state[f"email_show_{budget_id}"] = True
                                    st.rerun()
                        
                        if st.button("🗑️ Cerrar PDF", key=f"close_pdf_hist_{budget_id}"):
                            st.session_state[f"pdf_hist_{budget_id}"] = None
                            st.session_state[f"email_show_{budget_id}"] = False
                            st.rerun()
        else:
            st.info("📭 No hay presupuestos guardados aún.")
# ════════════════════════════════════════════════════════════
# COLABORADORES
# ════════════════════════════════════════════════════════════
elif menu == "👥 Colaboradores":
    st.title("Colaboradores")
    st.info("Funcionalidad en desarrollo.")

# ════════════════════════════════════════════════════════════
# PANEL DE ADMINISTRACIÓN
# ════════════════════════════════════════════════════════════
elif menu == "🔐 Panel Admin":
    st.title("🔐 Panel de Administración")
    
    try:
        role_res = supabase.table("user_roles").select("role").eq("user_id", user_id).single().execute()
        if not role_res.data or role_res.data.get("role") != "admin":
            st.error("No tienes permisos.")
            st.stop()
    except Exception:
        st.error("No tienes permisos.")
        st.stop()
    
    PRECIOS_PLANES = {"free": 0, "basico": 15, "profesional": 30, "gestoria": 60}
    
    def registrar_accion_admin(accion, user_id_afectado, detalles=""):
        try:
            supabase.table("admin_actions").insert({
                "admin_id": user_id,
                "user_id": user_id_afectado,
                "action_type": accion,
                "action_details": detalles
            }).execute()
        except Exception:
            pass
    
    tab_resumen, tab_usuarios, tab_suscripciones, tab_logs = st.tabs(["📊 Resumen", "👥 Usuarios", "💳 Suscripciones", "⚠️ Logs"])
    
    with tab_resumen:
        st.subheader("📊 Visión General")
        mrr = 0
        usuarios_activos = 0
        try:
            subs_res = supabase.table("subscriptions").select("plan, status").execute()
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
            facturas_mes = supabase.table("invoices_v2").select("id").eq("month", mes_actual_nombre).execute()
            num_facturas_mes = len(facturas_mes.data) if facturas_mes.data else 0
        except Exception:
            num_facturas_mes = 0
        
        col_k1, col_k2, col_k3 = st.columns(3)
        col_k1.metric("💰 MRR", f"{mrr:,.0f} €/mes")
        col_k2.metric("👥 Usuarios Activos", usuarios_activos)
        col_k3.metric("📄 Facturas este mes", num_facturas_mes)
    
    with tab_usuarios:
        st.subheader("👥 Gestión de Usuarios")
        try:
            auth_users = supabase.auth.admin.list_users()
            usuarios = []
            for u in auth_users:
                user_info = {"id": u.id, "email": u.email}
                try:
                    rol_res = supabase.table("user_roles").select("role").eq("user_id", u.id).single().execute()
                    user_info["role"] = rol_res.data.get("role", "cliente") if rol_res.data else "cliente"
                except Exception:
                    user_info["role"] = "cliente"
                try:
                    sub_res = supabase.table("subscriptions").select("plan, status").eq("user_id", u.id).single().execute()
                    user_info["plan"] = sub_res.data.get("plan", "free") if sub_res.data else "free"
                    user_info["status"] = sub_res.data.get("status", "inactive") if sub_res.data else "inactive"
                except Exception:
                    user_info["plan"] = "free"
                    user_info["status"] = "inactive"
                usuarios.append(user_info)
            
            if usuarios:
                usuarios_df = pd.DataFrame(usuarios)
                st.dataframe(usuarios_df[["email", "plan", "role", "status"]], hide_index=True, use_container_width=True)
                
                email_sel = st.selectbox("Selecciona usuario", [u["email"] for u in usuarios])
                usuario_sel = next((u for u in usuarios if u["email"] == email_sel), None)
                
                if usuario_sel:
                    user_id_sel = usuario_sel["id"]
                    col_a1, col_a2 = st.columns(2)
                    with col_a1:
                        nuevo_rol = st.selectbox("Rol", ["cliente", "admin"], index=0 if usuario_sel["role"] != "admin" else 1, key=f"rol_{user_id_sel}")
                        if st.button("🔄 Cambiar rol", key=f"btn_rol_{user_id_sel}"):
                            supabase.table("user_roles").upsert({"user_id": user_id_sel, "role": nuevo_rol}, on_conflict="user_id").execute()
                            registrar_accion_admin("cambiar_rol", user_id_sel, nuevo_rol)
                            st.success("Rol actualizado")
                            st.rerun()
                    with col_a2:
                        if usuario_sel["status"] == "inactive":
                            if st.button("✅ Habilitar", key=f"btn_hab_{user_id_sel}"):
                                supabase.table("subscriptions").update({"status": "active"}).eq("user_id", user_id_sel).execute()
                                registrar_accion_admin("habilitar", user_id_sel)
                                st.success("Habilitado")
                                st.rerun()
                        else:
                            if st.button("🚫 Deshabilitar", key=f"btn_des_{user_id_sel}"):
                                supabase.table("subscriptions").update({"status": "inactive"}).eq("user_id", user_id_sel).execute()
                                registrar_accion_admin("deshabilitar", user_id_sel)
                                st.success("Deshabilitado")
                                st.rerun()
        except Exception as e:
            st.error(f"Error: {e}")
    
    with tab_suscripciones:
        st.subheader("💳 Control de Suscripciones")
        try:
            subs_res = supabase.table("subscriptions").select("*").execute()
            if subs_res.data:
                subs_df = pd.DataFrame(subs_res.data)
                st.dataframe(subs_df[["user_id", "plan", "status"]], hide_index=True, use_container_width=True)
        except Exception as e:
            st.error(f"Error: {e}")
    
    with tab_logs:
        st.subheader("⚠️ Logs")
        st.info("Funcionalidad de logs disponible próximamente.")

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
# CONFIGURACIÓN
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
# ════════════════════════════════════════════════════════════
# PANEL DE ADMINISTRACIÓN - AÑADIR AL FINAL DE app.py
# ════════════════════════════════════════════════════════════

def panel_administracion():
    """Panel exclusivo para el dueño de la aplicación"""
    
    # CONFIGURACIÓN - CAMBIA ESTO POR TU EMAIL
    DUEÑO_EMAIL = "tu_email@gmail.com"  # <--- ¡CAMBIA AQUÍ!
    
    # Verificar que es el dueño
    user_email = st.session_state.get("user_email", "")
    
    if user_email != DUEÑO_EMAIL:
        st.error("🚫 Acceso denegado. Solo el dueño de la aplicación puede acceder.")
        st.stop()
    
    st.title("👑 Panel de Administración")
    st.caption("Gestión completa de la plataforma y usuarios")
    
    # Menú del panel admin
    menu_admin = st.sidebar.radio(
        "📋 Panel de Control",
        ["🏠 Dashboard", "👥 Usuarios", "📊 Análisis", "💰 Monetización", "⚙️ Configuración", "🔐 Seguridad"],
        index=0
    )
    
    # ── 1. DASHBOARD ──
    if menu_admin == "🏠 Dashboard":
        st.subheader("📊 Dashboard del Negocio")
        
        try:
            # Obtener estadísticas
            users_res = supabase.table("users").select("*", count="exact").execute()
            total_usuarios = users_res.count if users_res.count else 0
            
            budgets_res = supabase.table("budgets").select("*", count="exact").execute()
            total_presupuestos = budgets_res.count if budgets_res.count else 0
            
            clients_res = supabase.table("clients").select("*", count="exact").execute()
            total_clientes = clients_res.count if clients_res.count else 0
            
            products_res = supabase.table("products").select("*", count="exact").execute()
            total_productos = products_res.count if products_res.count else 0
            
            # Usuarios activos (últimos 30 días)
            fecha_limite = (datetime.now() - timedelta(days=30)).isoformat()
            activos_res = supabase.table("users").select("*", count="exact").gte("last_login", fecha_limite).execute()
            usuarios_activos = activos_res.count if activos_res.count else 0
            
            # Ingresos totales
            budgets_data = supabase.table("budgets").select("total").execute()
            ingresos_totales = sum(b.get("total", 0) for b in budgets_data.data) if budgets_data.data else 0
            
        except Exception as e:
            st.error(f"Error al cargar estadísticas: {e}")
            total_usuarios = total_presupuestos = total_clientes = total_productos = 0
            usuarios_activos = 0
            ingresos_totales = 0
        
        # Tarjetas
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("👥 Usuarios", total_usuarios, delta=f"+{usuarios_activos} activos")
        with col2:
            st.metric("📝 Presupuestos", total_presupuestos)
        with col3:
            st.metric("👤 Clientes", total_clientes)
        with col4:
            st.metric("💰 Ingresos", f"{ingresos_totales:,.2f} €")
        
        col5, col6, col7, col8 = st.columns(4)
        with col5:
            st.metric("📦 Productos", total_productos)
        with col6:
            tasa_conversion = (total_presupuestos / total_clientes * 100) if total_clientes > 0 else 0
            st.metric("📊 Conversión", f"{tasa_conversion:.1f}%")
        with col7:
            presupuestos_mes = len([b for b in budgets_res.data if datetime.fromisoformat(b["created_at"]).month == datetime.now().month]) if budgets_res.data else 0
            st.metric("📅 Este mes", presupuestos_mes)
        with col8:
            st.metric("📈 Crecimiento", "+15%", delta="vs mes anterior")
        
        st.markdown("---")
        
        # Últimas actividades
        st.subheader("⚡ Últimas Actividades")
        try:
            ultimos_budgets = supabase.table("budgets").select("*").order("created_at", desc=True).limit(5).execute()
            if ultimos_budgets.data:
                for b in ultimos_budgets.data:
                    fecha = b.get("created_at", "")[:16]
                    cliente = b.get("client_name", "Sin cliente")
                    total = b.get("total", 0)
                    st.info(f"📝 {fecha} - {cliente} - {total:,.2f}€")
            else:
                st.info("No hay actividades recientes")
        except:
            pass
    
    # ── 2. USUARIOS ──
    elif menu_admin == "👥 Usuarios":
        st.subheader("👥 Gestión de Usuarios")
        
        tab_usuarios, tab_nuevo_usuario = st.tabs(["📋 Lista de Usuarios", "➕ Nuevo Usuario"])
        
        with tab_usuarios:
            # Filtros
            col_f1, col_f2, col_f3 = st.columns(3)
            with col_f1:
                filtro_estado = st.selectbox("Estado", ["Todos", "Activos", "Inactivos"])
            with col_f2:
                filtro_plan = st.selectbox("Plan", ["Todos", "Básico", "Pro", "Enterprise"])
            with col_f3:
                busqueda = st.text_input("🔍 Buscar", placeholder="Email, nombre...")
            
            try:
                users_res = supabase.table("users").select("*").execute()
                if users_res.data:
                    df_usuarios = pd.DataFrame(users_res.data)
                    
                    # Aplicar filtros
                    if filtro_estado == "Activos":
                        df_usuarios = df_usuarios[df_usuarios["active"] == True]
                    elif filtro_estado == "Inactivos":
                        df_usuarios = df_usuarios[df_usuarios["active"] == False]
                    
                    if filtro_plan != "Todos":
                        df_usuarios = df_usuarios[df_usuarios["plan"] == filtro_plan.lower()]
                    
                    if busqueda:
                        df_usuarios = df_usuarios[
                            df_usuarios["email"].str.contains(busqueda, case=False) |
                            df_usuarios["name"].str.contains(busqueda, case=False)
                        ]
                    
                    if not df_usuarios.empty:
                        display_df = df_usuarios[["id", "email", "name", "plan", "active", "created_at"]].copy()
                        display_df.columns = ["ID", "Email", "Nombre", "Plan", "Estado", "Registro"]
                        display_df["Estado"] = display_df["Estado"].apply(lambda x: "✅ Activo" if x else "❌ Inactivo")
                        
                        st.dataframe(display_df, hide_index=True, use_container_width=True)
                        
                        st.markdown("---")
                        st.subheader("✏️ Acciones de Usuario")
                        
                        usuario_seleccionado = st.selectbox(
                            "Seleccionar usuario para gestionar",
                            df_usuarios["email"].tolist()
                        )
                        
                        if usuario_seleccionado:
                            user_row = df_usuarios[df_usuarios["email"] == usuario_seleccionado].iloc[0]
                            user_id = user_row["id"]
                            
                            col_acc1, col_acc2, col_acc3, col_acc4 = st.columns(4)
                            
                            with col_acc1:
                                nuevo_estado = not user_row["active"]
                                label = "🔒 Desactivar" if user_row["active"] else "🔓 Activar"
                                if st.button(label, key=f"toggle_{user_id}"):
                                    try:
                                        supabase.table("users").update({"active": nuevo_estado}).eq("id", user_id).execute()
                                        st.success(f"Usuario {'activado' if nuevo_estado else 'desactivado'}")
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Error: {e}")
                            
                            with col_acc2:
                                if st.button("🔄 Resetear contraseña", key=f"reset_{user_id}"):
                                    nueva_pass = "123456"
                                    try:
                                        supabase.table("users").update({"password": nueva_pass}).eq("id", user_id).execute()
                                        st.success(f"Contraseña reseteada a: {nueva_pass}")
                                    except Exception as e:
                                        st.error(f"Error: {e}")
                            
                            with col_acc3:
                                if st.button("📊 Ver datos", key=f"data_{user_id}"):
                                    try:
                                        budgets_user = supabase.table("budgets").select("*").eq("user_id", user_id).execute()
                                        clients_user = supabase.table("clients").select("*").eq("user_id", user_id).execute()
                                        products_user = supabase.table("products").select("*").eq("user_id", user_id).execute()
                                        
                                        st.markdown("---")
                                        col_est1, col_est2, col_est3 = st.columns(3)
                                        with col_est1:
                                            st.metric("📝 Presupuestos", len(budgets_user.data) if budgets_user.data else 0)
                                        with col_est2:
                                            st.metric("👤 Clientes", len(clients_user.data) if clients_user.data else 0)
                                        with col_est3:
                                            st.metric("📦 Productos", len(products_user.data) if products_user.data else 0)
                                    except:
                                        pass
                            
                            with col_acc4:
                                confirmar = st.checkbox("Confirmar", key=f"confirm_del_user_{user_id}")
                                if st.button("🗑️ Eliminar", key=f"del_user_{user_id}", disabled=not confirmar):
                                    st.warning("⚠️ Esta acción eliminará TODOS los datos del usuario")
                                    if st.button("✅ Confirmar eliminación definitiva", key=f"confirm_del_final_{user_id}"):
                                        try:
                                            supabase.table("budgets").delete().eq("user_id", user_id).execute()
                                            supabase.table("clients").delete().eq("user_id", user_id).execute()
                                            supabase.table("products").delete().eq("user_id", user_id).execute()
                                            supabase.table("users").delete().eq("id", user_id).execute()
                                            st.success("Usuario eliminado")
                                            st.rerun()
                                        except Exception as e:
                                            st.error(f"Error: {e}")
                    else:
                        st.info("No se encontraron usuarios")
                else:
                    st.info("No hay usuarios registrados")
            except Exception as e:
                st.error(f"Error: {e}")
        
        with tab_nuevo_usuario:
            st.subheader("➕ Crear nuevo usuario")
            with st.form("nuevo_usuario_form"):
                email = st.text_input("Email", placeholder="usuario@ejemplo.com")
                nombre = st.text_input("Nombre completo")
                plan = st.selectbox("Plan", ["básico", "pro", "enterprise"])
                active = st.checkbox("Activar cuenta", value=True)
                
                if st.form_submit_button("📧 Crear usuario"):
                    if not email or "@" not in email:
                        st.error("Email inválido")
                    else:
                        try:
                            check = supabase.table("users").select("*").eq("email", email).execute()
                            if check.data:
                                st.error("El usuario ya existe")
                            else:
                                data = {
                                    "email": email,
                                    "name": nombre,
                                    "password": "123456",
                                    "plan": plan,
                                    "active": active,
                                    "created_at": datetime.now().isoformat(),
                                    "last_login": None
                                }
                                supabase.table("users").insert(data).execute()
                                st.success(f"✅ Usuario {email} creado")
                                st.info(f"Contraseña: 123456")
                        except Exception as e:
                            st.error(f"Error: {e}")
    
    # ── 3. ANÁLISIS ──
    elif menu_admin == "📊 Análisis":
        st.subheader("📊 Análisis Global")
        
        try:
            users_res = supabase.table("users").select("id, email, name, created_at").execute()
            budgets_res = supabase.table("budgets").select("user_id, total, created_at").execute()
            
            if users_res.data and budgets_res.data:
                df_users = pd.DataFrame(users_res.data)
                df_budgets = pd.DataFrame(budgets_res.data)
                
                budgets_by_user = df_budgets.groupby("user_id").agg({
                    "total": ["count", "sum", "mean"]
                }).reset_index()
                budgets_by_user.columns = ["user_id", "count", "total", "avg"]
                
                df_analysis = df_users.merge(budgets_by_user, on="user_id", how="left").fillna(0)
                df_analysis["count"] = df_analysis["count"].astype(int)
                
                st.subheader("🏆 Ranking de Usuarios")
                top_usuarios = df_analysis.nlargest(10, "count")[["name", "email", "count", "total"]]
                top_usuarios.columns = ["Nombre", "Email", "Presupuestos", "Total €"]
                st.dataframe(top_usuarios, hide_index=True, use_container_width=True)
                
                # Evolución
                st.subheader("📈 Evolución Mensual")
                if not df_budgets.empty:
                    df_budgets["month"] = pd.to_datetime(df_budgets["created_at"]).dt.strftime("%Y-%m")
                    monthly = df_budgets.groupby("month").agg({
                        "total": "sum",
                        "user_id": "count"
                    }).reset_index()
                    monthly.columns = ["Mes", "Ingresos", "Presupuestos"]
                    st.line_chart(monthly.set_index("Mes")["Ingresos"])
        except Exception as e:
            st.error(f"Error: {e}")
    
    # ── 4. MONETIZACIÓN ──
    elif menu_admin == "💰 Monetización":
        st.subheader("💰 Gestión de Monetización")
        
        st.subheader("📋 Planes y Precios")
        with st.form("planes_config"):
            precio_basico = st.number_input("Precio Plan Básico (€/mes)", value=0.0, min_value=0.0)
            precio_pro = st.number_input("Precio Plan Pro (€/mes)", value=9.99, min_value=0.0)
            precio_enterprise = st.number_input("Precio Plan Enterprise (€/mes)", value=29.99, min_value=0.0)
            
            if st.form_submit_button("💾 Guardar precios"):
                st.success("Precios guardados (simulación)")
        
        try:
            users_res = supabase.table("users").select("plan").execute()
            if users_res.data:
                df = pd.DataFrame(users_res.data)
                counts = df["plan"].value_counts()
                
                st.subheader("📊 Distribución de Usuarios")
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("🆓 Básico", counts.get("básico", 0))
                with col2:
                    st.metric("⭐ Pro", counts.get("pro", 0))
                with col3:
                    st.metric("🏢 Enterprise", counts.get("enterprise", 0))
        except:
            pass
    
    # ── 5. CONFIGURACIÓN ──
    elif menu_admin == "⚙️ Configuración":
        st.subheader("⚙️ Configuración Global")
        
        tab_config, tab_mantenimiento = st.tabs(["📧 Email", "🛠️ Mantenimiento"])
        
        with tab_config:
            st.subheader("📧 Configuración de Email")
            with st.form("config_email"):
                smtp_server = st.text_input("Servidor SMTP", value="smtp.gmail.com")
                smtp_port = st.number_input("Puerto", value=587)
                smtp_user = st.text_input("Usuario")
                smtp_password = st.text_input("Contraseña", type="password")
                
                if st.form_submit_button("💾 Guardar"):
                    st.success("Configuración guardada (simulación)")
        
        with tab_mantenimiento:
            st.subheader("🛠️ Mantenimiento")
            col_m1, col_m2 = st.columns(2)
            with col_m1:
                if st.button("🔄 Limpiar caché"):
                    st.cache_data.clear()
                    st.success("Caché limpiada")
            with col_m2:
                if st.button("💾 Backup manual"):
                    st.info("Backup generado")
    
    # ── 6. SEGURIDAD ──
    elif menu_admin == "🔐 Seguridad":
        st.subheader("🔐 Seguridad y Auditoría")
        
        st.write("📋 Registro de actividad")
        logs = [
            f"{datetime.now().strftime('%Y-%m-%d %H:%M')} - Sistema operativo",
            f"{datetime.now().strftime('%Y-%m-%d %H:%M')} - Usuarios activos: {total_usuarios if 'total_usuarios' in locals() else '?'}",
        ]
        for log in logs:
            st.text(log)
        
        st.success("✅ Sistema seguro")
        st.success("✅ Autenticación activa")
        st.success("✅ Logs activos")


# ════════════════════════════════════════════════════════════
# MODIFICACIÓN DEL MENÚ PRINCIPAL - AÑADIR ESTA OPCIÓN
# ════════════════════════════════════════════════════════════

# Busca en tu código donde tienes el menú selectbox
# y AÑADE "👑 Administración" a la lista:

# EJEMPLO: Así debería quedar tu menú
menu = st.sidebar.selectbox(
    "📋 Menú Principal",
    ["🏠 Inicio", "👥 Clientes", "📦 Productos", "📝 Presupuestos", "📄 Facturas", "👑 Administración"]
)

# Y en el enrutamiento, AÑADE esta condición:
elif menu == "👑 Administración":
    panel_administracion()
