# app.py
import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from datetime import datetime, date, timedelta
import json
import time

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
from banking import iniciar_conexion_gocardless, completar_importacion
from auth_utils import login_user, register_user, reset_password, logout, APP_URL
from data_service import (
    get_invoices, get_clients, get_suppliers, get_products, get_expenses,
    get_bank_transactions, get_recurring_invoices, get_budgets, get_journal_entries
)
from certificate_manager import (
    guardar_certificado_usuario, obtener_certificado_usuario,
    eliminar_certificado_usuario, tiene_certificado
)

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
    if st.button("🔒 Cerrar sesión"):
        logout(supabase)
        st.rerun()

menu = st.sidebar.radio("Navegación", [
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
    "⚙️ Configuración"
])

user_id = st.session_state.user_id

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
        
        column_config = {
            "Nombre": st.column_config.TextColumn("Nombre", width="medium"),
            "NIF/CIF": st.column_config.TextColumn("NIF/CIF", width="small"),
            "Dirección": st.column_config.TextColumn("Dirección", width="large"),
            "Tipo": st.column_config.TextColumn("Tipo", width="small"),
        }
        
        st.dataframe(
            clientes_display,
            hide_index=True,
            use_container_width=True,
            column_config=column_config
        )
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
        
        column_config = {
            "Nombre": st.column_config.TextColumn("Nombre", width="medium"),
            "NIF/CIF": st.column_config.TextColumn("NIF/CIF", width="small"),
            "Dirección": st.column_config.TextColumn("Dirección", width="large"),
        }
        
        st.dataframe(
            proveedores_display,
            hide_index=True,
            use_container_width=True,
            column_config=column_config
        )
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
        
        column_config = {
            "Nombre": st.column_config.TextColumn("Nombre", width="medium"),
            "Descripción": st.column_config.TextColumn("Descripción", width="large"),
            "Precio": st.column_config.NumberColumn("Precio", format="%.2f €", width="small"),
            "IVA %": st.column_config.NumberColumn("IVA %", format="%d %%", width="small"),
            "IRPF %": st.column_config.NumberColumn("IRPF %", format="%d %%", width="small"),
        }
        
        st.dataframe(
            productos_display,
            hide_index=True,
            use_container_width=True,
            column_config=column_config
        )
    else:
        st.info("No hay productos en el catálogo.")
        # ════════════════════════════════════════════════════════════
# VENTAS (con tabla mejorada: iconos, filtros y ordenación)
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
                        total_linea = base_linea + vat_amount + irpf_amount
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
                total_factura = base_total + vat_total + irpf_total
                st.write(f"Base imponible: {money(base_total)} | IVA: {money(vat_total)} | IRPF: {money(irpf_total)} | TOTAL: {money(total_factura)}")
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
                        total_linea = base_linea + vat_amount + irpf_amount
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
                total_factura = base_total + vat_total + irpf_total
                st.write(f"Base imponible: {money(base_total)} | IVA: {money(vat_total)} | IRPF: {money(irpf_total)} | TOTAL: {money(total_factura)}")
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

    # ============ TABLA MEJORADA DE FACTURAS EMITIDAS ============
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
                            from facturae_utils import generar_facturae_xml
                            
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
                prov_nombre = st.selectbox("Proveedor", options=proveedores_df["name"].tolist(), index=proveedores_df["name"].tolist().index(datos.get("provider_name", "")))
                tipo_gasto = st.selectbox("Tipo de gasto", TIPOS_GASTO, index=TIPOS_GASTO.index(datos.get("expense_type", "Otros")))
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
# RESTO DE SECCIONES (Facturación recurrente, Libro, Contabilidad,
# Impuestos, Conciliación, Dashboards, Presupuestos, Colaboradores,
# Configuración) - SE MANTIENEN COMO EN TU VERSIÓN ANTERIOR
# ════════════════════════════════════════════════════════════

# ... (El resto del código de Presupuestos, Configuración, etc.
#      se mantiene EXACTAMENTE igual que en tu versión actual)
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
                        "total": r["base_amount"] + (r["base_amount"]*r["vat_percentage"]/100) + (r["base_amount"]*r["irpf_percentage"]/100),
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
# LIBRO CONTABLE GENERAL
# ════════════════════════════════════════════════════════════
elif menu == "📖 Libro Contable General":
    st.title("Libro Registro")
    mes = st.selectbox("Mes", LISTA_MESES, index=datetime.now().month - 1)
    inv = get_invoices(user_id)
    exp = get_expenses(user_id)
    if not inv.empty:
        inv["tipo"] = "Venta"
        inv.rename(columns={"invoice_number": "numero"}, inplace=True)
    if not exp.empty:
        exp["tipo"] = "Gasto"
        exp.rename(columns={"expense_number": "numero"}, inplace=True)
        if "category" in exp.columns:
            exp.rename(columns={"category": "concept"}, inplace=True)
        if "irpf_amount" not in exp.columns:
            exp["irpf_amount"] = 0
    df = pd.concat([inv, exp], ignore_index=True)
    if not df.empty:
        df = df[df["month"] == mes]
        st.dataframe(df[["numero", "date", "concept", "base_amount", "total", "tipo"]], width='stretch')
    else:
        st.info("No hay movimientos en este mes.")

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
            cuentas = supabase.table("journal_entry_lines").select("account").eq("user_id", user_id).execute()
            cuentas_df = pd.DataFrame(cuentas.data) if cuentas.data else pd.DataFrame()
            if not cuentas_df.empty:
                cuenta_sel = st.selectbox("Selecciona cuenta", cuentas_df["account"].unique())
                movs = supabase.table("journal_entry_lines")\
                    .select("*, journal_entries(date)")\
                    .eq("user_id", user_id)\
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
        activo_total = activo_corriente
        pasivo_corriente = exp_f["total"].sum() if not exp_f.empty else 0.0
        pasivo_total = pasivo_corriente
        patrimonio_neto = activo_total - pasivo_total
        col_b1, col_b2, col_b3 = st.columns(3)
        col_b1.metric("Activo (Cuentas a cobrar)", money(activo_total))
        col_b2.metric("Pasivo (Cuentas a pagar)", money(pasivo_total))
        col_b3.metric("Patrimonio Neto", money(patrimonio_neto))
        st.caption("Balance simplificado: Activo = facturas emitidas, Pasivo = gastos registrados.")

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
    anio = st.selectbox("Año", [2025,2026,2027,2028,2029,2030], index=[2025,2026,2027,2028,2029,2030].index(anio_actual) if anio_actual in [2025,2026,2027,2028,2029,2030] else 0)
    trimestre = st.selectbox("Trimestre", ["1T (Ene-Mar)","2T (Abr-Jun)","3T (Jul-Sep)","4T (Oct-Dic)"], index=["1T (Ene-Mar)","2T (Abr-Jun)","3T (Jul-Sep)","4T (Oct-Dic)"].index(trimestre_actual))
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
    st.subheader(f"Resumen {trimestre} {anio}")
    col1,col2,col3 = st.columns(3)
    col1.metric("Ventas (base)", money(base_ventas))
    col2.metric("IVA repercutido", money(iva_repercutido))
    col3.metric("IRPF retenido", money(irpf_retenido))
    col4,col5,col6 = st.columns(3)
    col4.metric("Compras (base)", money(base_compras))
    col5.metric("IVA soportado", money(iva_soportado))
    col6.metric("IVA a ingresar", money(max(iva_repercutido - iva_soportado, 0)))
    st.markdown("---")
    st.subheader("Pago fraccionado IRPF (estimación)")
    col7,col8,col9 = st.columns(3)
    col7.metric("Beneficio neto", money(beneficio_neto))
    col8.metric("% aplicado", "20 %")
    col9.metric("💶 Pago fraccionado", money(pago_fraccionado))
    if st.button("📄 Generar archivo Modelo 303"):
        iva_ingresar = max(iva_repercutido - iva_soportado, 0)
        contenido = f"303\r\n{anio}\r\n{trimestre}\r\n{int(base_ventas*100):011d}\r\n{int(iva_repercutido*100):011d}\r\n{int(base_compras*100):011d}\r\n{int(iva_soportado*100):011d}\r\n{int(iva_ingresar*100):011d}\r\n{int(abs(irpf_retenido)*100):011d}\r\n"
        st.download_button("Descargar 303.txt", contenido.encode("utf-8"), f"303_{anio}_{trimestre.replace(' ','')}.txt", "text/plain")

# ════════════════════════════════════════════════════════════
# CONCILIACIÓN BANCARIA
# ════════════════════════════════════════════════════════════
elif menu == "🏦 Conciliación Bancaria":
    st.title("Conciliación Bancaria")
    tab1, tab2 = st.tabs(["Cargar CSV", "GoCardless (Sandbox)"])
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
                            st.error(f"Error al insertar movimiento: {e}")
                    st.success("Movimientos importados correctamente.")
                    get_bank_transactions.clear()
                    st.rerun()
            except Exception as e:
                st.error(f"Error al leer CSV: {e}")
    with tab2:
        st.subheader("Importar desde GoCardless (Sandbox)")
        st.markdown("Conecta tu banco de pruebas y descarga los últimos 30 días automáticamente.")
        if "gocardless_step" not in st.session_state:
            st.session_state.gocardless_step = "idle"
        if st.session_state.gocardless_step == "idle":
            if st.button("🔌 Iniciar conexión con GoCardless"):
                exito, link, req_id = iniciar_conexion_gocardless()
                if exito:
                    st.session_state.gocardless_step = "waiting_auth"
                    st.rerun()
                else:
                    st.error(link)
        elif st.session_state.gocardless_step == "waiting_auth":
            link = st.session_state.get("gocardless_link", "#")
            st.info(f"🔗 [Abrir enlace de autorización]({link}) (sandbox)")
            if st.button("✅ He autorizado la cuenta (continuar)"):
                exito, mensaje, df = completar_importacion(user_id, supabase)
                if exito:
                    st.success(mensaje)
                    if df is not None and not df.empty:
                        st.dataframe(df.head(10))
                    st.session_state.gocardless_step = "idle"
                    get_bank_transactions.clear()
                else:
                    st.error(mensaje)
                    st.session_state.gocardless_step = "idle"
                st.rerun()
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
                                    st.error(f"Error al vincular factura: {e}")
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
                                    st.error(f"Error al vincular gasto: {e}")
    else:
        st.info("No hay movimientos bancarios.")

# ════════════════════════════════════════════════════════════
# DASHBOARDS
# ════════════════════════════════════════════════════════════
elif menu == "📊 Dashboards":
    st.title("📊 Dashboards de Facturación")
    invoices = get_invoices(user_id)
    if invoices.empty:
        st.info("No hay facturas para mostrar.")
    else:
        invoices["date_dt"] = pd.to_datetime(invoices["date"], errors="coerce")
        invoices["year"] = invoices["date_dt"].dt.year
        invoices["month_name"] = invoices["date_dt"].dt.month.apply(lambda x: LISTA_MESES[x-1] if 1 <= x <= 12 else "Desconocido")
        invoices["month_num"] = invoices["date_dt"].dt.month
        col1, col2 = st.columns(2)
        with col1:
            years_disponibles = sorted(invoices["year"].dropna().unique(), reverse=True)
            year_seleccionado = st.selectbox("📅 Año", years_disponibles, index=0 if years_disponibles else 0)
        with col2:
            opciones_meses = ["Todos"] + LISTA_MESES
            mes_seleccionado = st.selectbox("📆 Mes", opciones_meses, index=0)
        data_filtrada = invoices[invoices["year"] == year_seleccionado].copy()
        if mes_seleccionado != "Todos":
            data_filtrada = data_filtrada[data_filtrada["month_name"] == mes_seleccionado]
        if data_filtrada.empty:
            st.warning("No hay facturas en el período seleccionado.")
        else:
            total_ingresos = data_filtrada["total"].sum()
            num_facturas = len(data_filtrada)
            promedio = total_ingresos / num_facturas if num_facturas > 0 else 0
            kpi1, kpi2, kpi3 = st.columns(3)
            kpi1.metric("💰 Total Ingresos", money(total_ingresos))
            kpi2.metric("📄 Facturas Emitidas", num_facturas)
            kpi3.metric("📊 Promedio por Venta", money(promedio))
            st.markdown("---")
            if mes_seleccionado == "Todos":
                ingresos_mensuales = data_filtrada.groupby(["month_num", "month_name"])["total"].sum().reset_index()
                ingresos_mensuales = ingresos_mensuales.sort_values("month_num")
                x_labels = ingresos_mensuales["month_name"].tolist()
                valores = ingresos_mensuales["total"].tolist()
                titulo = f"Ingresos en {year_seleccionado}"
            else:
                data_filtrada["day"] = data_filtrada["date_dt"].dt.day
                ingresos_diarios = data_filtrada.groupby("day")["total"].sum().reset_index()
                x_labels = [str(d) for d in ingresos_diarios["day"]]
                valores = ingresos_diarios["total"].tolist()
                titulo = f"Ingresos diarios en {mes_seleccionado} {year_seleccionado}"
            if valores:
                fig, ax = plt.subplots(figsize=(10, 5))
                ax.bar(range(len(valores)), valores, color="#1E3A8A", edgecolor="white")
                ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{x:,.0f} €"))
                ax.set_xticks(range(len(x_labels)))
                ax.set_xticklabels(x_labels, rotation=45, ha="right")
                ax.set_ylabel("Total (€)")
                ax.set_title(titulo, fontsize=16, fontweight="bold", color="#0F172A")
                ax.grid(axis="y", linestyle="--", alpha=0.7)
                ax.spines["top"].set_visible(False)
                ax.spines["right"].set_visible(False)
                ax.spines["left"].set_visible(False)
                fig.tight_layout(pad=2)
                st.pyplot(fig)

# ════════════════════════════════════════════════════════════
# PRESUPUESTOS
# ════════════════════════════════════════════════════════════
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
    except Exception as e:
        st.error(f"Error al cargar configuración: {e}")
        empresa = {"user_id": user_id, "company_name": AUTONOMO_NAME, "company_tax_id": AUTONOMO_TAX_ID, "company_address": AUTONOMO_ADDRESS, "company_iban": AUTONOMO_IBAN, "company_phone": "", "company_email": "", "company_logo": ""}

    if "editing_budget_id" not in st.session_state:
        st.session_state.editing_budget_id = None
    if "edit_budget_data" not in st.session_state:
        st.session_state.edit_budget_data = None

    tab_nuevo, tab_historial = st.tabs(["Nuevo / Editar presupuesto", "Historial de presupuestos"])

    with tab_nuevo:
        clientes_df = get_clients(user_id)
        productos_df = get_products(user_id)
        if not productos_df.empty:
            for col in ["description", "price", "default_vat_percentage", "default_irpf_percentage"]:
                if col not in productos_df.columns:
                    productos_df[col] = "" if col == "description" else 0.0

        modo_edicion = st.radio("Modo de trabajo", ["Crear nuevo presupuesto", "Editar presupuesto existente"], horizontal=True, key="modo_presupuesto", index=0 if st.session_state.editing_budget_id is None else 1)

        if modo_edicion == "Editar presupuesto existente":
            budgets_df = get_budgets(user_id)
            if budgets_df.empty:
                st.warning("No hay presupuestos guardados.")
                st.stop()
            budget_sel = st.selectbox("Selecciona el presupuesto a editar", budgets_df["budget_number"].tolist(), key="editar_budget_select")
            if budget_sel:
                budget_row = budgets_df[budgets_df["budget_number"] == budget_sel].iloc[0]
                budget_id = budget_row["id"]
                try:
                    resp = supabase.table("budgets").select("*").eq("id", budget_id).single().execute()
                    if resp.data:
                        budget_data = resp.data
                        st.session_state.editing_budget_id = budget_id
                        st.session_state.edit_budget_data = budget_data
                except Exception as e:
                    st.error(f"Error al cargar presupuesto: {e}")
            if st.button("Cancelar edición", key="cancel_edit"):
                st.session_state.editing_budget_id = None
                st.session_state.edit_budget_data = None
                st.rerun()
        else:
            st.session_state.editing_budget_id = None
            st.session_state.edit_budget_data = None

        if st.session_state.editing_budget_id and st.session_state.edit_budget_data:
            budget_data = st.session_state.edit_budget_data
            cliente_pre = {"name": budget_data.get("client_name", ""), "tax_id": budget_data.get("client_tax_id", ""), "address": budget_data.get("client_address", "")}
            lineas_pre = json.loads(budget_data.get("lines", "[]"))
            fecha_pre = budget_data.get("date", str(date.today()))
            try:
                fecha_pre_dt = datetime.strptime(fecha_pre, "%Y-%m-%d").date()
            except:
                fecha_pre_dt = date.today()
        else:
            cliente_pre = {"name": "", "tax_id": "", "address": ""}
            lineas_pre = []
            fecha_pre_dt = date.today()

        st.subheader("Datos del cliente")
        modo_cliente = st.radio("Seleccionar cliente", ["Existente", "Nuevo (manual)"], horizontal=True, key="modo_cliente")
        if modo_cliente == "Existente":
            if clientes_df.empty:
                st.warning("No hay clientes registrados. Cambie a modo manual.")
                cliente = {"name": "", "tax_id": "", "address": ""}
            else:
                cliente_sel = st.selectbox("Cliente", clientes_df["name"].tolist(), key="cliente_select")
                cliente_row = clientes_df[clientes_df["name"] == cliente_sel].iloc[0]
                cliente = {"name": cliente_row["name"], "tax_id": cliente_row["tax_id"], "address": cliente_row["address"]}
        else:
            cliente = {
                "name": st.text_input("Nombre/Razón Social", value=cliente_pre["name"], key="manual_name"),
                "tax_id": st.text_input("RTN / NIF", value=cliente_pre["tax_id"], key="manual_taxid"),
                "address": st.text_input("Dirección", value=cliente_pre["address"], key="manual_address")
            }

        st.markdown("---")
        fecha = st.date_input("Fecha del presupuesto", value=fecha_pre_dt, key="fecha_presupuesto")
        st.subheader("Líneas del presupuesto")
        num_lineas = st.number_input("Número de líneas", min_value=1, max_value=20, value=max(len(lineas_pre), 1), step=1, key="num_lineas")
        lista_productos = ["-- Manual --"]
        if not productos_df.empty and "name" in productos_df.columns:
            lista_productos += productos_df["name"].tolist()
        lineas = []
        for i in range(int(num_lineas)):
            lin_pre = lineas_pre[i] if i < len(lineas_pre) else None
            cols = st.columns([3, 2, 2, 2])
            with cols[0]:
                prod_sel = st.selectbox(f"Producto {i+1}", lista_productos, key=f"bud_prod_{i}")
                if prod_sel == "-- Manual --":
                    desc_manual = st.text_input(f"Descripción {i+1}", value=lin_pre.get("description", "") if lin_pre else "", key=f"bud_desc_{i}")
                else:
                    prod_info = productos_df[productos_df["name"] == prod_sel]
                    descripcion_producto = prod_info.iloc[0].get("description", "") if not prod_info.empty else ""
                    desc_manual = st.text_area(f"Descripción {i+1} (editable)", value=descripcion_producto or "", key=f"bud_desc_{i}", height=80)
            with cols[1]:
                cantidad = st.number_input(f"Cantidad {i+1}", min_value=1.0, value=float(lin_pre["quantity"]) if lin_pre else 1.0, step=1.0, key=f"bud_qty_{i}")
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
                precio = st.number_input(f"Precio ud. {i+1}", min_value=0.0, value=precio_default, step=10.0, key=f"bud_price_{i}")
                vat = st.number_input(f"IVA % {i+1}", value=vat_default, step=1.0, key=f"bud_vat_{i}")
                irpf = st.number_input(f"IRPF % {i+1}", value=irpf_default, step=1.0, key=f"bud_irpf_{i}")
            with cols[3]:
                base_linea = cantidad * precio
                vat_amount = base_linea * vat / 100
                irpf_amount = base_linea * irpf / 100
                total_linea = base_linea + vat_amount + irpf_amount
                st.text(f"Total: {money(total_linea)}")
            descripcion_linea = f"{prod_sel}\n{desc_manual.strip()}" if prod_sel != "-- Manual --" and desc_manual.strip() else (desc_manual.strip() if desc_manual.strip() else prod_sel)
            lineas.append({"description": descripcion_linea, "quantity": cantidad, "unit_price": precio, "base_amount": base_linea, "vat_percentage": vat, "vat_amount": vat_amount, "irpf_percentage": irpf, "irpf_amount": irpf_amount, "total": total_linea})

        if lineas:
            base_total = sum(l["base_amount"] for l in lineas)
            vat_total = sum(l["vat_amount"] for l in lineas)
            irpf_total = sum(l["irpf_amount"] for l in lineas)
            total = base_total + vat_total + irpf_total
        else:
            base_total = vat_total = irpf_total = total = 0.0

        st.markdown("---")
        st.subheader("🔍 Vista previa del presupuesto")
        with st.container(border=True):
            st.markdown(f"**{empresa.get('company_name', '')}**")
            st.markdown(f"{empresa.get('company_address', '')}")
            st.markdown(f"NIF: {empresa.get('company_tax_id', '')}")
            st.markdown("---")
            st.markdown(f"**PRESUPUESTO** (fecha: {fecha.strftime('%d/%m/%Y')})")
            st.markdown(f"**Cliente:** {cliente.get('name', '')} - NIF: {cliente.get('tax_id', '')}")
            if lineas:
                lineas_df = pd.DataFrame(lineas)
                vista_df = lineas_df[["description", "quantity", "unit_price", "total"]].copy()
                vista_df.columns = ["Descripción", "Cant.", "Precio ud.", "Total"]
                vista_df["Precio ud."] = vista_df["Precio ud."].apply(lambda x: f"{x:,.2f} €")
                vista_df["Total"] = vista_df["Total"].apply(lambda x: f"{x:,.2f} €")
                st.dataframe(vista_df, hide_index=True, use_container_width=True)
            st.markdown("---")
            st.markdown(f"**Base imponible:** {money(base_total)}")
            st.markdown(f"**IVA:** {money(vat_total)}")
            st.markdown(f"### **TOTAL: {money(total)}**")

        st.markdown("---")
        col_acc1, col_acc2, col_acc3 = st.columns(3)
        with col_acc1:
            if st.button("💾 Guardar presupuesto", key="guardar_presupuesto"):
                if not validar_nif_cif(cliente.get("tax_id", "")):
                    st.error("El NIF del cliente no es válido.")
                else:
                    if st.session_state.editing_budget_id:
                        try:
                            supabase.table("budgets").update({
                                "date": str(fecha), "client_name": cliente.get("name", ""),
                                "client_tax_id": cliente.get("tax_id", ""), "client_address": cliente.get("address", ""),
                                "lines": json.dumps(lineas), "base_total": base_total, "vat_total": vat_total,
                                "irpf_total": irpf_total, "total": total,
                                "vat_pct": lineas[0]["vat_percentage"] if lineas else 21,
                                "irpf_pct": lineas[0]["irpf_percentage"] if lineas else 0,
                            }).eq("id", st.session_state.editing_budget_id).execute()
                            st.success("Presupuesto actualizado correctamente.")
                            st.session_state.editing_budget_id = None
                            st.session_state.edit_budget_data = None
                            get_budgets.clear()
                            time.sleep(0.5)
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error al actualizar presupuesto: {e}")
                    else:
                        budget_number = obtener_siguiente_numero_presupuesto(user_id)
                        data = {
                            "user_id": user_id, "budget_number": budget_number,
                            "date": str(fecha), "client_name": cliente.get("name", ""),
                            "client_tax_id": cliente.get("tax_id", ""), "client_address": cliente.get("address", ""),
                            "lines": json.dumps(lineas), "base_total": base_total, "vat_total": vat_total,
                            "irpf_total": irpf_total, "total": total,
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
                            st.error(f"Error al guardar presupuesto: {e}")
        with col_acc2:
            if st.button("📄 Generar PDF del presupuesto", key="pdf_presupuesto"):
                if not validar_nif_cif(cliente.get("tax_id", "")):
                    st.error("El NIF del cliente no es válido.")
                else:
                    empresa["user_id"] = user_id
                    vat_pct = lineas[0]["vat_percentage"] if lineas else 21
                    temp_budget_number = obtener_siguiente_numero_presupuesto(user_id)
                    cliente_pdf = {"name": cliente.get("name", ""), "tax_id": cliente.get("tax_id", ""), "address": cliente.get("address", "")}
                    if empresa and cliente_pdf and lineas:
                        pdf_bytes = make_budget_pdf(empresa, cliente_pdf, lineas, base_total, vat_total, total, vat_pct, budget_number=temp_budget_number)
                        if pdf_bytes:
                            st.download_button("⬇️ Descargar PDF", pdf_bytes, "presupuesto.pdf", mime="application/pdf", key="download_pdf")
                            destinatario = st.text_input("Email para enviar presupuesto", key="email_presupuesto_nuevo", placeholder="cliente@ejemplo.com")
                            if st.button("📧 Enviar presupuesto por email", key="send_budget_email_nuevo"):
                                if not destinatario or "@" not in destinatario:
                                    st.error("Introduce un email válido.")
                                else:
                                    with st.spinner("Enviando email..."):
                                        exito = enviar_factura_email(destinatario, f"Presupuesto {temp_budget_number}", "Adjunto le enviamos el presupuesto solicitado.", pdf_bytes, f"Presupuesto_{temp_budget_number}.pdf")
                                    if exito:
                                        st.success("Presupuesto enviado correctamente")
                                    else:
                                        st.error("No se pudo enviar el email")
                    else:
                        st.error("Faltan datos para generar el presupuesto.")

    with tab_historial:
        st.subheader("Presupuestos guardados")
        budgets_df = get_budgets(user_id)
        if not budgets_df.empty:
            budgets_display = budgets_df[["budget_number", "date", "client_name", "base_total", "total", "status"]].copy()
            budgets_display.columns = ["Nº Presupuesto", "Fecha", "Cliente", "Base Imponible", "Total", "Estado"]
            budgets_display["Fecha"] = pd.to_datetime(budgets_display["Fecha"]).dt.strftime("%d/%m/%Y")
            column_config = {
                "Nº Presupuesto": st.column_config.TextColumn("Nº Presupuesto", width="small"),
                "Fecha": st.column_config.TextColumn("Fecha", width="small"),
                "Cliente": st.column_config.TextColumn("Cliente", width="medium"),
                "Base Imponible": st.column_config.NumberColumn("Base Imponible", format="%.2f €", width="small"),
                "Total": st.column_config.NumberColumn("Total", format="%.2f €", width="small"),
                "Estado": st.column_config.TextColumn("Estado", width="small"),
            }
            st.markdown("**Haz clic en una fila para ver acciones:**")
            event = st.dataframe(budgets_display, hide_index=True, use_container_width=True, column_config=column_config, selection_mode="single-row", on_select="rerun", key="budgets_table")
            if (event.selection and event.selection.rows and len(event.selection.rows) > 0):
                selected_row = event.selection.rows[0]
                if selected_row is not None and 0 <= selected_row < len(budgets_df):
                    budget_row = budgets_df.iloc[selected_row]
                    budget_id = budget_row["id"]
                    try:
                        resp = supabase.table("budgets").select("*").eq("id", budget_id).single().execute()
                        budget_data = resp.data if resp.data else budget_row.to_dict()
                    except Exception:
                        budget_data = budget_row.to_dict()
                    st.markdown("---")
                    st.subheader(f"Acciones para presupuesto {budget_data['budget_number']}")
                    st.write(f"**Cliente:** {budget_data.get('client_name', '')}")
                    st.write(f"**Fecha:** {budget_data.get('date', '')}")
                    st.write(f"**Total:** {money(budget_data.get('total', 0))}")
                    try:
                        lineas_db = json.loads(budget_data.get("lines", "[]"))
                        if lineas_db:
                            st.table(pd.DataFrame(lineas_db)[["description", "quantity", "unit_price", "total"]])
                    except Exception:
                        lineas_db = []
                    client_d = {"name": budget_data.get("client_name", ""), "tax_id": budget_data.get("client_tax_id", ""), "address": budget_data.get("client_address", "")}
                    col1, col2, col3, col4 = st.columns(4)
                    with col1:
                        if st.button("📄 Descargar PDF", key=f"pdf_{budget_id}"):
                            empresa["user_id"] = user_id
                            if empresa and client_d and lineas_db:
                                pdf_bytes = make_budget_pdf(empresa, client_d, lineas_db, budget_data.get("base_total", 0), budget_data.get("vat_total", 0), budget_data.get("total", 0), budget_data.get("vat_pct", 21), budget_number=budget_data.get("budget_number", "---"))
                                if pdf_bytes:
                                    st.download_button("Descargar PDF", pdf_bytes, f"Presupuesto_{budget_data['budget_number']}.pdf", mime="application/pdf", key=f"dl_{budget_id}")
                    with col2:
                        if st.button("📧 Enviar por email", key=f"email_btn_{budget_id}"):
                            st.session_state[f"show_email_{budget_id}"] = True
                        if st.session_state.get(f"show_email_{budget_id}", False):
                            destinatario = st.text_input("Email del destinatario", key=f"email_dest_{budget_id}", placeholder="cliente@ejemplo.com")
                            if st.button("✅ Enviar ahora", key=f"send_{budget_id}"):
                                if not destinatario or "@" not in destinatario:
                                    st.error("Introduce un email válido.")
                                else:
                                    empresa["user_id"] = user_id
                                    if empresa and client_d and lineas_db:
                                        pdf_bytes = make_budget_pdf(empresa, client_d, lineas_db, budget_data.get("base_total", 0), budget_data.get("vat_total", 0), budget_data.get("total", 0), budget_data.get("vat_pct", 21), budget_number=budget_data.get("budget_number", "---"))
                                        if pdf_bytes:
                                            with st.spinner("Enviando email..."):
                                                exito = enviar_factura_email(destinatario, f"Presupuesto {budget_data['budget_number']}", "Adjunto le enviamos el presupuesto solicitado.", pdf_bytes, f"Presupuesto_{budget_data['budget_number']}.pdf")
                                            if exito:
                                                st.success("Presupuesto enviado correctamente")
                                                st.session_state[f"show_email_{budget_id}"] = False
                                                time.sleep(1)
                                                st.rerun()
                                            else:
                                                st.error("No se pudo enviar el email")
                    with col3:
                        if st.button("✏️ Editar", key=f"edit_{budget_id}"):
                            st.session_state.editing_budget_id = budget_id
                            st.session_state.edit_budget_data = budget_data
                            st.rerun()
                    with col4:
                        confirmado = st.checkbox("Confirmar eliminación", key=f"confirm_del_{budget_id}")
                        if st.button("🗑️ Eliminar", key=f"del_{budget_id}", disabled=not confirmado):
                            try:
                                supabase.table("budgets").delete().eq("id", budget_id).execute()
                                st.success("Presupuesto eliminado.")
                                get_budgets.clear()
                                time.sleep(0.5)
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error al eliminar presupuesto: {e}")
        else:
            st.info("No hay presupuestos guardados aún.")

# ════════════════════════════════════════════════════════════
# COLABORADORES
# ════════════════════════════════════════════════════════════
elif menu == "👥 Colaboradores":
    st.title("Colaboradores")
    st.info("Funcionalidad en desarrollo.")

# ════════════════════════════════════════════════════════════
# CONFIGURACIÓN (con gestión de certificado digital)
# ════════════════════════════════════════════════════════════
elif menu == "⚙️ Configuración":
    st.title("Configuración de empresa y plantillas")
    try:
        config_res = supabase.table("settings").select("*").eq("user_id", user_id).execute()
        settings = config_res.data[0] if config_res.data else {}
    except Exception as e:
        st.error(f"Error al cargar configuración: {e}")
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
                st.error("El NIF/CIF de la empresa no es válido.")
            else:
                iban_val = (iban or "").strip()
                if iban_val and not validar_iban(iban_val):
                    st.error("El IBAN introducido no es válido.")
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
                        st.error(f"Error al guardar configuración: {e}")

    # ============ GESTIÓN DE CERTIFICADO DIGITAL ============
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
