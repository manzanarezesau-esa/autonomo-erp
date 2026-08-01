# email_utils.py
import smtplib, ssl
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.text import MIMEText
from email import encoders
import streamlit as st

def enviar_factura_email(destinatario, asunto, cuerpo, pdf_bytes, filename):
    smtp_server = st.secrets.get("SMTP_SERVER", "smtp.gmail.com")
    port = st.secrets.get("SMTP_PORT", 587)
    username = st.secrets.get("SMTP_USERNAME", "")
    password = st.secrets.get("SMTP_PASSWORD", "")
    if not username or not password:
        st.error("Configura las credenciales SMTP en secrets.toml")
        return False
    msg = MIMEMultipart()
    msg['From'] = username
    msg['To'] = destinatario
    msg['Subject'] = asunto
    msg.attach(MIMEText(cuerpo, 'html'))
    part = MIMEBase('application', 'octet-stream')
    part.set_payload(pdf_bytes)
    encoders.encode_base64(part)
    part.add_header('Content-Disposition', f'attachment; filename="{filename}"')
    msg.attach(part)
    try:
        context = ssl.create_default_context()
        with smtplib.SMTP(smtp_server, port) as server:
            server.starttls(context=context)
            server.login(username, password)
            server.sendmail(username, destinatario, msg.as_string())
        return True
    except Exception as e:
        st.error(f"Error al enviar email: {e}")
        return False

