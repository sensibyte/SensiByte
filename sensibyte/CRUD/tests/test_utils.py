# Unit tests: https://docs.djangoproject.com/en/5.2/topics/testing/overview/

import os
import unittest
from datetime import date
import pandas as pd

from CRUD.utils import (
    code_nh, gen_automatic_nh_hash, normalize_text,
    get_str, get_from_cache, numeric_column_transformer,
    parse_fecha, parse_age, search_value_in_columns,
    search_mic_in_columns, search_halo_in_columns,
    parse_mic, parse_halo
)


class UtilsFuncionesTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        os.environ["HASH_SALT_PRE"] = "pre_"
        os.environ["HASH_SALT_POST"] = "_post"

    # codificación de un nulo
    def test_code_nh_none(self):
        self.assertIsNone(code_nh(None))

    # tipado y tamaño del hash por función code_nh()
    def test_code_nh_returns_deterministic_hash(self):
        val = code_nh("12345")
        self.assertIsInstance(val, str)
        self.assertEqual(len(val), 64)

    # tamaño del hash truncado por función gen_automatic_nh_hash()
    def test_gen_automatic_nh_hash_is_truncated(self):
        h = gen_automatic_nh_hash(123, 45, 67)
        self.assertEqual(len(h), 16)

    # normalización de texto sin espacios ni caracteres especiales
    def test_normalize_text_varios(self):
        cases = [
            ("Águila", "aguila"),
            ("  FuÍ  ", "fui"),
            ("", ""),
            (None, ""),
        ]
        for entrada, esperado in cases:
            self.assertEqual(normalize_text(entrada), esperado)

    def test_get_str_normaliza(self):
        row = {"clave": "  Texto "}
        self.assertEqual(get_str(row, "clave"), "texto")
        # Nos aseguramos que no hay KeyError ni devuelve otra cosa distinta a cadena vacía en estos casos
        # caso con clave existente pero valor None
        self.assertEqual(get_str({"clave": None}, "clave"), "")
        # caso con valor no incluido en el diccionario
        self.assertEqual(get_str({}, "missing"), "")

    def test_get_from_cache_hit_y_miss(self):
        cache = {"abc": 123}
        self.assertEqual(get_from_cache(cache, "abc"), 123)
        # con clave sin normalizar
        self.assertEqual(get_from_cache(cache, " ABC "), 123)
        # sin clave debería ser None
        self.assertIsNone(get_from_cache(cache, "zzz"))

    def test_numeric_column_transformer(self):
        s = pd.Series(["1", "2.5", "abc", ">4"])
        out = numeric_column_transformer(s)
        self.assertEqual(list(out), [1, 2.5, "abc", ">4"])

    def test_parse_fecha_varios_formatos(self):
        casos = [
            ("31/12/2024", date(2024, 12, 31)),
            ("12 marzo 2024", date(2024, 3, 12)),
            ("31-01-2024", date(2024, 1, 31)),
            ("99-99-9999", None),
            (None, None),
        ]
        for valor, esperado in casos:
            self.assertEqual(parse_fecha(valor), esperado)

    def test_parse_age_varios(self):
        casos = [
            (20, 20.0),
            ("20.4", 20.4),
            ("25,5", 25.5),
            ("texto", None),
            (None, None),
        ]
        for val, esperado in casos:
            self.assertEqual(parse_age(val), esperado)

    def test_search_value_in_columns(self):
        row = pd.Series({"amoxicilina": "R", "otro": ""})
        alias = ["amox", "amx", "amoxicilina"]
        col, val = search_value_in_columns(row, alias)
        self.assertEqual((col, val), ("amoxicilina", "R"))

        col, val = search_value_in_columns(row, ["ausente"])
        self.assertEqual((col, val), (None, None)) # si no está en los alias devuelve None

    def test_search_mic_in_columns(self):
        row = pd.Series({"amoxicilina-CMI": "2"})
        alias = ["amox", "amx", "amoxicilina"]
        col, val = search_mic_in_columns(row, alias)
        self.assertEqual((col, val), ("amoxicilina-CMI", "2"))

    def test_search_halo_in_columns(self):
        row = pd.Series({"amoxicilina_mm": "30"})
        alias = ["amox", "amx", "amoxicilina"]
        col, val = search_halo_in_columns(row, alias)
        self.assertEqual((col, val), ("amoxicilina_mm", "30"))

    def test_parse_mic_varios(self):
        casos = [
            ("2", 2.0),
            ("<2", 2.0),
            ("≤2", 2.0),
            ("≥2", 4.0),
            ("<=2", 2.0),
            (">=2", 4.0),
            (">16", 32.0),
            ("1/19", 1.0),
            ("=8", 8.0),
            ("27851", 4.0),  # error Excel (abril-1976)
            ("", None),
        ]
        for val, esperado in casos:
            self.assertEqual(parse_mic(val), esperado)

    def test_parse_halo_varios(self):
        casos = [
            ("20", 20.0),
            ("<20", 20.0),
            (">20", 20.0),
            ("=15", 15.0),
            ("text", None),
        ]
        for val, esperado in casos:
            self.assertEqual(parse_halo(val), esperado)
