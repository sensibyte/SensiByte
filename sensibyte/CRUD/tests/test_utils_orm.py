# Utilizaremos pytest-django, que permite crear un acceso a la base de datos
# https://pytest-django.readthedocs.io/en/latest/database.html

import pytest
from CRUD.utils import build_alias_cache, detect_arm
from Base.models import (
    MecanismoResistenciaHospital, SubtipoMecanismoResistenciaHospital,
    MecResValoresPositivosHospital, Hospital, MecanismoResistencia, SubtipoMecanismoResistencia
)
import pandas as pd


@pytest.mark.django_db
def test_build_alias_cache_creates_normalized_keys():
    # inicializamos los objetos
    hospital = Hospital.objects.create(nombre="Hosp")
    base_mec = MecanismoResistencia.objects.create(nombre="Beta-Lactamasas")
    mec_hosp = MecanismoResistenciaHospital.objects.create(hospital=hospital, mecanismo=base_mec, alias=["BL", "Beta"])

    # construimos la caché de alias
    cache = build_alias_cache(MecanismoResistenciaHospital.objects.all())

    keys = list(cache.keys())

    # comprobaciones
    assert "betalactamasas" in keys
    assert "bl" in keys
    assert cache["bl"] == mec_hosp


@pytest.mark.django_db
def test_detect_arm_detects_by_column_and_observation():
    # inicializamos los objetos
    hospital = Hospital.objects.create(nombre="Hosp")

    mec_base = MecanismoResistencia.objects.create(nombre="CTX-M")
    sub_base = SubtipoMecanismoResistencia.objects.create(nombre="CTX-M-15", mecanismo=mec_base)

    mec_hosp = MecanismoResistenciaHospital.objects.create(
        hospital=hospital, mecanismo=mec_base, alias=["ctxm"]
    )
    sub_hosp = SubtipoMecanismoResistenciaHospital.objects.create(
        hospital=hospital, subtipo_mecanismo=sub_base, alias=["ctxm15"]
    )
    val_pos = MecResValoresPositivosHospital.objects.create(hospital=hospital, alias=["positivo", "detectado"])

    # inicializamos los datos para detección por columna y por observaciones
    row = pd.Series({"ctxm": "detectado",
                     "observaciones": "Se detecta CTX-M-15"})

    mapping = {"observaciones": "observaciones"}

    mecs, subs = detect_arm(row, mapping, [mec_hosp], [sub_hosp], [val_pos])

    # comprobaciones
    assert mec_hosp in mecs
    assert sub_hosp in subs
