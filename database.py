# database.py
import streamlit as st
from supabase import create_client, Client
import pandas as pd
from datetime import datetime, date

@st.cache_resource
def init_supabase() -> Client:
    SUPABASE_URL = st.secrets.get("SUPABASE_URL")
    SUPABASE_KEY = st.secrets.get("SUPABASE_ANON_KEY")
    if not SUPABASE_URL or not SUPABASE_KEY:
        st.error("Faltan variables en st.secrets. Define: SUPABASE_URL y SUPABASE_ANON_KEY.")
        st.stop()
    return create_client(SUPABASE_URL, SUPABASE_KEY)

def _get_supabase() -> Client:
    """
    Devuelve siempre el cliente de Supabase inicializado y cacheado.
    La instancia es única (por el decorador @st.cache_resource) y sobre ella
    se aplican las autenticaciones, garantizando un objeto Client válido.
    """
    return init_supabase()

def safe_df(resp):
    if getattr(resp, "data", None):
        return pd.DataFrame(resp.data)
    return pd.DataFrame()

def refetch(tabla: str, columnas: str = "*", user_id: str = None):
    supabase = _get_supabase()
    query = supabase.table(tabla).select(columnas)
    if user_id:
        query = query.eq("user_id", user_id)
    return query.execute()

def money(x):
    try:
        return f"{float(x):,.2f} €"
    except (ValueError, TypeError):
        return "0.00 €"

def generar_asiento_factura(invoice_id, user_id, fecha, base, iva, total, cliente_nombre):
    supabase = _get_supabase()
    check = supabase.table("invoices_v2").select("id").eq("id", invoice_id).execute()
    if not check.data:
        raise Exception("La factura no existe en la base de datos.")
    entry = {
        "user_id": user_id,
        "date": fecha,
        "description": f"Factura {invoice_id} - {cliente_nombre}",
        "invoice_id": invoice_id
    }
    res = supabase.table("journal_entries").insert(entry).execute()
    if not res.data:
        raise Exception("No se pudo crear la entrada del diario contable.")
    entry_id = res.data[0]["id"]
    lineas = [
        {"journal_entry_id": entry_id, "account": "4300 Clientes", "debit": total, "credit": 0, "description": "Deudor", "user_id": user_id},
        {"journal_entry_id": entry_id, "account": "7000 Ventas", "debit": 0, "credit": base, "description": "Ingreso", "user_id": user_id},
        {"journal_entry_id": entry_id, "account": "4770 IVA repercutido", "debit": 0, "credit": iva, "description": "IVA devengado", "user_id": user_id}
    ]
    for l in lineas:
        supabase.table("journal_entry_lines").insert(l).execute()

def generar_asiento_gasto(expense_id, user_id, fecha, base, iva, total, proveedor_nombre):
    supabase = _get_supabase()
    check = supabase.table("expenses_v2").select("id").eq("id", expense_id).execute()
    if not check.data:
        raise Exception("El gasto no existe en la base de datos.")
    entry = {
        "user_id": user_id,
        "date": fecha,
        "description": f"Gasto {expense_id} - {proveedor_nombre}",
        "expense_id": expense_id
    }
    res = supabase.table("journal_entries").insert(entry).execute()
    if not res.data:
        raise Exception("No se pudo crear la entrada del diario contable.")
    entry_id = res.data[0]["id"]
    lineas = [
        {"journal_entry_id": entry_id, "account": "6000 Compras", "debit": base, "credit": 0, "description": "Gasto", "user_id": user_id},
        {"journal_entry_id": entry_id, "account": "4720 IVA soportado", "debit": iva, "credit": 0, "description": "IVA deducible", "user_id": user_id},
        {"journal_entry_id": entry_id, "account": "4100 Acreedores", "debit": 0, "credit": total, "description": "Proveedor", "user_id": user_id}
    ]
    for l in lineas:
        supabase.table("journal_entry_lines").insert(l).execute()

def crear_factura_con_rollback(invoice_data, lineas_data, user_id, cliente_nombre):
    supabase = _get_supabase()
    invoice_id = None
    try:
        res = supabase.table("invoices_v2").insert(invoice_data).execute()
        if not res.data:
            return False, None, "❌ No se pudo crear la factura (error en cabecera)."
        invoice_id = res.data[0]["id"]
        for linea in lineas_data:
            linea["invoice_id"] = invoice_id
            linea["user_id"] = user_id
            supabase.table("invoice_items").insert(linea).execute()
        generar_asiento_factura(
            invoice_id, user_id,
            invoice_data["date"], invoice_data["base_amount"],
            invoice_data["vat_amount"], invoice_data["total"],
            cliente_nombre
        )
        return True, invoice_id, "Factura y asiento contable generados correctamente."
    except Exception as e:
        if invoice_id:
            try:
                supabase.table("invoices_v2").delete().eq("id", invoice_id).execute()
            except Exception:
                pass
        return False, None, f"Error al crear factura: {str(e)}"

def crear_gasto_con_rollback(expense_data, user_id, proveedor_nombre):
    supabase = _get_supabase()
    expense_id = None
    try:
        res = supabase.table("expenses_v2").insert(expense_data).execute()
        if not res.data:
            return False, None, "❌ No se pudo registrar el gasto."
        expense_id = res.data[0]["id"]
        generar_asiento_gasto(
            expense_id, user_id,
            expense_data["date"], expense_data["base_amount"],
            expense_data["vat_amount"], expense_data["total"],
            proveedor_nombre
        )
        return True, expense_id, "Gasto y asiento contable guardados correctamente."
    except Exception as e:
        if expense_id:
            try:
                supabase.table("expenses_v2").delete().eq("id", expense_id).execute()
            except Exception:
                pass
        return False, None, f"Error al registrar gasto: {str(e)}"

def obtener_siguiente_numero_factura(user_id):
    supabase = _get_supabase()
    res = supabase.table("invoices_v2")\
        .select("invoice_number")\
        .eq("user_id", user_id)\
        .order("created_at", desc=True)\
        .limit(1)\
        .execute()
    if res.data and len(res.data) > 0:
        ultimo = res.data[0]["invoice_number"]
        try:
            num = int(ultimo.split("-")[-1])
            return f"F-{datetime.now().year}-{num+1:04d}"
        except (IndexError, ValueError):
            pass
    return f"F-{datetime.now().year}-0001"

def obtener_siguiente_numero_presupuesto(user_id):
    supabase = _get_supabase()
    res = supabase.table("budgets")\
        .select("budget_number")\
        .eq("user_id", user_id)\
        .order("created_at", desc=True)\
        .limit(1)\
        .execute()
    if res.data and len(res.data) > 0:
        ultimo = res.data[0]["budget_number"]
        try:
            num = int(ultimo.split("-")[-1])
            return f"P-{datetime.now().year}-{num+1:04d}"
        except (IndexError, ValueError):
            pass
    return f"P-{datetime.now().year}-0001"




