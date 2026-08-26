# database.py
import streamlit as st
import hashlib
import pandas as pd
from datetime import datetime, timezone
from supabase import create_client, Client

@st.cache_resource
def init_supabase() -> Client:
    SUPABASE_URL = st.secrets.get("SUPABASE_URL")
    SUPABASE_KEY = st.secrets.get("SUPABASE_ANON_KEY")
    if not SUPABASE_URL or not SUPABASE_KEY:
        st.error("Faltan variables en st.secrets. Define: SUPABASE_URL y SUPABASE_ANON_KEY.")
        st.stop()
    return create_client(SUPABASE_URL, SUPABASE_KEY)

def _get_supabase() -> Client:
    """Devuelve siempre el cliente de Supabase inicializado y cacheado."""
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

# ------------------------------------------------------------
# Funciones para hash encadenado Veri*Factu
# ------------------------------------------------------------
def obtener_ultimo_hash(user_id: str) -> str:
    """Recupera el hash de la última factura del usuario."""
    supabase = _get_supabase()
    res = supabase.table("invoices_v2")\
        .select("hash")\
        .eq("user_id", user_id)\
        .order("created_at", desc=True)\
        .limit(1)\
        .execute()
    if res.data and res.data[0].get("hash"):
        return res.data[0]["hash"]
    return ""

def generar_hash_factura(nif_emisor: str, numero_factura: str, fecha_expedicion: str, tipo_factura: str, importe_total: float, hash_anterior: str):
    """Genera una huella SHA-256 en mayúsculas según estándar Veri*Factu."""
    timestamp_iso = datetime.now(timezone.utc).isoformat(timespec='milliseconds')
    nif_limpio = (nif_emisor or "").strip().upper()
    cadena = f"{nif_limpio}|{numero_factura}|{fecha_expedicion}|{tipo_factura}|{float(importe_total):.2f}|{hash_anterior}|{timestamp_iso}"
    hash_resultado = hashlib.sha256(cadena.encode('utf-8')).hexdigest().upper()
    return hash_resultado, timestamp_iso

def auditar_factura(invoice_id: str, accion: str, hash_factura: str, user_id: str):
    """Registra en facturas_audit con timestamp preciso en milisegundos."""
    supabase = _get_supabase()
    timestamp_actual = datetime.now(timezone.utc).isoformat(timespec='milliseconds')
    try:
        supabase.table("facturas_audit").insert({
            "invoice_id": invoice_id,
            "accion": accion,
            "user_id": user_id,
            "hash": hash_factura,
            "created_at": timestamp_actual
        }).execute()
    except Exception as e:
        st.warning(f"No se pudo registrar auditoría: {e}")

# ------------------------------------------------------------
# Funciones de asientos contables
# ------------------------------------------------------------
def generar_asiento_factura(invoice_id, user_id, fecha, base, iva, irpf, total, cliente_nombre):
    """
    Genera el asiento contable de una factura de venta.
    
    Parámetros:
    - invoice_id: ID de la factura
    - user_id: ID del usuario
    - fecha: Fecha de la factura
    - base: Base imponible
    - iva: IVA repercutido
    - irpf: IRPF retenido (puede ser 0)
    - total: Total de la factura (base + iva - irpf)
    - cliente_nombre: Nombre del cliente
    """
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
    
    # El total a cobrar = total + irpf (porque el IRPF se retiene pero se cobra al cliente)
    total_cobrar = total + irpf if irpf > 0 else total
    
    lineas = [
        {"journal_entry_id": entry_id, "account": "4300 Clientes", "debit": total_cobrar, "credit": 0, "description": "Deudor", "user_id": user_id},
        {"journal_entry_id": entry_id, "account": "7000 Ventas", "debit": 0, "credit": base, "description": "Ingreso", "user_id": user_id},
        {"journal_entry_id": entry_id, "account": "4770 IVA repercutido", "debit": 0, "credit": iva, "description": "IVA devengado", "user_id": user_id}
    ]
    
    # Agregar línea de IRPF si existe
    if irpf > 0:
        lineas.append({
            "journal_entry_id": entry_id,
            "account": "4730 H.P. retenciones",
            "debit": 0,
            "credit": irpf,
            "description": "IRPF retenido",
            "user_id": user_id
        })
    
    for l in lineas:
        supabase.table("journal_entry_lines").insert(l).execute()
    
    return entry_id

def generar_asiento_gasto(expense_id, user_id, fecha, base, iva, irpf, total, proveedor_nombre):
    """
    Genera el asiento contable de un gasto.
    
    Parámetros:
    - expense_id: ID del gasto
    - user_id: ID del usuario
    - fecha: Fecha del gasto
    - base: Base imponible
    - iva: IVA soportado
    - irpf: IRPF retenido (puede ser 0, ej: alquileres)
    - total: Total del gasto (base + iva - irpf)
    - proveedor_nombre: Nombre del proveedor
    """
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
    
    # El total a pagar = total + irpf (porque el IRPF se retiene pero se paga al proveedor)
    total_pagar = total + irpf if irpf > 0 else total
    
    lineas = [
        {"journal_entry_id": entry_id, "account": "6000 Compras", "debit": base, "credit": 0, "description": "Gasto", "user_id": user_id},
        {"journal_entry_id": entry_id, "account": "4720 IVA soportado", "debit": iva, "credit": 0, "description": "IVA deducible", "user_id": user_id},
        {"journal_entry_id": entry_id, "account": "4100 Acreedores", "debit": 0, "credit": total_pagar, "description": "Proveedor", "user_id": user_id}
    ]
    
    # Agregar línea de IRPF si existe
    if irpf > 0:
        lineas.append({
            "journal_entry_id": entry_id,
            "account": "4730 H.P. retenciones",
            "debit": irpf,
            "credit": 0,
            "description": "IRPF retenido",
            "user_id": user_id
        })
    
    for l in lineas:
        supabase.table("journal_entry_lines").insert(l).execute()
    
    return entry_id

# ------------------------------------------------------------
# Creación segura de factura con rollback real
# ------------------------------------------------------------
def crear_factura_con_rollback(invoice_data, lineas_data, user_id, cliente_nombre):
    """
    Crea una factura con rollback real si algo falla.
    
    Retorna:
    - (exito, invoice_id, mensaje)
    """
    supabase = _get_supabase()
    
    # 1. Validar NIF del emisor antes de nada
    config_res = supabase.table("settings").select("company_tax_id").eq("user_id", user_id).execute()
    nif_emisor = config_res.data[0].get("company_tax_id") if config_res.data else None
    
    if not nif_emisor:
        return False, None, "❌ Error: Debes configurar el NIF/CIF de tu empresa en Configuración antes de emitir facturas."

    if not lineas_data:
        return False, None, "❌ Error: La factura debe tener al menos una línea de detalle."

    # 2. Verificar que no exista duplicado
    invoice_number = invoice_data.get("invoice_number", "")
    existing = supabase.table("invoices_v2")\
        .select("id")\
        .eq("user_id", user_id)\
        .eq("invoice_number", invoice_number)\
        .execute()
    
    if existing.data and len(existing.data) > 0:
        return False, None, f"❌ Error: Ya existe una factura con número {invoice_number}."

    invoice_id = None
    entry_id = None
    
    try:
        # 3. Obtener hash anterior
        hash_anterior = obtener_ultimo_hash(user_id)

        # 4. Generar hash Veri*Factu
        hash_nuevo, timestamp_hash = generar_hash_factura(
            nif_emisor,
            invoice_data["invoice_number"],
            invoice_data["date"],
            invoice_data.get("tipo", "normal"),
            invoice_data["total"],
            hash_anterior
        )

        invoice_data["hash"] = hash_nuevo
        invoice_data["hash_anterior"] = hash_anterior
        invoice_data["hash_timestamp"] = timestamp_hash

        # 5. Insertar cabecera de la factura
        res = supabase.table("invoices_v2").insert(invoice_data).execute()
        if not res.data:
            return False, None, "❌ No se pudo crear la factura (error en cabecera)."
        invoice_id = res.data[0]["id"]

        # 6. Insertar líneas de factura
        for linea in lineas_data:
            linea["invoice_id"] = invoice_id
            linea["user_id"] = user_id
            supabase.table("invoice_items").insert(linea).execute()

        # 7. Generar asiento contable
        entry_id = generar_asiento_factura(
            invoice_id, user_id,
            invoice_data["date"], invoice_data["base_amount"],
            invoice_data["vat_amount"], invoice_data.get("irpf_amount", 0),
            invoice_data["total"],
            cliente_nombre
        )

        # 8. Registrar auditoría
        auditar_factura(invoice_id, "creada", hash_nuevo, user_id)

        return True, invoice_id, "Factura y asiento contable generados correctamente."
        
    except Exception as e:
        # ROLLBACK: Eliminar en orden inverso
        st.warning(f"Se produjo un error, revirtiendo cambios...: {str(e)}")
        
        # 1. Eliminar líneas del asiento contable
        if entry_id:
            try:
                supabase.table("journal_entry_lines").delete().eq("journal_entry_id", entry_id).execute()
                supabase.table("journal_entries").delete().eq("id", entry_id).execute()
            except Exception as rollback_e:
                st.warning(f"No se pudo revertir el asiento contable: {rollback_e}")
        
        # 2. Eliminar líneas de factura
        if invoice_id:
            try:
                supabase.table("invoice_items").delete().eq("invoice_id", invoice_id).execute()
            except Exception as rollback_e:
                st.warning(f"No se pudo revertir las líneas de factura: {rollback_e}")
        
        # 3. Eliminar cabecera de factura
        if invoice_id:
            try:
                supabase.table("invoices_v2").delete().eq("id", invoice_id).execute()
            except Exception as rollback_e:
                st.warning(f"No se pudo revertir la factura: {rollback_e}")
        
        return False, None, f"Error al crear la factura: {str(e)}"

def crear_gasto_con_rollback(expense_data, user_id, proveedor_nombre):
    """
    Crea un gasto con rollback real si algo falla.
    
    Retorna:
    - (exito, expense_id, mensaje)
    """
    supabase = _get_supabase()
    expense_id = None
    entry_id = None
    
    try:
        # 1. Insertar gasto
        res = supabase.table("expenses_v2").insert(expense_data).execute()
        if not res.data:
            return False, None, "❌ No se pudo registrar el gasto."
        expense_id = res.data[0]["id"]
        
        # 2. Generar asiento contable
        entry_id = generar_asiento_gasto(
            expense_id, user_id,
            expense_data["date"], expense_data["base_amount"],
            expense_data["vat_amount"], expense_data.get("irpf_amount", 0),
            expense_data["total"],
            proveedor_nombre
        )
        
        return True, expense_id, "Gasto y asiento contable guardados correctamente."
        
    except Exception as e:
        # ROLLBACK
        st.warning(f"Se produjo un error, revirtiendo cambios...: {str(e)}")
        
        if entry_id:
            try:
                supabase.table("journal_entry_lines").delete().eq("journal_entry_id", entry_id).execute()
                supabase.table("journal_entries").delete().eq("id", entry_id).execute()
            except Exception:
                pass
        
        if expense_id:
            try:
                supabase.table("expenses_v2").delete().eq("id", expense_id).execute()
            except Exception:
                pass
        
        return False, None, f"Error al registrar gasto: {str(e)}"

# ------------------------------------------------------------
# Numeración automática
# ------------------------------------------------------------
def obtener_siguiente_numero_factura(user_id, serie="F"):
    """Obtiene el siguiente número de factura para el año actual."""
    supabase = _get_supabase()
    year_actual = datetime.now().year
    
    # Buscar la última factura del año actual con la serie especificada
    res = supabase.table("invoices_v2")\
        .select("invoice_number")\
        .eq("user_id", user_id)\
        .ilike("invoice_number", f"{serie}-{year_actual}-%")\
        .order("invoice_number", desc=True)\
        .limit(1)\
        .execute()
    
    if res.data and len(res.data) > 0:
        ultimo = res.data[0]["invoice_number"]
        try:
            num = int(ultimo.split("-")[-1])
            return f"{serie}-{year_actual}-{num+1:04d}"
        except (IndexError, ValueError):
            pass
    
    return f"{serie}-{year_actual}-0001"

def obtener_siguiente_numero_presupuesto(user_id):
    """Obtiene el siguiente número de presupuesto para el año actual."""
    supabase = _get_supabase()
    year_actual = datetime.now().year
    
    res = supabase.table("budgets")\
        .select("budget_number")\
        .eq("user_id", user_id)\
        .ilike("budget_number", f"P-{year_actual}-%")\
        .order("budget_number", desc=True)\
        .limit(1)\
        .execute()
    
    if res.data and len(res.data) > 0:
        ultimo = res.data[0]["budget_number"]
        try:
            num = int(ultimo.split("-")[-1])
            return f"P-{year_actual}-{num+1:04d}"
        except (IndexError, ValueError):
            pass
    
    return f"P-{year_actual}-0001"
