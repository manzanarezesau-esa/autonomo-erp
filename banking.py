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

def crear_agreement(access_token):
    url = f"{BASE_URL}/agreements/enduser/"
    headers = {"accept": "application/json", "Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    data = {"institution_id": INSTITUTION_ID, "max_historical_days": 90, "access_valid_for_days": 30, "access_scope": ["balances", "details", "transactions"]}
    resp = requests.post(url, headers=headers, json=data)
    resp.raise_for_status()
    return resp.json()["id"]

def crear_requisition(access_token, agreement_id):
    url = f"{BASE_URL}/requisitions/"
    headers = {"accept": "application/json", "Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
    data = {"redirect": REDIRECT_URI, "institution_id": INSTITUTION_ID, "agreement": agreement_id, "reference": "hondureformas"}
    resp = requests.post(url, headers=headers, json=data)
    resp.raise_for_status()
    return resp.json()["id"], resp.json()["link"]

def esperar_autorizacion(access_token, requisition_id):
    import time
    url = f"{BASE_URL}/requisitions/{requisition_id}/"
    headers = {"accept": "application/json", "Authorization": f"Bearer {access_token}"}
    for _ in range(20):
        resp = requests.get(url, headers=headers)
        if resp.status_code == 200 and resp.json()["status"] == "LN":
            return True
        time.sleep(3)
    return False

def obtener_cuentas(access_token, requisition_id):
    url = f"{BASE_URL}/requisitions/{requisition_id}/"
    headers = {"accept": "application/json", "Authorization": f"Bearer {access_token}"}
    resp = requests.get(url, headers=headers)
    resp.raise_for_status()
    return resp.json()["accounts"]

def descargar_transacciones(access_token, account_id, date_from, date_to):
    url = f"{BASE_URL}/accounts/{account_id}/transactions/"
    headers = {"accept": "application/json", "Authorization": f"Bearer {access_token}"}
    params = {"date_from": date_from, "date_to": date_to}
    resp = requests.get(url, headers=headers, params=params)
    resp.raise_for_status()
    data = resp.json()
    return data.get("transactions", {}).get("booked", [])

# ------------------------------------------------------------
# Función 1: Inicia la conexión (devuelve link y guarda token/req en sesión)
# ------------------------------------------------------------
def iniciar_conexion_gocardless():
    token = obtener_token_gocardless()
    if not token:
        return False, "No se pudo autenticar con GoCardless.", None

    try:
        agreement_id = crear_agreement(token)
        req_id, link = crear_requisition(token, agreement_id)
    except Exception as e:
        return False, f"Error al crear la requisición: {e}", None

    # Guardar en session_state para usarlos en el paso 2
    st.session_state.gocardless_token = token
    st.session_state.gocardless_req_id = req_id
    st.session_state.gocardless_link = link
    st.session_state.gocardless_step = "waiting_auth"
    return True, link, req_id

# ------------------------------------------------------------
# Función 2: Completa la importación después de autorizar
# ------------------------------------------------------------
def completar_importacion(user_id, supabase_client):
    if "gocardless_token" not in st.session_state or "gocardless_req_id" not in st.session_state:
        return False, "No hay una conexión pendiente. Inicia la conexión primero.", None

    token = st.session_state.gocardless_token
    req_id = st.session_state.gocardless_req_id

    # Esperar autorización (solo se llama cuando el usuario ya pulsó "He autorizado")
    if not esperar_autorizacion(token, req_id):
        return False, "La autorización no se completó a tiempo.", None

    try:
        accounts = obtener_cuentas(token, req_id)
        if not accounts:
            return False, "No se encontraron cuentas.", None
    except Exception as e:
        return False, f"Error al obtener cuentas: {e}", None

    hoy = datetime.now()
    desde = (hoy - timedelta(days=30)).strftime("%Y-%m-%d")
    hasta = hoy.strftime("%Y-%m-%d")

    try:
        transacciones = descargar_transacciones(token, accounts[0], desde, hasta)
    except Exception as e:
        return False, f"Error al descargar transacciones: {e}", None

    if not transacciones:
        # Limpiar estado
        for key in ["gocardless_token", "gocardless_req_id", "gocardless_link", "gocardless_step"]:
            st.session_state.pop(key, None)
        return True, "No hay transacciones en el período.", pd.DataFrame()

    df = pd.DataFrame(transacciones)
    registros = []
    for _, row in df.iterrows():
        registros.append({
            "user_id": user_id,
            "date": row.get("bookingDate", ""),
            "description": row.get("remittanceInformationUnstructured", ""),
            "amount": float(row.get("transactionAmount", {}).get("amount", 0)),
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

