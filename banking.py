import requests
import pandas as pd
from datetime import datetime, timedelta
import streamlit as st

BASE_URL = "https://bankaccountdata.gocardless.com/api/v2"
INSTITUTION_ID = "SANDBOXFINANCE_SFIN0000"
# Aquí está el cambio: ahora leerá la URL de la nube si existe, o usará localhost para pruebas
REDIRECT_URI = st.secrets.get("APP_URL", "http://localhost:8501/callback")

def obtener_token_gocardless():
    secret_id = st.secrets.get("GOCARDLESS_SECRET_ID")
    secret_key = st.secrets.get("GOCARDLESS_SECRET_KEY")
    if not secret_id or not secret_key:
        st.error("Faltan las credenciales de GoCardless en secrets.toml")
        return None
    url = f"{BASE_URL}/token/new/"
    headers = {"accept": "application/json"}
    data = {"secret_id": secret_id, "secret_key": secret_key}
    try:
        resp = requests.post(url, headers=headers, json=data)
        resp.raise_for_status()
        return resp.json()["access"]
    except Exception as e:
        st.error(f"Error al autenticar con GoCardless: {e}")
        return None

def obtener_bancos_disponibles(access_token, country="ES"):
    """
    Obtiene la lista de bancos disponibles para un país.
    
    Parámetros:
    - access_token: Token de acceso de GoCardless
    - country: Código de país ISO (por defecto "ES")
    
    Retorna:
    - Lista de bancos disponibles
    """
    url = f"{BASE_URL}/institutions/"
    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {access_token}"
    }
    params = {"country": country}
    
    try:
        resp = requests.get(url, headers=headers, params=params)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        st.error(f"Error al obtener bancos: {e}")
        return []

def crear_agreement(access_token, institution_id=None):
    """
    Crea un acuerdo con el banco seleccionado.
    
    Parámetros:
    - access_token: Token de acceso
    - institution_id: ID del banco (si es None, usa sandbox)
    """
    if not institution_id:
        institution_id = INSTITUTION_ID
    
    url = f"{BASE_URL}/agreements/enduser/"
    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    data = {
        "institution_id": institution_id,
        "max_historical_days": 90,
        "access_valid_for_days": 30,
        "access_scope": ["balances", "details", "transactions"]
    }
    resp = requests.post(url, headers=headers, json=data)
    resp.raise_for_status()
    return resp.json()["id"]

def crear_requisition(access_token, agreement_id, institution_id=None):
    """
    Crea una requisición para el banco seleccionado.
    
    Parámetros:
    - access_token: Token de acceso
    - agreement_id: ID del acuerdo
    - institution_id: ID del banco (si es None, usa sandbox)
    """
    if not institution_id:
        institution_id = INSTITUTION_ID
    
    url = f"{BASE_URL}/requisitions/"
    headers = {
        "accept": "application/json",
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json"
    }
    data = {
        "redirect": REDIRECT_URI,
        "institution_id": institution_id,
        "agreement": agreement_id,
        "reference": "hondureformas"
    }
    resp = requests.post(url, headers=headers, json=data)
    resp.raise_for_status()
    return resp.json()["id"], resp.json()["link"]

def esperar_autorizacion(access_token, requisition_id):
    """
    Espera a que el usuario autorice la conexión.
    Nota: Esta función bloquea la UI, usar con precaución.
    """
    import time
    url = f"{BASE_URL}/requisitions/{requisition_id}/"
    headers = {"accept": "application/json", "Authorization": f"Bearer {access_token}"}
    for _ in range(20):
        resp = requests.get(url, headers=headers)
        if resp.status_code == 200 and resp.json()["status"] == "LN":
            return True
        time.sleep(3)
    return False

def verificar_autorizacion(access_token, requisition_id):
    """
    Verifica el estado de la autorización sin bloquear la UI.
    
    Retorna:
    - True si está autorizado, False si no
    """
    url = f"{BASE_URL}/requisitions/{requisition_id}/"
    headers = {"accept": "application/json", "Authorization": f"Bearer {access_token}"}
    try:
        resp = requests.get(url, headers=headers)
        if resp.status_code == 200:
            return resp.json()["status"] == "LN"
    except Exception:
        pass
    return False

def obtener_cuentas(access_token, requisition_id):
    """Obtiene las cuentas asociadas a una requisición."""
    url = f"{BASE_URL}/requisitions/{requisition_id}/"
    headers = {"accept": "application/json", "Authorization": f"Bearer {access_token}"}
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return resp.json()["accounts"]

def descargar_transacciones(access_token, account_id, date_from, date_to):
    """
    Descarga las transacciones de una cuenta.
    Incluye manejo de paginación.
    """
    url = f"{BASE_URL}/accounts/{account_id}/transactions/"
    headers = {"accept": "application/json", "Authorization": f"Bearer {access_token}"}
    params = {"date_from": date_from, "date_to": date_to}
    
    todas_transacciones = []
    
    try:
        resp = requests.get(url, headers=headers, params=params)
        resp.raise_for_status()
        data = resp.json()
        
        transacciones = data.get("transactions", {})
        todas_transacciones.extend(transacciones.get("booked", []))
        todas_transacciones.extend(transacciones.get("pending", []))
        
        return todas_transacciones
    except Exception as e:
        st.warning(f"Error al descargar transacciones: {e}")
        return []

def parse_amount(row):
    """
    Parsea el importe de una transacción de forma segura.
    """
    try:
        amount_data = row.get("transactionAmount", {})
        if isinstance(amount_data, dict):
            amount_str = amount_data.get("amount", "0")
        else:
            amount_str = str(amount_data)
        
        # Limpiar y convertir
        amount_str = amount_str.replace(",", ".").strip()
        return float(amount_str)
    except Exception:
        return 0.0

# ------------------------------------------------------------
# Función 1: Inicia la conexión (devuelve link, NO guarda en session_state)
# ------------------------------------------------------------
def iniciar_conexion_gocardless(institution_id=None):
    """
    Inicia la conexión con GoCardless.
    
    Parámetros:
    - institution_id: ID del banco (si es None, usa sandbox)
    
    Retorna:
    - (exito, link, req_id)
    """
    token = obtener_token_gocardless()
    if not token:
        return False, "No se pudo autenticar con GoCardless.", None

    try:
        agreement_id = crear_agreement(token, institution_id)
        req_id, link = crear_requisition(token, agreement_id, institution_id)
    except Exception as e:
        return False, f"Error al crear la requisición: {e}", None

    # Guardar token en session_state para usarlo después
    st.session_state.gocardless_token = token
    
    return True, link, req_id

# ------------------------------------------------------------
# Función 2: Completa la importación después de autorizar
# ------------------------------------------------------------
def completar_importacion(user_id, supabase_client):
    """
    Completa la importación de transacciones después de la autorización.
    
    Parámetros:
    - user_id: ID del usuario
    - supabase_client: Cliente de Supabase
    
    Retorna:
    - (exito, mensaje, dataframe)
    """
    if "gocardless_token" not in st.session_state or "gocardless_req_id" not in st.session_state:
        return False, "No hay una conexión pendiente. Inicia la conexión primero.", None

    token = st.session_state.gocardless_token
    req_id = st.session_state.gocardless_req_id

    # Verificar autorización (sin bloquear la UI)
    if not verificar_autorizacion(token, req_id):
        return False, "La autorización no se ha completado todavía. Por favor, autoriza en el enlace proporcionado.", None

    try:
        accounts = obtener_cuentas(token, req_id)
        if not accounts:
            return False, "No se encontraron cuentas.", None
    except Exception as e:
        return False, f"Error al obtener cuentas: {e}", None

    hoy = datetime.now()
    desde = (hoy - timedelta(days=30)).strftime("%Y-%m-%d")
    hasta = hoy.strftime("%Y-%m-%d")

    # Descargar transacciones de todas las cuentas
    todas_transacciones = []
    for account_id in accounts:
        try:
            trans = descargar_transacciones(token, account_id, desde, hasta)
            todas_transacciones.extend(trans)
        except Exception as e:
            st.warning(f"Error al descargar cuenta {account_id}: {e}")

    if not todas_transacciones:
        # Limpiar estado
        for key in ["gocardless_token", "gocardless_req_id", "gocardless_link", "gocardless_step"]:
            st.session_state.pop(key, None)
        return True, "No hay transacciones en el período.", pd.DataFrame()

    df = pd.DataFrame(todas_transacciones)
    registros = []
    for _, row in df.iterrows():
        registros.append({
            "user_id": user_id,
            "date": row.get("bookingDate", row.get("valueDate", "")),
            "description": row.get("remittanceInformationUnstructured", row.get("additionalInformation", "")),
            "amount": parse_amount(row),
            "matched_invoice_id": None,
            "matched_expense_id": None
        })

    try:
        for reg in registros:
            supabase_client.table("bank_transactions").insert(reg).execute()
    except Exception as e:
        return False, f"Error al guardar movimientos: {e}", None

    # Limpiar estado tras éxito
    for key in ["gocardless_token", "gocardless_req_id", "gocardless_link", "gocardless_step"]:
        st.session_state.pop(key, None)

    return True, f"Importados {len(registros)} movimientos correctamente.", df
