# data_service.py
import streamlit as st
import pandas as pd
from database import refetch

@st.cache_data(ttl=60)
def get_invoices(user_id):
    resp = refetch("invoices_v2", "*, clients_v2(name)", user_id)
    df = pd.DataFrame(resp.data) if resp.data else pd.DataFrame()
    if not df.empty and "clients_v2" in df.columns:
        df["client_name"] = df["clients_v2"].apply(lambda x: x["name"] if isinstance(x, dict) else "")
        df.drop(columns=["clients_v2"], inplace=True)
    return df

@st.cache_data(ttl=60)
def get_clients(user_id):
    resp = refetch("clients_v2", "id, name, tax_id, address, type", user_id)
    return pd.DataFrame(resp.data) if resp.data else pd.DataFrame()

@st.cache_data(ttl=60)
def get_suppliers(user_id):
    resp = refetch("suppliers_v2", "id, name, tax_id, address", user_id)
    return pd.DataFrame(resp.data) if resp.data else pd.DataFrame()

@st.cache_data(ttl=60)
def get_products(user_id):
    resp = refetch("products_v2", "id, name, price, default_vat_percentage, default_irpf_percentage", user_id)
    return pd.DataFrame(resp.data) if resp.data else pd.DataFrame()

@st.cache_data(ttl=60)
def get_expenses(user_id):
    resp = refetch("expenses_v2", "*, suppliers_v2(name)", user_id)
    df = pd.DataFrame(resp.data) if resp.data else pd.DataFrame()
    if not df.empty and "suppliers_v2" in df.columns:
        df["supplier_name"] = df["suppliers_v2"].apply(lambda x: x["name"] if isinstance(x, dict) else "")
        df.drop(columns=["suppliers_v2"], inplace=True)
    return df

@st.cache_data(ttl=60)
def get_bank_transactions(user_id):
    resp = refetch("bank_transactions", "*", user_id)
    return pd.DataFrame(resp.data) if resp.data else pd.DataFrame()

@st.cache_data(ttl=60)
def get_recurring_invoices(user_id):
    # Obtenemos las facturas recurrentes sin join implícito para evitar errores de relación en PostgREST
    resp = refetch("recurring_invoices", "*", user_id)
    df = pd.DataFrame(resp.data) if resp.data else pd.DataFrame()

    if not df.empty:
        # Obtenemos todos los clientes del usuario
        clientes = get_clients(user_id)
        if not clientes.empty and "client_id" in df.columns:
            # Hacemos merge manual con los nombres de los clientes
            df = df.merge(
                clientes[["id", "name"]],
                left_on="client_id",
                right_on="id",
                how="left",
                suffixes=("", "_cliente")
            )
            # Renombramos la columna 'name' a 'client_name'
            df.rename(columns={"name": "client_name"}, inplace=True)
            # Eliminamos la columna auxiliar 'id' del cliente
            df.drop(columns=["id_cliente"], inplace=True, errors="ignore")
        else:
            # Si no hay clientes, creamos columna vacía
            df["client_name"] = ""

    return df

@st.cache_data(ttl=60)
def get_budgets(user_id):
    resp = refetch("budgets", "id, budget_number, date, client_name, base_total, total, status", user_id)
    return pd.DataFrame(resp.data) if resp.data else pd.DataFrame()

@st.cache_data(ttl=60)
def get_journal_entries(user_id):
    resp = refetch("journal_entries", "id, date, description", user_id)
    return pd.DataFrame(resp.data) if resp.data else pd.DataFrame()


