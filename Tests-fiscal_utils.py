# ════════════════════════════════════════════════════════════
# TESTS — fiscal_utils.py
# Ejecutar: pytest tests/test_fiscal_utils.py -v
# ════════════════════════════════════════════════════════════
from decimal import Decimal
import pandas as pd
import pytest

from fiscal_utils import (
    _to_decimal,
    _q2,
    _sum_column,
    filter_by_period,
    calculate_irpf_provision,
    calculate_fiscal_summary,
    IRPF_PAGO_FRACCIONADO,
)


# ────────────────────────────────────────────────────────────
# FIXTURES — Datos de prueba reutilizables
# ────────────────────────────────────────────────────────────
@pytest.fixture
def facturas_q1_sin_retencion():
    """3 facturas Q1 2025 sin IRPF retenido, con IVA 21%."""
    return pd.DataFrame([
        {
            "id": "f1", "date": "2025-01-15", "status": "pagada",
            "base_amount": 1000.0, "vat_amount": 210.0,
            "irpf_amount": 0.0, "total": 1210.0,
        },
        {
            "id": "f2", "date": "2025-02-20", "status": "pendiente",
            "base_amount": 2000.0, "vat_amount": 420.0,
            "irpf_amount": 0.0, "total": 2420.0,
        },
        {
            "id": "f3", "date": "2025-03-10", "status": "pagada",
            "base_amount": 500.0, "vat_amount": 105.0,
            "irpf_amount": 0.0, "total": 605.0,
        },
    ])


@pytest.fixture
def facturas_q1_con_retencion():
    """2 facturas Q1 2025 con IRPF retenido (15% típico profesional)."""
    return pd.DataFrame([
        {
            "id": "f1", "date": "2025-01-20", "status": "pagada",
            "base_amount": 1000.0, "vat_amount": 210.0,
            "irpf_amount": 150.0, "total": 1060.0,
        },
        {
            "id": "f2", "date": "2025-02-15", "status": "pagada",
            "base_amount": 2000.0, "vat_amount": 420.0,
            "irpf_amount": 300.0, "total": 2120.0,
        },
    ])


@pytest.fixture
def gastos_q1():
    """2 gastos Q1 2025 con IVA soportado."""
    return pd.DataFrame([
        {
            "id": "g1", "date": "2025-01-10", "status": None,
            "base_amount": 300.0, "vat_amount": 63.0,
            "irpf_amount": 0.0, "total": 363.0,
        },
        {
            "id": "g2", "date": "2025-02-05", "status": None,
            "base_amount": 200.0, "vat_amount": 42.0,
            "irpf_amount": 0.0, "total": 242.0,
        },
    ])


@pytest.fixture
def gastos_con_perdida():
    """Gastos que generan pérdida en Q1 2025."""
    return pd.DataFrame([
        {
            "id": "g1", "date": "2025-01-10", "status": None,
            "base_amount": 5000.0, "vat_amount": 1050.0,
            "irpf_amount": 0.0, "total": 6050.0,
        },
    ])


@pytest.fixture
def facturas_con_anuladas():
    """Facturas Q1 con una anulada y una rectificada."""
    return pd.DataFrame([
        {
            "id": "f1", "date": "2025-01-15", "status": "pagada",
            "base_amount": 1000.0, "vat_amount": 210.0,
            "irpf_amount": 0.0, "total": 1210.0,
        },
        {
            "id": "f2", "date": "2025-02-10", "status": "anulada",
            "base_amount": 9999.0, "vat_amount": 9999.0,
            "irpf_amount": 0.0, "total": 9999.0,
        },
        {
            "id": "f3", "date": "2025-03-05", "status": "rectificada",
            "base_amount": 500.0, "vat_amount": 105.0,
            "irpf_amount": 0.0, "total": 605.0,
        },
    ])


# ────────────────────────────────────────────────────────────
# TESTS — Helpers de conversión
# ────────────────────────────────────────────────────────────
class TestToDecimal:
    def test_convierte_float(self):
        assert _to_decimal(100.5) == Decimal("100.5")

    def test_convierte_string_punto(self):
        assert _to_decimal("1000.25") == Decimal("1000.25")

    def test_convierte_string_coma(self):
        assert _to_decimal("1000,25") == Decimal("1000.25")

    def test_none_devuelve_cero(self):
        assert _to_decimal(None) == Decimal("0")

    def test_vacio_devuelve_cero(self):
        assert _to_decimal("") == Decimal("0")

    def test_nan_devuelve_cero(self):
        assert _to_decimal(float("nan")) == Decimal("0")

    def test_valor_invalido_devuelve_cero(self):
        assert _to_decimal("no es número") == Decimal("0")

    def test_no_redondea_en_conversion(self):
        # Comprobación clave: NO debe redondear durante la conversión
        assert _to_decimal(1.005) == Decimal("1.005")


class TestQ2:
    def test_redondeo_half_up(self):
        assert _q2(Decimal("1.005")) == Decimal("1.01")
        assert _q2(Decimal("1.004")) == Decimal("1.00")

    def test_redondeo_negativo(self):
        # -1.005 → half-up siempre se aleja del cero
        assert _q2(Decimal("-1.005")) == Decimal("-1.01")


class TestSumColumn:
    def test_suma_columna_normal(self, facturas_q1_sin_retencion):
        assert _sum_column(facturas_q1_sin_retencion, "base_amount") == Decimal("3500.0")

    def test_columna_inexistente(self, facturas_q1_sin_retencion):
        assert _sum_column(facturas_q1_sin_retencion, "columna_que_no_existe") == Decimal("0")

    def test_df_vacio(self):
        assert _sum_column(pd.DataFrame(), "base_amount") == Decimal("0")

    def test_columna_con_nulos(self):
        df = pd.DataFrame({"base_amount": [100.0, None, 200.0, float("nan")]})
        assert _sum_column(df, "base_amount") == Decimal("300.0")


# ────────────────────────────────────────────────────────────
# TESTS — Filtrado por período
# ────────────────────────────────────────────────────────────
class TestFilterByPeriod:
    def test_filtro_por_año(self, facturas_q1_sin_retencion):
        result = filter_by_period(facturas_q1_sin_retencion, year=2025)
        assert len(result) == 3

    def test_filtro_por_año_sin_datos(self, facturas_q1_sin_retencion):
        result = filter_by_period(facturas_q1_sin_retencion, year=2024)
        assert result.empty

    def test_filtro_por_mes_int(self, facturas_q1_sin_retencion):
        result = filter_by_period(facturas_q1_sin_retencion, year=2025, month=1)
        assert len(result) == 1
        assert result.iloc[0]["id"] == "f1"

    def test_filtro_por_mes_string_espanol(self, facturas_q1_sin_retencion):
        """Bug que arreglamos: aceptar 'Enero' como string."""
        result = filter_by_period(facturas_q1_sin_retencion, year=2025, month="Enero")
        assert len(result) == 1
        assert result.iloc[0]["id"] == "f1"

    def test_filtro_por_mes_string_case_insensitive(self, facturas_q1_sin_retencion):
        result = filter_by_period(facturas_q1_sin_retencion, year=2025, month="ENERO")
        assert len(result) == 1

    def test_filtro_por_mes_todos(self, facturas_q1_sin_retencion):
        result = filter_by_period(facturas_q1_sin_retencion, year=2025, month="Todos")
        assert len(result) == 3

    def test_filtro_por_trimestre_q1(self, facturas_q1_sin_retencion):
        result = filter_by_period(facturas_q1_sin_retencion, year=2025, quarter=1)
        assert len(result) == 3

    def test_filtro_por_trimestre_q2_vacio(self, facturas_q1_sin_retencion):
        result = filter_by_period(facturas_q1_sin_retencion, year=2025, quarter=2)
        assert result.empty

    def test_trimestre_tiene_prioridad_sobre_mes(self, facturas_q1_sin_retencion):
        """Si ambos se pasan, quarter gana."""
        result = filter_by_period(
            facturas_q1_sin_retencion, year=2025, month=1, quarter=1
        )
        # Debe traer todo Q1, no solo enero
        assert len(result) == 3

    def test_excluye_anuladas(self, facturas_con_anuladas):
        result = filter_by_period(facturas_con_anuladas, year=2025, quarter=1)
        # Solo f1 (pagada) y f3 (rectificada), no f2 (anulada)
        assert len(result) == 2
        assert "f2" not in result["id"].tolist()

    def test_incluye_anuladas_si_se_pide(self, facturas_con_anuladas):
        result = filter_by_period(
            facturas_con_anuladas, year=2025, quarter=1, exclude_cancelled=False
        )
        assert len(result) == 3

    def test_df_vacio(self):
        assert filter_by_period(pd.DataFrame(), year=2025).empty

    def test_columna_fecha_inexistente(self):
        df = pd.DataFrame([{"foo": 1}])
        assert filter_by_period(df, year=2025).empty

    def test_fechas_invalidas_se_descartan(self):
        df = pd.DataFrame([
            {"date": "2025-01-15", "base_amount": 100},
            {"date": "no es fecha", "base_amount": 200},
        ])
        result = filter_by_period(df, year=2025)
        assert len(result) == 1


# ────────────────────────────────────────────────────────────
# TESTS — Provisión IRPF (LA PIEZA CLAVE)
# ────────────────────────────────────────────────────────────
class TestCalculateIrpfProvision:
    def test_sin_retencion_beneficio_positivo_aplica_20(self):
        """Sin retenciones + beneficio positivo → 20 % modelo 130."""
        result = calculate_irpf_provision(
            beneficio_bruto=Decimal("1000"),
            irpf_retenido=Decimal("0"),
        )
        assert result["provision_irpf"] == Decimal("200.00")
        assert result["modo"] == "pago_fraccionado_20"

    def test_con_retencion_usa_solo_retencion(self):
        """Con retención → solo retención, NO se suma el 20 %."""
        result = calculate_irpf_provision(
            beneficio_bruto=Decimal("1000"),
            irpf_retenido=Decimal("150"),
        )
        assert result["provision_irpf"] == Decimal("150")
        assert result["modo"] == "retencion_cliente"

    def test_no_doble_imposicion(self):
        """Regla de oro: nunca retención + 20 % a la vez."""
        result = calculate_irpf_provision(
            beneficio_bruto=Decimal("1000"),
            irpf_retenido=Decimal("150"),
        )
        # 150 + 200 = 350 sería ERROR. Debe ser solo 150.
        assert result["provision_irpf"] != Decimal("350")
        assert result["provision_irpf"] == Decimal("150")

    def test_beneficio_negativo_provision_cero(self):
        """Pérdidas → provisión 0 aunque no haya retención."""
        result = calculate_irpf_provision(
            beneficio_bruto=Decimal("-500"),
            irpf_retenido=Decimal("0"),
        )
        assert result["provision_irpf"] == Decimal("0")
        assert result["modo"] == "sin_retencion"

    def test_beneficio_cero_provision_cero(self):
        result = calculate_irpf_provision(
            beneficio_bruto=Decimal("0"),
            irpf_retenido=Decimal("0"),
        )
        assert result["provision_irpf"] == Decimal("0")

    def test_beneficio_negativo_con_retencion_prevalece_retencion(self):
        """Si hay retención aunque haya pérdida, la retención se devuelve."""
        result = calculate_irpf_provision(
            beneficio_bruto=Decimal("-100"),
            irpf_retenido=Decimal("50"),
        )
        assert result["provision_irpf"] == Decimal("50")
        assert result["modo"] == "retencion_cliente"

    def test_pago_fraccionado_desactivado(self):
        result = calculate_irpf_provision(
            beneficio_bruto=Decimal("1000"),
            irpf_retenido=Decimal("0"),
            aplica_pago_fraccionado=False,
        )
        assert result["provision_irpf"] == Decimal("0")
        assert result["modo"] == "sin_retencion"

    def test_constante_20_por_ciento(self):
        """Verifica que el tipo esté parametrizado correctamente."""
        assert IRPF_PAGO_FRACCIONADO == Decimal("0.20")


# ────────────────────────────────────────────────────────────
# TESTS — calculate_fiscal_summary (integración)
# ────────────────────────────────────────────────────────────
class TestFiscalSummary:
    def test_escenario_1_beneficio_sin_retencion(
        self, facturas_q1_sin_retencion, gastos_q1
    ):
        """
        Escenario 1: Q1 con beneficio, sin retenciones.
        Debe aplicar 20 % sobre beneficio positivo.
        """
        s = calculate_fiscal_summary(
            facturas_q1_sin_retencion, gastos_q1, year=2025, quarter=1
        )

        # Ventas: 1000 + 2000 + 500 = 3500
        assert s["base_ventas"] == 3500.0
        # Gastos: 300 + 200 = 500
        assert s["base_gastos"] == 500.0
        # Beneficio bruto: 3000
        assert s["beneficio_bruto"] == 3000.0
        # IVA repercutido: 210 + 420 + 105 = 735
        assert s["iva_repercutido"] == 735.0
        # IVA soportado: 63 + 42 = 105
        assert s["iva_soportado"] == 105.0
        assert s["iva_neto"] == 630.0
        # IRPF retenido: 0
        assert s["irpf_ventas"] == 0.0
        # Provisión: 20 % de 3000 = 600
        assert s["provision_irpf"] == 600.0
        assert s["modo_provision"] == "pago_fraccionado_20"
        # Ganancia neta: 3000 - 600 = 2400
        assert s["ganancia_neta"] == 2400.0
        assert s["num_invoices"] == 3
        assert s["num_expenses"] == 2

    def test_escenario_2_con_retencion_irpf(
        self, facturas_q1_con_retencion, gastos_q1
    ):
        """
        Escenario 2: Q1 con retenciones IRPF.
        Provisión debe ser EXACTAMENTE la suma de retenciones.
        """
        s = calculate_fiscal_summary(
            facturas_q1_con_retencion, gastos_q1, year=2025, quarter=1
        )

        # Ventas: 1000 + 2000 = 3000
        assert s["base_ventas"] == 3000.0
        assert s["base_gastos"] == 500.0
        assert s["beneficio_bruto"] == 2500.0

        # Retenciones: 150 + 300 = 450
        assert s["irpf_ventas"] == 450.0
        assert s["provision_irpf"] == 450.0
        assert s["modo_provision"] == "retencion_cliente"

        # Ganancia neta: 2500 - 450 = 2050 (NO 2500 - 450 - 500)
        assert s["ganancia_neta"] == 2050.0

        # Test anti-regresión: nunca el 20 % + retención
        assert s["provision_irpf"] != 950.0  # 450 + 500

    def test_escenario_3_perdidas_provision_cero(
        self, facturas_q1_sin_retencion, gastos_con_perdida
    ):
        """
        Escenario 3: Q1 con pérdidas.
        Provisión debe ser 0 €, nunca negativa.
        """
        s = calculate_fiscal_summary(
            facturas_q1_sin_retencion, gastos_con_perdida, year=2025, quarter=1
        )

        # Ventas: 3500, Gastos: 5000 → pérdida
        assert s["base_ventas"] == 3500.0
        assert s["base_gastos"] == 5000.0
        assert s["beneficio_bruto"] == -1500.0

        # Provisión CERO, no -300
        assert s["provision_irpf"] == 0.0
        assert s["modo_provision"] == "sin_retencion"

        # Ganancia neta = beneficio (sin restar nada)
        assert s["ganancia_neta"] == -1500.0

    def test_escenario_4_excluye_anuladas(self, facturas_con_anuladas, gastos_q1):
        """
        Escenario 4: facturas anuladas no deben contar en los totales.
        """
        s = calculate_fiscal_summary(
            facturas_con_anuladas, gastos_q1, year=2025, quarter=1
        )

        # Solo f1 (1000) y f3 (500). f2 anulada (9999) excluida.
        assert s["base_ventas"] == 1500.0
        assert s["num_invoices"] == 2

    def test_ticket_promedio(self, facturas_q1_sin_retencion, gastos_q1):
        s = calculate_fiscal_summary(
            facturas_q1_sin_retencion, gastos_q1, year=2025, quarter=1
        )
        # 3500 / 3 = 1166.67
        assert s["ticket_promedio"] == 1166.67

    def test_ticket_promedio_sin_facturas(self, gastos_q1):
        s = calculate_fiscal_summary(
            pd.DataFrame(), gastos_q1, year=2025, quarter=1
        )
        assert s["ticket_promedio"] == 0.0
        assert s["num_invoices"] == 0

    def test_sin_datos_periodo(self, facturas_q1_sin_retencion, gastos_q1):
        s = calculate_fiscal_summary(
            facturas_q1_sin_retencion, gastos_q1, year=2024, quarter=1
        )
        assert s["base_ventas"] == 0.0
        assert s["base_gastos"] == 0.0
        assert s["provision_irpf"] == 0.0
        assert s["ganancia_neta"] == 0.0

    def test_raw_decimal_incluido(self, facturas_q1_sin_retencion, gastos_q1):
        """Verifica que se devuelven los Decimal para la AEAT."""
        s = calculate_fiscal_summary(
            facturas_q1_sin_retencion, gastos_q1, year=2025, quarter=1
        )
        raw = s["_raw_decimal"]
        assert isinstance(raw["base_ventas"], Decimal)
        assert raw["base_ventas"] == Decimal("3500.0")
        assert raw["iva_neto"] == Decimal("630.0")

    def test_filtrado_por_mes_string(self, facturas_q1_sin_retencion, gastos_q1):
        """Integración: pasar 'Enero' debe filtrar solo enero."""
        s = calculate_fiscal_summary(
            facturas_q1_sin_retencion, gastos_q1, year=2025, month="Enero"
        )
        assert s["base_ventas"] == 1000.0
        assert s["num_invoices"] == 1

    def test_redondeo_final_correcto(self):
        """
        Test anti-regresión: valores con decimales infinitos
        deben redondearse SOLO al final, no en cada operación.
        """
        df_inv = pd.DataFrame([
            {"date": "2025-01-01", "status": "pagada",
             "base_amount": 333.33, "vat_amount": 70.0,
             "irpf_amount": 0.0, "total": 403.33},
            {"date": "2025-01-02", "status": "pagada",
             "base_amount": 333.33, "vat_amount": 70.0,
             "irpf_amount": 0.0, "total": 403.33},
            {"date": "2025-01-03", "status": "pagada",
             "base_amount": 333.34, "vat_amount": 70.0,
             "irpf_amount": 0.0, "total": 403.34},
        ])
        s = calculate_fiscal_summary(df_inv, pd.DataFrame(), year=2025)
        # 333.33 + 333.33 + 333.34 = 1000.00 exacto
        assert s["base_ventas"] == 1000.0


# ────────────────────────────────────────────────────────────
# TESTS — Regresión: coherencia entre vistas
# ────────────────────────────────────────────────────────────
class TestCoherenciaVistas:
    """
    Estos tests son el verdadero motivo de fiscal_utils.py.
    Salpicadero, PyG y Modelo 303 DEBEN devolver el mismo número.
    """

    def test_salpicadero_y_pyg_coinciden(
        self, facturas_q1_sin_retencion, gastos_q1
    ):
        # Salpicadero: filtro por trimestre
        s_salpicadero = calculate_fiscal_summary(
            facturas_q1_sin_retencion, gastos_q1, year=2025, quarter=1
        )
        # PyG: filtro por año completo (mismo dataset, misma cifra)
        s_pyg = calculate_fiscal_summary(
            facturas_q1_sin_retencion, gastos_q1, year=2025
        )
        # Como todo el dataset está en Q1, deben coincidir
        assert s_salpicadero["ganancia_neta"] == s_pyg["ganancia_neta"]
        assert s_salpicadero["provision_irpf"] == s_pyg["provision_irpf"]

    def test_modelo303_y_salpicadero_iva_coinciden(
        self, facturas_q1_sin_retencion, gastos_q1
    ):
        s_303 = calculate_fiscal_summary(
            facturas_q1_sin_retencion, gastos_q1, year=2025, quarter=1
        )
        s_salp = calculate_fiscal_summary(
            facturas_q1_sin_retencion, gastos_q1, year=2025, quarter=1
        )
        assert s_303["iva_neto"] == s_salp["iva_neto"]
