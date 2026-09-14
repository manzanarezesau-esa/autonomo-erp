# ════════════════════════════════════════════════════════════
# TESTS — modelo303_utils.py
# Ejecutar: pytest tests/test_modelo303_utils.py -v
# ════════════════════════════════════════════════════════════
import pytest

from modelo303_utils import (
    generar_fichero_aeat_303,
    validar_fichero_aeat,
)


# ────────────────────────────────────────────────────────────
# FIXTURES — Datos de prueba reutilizables
# ────────────────────────────────────────────────────────────
@pytest.fixture
def datos_trimestre_normal():
    """Trimestre con actividad normal: ventas > compras."""
    return {
        "anio": 2026,
        "trimestre": "3T (Jul-Sep)",
        "base_ventas": 27300.00,
        "iva_repercutido": 5106.00,
        "base_compras": 4076.37,
        "iva_soportado": 856.09,
        "nif_emisor": "12345678Z",
        "nombre_emisor": "JUAN PEREZ GARCIA",
    }


@pytest.fixture
def datos_trimestre_negativo():
    """Trimestre donde IVA soportado > repercutido (a compensar)."""
    return {
        "anio": 2026,
        "trimestre": "1T (Ene-Mar)",
        "base_ventas": 1000.00,
        "iva_repercutido": 210.00,
        "base_compras": 5000.00,
        "iva_soportado": 1050.00,
        "nif_emisor": "12345678Z",
        "nombre_emisor": "JUAN PEREZ GARCIA",
    }


@pytest.fixture
def datos_trimestre_vacio():
    """Trimestre sin actividad."""
    return {
        "anio": 2026,
        "trimestre": "2T (Abr-Jun)",
        "base_ventas": 0.0,
        "iva_repercutido": 0.0,
        "base_compras": 0.0,
        "iva_soportado": 0.0,
        "nif_emisor": "12345678Z",
        "nombre_emisor": "JUAN PEREZ GARCIA",
    }


def _generar(datos):
    """Helper para generar el fichero con los datos de un fixture."""
    return generar_fichero_aeat_303(
        datos["anio"],
        datos["trimestre"],
        datos["base_ventas"],
        datos["iva_repercutido"],
        datos["base_compras"],
        datos["iva_soportado"],
        datos["nif_emisor"],
        datos["nombre_emisor"],
    )


# ────────────────────────────────────────────────────────────
# TESTS — Estructura del fichero
# ────────────────────────────────────────────────────────────
class TestEstructuraFichero:
    def test_devuelve_string(self, datos_trimestre_normal):
        fichero = _generar(datos_trimestre_normal)
        assert isinstance(fichero, str)

    def test_tiene_dos_registros(self, datos_trimestre_normal):
        fichero = _generar(datos_trimestre_normal)
        lineas = fichero.split("\r\n")
        assert len(lineas) == 2

    def test_registro_1_tiene_100_chars(self, datos_trimestre_normal):
        fichero = _generar(datos_trimestre_normal)
        lineas = fichero.split("\r\n")
        assert len(lineas[0]) == 100

    def test_registro_2_tiene_100_chars(self, datos_trimestre_normal):
        fichero = _generar(datos_trimestre_normal)
        lineas = fichero.split("\r\n")
        assert len(lineas[1]) == 100

    def test_registro_1_empieza_con_01(self, datos_trimestre_normal):
        fichero = _generar(datos_trimestre_normal)
        lineas = fichero.split("\r\n")
        assert lineas[0][:2] == "01"

    def test_registro_2_empieza_con_99(self, datos_trimestre_normal):
        fichero = _generar(datos_trimestre_normal)
        lineas = fichero.split("\r\n")
        assert lineas[1][:2] == "99"

    def test_separador_crlf(self, datos_trimestre_normal):
        fichero = _generar(datos_trimestre_normal)
        assert "\r\n" in fichero


# ────────────────────────────────────────────────────────────
# TESTS — NIF del emisor
# ────────────────────────────────────────────────────────────
class TestNIF:
    def test_nif_limpio_ocupa_posiciones_3_11(self, datos_trimestre_normal):
        fichero = _generar(datos_trimestre_normal)
        linea = fichero.split("\r\n")[0]
        nif = linea[2:11]
        assert nif == "12345678Z"

    def test_nif_con_guiones_se_limpia(self, datos_trimestre_normal):
        datos = datos_trimestre_normal.copy()
        datos["nif_emisor"] = "12345678-Z"
        fichero = _generar(datos)
        nif = fichero.split("\r\n")[0][2:11]
        assert nif == "12345678Z"

    def test_nif_con_espacios_se_limpia(self, datos_trimestre_normal):
        datos = datos_trimestre_normal.copy()
        datos["nif_emisor"] = " 12345678 Z "
        fichero = _generar(datos)
        nif = fichero.split("\r\n")[0][2:11]
        assert nif == "12345678Z"

    def test_nif_minusculas_se_pasa_mayusculas(self, datos_trimestre_normal):
        datos = datos_trimestre_normal.copy()
        datos["nif_emisor"] = "12345678z"
        fichero = _generar(datos)
        nif = fichero.split("\r\n")[0][2:11]
        assert nif == "12345678Z"

    def test_nif_corto_se_rellena_con_espacios(self, datos_trimestre_normal):
        datos = datos_trimestre_normal.copy()
        datos["nif_emisor"] = "1234"
        fichero = _generar(datos)
        nif = fichero.split("\r\n")[0][2:11]
        assert len(nif) == 9
        assert nif.startswith("1234")

    def test_nif_largo_se_corta_a_9(self, datos_trimestre_normal):
        datos = datos_trimestre_normal.copy()
        datos["nif_emisor"] = "1234567890123Z"
        fichero = _generar(datos)
        nif = fichero.split("\r\n")[0][2:11]
        assert len(nif) == 9


# ────────────────────────────────────────────────────────────
# TESTS — Nombre del emisor
# ────────────────────────────────────────────────────────────
class TestNombre:
    def test_nombre_ocupa_posiciones_12_40(self, datos_trimestre_normal):
        fichero = _generar(datos_trimestre_normal)
        linea = fichero.split("\r\n")[0]
        nombre = linea[11:40]
        assert nombre.strip() == "JUAN PEREZ GARCIA"

    def test_nombre_largo_se_corta_a_29(self, datos_trimestre_normal):
        datos = datos_trimestre_normal.copy()
        datos["nombre_emisor"] = "A" * 50
        fichero = _generar(datos)
        nombre = fichero.split("\r\n")[0][11:40]
        assert len(nombre) == 29
        assert nombre.strip() == "A" * 29

    def test_nombre_corto_se_rellena(self, datos_trimestre_normal):
        datos = datos_trimestre_normal.copy()
        datos["nombre_emisor"] = "JUAN"
        fichero = _generar(datos)
        nombre = fichero.split("\r\n")[0][11:40]
        assert len(nombre) == 29


# ────────────────────────────────────────────────────────────
# TESTS — Ejercicio y período
# ────────────────────────────────────────────────────────────
class TestEjercicioYPeriodo:
    def test_ejercicio_ocupa_posiciones_41_44(self, datos_trimestre_normal):
        fichero = _generar(datos_trimestre_normal)
        ejercicio = fichero.split("\r\n")[0][40:44]
        assert ejercicio == "2026"

    def test_trimestre_1T_mapea_a_01(self):
        fichero = generar_fichero_aeat_303(
            2026, "1T (Ene-Mar)", 0, 0, 0, 0, "12345678Z", "TEST"
        )
        periodo = fichero.split("\r\n")[0][44:46]
        assert periodo == "01"

    def test_trimestre_2T_mapea_a_02(self):
        fichero = generar_fichero_aeat_303(
            2026, "2T (Abr-Jun)", 0, 0, 0, 0, "12345678Z", "TEST"
        )
        periodo = fichero.split("\r\n")[0][44:46]
        assert periodo == "02"

    def test_trimestre_3T_mapea_a_03(self):
        fichero = generar_fichero_aeat_303(
            2026, "3T (Jul-Sep)", 0, 0, 0, 0, "12345678Z", "TEST"
        )
        periodo = fichero.split("\r\n")[0][44:46]
        assert periodo == "03"

    def test_trimestre_4T_mapea_a_04(self):
        fichero = generar_fichero_aeat_303(
            2026, "4T (Oct-Dic)", 0, 0, 0, 0, "12345678Z", "TEST"
        )
        periodo = fichero.split("\r\n")[0][44:46]
        assert periodo == "04"


# ────────────────────────────────────────────────────────────
# TESTS — Importes (posiciones y formato)
# ────────────────────────────────────────────────────────────
class TestImportes:
    def test_base_ventas_posiciones_52_66(self, datos_trimestre_normal):
        fichero = _generar(datos_trimestre_normal)
        base = fichero.split("\r\n")[0][51:66]
        # 27300.00 € = 2730000 céntimos
        assert base == "000000002730000"

    def test_iva_repercutido_posiciones_67_81(self, datos_trimestre_normal):
        fichero = _generar(datos_trimestre_normal)
        iva = fichero.split("\r\n")[0][66:81]
        # 5106.00 € = 510600 céntimos
        assert iva == "000000000510600"

    def test_base_compras_posiciones_82_96(self, datos_trimestre_normal):
        fichero = _generar(datos_trimestre_normal)
        base = fichero.split("\r\n")[0][81:96]
        # 4076.37 € = 407637 céntimos
        assert base == "000000000407637"

    def test_iva_soportado_posiciones_97_111(self, datos_trimestre_normal):
        fichero = _generar(datos_trimestre_normal)
        iva = fichero.split("\r\n")[0][96:111]
        # 856.09 € = 85609 céntimos
        assert iva == "000000000085609"

    def test_resultado_positivo_sin_signo(self, datos_trimestre_normal):
        fichero = _generar(datos_trimestre_normal)
        resultado = fichero.split("\r\n")[0][111:126]
        # 5106.00 - 856.09 = 4249.91 € = 424991 céntimos
        assert resultado == "000000000424991"

    def test_resultado_negativo_con_signo_menos(self, datos_trimestre_negativo):
        fichero = _generar(datos_trimestre_negativo)
        resultado = fichero.split("\r\n")[0][111:126]
        # 210.00 - 1050.00 = -840.00 €
        assert resultado.startswith("-")
        assert "84000" in resultado

    def test_importe_cero(self, datos_trimestre_vacio):
        fichero = _generar(datos_trimestre_vacio)
        base_ventas = fichero.split("\r\n")[0][51:66]
        assert base_ventas == "000000000000000"

    def test_redondeo_a_centimos(self):
        """Importe con decimales raros debe redondearse a céntimos."""
        fichero = generar_fichero_aeat_303(
            2026, "1T (Ene-Mar)",
            100.555,  # se redondea a 100.56 → 10056 céntimos
            21.116,   # se redondea a 21.12 → 2112 céntimos
            0, 0,
            "12345678Z", "TEST"
        )
        base = fichero.split("\r\n")[0][51:66]
        assert base == "000000000010056"


# ────────────────────────────────────────────────────────────
# TESTS — Validación del fichero
# ────────────────────────────────────────────────────────────
class TestValidacion:
    def test_fichero_valido(self, datos_trimestre_normal):
        fichero = _generar(datos_trimestre_normal)
        es_valido, mensaje = validar_fichero_aeat(fichero)
        assert es_valido is True
        assert "válida" in mensaje.lower() or "ok" in mensaje.lower()

    def test_fichero_vacio(self):
        es_valido, mensaje = validar_fichero_aeat("")
        assert es_valido is False

    def test_fichero_solo_espacios(self):
        es_valido, mensaje = validar_fichero_aeat("   ")
        assert es_valido is False

    def test_falta_registro_99(self, datos_trimestre_normal):
        fichero = _generar(datos_trimestre_normal)
        solo_registro_1 = fichero.split("\r\n")[0]
        es_valido, mensaje = validar_fichero_aeat(solo_registro_1)
        assert es_valido is False

    def test_registro_1_no_empieza_con_01(self, datos_trimestre_normal):
        fichero = _generar(datos_trimestre_normal)
        lineas = fichero.split("\r\n")
        lineas[0] = "02" + lineas[0][2:]
        fichero_alterado = "\r\n".join(lineas)
        es_valido, mensaje = validar_fichero_aeat(fichero_alterado)
        assert es_valido is False

    def test_registro_1_longitud_incorrecta(self, datos_trimestre_normal):
        fichero = _generar(datos_trimestre_normal)
        lineas = fichero.split("\r\n")
        lineas[0] = lineas[0][:50]  # recortado
        fichero_alterado = "\r\n".join(lineas)
        es_valido, mensaje = validar_fichero_aeat(fichero_alterado)
        assert es_valido is False

    def test_nif_vacio(self, datos_trimestre_normal):
        datos = datos_trimestre_normal.copy()
        datos["nif_emisor"] = "         "  # solo espacios
        fichero = _generar(datos)
        es_valido, mensaje = validar_fichero_aeat(fichero)
        assert es_valido is False

    def test_ejercicio_no_numerico(self, datos_trimestre_normal):
        fichero = _generar(datos_trimestre_normal)
        lineas = fichero.split("\r\n")
        # Forzar ejercicio inválido
        linea = lineas[0]
        linea_alterada = linea[:40] + "XXXX" + linea[44:]
        lineas[0] = linea_alterada
        fichero_alterado = "\r\n".join(lineas)
        es_valido, mensaje = validar_fichero_aeat(fichero_alterado)
        assert es_valido is False

    def test_periodo_invalido(self, datos_trimestre_normal):
        fichero = _generar(datos_trimestre_normal)
        lineas = fichero.split("\r\n")
        linea = lineas[0]
        linea_alterada = linea[:44] + "99" + linea[46:]
        lineas[0] = linea_alterada
        fichero_alterado = "\r\n".join(lineas)
        es_valido, mensaje = validar_fichero_aeat(fichero_alterado)
        assert es_valido is False


# ────────────────────────────────────────────────────────────
# TESTS — Integración (generar + validar)
# ────────────────────────────────────────────────────────────
class TestIntegracion:
    def test_round_trip_normal(self, datos_trimestre_normal):
        fichero = _generar(datos_trimestre_normal)
        es_valido, _ = validar_fichero_aeat(fichero)
        assert es_valido is True

    def test_round_trip_negativo(self, datos_trimestre_negativo):
        fichero = _generar(datos_trimestre_negativo)
        es_valido, _ = validar_fichero_aeat(fichero)
        assert es_valido is True

    def test_round_trip_vacio(self, datos_trimestre_vacio):
        fichero = _generar(datos_trimestre_vacio)
        es_valido, _ = validar_fichero_aeat(fichero)
        assert es_valido is True

    def test_todos_los_trimestres_generan_valido(self):
        trimestres = ["1T (Ene-Mar)", "2T (Abr-Jun)", "3T (Jul-Sep)", "4T (Oct-Dic)"]
        for trimestre in trimestres:
            fichero = generar_fichero_aeat_303(
                2026, trimestre, 100, 21, 50, 10.5, "12345678Z", "TEST"
            )
            es_valido, _ = validar_fichero_aeat(fichero)
            assert es_valido is True, f"Falló con {trimestre}"
