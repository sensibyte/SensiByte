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
    assert "beta-lactamasas" in keys
    assert "bl" in keys
    assert cache["bl"] == mec_hosp


@pytest.mark.django_db
def test_detect_arm_detects_blee_and_oxa48_by_column_and_observation():
    hospital = Hospital.objects.create(nombre="Hosp")

    # mecanismos y subtipos base
    mec_base = MecanismoResistencia.objects.create(nombre="BLEE")
    mec_base2 = MecanismoResistencia.objects.create(nombre="Carbapenemasa")

    sub_base = SubtipoMecanismoResistencia.objects.create(nombre="TEM-1", mecanismo=mec_base)
    sub_base2 = SubtipoMecanismoResistencia.objects.create(nombre="OXA-48", mecanismo=mec_base2)

    # configuraciones a nivel hospital
    mec_hosp = MecanismoResistenciaHospital.objects.create(
        hospital=hospital, mecanismo=mec_base, alias=["blee"]
    )
    sub_hosp = SubtipoMecanismoResistenciaHospital.objects.create(
        hospital=hospital, subtipo_mecanismo=sub_base, alias=["tem1"]
    )

    mec_hosp2 = MecanismoResistenciaHospital.objects.create(
        hospital=hospital, mecanismo=mec_base2, alias=["carbapenemasa"]
    )
    sub_hosp2 = SubtipoMecanismoResistenciaHospital.objects.create(
        hospital=hospital, subtipo_mecanismo=sub_base2, alias=["oxa-48", "OXA-48"]
    )

    val_pos = MecResValoresPositivosHospital.objects.create(
        hospital=hospital, alias=["positiva", "detectado"]
    )

    row = pd.Series({
        "BLEE": "positiva",
        "observaciones": "Cepa portadora de beta lactamasa de espectro extendido (BLEE) de tipo TEM-1. Cepa portadora de carbapenemasa OXA-48."
    })
    mapping = {"observaciones": "observaciones"}

    mecs, subs = detect_arm(row, mapping, [mec_hosp], [sub_hosp], [val_pos])
    mecs2, subs2 = detect_arm(row, mapping, [mec_hosp2], [sub_hosp2], [val_pos])

    assert mec_hosp in mecs
    assert sub_hosp in subs
    assert mec_hosp2 in mecs2
    assert sub_hosp2 in subs2
