# stripe_utils.py
import streamlit as st
import stripe
from database import _get_supabase
from datetime import datetime, timezone


def init_stripe():
    """
    Inicializa Stripe con la clave secreta desde secrets.
    
    Retorna:
    - API key de Stripe o None si no está configurada
    """
    stripe.api_key = st.secrets.get("STRIPE_SECRET_KEY", "")
    return stripe.api_key


def crear_customer(user_id, email):
    """
    Crea un customer en Stripe para el usuario.
    
    Parámetros:
    - user_id: ID del usuario en Supabase
    - email: Email del usuario
    
    Retorna:
    - ID del customer en Stripe o None si falla
    """
    stripe.api_key = init_stripe()
    if not stripe.api_key:
        st.error("Stripe no está configurado. Añade STRIPE_SECRET_KEY en secrets.")
        return None
    
    try:
        supabase = _get_supabase()
        
        # Verificar si ya existe un customer para este usuario
        existing = supabase.table("subscriptions")\
            .select("stripe_customer_id")\
            .eq("user_id", user_id)\
            .execute()
        
        if existing.data and existing.data[0].get("stripe_customer_id"):
            return existing.data[0]["stripe_customer_id"]
        
        # Crear nuevo customer en Stripe
        customer = stripe.Customer.create(
            email=email,
            metadata={"user_id": user_id}
        )
        
        # Guardar el customer_id en Supabase
        supabase.table("subscriptions").upsert({
            "user_id": user_id,
            "stripe_customer_id": customer.id,
            "plan": "free",
            "status": "active"
        }, on_conflict="user_id").execute()
        
        return customer.id
        
    except stripe.error.StripeError as e:
        st.error(f"Error de Stripe: {str(e)}")
        return None
    except Exception as e:
        st.error(f"Error al crear customer: {str(e)}")
        return None


def crear_checkout_session(user_id, email, plan):
    """
    Crea una sesión de checkout para suscripción.
    
    Parámetros:
    - user_id: ID del usuario
    - email: Email del usuario
    - plan: 'basico', 'profesional', 'gestoria'
    
    Retorna:
    - URL de checkout de Stripe o None si falla
    """
    stripe.api_key = init_stripe()
    if not stripe.api_key:
        st.error("Stripe no está configurado.")
        return None
    
    # Precios de Stripe (configúralos en el dashboard de Stripe)
    PRECIOS = {
        "basico": st.secrets.get("STRIPE_PRICE_BASICO", ""),
        "profesional": st.secrets.get("STRIPE_PRICE_PROFESIONAL", ""),
        "gestoria": st.secrets.get("STRIPE_PRICE_GESTORIA", "")
    }
    
    price_id = PRECIOS.get(plan, "")
    if not price_id:
        st.error(f"No hay precio configurado para el plan '{plan}'. Añade STRIPE_PRICE_{plan.upper()} en secrets.")
        return None
    
    try:
        # Obtener o crear customer
        customer_id = crear_customer(user_id, email)
        if not customer_id:
            return None
        
        # URLs de retorno
        success_url = st.secrets.get("STRIPE_SUCCESS_URL", "http://localhost:8501")
        cancel_url = st.secrets.get("STRIPE_CANCEL_URL", "http://localhost:8501")
        
        # Crear sesión de checkout
        checkout_session = stripe.checkout.Session.create(
            customer=customer_id,
            payment_method_types=["card"],
            line_items=[{
                "price": price_id,
                "quantity": 1,
            }],
            mode="subscription",
            success_url=f"{success_url}?session_id={{CHECKOUT_SESSION_ID}}",
            cancel_url=cancel_url,
            metadata={
                "user_id": user_id,
                "plan": plan
            }
        )
        
        return checkout_session.url
        
    except stripe.error.StripeError as e:
        st.error(f"Error de Stripe al crear checkout: {str(e)}")
        return None
    except Exception as e:
        st.error(f"Error al crear checkout: {str(e)}")
        return None


def obtener_suscripcion_usuario(user_id):
    """
    Obtiene la suscripción del usuario desde Supabase.
    
    Parámetros:
    - user_id: ID del usuario
    
    Retorna:
    - Diccionario con datos de suscripción o None
    """
    supabase = _get_supabase()
    try:
        result = supabase.table("subscriptions")\
            .select("*")\
            .eq("user_id", user_id)\
            .single()\
            .execute()
        return result.data if result.data else None
    except Exception:
        return None


def verificar_acceso(user_id, plan_requerido="basico"):
    """
    Verifica si el usuario tiene acceso al plan requerido.
    
    Parámetros:
    - user_id: ID del usuario
    - plan_requerido: 'free', 'basico', 'profesional', 'gestoria'
    
    Retorna:
    - True si tiene acceso, False si no
    """
    niveles = {"free": 0, "basico": 1, "profesional": 2, "gestoria": 3}
    
    suscripcion = obtener_suscripcion_usuario(user_id)
    if not suscripcion:
        plan_actual = "free"
    else:
        plan_actual = suscripcion.get("plan", "free")
    
    nivel_actual = niveles.get(plan_actual, 0)
    nivel_requerido = niveles.get(plan_requerido, 0)
    
    return nivel_actual >= nivel_requerido


def actualizar_suscripcion(session_id):
    """
    Actualiza la suscripción después del pago (llamado desde webhook o success URL).
    
    Parámetros:
    - session_id: ID de la sesión de checkout de Stripe
    
    Retorna:
    - True si se actualizó correctamente
    """
    stripe.api_key = init_stripe()
    if not stripe.api_key:
        return False
    
    try:
        # Obtener la sesión de checkout
        session = stripe.checkout.Session.retrieve(session_id)
        
        if session.payment_status == "paid":
            user_id = session.metadata.get("user_id")
            plan = session.metadata.get("plan", "free")
            
            if not user_id:
                return False
            
            supabase = _get_supabase()
            
            # Actualizar suscripción
            supabase.table("subscriptions").upsert({
                "user_id": user_id,
                "stripe_subscription_id": session.subscription,
                "plan": plan,
                "status": "active",
                "current_period_end": datetime.now(timezone.utc).isoformat(),
                "updated_at": "now()"
            }, on_conflict="user_id").execute()
            
            # Registrar pago
            monto = session.amount_total / 100 if session.amount_total else 0
            supabase.table("payments").insert({
                "user_id": user_id,
                "stripe_payment_id": session.payment_intent,
                "amount": monto,
                "currency": "EUR",
                "status": "paid",
                "plan": plan
            }).execute()
            
            return True
        return False
        
    except stripe.error.StripeError as e:
        st.error(f"Error de Stripe: {str(e)}")
        return False
    except Exception as e:
        st.error(f"Error al actualizar suscripción: {str(e)}")
        return False


def cancelar_suscripcion(user_id):
    """
    Cancela la suscripción del usuario.
    
    Parámetros:
    - user_id: ID del usuario
    
    Retorna:
    - True si se canceló correctamente
    """
    stripe.api_key = init_stripe()
    if not stripe.api_key:
        return False
    
    supabase = _get_supabase()
    try:
        # Obtener el subscription_id de Stripe
        result = supabase.table("subscriptions")\
            .select("stripe_subscription_id")\
            .eq("user_id", user_id)\
            .single()\
            .execute()
        
        if result.data and result.data.get("stripe_subscription_id"):
            # Cancelar en Stripe
            stripe.Subscription.delete(result.data["stripe_subscription_id"])
        
        # Actualizar en Supabase
        supabase.table("subscriptions").update({
            "plan": "free",
            "status": "cancelled",
            "stripe_subscription_id": None,
            "updated_at": "now()"
        }).eq("user_id", user_id).execute()
        
        return True
        
    except stripe.error.StripeError as e:
        st.error(f"Error de Stripe: {str(e)}")
        return False
    except Exception as e:
        st.error(f"Error al cancelar suscripción: {str(e)}")
        return False


def obtener_historial_pagos(user_id):
    """
    Obtiene el historial de pagos del usuario.
    
    Parámetros:
    - user_id: ID del usuario
    
    Retorna:
    - Lista de pagos
    """
    supabase = _get_supabase()
    try:
        result = supabase.table("payments")\
            .select("*")\
            .eq("user_id", user_id)\
            .order("created_at", desc=True)\
            .execute()
        return result.data if result.data else []
    except Exception:
        return []


def procesar_webhook(payload, sig_header):
    """
    Procesa el webhook de Stripe (para usar con Supabase Functions o backend).
    
    Parámetros:
    - payload: Cuerpo del webhook (bytes)
    - sig_header: Firma del webhook
    
    Retorna:
    - True si se procesó correctamente
    """
    webhook_secret = st.secrets.get("STRIPE_WEBHOOK_SECRET", "")
    if not webhook_secret:
        return False
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, webhook_secret
        )
        
        # Manejar eventos relevantes
        if event["type"] == "checkout.session.completed":
            session = event["data"]["object"]
            return actualizar_suscripcion(session["id"])
        
        elif event["type"] == "customer.subscription.deleted":
            subscription = event["data"]["object"]
            # Buscar usuario por subscription_id
            supabase = _get_supabase()
            result = supabase.table("subscriptions")\
                .select("user_id")\
                .eq("stripe_subscription_id", subscription["id"])\
                .single()\
                .execute()
            
            if result.data:
                user_id = result.data["user_id"]
                supabase.table("subscriptions").update({
                    "plan": "free",
                    "status": "cancelled",
                    "stripe_subscription_id": None
                }).eq("user_id", user_id).execute()
            
            return True
        
        return True
        
    except stripe.error.SignatureVerificationError:
        st.error("Firma del webhook inválida")
        return False
    except Exception as e:
        st.error(f"Error al procesar webhook: {str(e)}")
        return False


def procesar_success_url():
    """
    Procesa la URL de éxito después del pago.
    Se llama cuando el usuario es redirigido con ?session_id=xxx
    """
    query_params = st.query_params
    session_id = query_params.get("session_id")
    
    if session_id:
        if actualizar_suscripcion(session_id):
            st.success("✅ Pago procesado correctamente. Tu suscripción está activa.")
            st.query_params.clear()
            time.sleep(2)
            st.rerun()
        else:
            st.warning("El pago aún no se ha confirmado. Puede tardar unos segundos.")
