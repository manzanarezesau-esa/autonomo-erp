# formatters.py
def money(amount):
    """Formatea un valor numérico como cadena de moneda en euros."""
    try:
        return f"{float(amount):,.2f} €"
    except (ValueError, TypeError):
        return "0.00 €"

