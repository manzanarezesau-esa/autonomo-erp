# config.py
# ============================================================
# CONFIGURACIÓN GENERAL DE HONDUREFORMAS ERP
# ============================================================

# Lista de meses en español
LISTA_MESES = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"
]

# Datos por defecto del autónomo
AUTONOMO_NAME = "ANAEL ESAU MANZANAREZ"
AUTONOMO_TAX_ID = "56546112Z"
AUTONOMO_ADDRESS = "calle san valenti 43 bajo, TERRASA (BARCELONA)"
AUTONOMO_IBAN = "ES2621000474190200439558"

# Tipos de gasto (incluye "Nomina" para nóminas)
TIPOS_GASTO = [
    "Seguridad Social",
    "Gestoría",
    "Suministros",
    "Alquiler",
    "Material",
    "Nomina",
    "Otros"
]

# Porcentajes de Seguridad Social (aproximados)
SS_EMPLEADO = 0.0635    # 6.35% a cargo del empleado
SS_EMPRESA = 0.2930     # 29.30% a cargo de la empresa

# Planes de suscripción
PLANES_PRECIOS = {
    "free": 0,
    "basico": 15,
    "profesional": 30,
    "gestoria": 60
}

# Emails de administrador
ADMIN_EMAILS = [
    "esamanzanarez@gmail.com",
    "admin@hondureformas.com"
]
