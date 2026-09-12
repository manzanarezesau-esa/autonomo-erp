# ════════════════════════════════════════════════════════════
# FISCAL_UTILS.PY — SINGLE SOURCE OF TRUTH (CÁLCULOS FISCALES)
# ════════════════════════════════════════════════════════════
from decimal import Decimal, ROUND_HALF_UP
from typing import Dict, Any, Optional, Union
import pandas as pd

# Constantes fiscales (parametriza aquí, no hardcodees en app.py)
IRPF_PAGO_FRACCIONADO = Decimal("0.20")  # 20 % modelo 130
TWO_PLACES = Decimal("0.01")


# ────────────────────────────────────────────────────────────
# HELPERS INTERNOS
# ────────────────────────────────────────────────────────────
def _to_decimal(val: Any) -> Decimal:
    """Convierte cualquier valor a Decimal SIN redondear (redondeo al final)."""
    if val is None or val == "":
        return Decimal("0")
    try:
        if isinstance(val, float) and pd.isna(val):
            return Decimal("0")
    except Exception:
        pass
    try:
        return Decimal(str(val).strip().replace(",", "."))
    except Exception:
        return Decimal("0")


def _q2(d: Decimal) -> Decimal:
    """Quantiza a 2 decimales con redondeo comercial (half-up)."""
    return d.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def _sum_column(df: pd.DataFrame, col: str) -> Decimal:
    """Suma una columna como Decimal, devolviendo 0 si no existe."""
    if df.empty or col not in df.columns:
        return Decimal("0")
    return sum((_to_decimal(v) for v in df[col].tolist()), Decimal("0"))


# ────────────────────────────────────────────────────────────
# FILTRADO DE PERÍODOS
# ────────────────────────────────────────────────────────────
def filter_by_period(
    df: pd.DataFrame,
    year: Optional[int] = None,
    month: Optional[Union[int, str]] = None,
    quarter: Optional[int] = None,
    date_col: str = "date",
    exclude_cancelled: bool = True,
) -> pd.DataFrame:
    """
    Filtra un DataFrame contable por Año, Mes o Trimestre.

    - `month` acepta int (1-12) o string con nombre ("Enero").
    - `quarter` y `month` son mutuamente excluyentes; si ambos se pasan,
      se aplica solo `quarter` (más específico por defecto).
    - Excluye registros con status "anulada" si existe la columna.
    """
    if df.empty or date_col not in df.columns:
        return pd.DataFrame()

    result = df.copy()

    if exclude_cancelled and "status" in result.columns:
        result = result[
            result["status"].astype(str).str.lower() != "anulada"
        ]

    result["_dt"] = pd.to_datetime(result[date_col], errors="coerce")
    result = result.dropna(subset=["_dt"])

    if result.empty:
        return pd.DataFrame()

    if year is not None:
        result = result[result["_dt"].dt.year == int(year)]

    if quarter is not None:
        quarter_months = {
            1: [1, 2, 3], 2: [4, 5, 6], 3: [7, 8, 9], 4: [10, 11, 12]
        }
        valid_months = quarter_months.get(int(quarter), [])
        result = result[result["_dt"].dt.month.isin(valid_months)]
    elif month is not None and str(month).lower() not in ("todos", "all", ""):
        # Acepta int y nombre de mes
        if isinstance(month, int) or str(month).isdigit():
            result = result[result["_dt"].dt.month == int(month)]
        else:
            meses_es = {
                "enero": 1, "febrero": 2, "marzo": 3,
                "abril": 4, "mayo": 5, "junio": 6,
                "julio": 7, "agosto": 8, "septiembre": 9,
                "octubre": 10, "noviembre": 11, "diciembre": 12,
            }
            mes_num = meses_es.get(str(month).lower())
            if mes_num:
                result = result[result["_dt"].dt.month == mes_num]

    return result.drop(columns=["_dt"])


# ────────────────────────────────────────────────────────────
# IRPF / PAGO FRACCIONADO / NETO
# ────────────────────────────────────────────────────────────
def calculate_irpf_provision(
    beneficio_bruto: Decimal,
    irpf_retenido: Decimal,
    aplica_pago_fraccionado: bool = True,
) -> Dict[str, Decimal]:
    """
    Calcula la provisión fiscal IRPF coherente para todas las vistas.

    Lógica:
    - Si hay IRPF retenido en facturas > 0, ESE es el importe a provisionar.
      (No se suma también el 20%, sería contar dos veces.)
    - Si no hay retenciones, se provisiona el 20% del beneficio positivo
      (modelo 130 - pago fraccionado).
    - Nunca se provisiona sobre beneficio negativo.

    Devuelve dict con Decimal.
    """
    provision = Decimal("0")
    modo = "sin_retencion"

    if irpf_retenido > 0:
        provision = irpf_retenido
        modo = "retencion_cliente"
    elif aplica_pago_fraccionado and beneficio_bruto > 0:
        provision = _q2(beneficio_bruto * IRPF_PAGO_FRACCIONADO)
        modo = "pago_fraccionado_20"

    return {
        "provision_irpf": provision,
        "modo": modo,
        "base_calculo": beneficio_bruto if modo == "pago_fraccionado_20" else irpf_retenido,
    }


# ────────────────────────────────────────────────────────────
# MOTOR CENTRAL
# ────────────────────────────────────────────────────────────
def calculate_fiscal_summary(
    invoices_df: pd.DataFrame,
    expenses_df: pd.DataFrame,
    year: Optional[int] = None,
    month: Optional[Union[int, str]] = None,
    quarter: Optional[int] = None,
    aplicar_pago_fraccionado: bool = True,
) -> Dict[str, Any]:
    """
    Motor centralizado de cálculos fiscales.
    Devuelve métricas exactas (float para UI + Decimal para AEAT).
    """
    inv_f = filter_by_period(invoices_df, year=year, month=month, quarter=quarter)
    exp_f = filter_by_period(expenses_df, year=year, month=month, quarter=quarter)

    # Sumas sin redondeo intermedio
    base_ventas_dec      = _sum_column(inv_f, "base_amount")
    iva_repercutido_dec  = _sum_column(inv_f, "vat_amount")
    irpf_ventas_dec      = _sum_column(inv_f, "irpf_amount")
    total_ventas_dec     = _sum_column(inv_f, "total")

    base_gastos_dec      = _sum_column(exp_f, "base_amount")
    iva_soportado_dec    = _sum_column(exp_f, "vat_amount")
    irpf_gastos_dec      = _sum_column(exp_f, "irpf_amount")
    total_gastos_dec     = _sum_column(exp_f, "total")

    # Derivados
    beneficio_bruto_dec  = base_ventas_dec - base_gastos_dec
    iva_neto_dec         = iva_repercutido_dec - iva_soportado_dec
    resultado_caja_dec   = total_ventas_dec - total_gastos_dec

    num_invoices = int(len(inv_f))
    num_expenses = int(len(exp_f))

    ticket_promedio_dec = (
        _q2(base_ventas_dec / Decimal(num_invoices))
        if num_invoices > 0 else Decimal("0")
    )

    # Provisión IRPF unificada
    irpf_info = calculate_irpf_provision(
        beneficio_bruto=beneficio_bruto_dec,
        irpf_retenido=irpf_ventas_dec,
        aplica_pago_fraccionado=aplicar_pago_fraccionado,
    )
    provision_irpf_dec = irpf_info["provision_irpf"]

    # Neto después de impuestos (coherente en TODAS las vistas)
    ganancia_neta_dec = beneficio_bruto_dec - provision_irpf_dec

    # Redondeo SOLO al final para mostrar
    return {
        # ── UI (float) ──────────────────────────────────────
        "base_ventas":         float(_q2(base_ventas_dec)),
        "base_gastos":         float(_q2(base_gastos_dec)),
        "beneficio_bruto":     float(_q2(beneficio_bruto_dec)),
        "iva_repercutido":     float(_q2(iva_repercutido_dec)),
        "iva_soportado":       float(_q2(iva_soportado_dec)),
        "iva_neto":            float(_q2(iva_neto_dec)),
        "irpf_ventas":         float(_q2(irpf_ventas_dec)),
        "irpf_gastos":         float(_q2(irpf_gastos_dec)),
        "provision_irpf":      float(_q2(provision_irpf_dec)),
        "modo_provision":      irpf_info["modo"],
        "ganancia_neta":       float(_q2(ganancia_neta_dec)),
        "total_ventas":        float(_q2(total_ventas_dec)),
        "total_gastos":        float(_q2(total_gastos_dec)),
        "resultado_caja":      float(_q2(resultado_caja_dec)),
        "ticket_promedio":     float(ticket_promedio_dec),
        "num_invoices":        num_invoices,
        "num_expenses":        num_expenses,
        "total_operaciones":   num_invoices + num_expenses,

        # ── AEAT (Decimal exacto, sin redondeo de origen) ───
        "_raw_decimal": {
            "base_ventas":        base_ventas_dec,
            "base_gastos":        base_gastos_dec,
            "beneficio_bruto":    beneficio_bruto_dec,
            "iva_repercutido":    iva_repercutido_dec,
            "iva_soportado":      iva_soportado_dec,
            "iva_neto":           iva_neto_dec,
            "irpf_ventas":        irpf_ventas_dec,
            "provision_irpf":     provision_irpf_dec,
            "ganancia_neta":      ganancia_neta_dec,
        },
    }
