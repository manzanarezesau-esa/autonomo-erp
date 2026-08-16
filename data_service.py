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
    # Protección de columnas comunes
    for col in ["description", "base_amount", "vat_amount", "irpf_amount", "total"]:
        if col not in df.columns:
            df[col] = 0.0 if col != "description" else ""
    return df

@st.cache_data(ttl=60)
def get_clients(user_id):
    resp = refetch("clients_v2", "id, name, tax_id, address, type", user_id)
    df = pd.DataFrame(resp.data) if resp.data else pd.DataFrame()
    return df

@st.cache_data(ttl=60)
def get_suppliers(user_id):
    resp = refetch("suppliers_v2", "id, name, tax_id, address", user_id)
    df = pd.DataFrame(resp.data) if resp.data else pd.DataFrame()
    return df

@st.cache_data(ttl=60)
def get_products(user_id):
    # Incluimos explícitamente 'description' y protegemos su ausencia
    resp = refetch("products_v2", "id, name, description, price, default_vat_percentage, default_irpf_percentage", user_id)
    df = pd.DataFrame(resp.data) if resp.data else pd.DataFrame()
    if 'description' not in df.columns:
        df['description'] = ""
    return df

@st.cache_data(ttl=60)
def get_expenses(user_id):
    resp = refetch("expenses_v2", "*, suppliers_v2(name)", user_id)
    df = pd.DataFrame(resp.data) if resp.data else pd.DataFrame()
    if not df.empty and "suppliers_v2" in df.columns:
        df["supplier_name"] = df["suppliers_v2"].apply(lambda x: x["name"] if isinstance(x, dict) else "")
        df.drop(columns=["suppliers_v2"], inplace=True)
    if 'description' not in df.columns:
        df['description'] = ""
    return df

@st.cache_data(ttl=60)
def get_bank_transactions(user_id):
    resp = refetch("bank_transactions", "*", user_id)
    df = pd.DataFrame(resp.data) if resp.data else pd.DataFrame()
    return df

@st.cache_data(ttl=60)
def get_recurring_invoices(user_id):
    # Obtenemos las facturas recurrentes sin join implícito para evitar errores de relación
    resp = refetch("recurring_invoices", "*", user_id)
    df = pd.DataFrame(resp.data) if resp.data else pd.DataFrame()

    if not df.empty:
        clientes = get_clients(user_id)
        if not clientes.empty and "client_id" in df.columns:
            df = df.merge(
                clientes[["id", "name"]],
                left_on="client_id",
                right_on="id",
                how="left",
                suffixes=("", "_cliente")
            )
            df.rename(columns={"name": "client_name"}, inplace=True)
            df.drop(columns=["id_cliente"], inplace=True, errors="ignore")
        else:
            df["client_name"] = ""
    
    if 'description' not in df.columns:
        df['description'] = ""
    return df

@st.cache_data(ttl=60)
def get_budgets(user_id):
    # Incluimos 'description' explícitamente y protegemos
    resp = refetch("budgets", "id, budget_number, date, client_name, base_total, total, status, description", user_id)
    df = pd.DataFrame(resp.data) if resp.data else pd.DataFrame()
    if 'description' not in df.columns:
        df['description'] = ""
    return df

@st.cache_data(ttl=60)
def get_journal_entries(user_id):
    resp = refetch("journal_entries", "id, date, description", user_id)
    df = pd.DataFrame(resp.data) if resp.data else pd.DataFrame()
    if 'description' not in df.columns:
        df['description'] = ""
    return df



