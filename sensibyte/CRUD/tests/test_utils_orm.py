# Utilizaremos pytest-django, que permite crear un acceso a la base de datos
# https://pytest-django.readthedocs.io/en/latest/database.html
# https://stackoverflow.com/questions/25857655/django-tests-patch-object-in-all-tests
# https://klementomeri.medium.com/path-to-tight-sleep-with-test-automation-81916b567745
# https://djangostars.com/blog/django-pytest-testing/


import io
from datetime import date
from unittest.mock import Mock, patch
from unittest.mock import MagicMock

import pandas as pd
import pytest
from django.contrib.auth import get_user_model
from django.contrib.messages.storage.fallback import FallbackStorage
from django.test import RequestFactory

from Base.models import (
    Hospital, ClaseAntibiotico, FamiliaAntibiotico,
    SexoHospital, AmbitoHospital, ServicioHospital, TipoMuestraHospital,
    Sexo, Ambito, Servicio, TipoMuestra, CategoriaMuestraHospital,
    Registro, Aislado, ResultadoAntibiotico, EucastVersion,
    MecanismoResistenciaHospital, SubtipoMecanismoResistenciaHospital,
    MecanismoResistencia, SubtipoMecanismoResistencia,
    AliasInterpretacionHospital, MecResValoresPositivosHospital
)
from CRUD.utils import build_alias_cache, detect_arm
from CRUD.views import CargarAntibiogramaView

User = get_user_model()

from Base.models import (
    Microorganismo, MicroorganismoHospital,
    GrupoEucast, PerfilAntibiogramaHospital,
    Antibiotico, AntibioticoHospital
)


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

# TEST PARA LA FUNCIÓN DE CARGA DE ARCHIVOS Y CREACIÓN DE OBJETOS
# Fixtures de los objetos

# Usuario
@pytest.fixture
def hospital():
    """Fixture para crear un hospital de prueba"""
    return Hospital.objects.create(
        nombre="Hospital Test",
        codigo="HT001"
    )

# Hospital
@pytest.fixture
def usuario(hospital):
    """Fixture para crear un usuario con hospital asignado"""
    user = User.objects.create_user(
        username="testuser",
        password="testpass123",
        email="test@test.com"
    )
    user.hospital = hospital
    user.save()
    return user

# Grupo Eucast
@pytest.fixture
def grupo_eucast():
    """Fixture para GrupoEucast"""
    return GrupoEucast.objects.create(
        nombre="Enterobacterales",
    )


# Microorganismo
@pytest.fixture
def microorganismo(grupo_eucast):
    """Fixture para Microorganismo"""
    return Microorganismo.objects.create(
        nombre="Klebsiella pneumoniae",
        grupo_eucast=grupo_eucast
    )


# MicroorganismoHospital
@pytest.fixture
def microorganismo_hospital(hospital, microorganismo):
    """Fixture para MicroorganismoHospital"""
    return MicroorganismoHospital.objects.create(
        hospital=hospital,
        microorganismo=microorganismo
    )


# ClaseAntibiotico
@pytest.fixture
def clase_antibiotico():
    """Fixture para ClaseAntibiotico"""
    return ClaseAntibiotico.objects.create(
        nombre="Beta-lactámicos"
    )

# FamiliaAntibiotico
@pytest.fixture
def familia_antibiotico(clase_antibiotico):
    """Fixture para FamiliaAntibiotico"""
    return FamiliaAntibiotico.objects.create(
        nombre="Penicilinas",
        clase=clase_antibiotico
    )

# Antibiotico
@pytest.fixture
def antibiotico(familia_antibiotico):
    """Fixture para Antibiotico"""
    return Antibiotico.objects.create(
        nombre="Amoxicilina",
        abr="AMX",
        cid="33613",
        familia_antibiotico=familia_antibiotico,
        atc=["J01CA04"],
        atc_group1="Penicilinas de amplio espectro",
        atc_group2="Amoxicilina"
    )

# AntibioticoHospital
@pytest.fixture
def antibiotico_hospital(hospital, antibiotico):
    """Fixture para AntibioticoHospital"""
    ab_hosp = AntibioticoHospital.objects.create(
        hospital=hospital,
        antibiotico=antibiotico
    )
    ab_hosp.alias = ["amox", "amoxi"]
    ab_hosp.save()
    return ab_hosp


# PerfilAntibiogramaHospital
@pytest.fixture
def perfil_antibiograma(hospital, grupo_eucast, antibiotico_hospital):
    """Fixture para PerfilAntibiogramaHospital"""
    perfil = PerfilAntibiogramaHospital.objects.create(
        hospital=hospital,
        grupo_eucast=grupo_eucast
    )
    # Añadir el antibiótico al perfil
    perfil.antibioticos.add(antibiotico_hospital)
    return perfil


# Ambito
@pytest.fixture
def ambito():
    """Fixture para Ambito"""
    return Ambito.objects.create(
        nombre="Hospitalización"
    )

# Servicio
@pytest.fixture
def servicio():
    """Fixture para Servicio"""
    return Servicio.objects.create(
        nombre="Urología"
    )

# Sexo
@pytest.fixture
def sexo():
    """Fixture para Sexo"""
    return Sexo.objects.create(
        codigo="M",
        descripcion="Masculino"
    )


# TipoMuestra
@pytest.fixture
def tipo_muestra():
    """Fixture para TipoMuestra"""
    return TipoMuestra.objects.create(
        nombre="Orina",
        snomed="122575003",
        codigos_loinc=["630-4", "6463-4"]
    )

# SexoHospital
@pytest.fixture
def sexo_hospital(hospital, sexo):
    """Fixture para SexoHospital"""
    sexo_obj = SexoHospital.objects.create(
        hospital=hospital,
        sexo=sexo
    )
    sexo_obj.alias = ["masculino", "hombre", "varón"]
    sexo_obj.save()
    return sexo_obj


# AmbitoHospital
@pytest.fixture
def ambito_hospital(hospital, ambito):
    """Fixture para AmbitoHospital"""
    ambito_obj = AmbitoHospital.objects.create(
        hospital=hospital,
        ambito=ambito,
        ignorar_informes=False
    )
    ambito_obj.alias = ["hospitalización", "HOSPITALIZACIÓN"]
    ambito_obj.save()
    return ambito_obj


# ServicioHospital
@pytest.fixture
def servicio_hospital(hospital, servicio):
    """Fixture para ServicioHospital"""
    servicio_obj = ServicioHospital.objects.create(
        hospital=hospital,
        servicio=servicio,
        ignorar_informes=False
    )
    # Importante: incluir tanto versión con espacio como sin espacio
    servicio_obj.alias = ["UROLOGIA", "URO"]
    servicio_obj.save()
    return servicio_obj


# CategoriaMuestraHospital
@pytest.fixture
def categoria_muestra_hospital(hospital):
    """Fixture para CategoriaMuestraHospital"""
    return CategoriaMuestraHospital.objects.create(
        hospital=hospital,
        nombre="Orina",
        ignorar_minimo=False,
        ignorar_informes=False
    )


@pytest.fixture
def tipo_muestra_hospital(hospital, tipo_muestra, categoria_muestra_hospital):
    """Fixture para TipoMuestraHospital"""
    muestra = TipoMuestraHospital.objects.create(
        hospital=hospital,
        tipo_muestra=tipo_muestra,
        categoria=categoria_muestra_hospital
    )
    muestra.alias = ["urine", "urocultivo"]
    muestra.save()
    return muestra


# EucastVersion
@pytest.fixture
def eucast_version():
    """Fixture para EucastVersion"""
    return EucastVersion.objects.create(
        anyo=2024,
        version="14.0",
        fecha_inicio=date(2024, 1, 1),
        fecha_fin=date(2024, 12, 31),
        descripcion="Versión EUCAST 2024"
    )


# MecanimoResistencia
@pytest.fixture
def mecanismo_resistencia(grupo_eucast):
    """Fixture para MecanismoResistencia"""
    mec = MecanismoResistencia.objects.create(
        nombre="BLEE",
        descripcion="Beta-lactamasas de espectro extendido"
    )
    mec.grupos_eucast.add(grupo_eucast)
    return mec


# MecanismoResistenciaHospital
@pytest.fixture
def mecanismo_resistencia_hospital(hospital, mecanismo_resistencia, antibiotico):
    """Fixture para MecanismoResistenciaHospital"""
    mec_hosp = MecanismoResistenciaHospital.objects.create(
        hospital=hospital,
        mecanismo=mecanismo_resistencia
    )
    mec_hosp.alias = ["blee", "esbl", "beta-lactamasa"]
    mec_hosp.resistencia_adquirida.add(antibiotico)
    mec_hosp.save()
    return mec_hosp


# SubtipoMecanismoResistencia
@pytest.fixture
def subtipo_mecanismo_resistencia(mecanismo_resistencia):
    """Fixture para SubtipoMecanismoResistencia"""
    return SubtipoMecanismoResistencia.objects.create(
        nombre="CTX-M",
        mecanismo=mecanismo_resistencia
    )


@pytest.fixture
def subtipo_mecanismo_hospital(hospital, subtipo_mecanismo_resistencia):
    """Fixture para SubtipoMecanismoResistenciaHospital"""
    sub_hosp = SubtipoMecanismoResistenciaHospital.objects.create(
        hospital=hospital,
        subtipo_mecanismo=subtipo_mecanismo_resistencia
    )
    sub_hosp.alias = ["ctx-m", "ctxm"]
    sub_hosp.save()
    return sub_hosp


# AliasInterpretacionHospital
@pytest.fixture
def alias_interpretacion_hospital(hospital):
    """Fixture para AliasInterpretacionHospital"""
    alias_s = AliasInterpretacionHospital.objects.create(
        hospital=hospital,
        interpretacion='S'
    )
    alias_s.alias = ['sensible', 'sen', 's']
    alias_s.save()

    alias_r = AliasInterpretacionHospital.objects.create(
        hospital=hospital,
        interpretacion='R'
    )
    alias_r.alias = ['resistente', 'res', 'r']
    alias_r.save()

    alias_i = AliasInterpretacionHospital.objects.create(
        hospital=hospital,
        interpretacion='I'
    )
    alias_i.alias = ['intermedio', 'int', 'i']
    alias_i.save()

    return [alias_s, alias_r, alias_i]


# MecResValoresPositivosHospital
@pytest.fixture
def valores_positivos_hospital(hospital):
    """Fixture para MecResValoresPositivosHospital"""
    vals = MecResValoresPositivosHospital.objects.create(
        hospital=hospital
    )
    vals.alias = ['positivo', '+', 'pos', 'si', 'yes']
    vals.save()
    return vals


# RequestFactory. ref: https://medium.com/@altafkhan_24475/part-8-an-overview-of-request-factory-in-django-testing-d60de51b8e19
@pytest.fixture
def request_factory():
    """Fixture para RequestFactory"""
    return RequestFactory()

# Mocks de request
@pytest.fixture
def mock_request(request_factory, usuario):
    """Fixture para un request mock con usuario autenticado"""
    request = request_factory.post('/cargar-antibiograma/')
    request.user = usuario

    # Añadir soporte para 'contrib.messages'
    setattr(request, 'session', 'session')
    messages = FallbackStorage(request)
    setattr(request, '_messages', messages)

    return request


@pytest.fixture
def mock_files():
    """Fixture para archivos mock"""
    return []

# Datos demográficos
@pytest.fixture
def datos_demograficos_completos(sexo_hospital, ambito_hospital, servicio_hospital,
                                 tipo_muestra_hospital, eucast_version):
    """Fixture para datos demográficos completos"""
    return {
        'nh_hash': 'hash123abc',
        'edad': 45.0,
        'fecha': date(2024, 1, 15),
        'version_eucast': eucast_version,
        'sexo_obj': sexo_hospital,
        'ambito_obj': ambito_hospital,
        'servicio_obj': servicio_hospital,
        'muestra_obj': tipo_muestra_hospital
    }


# Registro
@pytest.fixture
def registro_completo(hospital, sexo_hospital, ambito_hospital, servicio_hospital,
                      tipo_muestra_hospital):
    """Fixture para un Registro completo"""
    return Registro.objects.create(
        hospital=hospital,
        nh_hash='hash123abc',
        fecha=date(2024, 1, 15),
        sexo=sexo_hospital,
        edad=45,
        ambito=ambito_hospital,
        servicio=servicio_hospital,
        tipo_muestra=tipo_muestra_hospital
    )

# Aislado
@pytest.fixture
def aislado_completo(hospital, registro_completo, microorganismo_hospital, eucast_version):
    """Fixture para un Aislado completo"""
    return Aislado.objects.create(
        hospital=hospital,
        registro=registro_completo,
        microorganismo=microorganismo_hospital,
        version_eucast=eucast_version
    )

# ResultadoAntibiotico
@pytest.fixture
def resultado_antibiotico(aislado_completo, antibiotico_hospital):
    """Fixture para ResultadoAntibiotico"""
    return ResultadoAntibiotico.objects.create(
        aislado=aislado_completo,
        antibiotico=antibiotico_hospital,
        interpretacion='S',
        cmi=2.0,
        halo=20
    )



# TESTS PARA _read_files()
@pytest.mark.django_db
class TestReadFiles:
    """Tests para el método _read_files"""

    def test_read_excel_single_sheet(self, mock_request):
        """Test leer archivo Excel con una sola hoja"""
        view = CargarAntibiogramaView()
        view.request = mock_request

        # Crear archivo Excel mock
        df_test = pd.DataFrame({
            'fecha': ['2024-01-01'],
            'microorganismo': ['E. coli'],
            'edad': [45]
        })

        excel_buffer = io.BytesIO()
        df_test.to_excel(excel_buffer, index=False)
        excel_buffer.seek(0)

        # mock del archivo
        mock_file = Mock()
        mock_file.name = 'test.xlsx'
        mock_file.read.return_value = excel_buffer.getvalue()

        with patch('pandas.read_excel', return_value={'Sheet1': df_test}):
            result = view._read_files([mock_file])

        assert len(result) == 1 # 1 fila
        assert isinstance(result[0], pd.DataFrame) # pd.DataFrame?
        assert list(result[0].columns) == ['fecha', 'microorganismo', 'edad'] # columnas

    def test_read_excel_multiple_sheets(self, mock_request):
        """Test leer archivo Excel con múltiples hojas"""
        view = CargarAntibiogramaView()
        view.request = mock_request

        df1 = pd.DataFrame({'col1': [1, 2]})
        df2 = pd.DataFrame({'col2': [3, 4]})

        mock_file = Mock()
        mock_file.name = 'test.xlsx'

        with patch('pandas.read_excel', return_value={'Sheet1': df1, 'Sheet2': df2}):
            result = view._read_files([mock_file])

        assert len(result) == 2 # 2 archivos?

    def test_read_csv_with_semicolon(self, mock_request):
        """Test leer CSV con punto y coma como separador"""
        view = CargarAntibiogramaView()
        view.request = mock_request

        csv_content = "fecha;microorganismo;edad\n2024-01-01;E. coli;45" # separado por ';'

        mock_file = Mock()
        mock_file.name = 'test.csv'
        mock_file.read.return_value = csv_content.encode('latin-1')

        result = view._read_files([mock_file])

        assert len(result) == 1 # 1 fila
        assert 'fecha' in result[0].columns # fecha en columnas
        assert 'microorganismo' in result[0].columns # microorganismo en columnas

    def test_read_csv_with_comma(self, mock_request):
        """Test leer CSV con coma como separador.
        Es análogo al test con punto y coma. """
        view = CargarAntibiogramaView()
        view.request = mock_request

        csv_content = "fecha,microorganismo,edad\n2024-01-01,E. coli,45"

        mock_file = Mock()
        mock_file.name = 'test.csv'
        mock_file.read.return_value = csv_content.encode('latin-1')

        result = view._read_files([mock_file])

        assert len(result) == 1

    def test_read_invalid_file(self, mock_request):
        """Test leer archivo inválido"""
        view = CargarAntibiogramaView()
        view.request = mock_request

        mock_file = Mock()
        mock_file.name = 'test.xlsx'
        mock_file.read.side_effect = Exception("Error de lectura")

        result = view._read_files([mock_file])

        assert result == [] # vacío si error?



# TESTS PARA _convert_mic_mm_column()

@pytest.mark.django_db
class TestConvertMicMmColumn:
    """Tests para el método _convert_mic_mm_column"""

    def test_convert_cmi_column(self):
        """Test conversión de columna CMI"""
        df = pd.DataFrame({
            'amoxicilina_cmi': ['<=0.5', '2', '>16'],
            'otra_col': ['a', 'b', 'c']
        })

        # se parchea la función real por un mock
        with patch('CRUD.views.numeric_column_transformer') as mock_transformer:
            mock_transformer.return_value = pd.Series([0.5, 2.0, 16.0])
            CargarAntibiogramaView._convert_mic_mm_column(df) # llamamos a la función

            mock_transformer.assert_called_once() # verificamos si se invoca para la columna '_cmi'

    def test_convert_halo_column(self):
        """Test conversión de columna halo (mm). La misma idea para columnas de halo"""
        df = pd.DataFrame({
            'amoxicilina_mm': ['12', '20', '25'],
            'otra_col': ['a', 'b', 'c']
        })

        with patch('CRUD.views.numeric_column_transformer') as mock_transformer:
            mock_transformer.return_value = pd.Series([12.0, 20.0, 25.0])
            CargarAntibiogramaView._convert_mic_mm_column(df)

            mock_transformer.assert_called_once()

    def test_no_conversion_for_other_columns(self):
        """Test que no convierte columnas que no sean CMI/MM"""
        df = pd.DataFrame({
            'fecha': ['2024-01-01'],
            'edad': ['45']
        })

        with patch('CRUD.views.numeric_column_transformer') as mock_transformer:
            CargarAntibiogramaView._convert_mic_mm_column(df)

            mock_transformer.assert_not_called() # que NO llame a la función



# TESTS PARA _build_cache()

@pytest.mark.django_db
class TestBuildCache:
    """Tests para el método _build_cache"""

    def test_build_cache_structure(self, hospital, antibiotico_hospital):
        """Test estructura del caché construido"""
        antibioticos_permitidos = [antibiotico_hospital]

        cache = CargarAntibiogramaView._build_cache(hospital, antibioticos_permitidos)

        # existen las claves?
        assert 'sexos_cache' in cache
        assert 'ambitos_cache' in cache
        assert 'servicios_cache' in cache
        assert 'muestras_cache' in cache
        assert 'antibioticos_dict' in cache
        assert 'nombres_ab_dict' in cache
        assert 'alias_hospital' in cache
        assert 'pos_vals' in cache
        assert 'mecanismos' in cache
        assert 'subtipos' in cache
        assert 'registros_cache' in cache

    def test_antibioticos_dict_content(self, hospital, antibiotico_hospital):
        """Test contenido del diccionario de antibióticos"""
        antibioticos_permitidos = [antibiotico_hospital]

        cache = CargarAntibiogramaView._build_cache(hospital,
                                                    antibioticos_permitidos)

        assert antibiotico_hospital.antibiotico.id in cache['antibioticos_dict'] # clave id Antibiotico?
        # valor asociado AntibioticoHospital?
        assert cache['antibioticos_dict'][antibiotico_hospital.antibiotico.id] == antibiotico_hospital

    def test_nombres_ab_dict_includes_aliases(self, hospital, antibiotico_hospital):
        """Test que nombres_ab_dict incluye abreviaturas y alias"""
        antibioticos_permitidos = [antibiotico_hospital]

        cache = CargarAntibiogramaView._build_cache(hospital, antibioticos_permitidos)

        ab_id = antibiotico_hospital.antibiotico.id
        assert ab_id in cache['nombres_ab_dict'] # se incluyen abr y alias?


# TESTS PARA _get_demographic_data()

@pytest.mark.django_db
class TestGetDemographicData:
    """Tests para el método _get_demographic_data"""

    def test_get_demographic_data_complete(self, hospital, sexo_hospital, ambito_hospital,
                                           servicio_hospital, tipo_muestra_hospital,
                                           microorganismo_hospital, eucast_version):
        """Test obtener datos demográficos completos"""

        # Preparar datos de entrada
        row = pd.Series({
            'nh': '12345',
            'edad': '45',
            'fecha': '2024-01-15',
            'sexo': 'Masculino',
            'ambito': 'Hospitalización',
            'servicio': 'Urología',
            'tipo_muestra': 'Orina'
        })

        mapping = {
            'nh': 'nh',
            'edad': 'edad',
            'fecha': 'fecha',
            'sexo': 'sexo',
            'ambito': 'ambito',
            'servicio': 'servicio',
            'tipo_muestra': 'tipo_muestra'
        }

        # Construimos el caché
        cache = CargarAntibiogramaView._build_cache(hospital, [])
        timestamp = 1234567890

        # Mockear la versión EUCAST
        with patch('CRUD.views.EucastVersion.get_version_from_date', return_value=eucast_version):
            result = CargarAntibiogramaView._get_demographic_data(
                row, mapping, cache, timestamp, 1, microorganismo_hospital.id
            )

        # Verificaciones
        assert result is not None, "El resultado no debe ser None" # hay resultado
        assert result['nh_hash'] is not None # existe nh_hash
        # exisen el resto de variables epidemiológicas y clínicas
        assert result['edad'] == 45.0
        assert result['fecha'] == date(2024, 1, 15)
        assert result['version_eucast'] == eucast_version
        assert result['sexo_obj'] == sexo_hospital
        assert result['ambito_obj'] == ambito_hospital
        assert result['servicio_obj'] == servicio_hospital
        assert result['muestra_obj'] == tipo_muestra_hospital

    def test_get_demographic_data_missing_nh(self, hospital, sexo_hospital, ambito_hospital,
                                             servicio_hospital, tipo_muestra_hospital,
                                             microorganismo_hospital, eucast_version):
        """Test con NH faltante genera hash automático"""
        row = pd.Series({
            'nh': None, # SIN NH!!
            'edad': '45',
            'fecha': '2024-01-15',
            'sexo': 'Masculino',
            'ambito': 'Hospitalización',
            'servicio': 'Urología',
            'tipo_muestra': 'Orina'
        })

        mapping = {
            'nh': 'nh',
            'edad': 'edad',
            'fecha': 'fecha',
            'sexo': 'sexo',
            'ambito': 'ambito',
            'servicio': 'servicio',
            'tipo_muestra': 'tipo_muestra'
        }

        cache = CargarAntibiogramaView._build_cache(hospital, [])
        timestamp = 1234567890

        with patch('CRUD.views.EucastVersion.get_version_from_date', return_value=eucast_version):
            result = CargarAntibiogramaView._get_demographic_data(
                row, mapping, cache, timestamp, 1, microorganismo_hospital.id
            )

        assert result is not None # Existe resultado
        assert result['nh_hash'] is not None # existe nh_has porque...
        # ... el hash debe ser generado automáticamente
        assert len(result['nh_hash']) > 0

    def test_get_demographic_data_incomplete_returns_none(self, hospital, microorganismo_hospital,
                                                          eucast_version):
        """Test con datos incompletos retorna None"""
        row = pd.Series({
            'nh': '12345',
            'edad': '45',
            # Falta fecha - campo obligatorio
            'sexo': 'Masculino'
        })

        mapping = {
            'nh': 'nh',
            'edad': 'edad',
            'fecha': 'fecha',
            'sexo': 'sexo'
        }

        cache = CargarAntibiogramaView._build_cache(hospital, [])
        timestamp = 1234567890

        with patch('CRUD.views.EucastVersion.get_version_from_date', return_value=eucast_version):
            result = CargarAntibiogramaView._get_demographic_data(
                row, mapping, cache, timestamp, 1, microorganismo_hospital.id
            )

        # Debe retornar None porque falta la fecha, no es un registro válido
        assert result is None


# TESTS PARA get_or_create_registro()

@pytest.mark.django_db
class TestGetOrCreateRegistro:
    """Tests para el método get_or_create_registro"""

    def test_create_new_registro(self, hospital, sexo_hospital, ambito_hospital,
                                 servicio_hospital, tipo_muestra_hospital):
        """Test crear nuevo registro"""
        datos = {
            'nh_hash': 'hash123',
            'edad': 45.0,
            'fecha': date(2024, 1, 15),
            'version_eucast': Mock(),
            'sexo_obj': sexo_hospital,
            'ambito_obj': ambito_hospital,
            'servicio_obj': servicio_hospital,
            'muestra_obj': tipo_muestra_hospital
        }

        contadores = {
            'registros_creados': 0,
            'registros_reutilizados': 0
        }

        registros_cache = {}

        registro = CargarAntibiogramaView.get_or_create_registro(
            datos, hospital, registros_cache, contadores
        )

        assert registro is not None # existe el registro
        assert contadores['registros_creados'] == 1 # hay un registro creado
        assert contadores['registros_reutilizados'] == 0 # no hay registro reutilizado (no es actualización)
        assert len(registros_cache) == 1 # en caché

    def test_reuse_existing_registro(self, hospital, sexo_hospital, ambito_hospital,
                                     servicio_hospital, tipo_muestra_hospital):
        """Test reutilizar registro existente"""
        # Crear registro primero
        registro_existente = Registro.objects.create(
            nh_hash='hash123',
            fecha=date(2024, 1, 15),
            sexo=sexo_hospital,
            edad=45.0,
            ambito=ambito_hospital,
            servicio=servicio_hospital,
            tipo_muestra=tipo_muestra_hospital,
            hospital=hospital
        )

        # Datos para el mismo registro
        datos = {
            'nh_hash': 'hash123',
            'edad': 45.0,
            'fecha': date(2024, 1, 15),
            'version_eucast': Mock(),
            'sexo_obj': sexo_hospital,
            'ambito_obj': ambito_hospital,
            'servicio_obj': servicio_hospital,
            'muestra_obj': tipo_muestra_hospital
        }

        contadores = {
            'registros_creados': 0,
            'registros_reutilizados': 0
        }

        registros_cache = {}

        registro = CargarAntibiogramaView.get_or_create_registro(
            datos, hospital, registros_cache, contadores
        )

        assert registro.id == registro_existente.id # el registro es el mismo
        assert contadores['registros_creados'] == 0 # no creado
        assert contadores['registros_reutilizados'] == 1 # reutilizado


# TESTS PARA _parse_mic_and_halo()

@pytest.mark.django_db
class TestParseMicAndHalo:
    """Tests para el método _parse_mic_and_halo"""

    def test_parse_valid_mic_and_halo(self):
        """Test parsear CMI y halo válidos"""
        with patch('CRUD.views.parse_mic', return_value=2.0), \
                patch('CRUD.views.parse_halo', return_value=20.0):
            cmi, halo = CargarAntibiogramaView._parse_mic_and_halo('2', '20')

            assert cmi == 2.0
            assert halo == 20.0

    def test_parse_none_values(self):
        """Test parsear valores None"""
        cmi, halo = CargarAntibiogramaView._parse_mic_and_halo(None, None)

        assert cmi is None
        assert halo is None

    def test_parse_with_exception(self):
        """Test parsear con excepción"""
        with patch('CRUD.views.parse_mic', side_effect=Exception("Error")):
            cmi, halo = CargarAntibiogramaView._parse_mic_and_halo('invalid', None)

            assert cmi is None
            assert halo is None


# TESTS PARA _get_interpretation()

@pytest.mark.django_db
class TestGetInterpretation:
    """Tests para el método _get_interpretation"""

    def test_get_standard_interpretation_from_alias(self, hospital):
        """Test obtener interpretación estándar desde alias"""
        alias_obj = AliasInterpretacionHospital.objects.create(
            hospital=hospital,
            interpretacion='S'
        )
        alias_obj.alias = ['sensible', 'sen']
        alias_obj.save()

        result = CargarAntibiogramaView._get_interpretation('sensible', [alias_obj])

        assert result == 'S'

    def test_get_interpretation_direct_value(self, hospital):
        """Test obtener interpretación con valor directo S/R/I"""
        result = CargarAntibiogramaView._get_interpretation('R', [])

        assert result == 'R'

    def test_get_interpretation_none(self):
        """Test interpretación con None"""
        result = CargarAntibiogramaView._get_interpretation(None, [])

        assert result == 'ND'

    def test_get_interpretation_invalid(self):
        """Test interpretación con valor inválido"""
        result = CargarAntibiogramaView._get_interpretation('INVALIDO', [])

        assert result == 'ND'


# TESTS PARA _is_duplicated()

@pytest.mark.django_db
class TestIsDuplicated:
    """Tests para el método _is_duplicated"""

    def test_not_duplicated_no_existing_isolates(self, hospital, microorganismo_hospital,
                                                 sexo_hospital, ambito_hospital,
                                                 servicio_hospital, tipo_muestra_hospital):
        """Test no duplicado cuando no hay aislados existentes"""
        registro = Registro.objects.create(
            nh_hash='hash123',
            fecha=date(2024, 1, 15),
            sexo=sexo_hospital,
            edad=45.0,
            ambito=ambito_hospital,
            servicio=servicio_hospital,
            tipo_muestra=tipo_muestra_hospital,
            hospital=hospital
        )

        resultados_finales = {
            1: ('S', 2.0, 20.0)
        }

        is_dup = CargarAntibiogramaView._is_duplicated(
            registro, microorganismo_hospital, resultados_finales
        )

        assert is_dup is False

    def test_duplicated_exact_match(self, hospital, microorganismo_hospital, antibiotico,
                                    sexo_hospital, ambito_hospital, servicio_hospital,
                                    tipo_muestra_hospital, eucast_version):
        """Test duplicado exacto"""
        registro = Registro.objects.create(
            nh_hash='hash123',
            fecha=date(2024, 1, 15),
            sexo=sexo_hospital,
            edad=45.0,
            ambito=ambito_hospital,
            servicio=servicio_hospital,
            tipo_muestra=tipo_muestra_hospital,
            hospital=hospital
        )

        aislado_existente = Aislado.objects.create(
            registro=registro,
            hospital=hospital,
            version_eucast=eucast_version,
            microorganismo=microorganismo_hospital
        )

        ab_hosp = AntibioticoHospital.objects.create(
            hospital=hospital,
            antibiotico=antibiotico
        )

        ResultadoAntibiotico.objects.create(
            aislado=aislado_existente,
            antibiotico=ab_hosp,
            interpretacion='S',
            cmi=2.0,
            halo=20.0
        )

        resultados_finales = {
            antibiotico.id: ('S', 2.0, 20.0)
        }

        is_dup = CargarAntibiogramaView._is_duplicated(
            registro, microorganismo_hospital, resultados_finales
        )

        assert is_dup is True

    def test_not_duplicated_different_results(self, hospital, microorganismo_hospital, antibiotico,
                                              sexo_hospital, ambito_hospital, servicio_hospital,
                                              tipo_muestra_hospital, eucast_version):
        """Test no duplicado con resultados diferentes"""
        registro = Registro.objects.create(
            nh_hash='hash123',
            fecha=date(2024, 1, 15),
            sexo=sexo_hospital,
            edad=45.0,
            ambito=ambito_hospital,
            servicio=servicio_hospital,
            tipo_muestra=tipo_muestra_hospital,
            hospital=hospital
        )

        aislado_existente = Aislado.objects.create(
            registro=registro,
            hospital=hospital,
            version_eucast=eucast_version,
            microorganismo=microorganismo_hospital
        )

        ab_hosp = AntibioticoHospital.objects.create(
            hospital=hospital,
            antibiotico=antibiotico
        )

        ResultadoAntibiotico.objects.create(
            aislado=aislado_existente,
            antibiotico=ab_hosp,
            interpretacion='S',
            cmi=2.0,
            halo=20.0
        )

        # Resultados diferentes
        resultados_finales = {
            antibiotico.id: ('R', 16.0, 10.0)
        }

        is_dup = CargarAntibiogramaView._is_duplicated(
            registro, microorganismo_hospital, resultados_finales
        )

        assert is_dup is False


# TESTS PARA _create_isolate()

@pytest.mark.django_db
class TestCreateIsolate:
    """Tests para el método _create_isolate"""

    def test_create_isolate_basic(self, hospital, microorganismo_hospital, antibiotico,
                                  sexo_hospital, ambito_hospital, servicio_hospital,
                                  tipo_muestra_hospital, eucast_version):
        """Test crear aislado básico"""
        registro = Registro.objects.create(
            nh_hash='hash123',
            fecha=date(2024, 1, 15),
            sexo=sexo_hospital,
            edad=45.0,
            ambito=ambito_hospital,
            servicio=servicio_hospital,
            tipo_muestra=tipo_muestra_hospital,
            hospital=hospital
        )

        resultados_finales = {
            antibiotico.id: ('S', 2.0, 20.0)
        }

        CargarAntibiogramaView._create_isolate(
            registro, hospital, eucast_version, microorganismo_hospital,
            resultados_finales, set(), set(), set()
        )

        assert Aislado.objects.filter(registro=registro).exists() # el registro existe
        aislado = Aislado.objects.get(registro=registro)
        assert aislado.microorganismo == microorganismo_hospital # el MicroorganismoHospital del aislado se corresponde
        assert ResultadoAntibiotico.objects.filter(aislado=aislado).count() == 1 # resultado para el antibiótico reado

    def test_create_isolate_with_intrinsic_resistance(self, hospital, microorganismo_hospital,
                                                      antibiotico, sexo_hospital, ambito_hospital,
                                                      servicio_hospital, tipo_muestra_hospital,
                                                      eucast_version):
        """Test crear aislado con resistencia intrínseca"""
        registro = Registro.objects.create(
            nh_hash='hash123',
            fecha=date(2024, 1, 15),
            sexo=sexo_hospital,
            edad=45.0,
            ambito=ambito_hospital,
            servicio=servicio_hospital,
            tipo_muestra=tipo_muestra_hospital,
            hospital=hospital
        )

        resultados_finales = {
            antibiotico.id: ('S', 2.0, 20.0)
        }

        resistencias_intrinsecas = {antibiotico.id}

        CargarAntibiogramaView._create_isolate(
            registro, hospital, eucast_version, microorganismo_hospital,
            resultados_finales, set(), set(), resistencias_intrinsecas
        )

        aislado = Aislado.objects.get(registro=registro)
        resultado = ResultadoAntibiotico.objects.get(aislado=aislado)

        # Debe guardarse como R por resistencia intrínseca!!
        assert resultado.interpretacion == 'R'

    def test_create_isolate_skips_empty_results(self, hospital, microorganismo_hospital,
                                                antibiotico, sexo_hospital, ambito_hospital,
                                                servicio_hospital, tipo_muestra_hospital,
                                                eucast_version):
        """Test crear aislado omitiendo resultados vacíos"""
        registro = Registro.objects.create(
            nh_hash='hash123',
            fecha=date(2024, 1, 15),
            sexo=sexo_hospital,
            edad=45.0,
            ambito=ambito_hospital,
            servicio=servicio_hospital,
            tipo_muestra=tipo_muestra_hospital,
            hospital=hospital
        )

        # Resultado completamente vacío
        resultados_finales = {
            antibiotico.id: ('ND', None, None)
        }

        CargarAntibiogramaView._create_isolate(
            registro, hospital, eucast_version, microorganismo_hospital,
            resultados_finales, set(), set(), set()
        )

        aislado = Aislado.objects.get(registro=registro)

        # No debe crear ResultadoAntibiotico por resultados nulos
        assert ResultadoAntibiotico.objects.filter(aislado=aislado).count() == 0

    def test_create_isolate_with_mechanisms(self, hospital, microorganismo_hospital, antibiotico,
                                            sexo_hospital, ambito_hospital, servicio_hospital,
                                            tipo_muestra_hospital, eucast_version):
        """Test crear aislado con mecanismos de resistencia"""
        registro = Registro.objects.create(
            nh_hash='hash123',
            fecha=date(2024, 1, 15),
            sexo=sexo_hospital,
            edad=45.0,
            ambito=ambito_hospital,
            servicio=servicio_hospital,
            tipo_muestra=tipo_muestra_hospital,
            hospital=hospital
        )

        # Crear mecanismo de resistencia
        mec_res = MecanismoResistencia.objects.create(
            nombre="BLEE",
            descripcion="Beta-lactamasas de espectro extendido"
        )

        mec = MecanismoResistenciaHospital.objects.create(
            hospital=hospital,
            mecanismo=mec_res
        )

        resultados_finales = {
            antibiotico.id: ('R', 16.0, 10.0)
        }

        mec_detectados = {mec}

        CargarAntibiogramaView._create_isolate(
            registro, hospital, eucast_version, microorganismo_hospital,
            resultados_finales, mec_detectados, set(), set()
        )

        aislado = Aislado.objects.get(registro=registro)

        assert aislado.mecanismos_resistencia.count() == 1 # aislado con un mecanimo de resistencia
        assert mec in aislado.mecanismos_resistencia.all() # el mecanismo está en el aislado


# TESTS PARA _get_arm()

@pytest.mark.django_db
class TestGetArm:
    """Tests para el método _get_arm (resistencias adquiridas)"""

    def test_get_arm_no_mechanisms(self, hospital):
        """Test sin mecanismos detectados"""
        row = pd.Series({'dato': 'valor'})
        mapping = {}
        resultados_procesados = {1: ('S', 2.0, 20.0)}

        with patch('CRUD.views.detect_arm', return_value=(set(), set())):
            mec_det, sub_det, resultados_finales = CargarAntibiogramaView._get_arm(
                row, mapping, resultados_procesados, [], [], []
            )

        assert len(mec_det) == 0 # no hay ni mecanismos ni subtipos de mecanismos
        assert len(sub_det) == 0
        assert resultados_finales == resultados_procesados # se incorporan los resultados procesados, sin mecs

    def test_get_arm_with_acquired_resistance(self, hospital, antibiotico, mecanismo_resistencia):
        """Test con resistencia adquirida detectada"""
        # Crear mecanismo con resistencia adquirida
        mec = MecanismoResistenciaHospital.objects.create(
            hospital=hospital,
            mecanismo=mecanismo_resistencia
        )
        mec.resistencia_adquirida.add(antibiotico)

        row = pd.Series({'blee': 'positivo'})
        mapping = {}
        resultados_procesados = {antibiotico.id: ('S', 2.0, 20.0)} # los resultados dicen 'S'

        with patch('CRUD.views.detect_arm', return_value=({mec}, set())):
            mec_det, sub_det, resultados_finales = CargarAntibiogramaView._get_arm(
                row, mapping, resultados_procesados, [mec], [], []
            )

        # Debe cambiar de S a R
        assert resultados_finales[antibiotico.id][0] == 'R'
        assert resultados_finales[antibiotico.id][1] == 2.0  # CMI conservada
        assert resultados_finales[antibiotico.id][2] == 20.0  # Halo conservado

    def test_get_arm_preserves_existing_r(self, hospital, antibiotico, mecanismo_resistencia):
        """Test que preserva interpretación R existente"""
        mec = MecanismoResistenciaHospital.objects.create(
            hospital=hospital,
            mecanismo=mecanismo_resistencia
        )
        mec.resistencia_adquirida.add(antibiotico)

        row = pd.Series({'blee': 'positivo'})
        mapping = {}
        resultados_procesados = {antibiotico.id: ('R', 16.0, 10.0)}

        with patch('CRUD.views.detect_arm', return_value=({mec}, set())):
            mec_det, sub_det, resultados_finales = CargarAntibiogramaView._get_arm(
                row, mapping, resultados_procesados, [mec], [], []
            )

        # Debe permanecer como R
        assert resultados_finales[antibiotico.id][0] == 'R'

    def test_get_arm_does_not_modify_nd(self, hospital, antibiotico, mecanismo_resistencia):
        """Test que no modifica interpretaciones ND/NA"""
        mec = MecanismoResistenciaHospital.objects.create(
            hospital=hospital,
            mecanismo=mecanismo_resistencia
        )
        mec.resistencia_adquirida.add(antibiotico)

        row = pd.Series({'blee': 'positivo'})
        mapping = {}
        resultados_procesados = {antibiotico.id: ('ND', None, None)}

        with patch('CRUD.views.detect_arm', return_value=({mec}, set())):
            mec_det, sub_det, resultados_finales = CargarAntibiogramaView._get_arm(
                row, mapping, resultados_procesados, [mec], [], []
            )

        # Debe permanecer como ND
        assert resultados_finales[antibiotico.id][0] == 'ND'


# TESTS PARA _apply_eucast_breakpoints()

@pytest.mark.django_db
class TestApplyEucastBreakpoints:
    """Tests para el método _apply_eucast_breakpoints"""

    def test_no_variants(self, hospital, antibiotico_hospital, microorganismo_hospital,
                         sexo_hospital, tipo_muestra_hospital, eucast_version):
        """Test antibiótico sin variantes"""
        result = CargarAntibiogramaView._apply_eucast_breakpoints(
            antibiotico_hospital, 2.0, 20.0, eucast_version,
            microorganismo_hospital, 45.0, sexo_hospital, tipo_muestra_hospital
        )

        # Sin variantes debe retornar diccionario vacío
        assert result == {}

    def test_with_variants_no_rules(self, hospital, antibiotico, microorganismo_hospital,
                                    sexo_hospital, tipo_muestra_hospital, eucast_version):
        """Test con variantes pero sin reglas EUCAST"""
        ab_hosp = AntibioticoHospital.objects.create(
            hospital=hospital,
            antibiotico=antibiotico
        )

        # Crear variante - debe tener la misma familia que el padre
        variante = Antibiotico.objects.create(
            nombre="Amoxicilina (oral)",
            abr="AMX-O",
            familia_antibiotico=antibiotico.familia_antibiotico,
            es_variante=True,
            parent=antibiotico,
            via_administracion="oral"
        )

        result = CargarAntibiogramaView._apply_eucast_breakpoints(
            ab_hosp, 2.0, 20.0, eucast_version,
            microorganismo_hospital, 45.0, sexo_hospital, tipo_muestra_hospital
        )

        # Sin reglas debe retornar diccionario vacío, da igual que haya una variante
        assert result == {}

    def test_with_applicable_rule(self, hospital, antibiotico, microorganismo_hospital,
                                  sexo_hospital, tipo_muestra_hospital, eucast_version):
        """Test con regla EUCAST aplicable"""
        ab_hosp = AntibioticoHospital.objects.create(
            hospital=hospital,
            antibiotico=antibiotico
        )

        # Crear variante
        variante = Antibiotico.objects.create(
            nombre="Amoxicilina (oral)",
            abr="AMX-O",
            familia_antibiotico=antibiotico.familia_antibiotico,
            es_variante=True,
            parent=antibiotico,
            via_administracion="oral"
        )

        # Crear regla mock
        mock_regla = MagicMock()
        mock_regla.antibiotico = variante
        mock_regla.version_eucast = eucast_version
        mock_regla.apply_to.return_value = True
        mock_regla.interpret.return_value = 'S'

        # Crear el queryset mock que contenga esa regla
        # https://stackoverflow.com/questions/53768225/mock-object-is-not-iterable?utm_source=chatgpt.com
        # https://stackless.readthedocs.io/en/3.6-slp/library/unittest.mock-examples.html?utm_source=chatgpt.com#mocking-a-generator-method
        mock_queryset = MagicMock()
        mock_queryset.exists.return_value = True
        mock_queryset.__iter__.return_value = iter([mock_regla])

        # Patchear con la regla de interpretación
        with patch('Base.models.ReglaInterpretacion.objects.filter', return_value=mock_queryset):
            result = CargarAntibiogramaView._apply_eucast_breakpoints(
                ab_hosp, 2.0, 20.0, eucast_version,
                microorganismo_hospital, 45.0, sexo_hospital, tipo_muestra_hospital
            )

        assert variante.id in result # está la variante?
        assert result[variante.id][0] == 'S' # el resultado de la variante es 'S'?


# TESTS PARA _get_antibiogram()

@pytest.mark.django_db
class TestGetAntibiogram:
    """Tests para el método _get_antibiogram"""

    def test_get_antibiogram_basic(self, mock_request, hospital, antibiotico, antibiotico_hospital,
                                   microorganismo_hospital, sexo_hospital, tipo_muestra_hospital,
                                   eucast_version):
        """Test procesamiento básico de antibiograma"""
        view = CargarAntibiogramaView()
        view.request = mock_request

        row = pd.Series({
            'amx': 'S',
            'amx_cmi': 2.0,
            'amx_mm': 20.0
        })

        nombres_ab_dict = {
            antibiotico.id: ['amx', 'amoxicilina']
        }

        antibioticos_dict = {
            antibiotico.id: antibiotico_hospital
        }

        with patch('CRUD.views.search_value_in_columns', return_value=('amx', 'S')), \
                patch('CRUD.views.search_mic_in_columns', return_value=('amx_cmi', 2.0)), \
                patch('CRUD.views.search_halo_in_columns', return_value=('amx_mm', 20.0)):

            result = view._get_antibiogram(
                row, nombres_ab_dict, antibioticos_dict, [],
                eucast_version, microorganismo_hospital, 45.0,
                sexo_hospital, tipo_muestra_hospital, set()
            )

        assert antibiotico.id in result # está el id del antibiótico en los resultados?
        assert result[antibiotico.id][0] == 'S' # el resultado es 'S'?

    def test_get_antibiogram_intrinsic_resistance(self, mock_request, hospital, antibiotico,
                                                  antibiotico_hospital, microorganismo_hospital,
                                                  sexo_hospital, tipo_muestra_hospital,
                                                  eucast_version):
        """Test con resistencia intrínseca"""
        view = CargarAntibiogramaView()
        view.request = mock_request

        row = pd.Series({
            'amx': 'S',
            'amx_cmi': 2.0
        })

        nombres_ab_dict = {
            antibiotico.id: ['amx']
        }

        antibioticos_dict = {
            antibiotico.id: antibiotico_hospital
        }

        resistencias_intrinsecas = {antibiotico.id}

        with patch('CRUD.views.search_value_in_columns', return_value=('amx', 'S')), \
                patch('CRUD.views.search_mic_in_columns', return_value=('amx_cmi', 2.0)), \
                patch('CRUD.views.search_halo_in_columns', return_value=(None, None)):

            # Ojo! Se pasa 'S' pero hay una resistencia intrínseca
            result = view._get_antibiogram(
                row, nombres_ab_dict, antibioticos_dict, [],
                eucast_version, microorganismo_hospital, 45.0,
                sexo_hospital, tipo_muestra_hospital, resistencias_intrinsecas
            )

        # Debe marcarse como R por resistencia intrínseca
        assert result[antibiotico.id][0] == 'R'

    def test_get_antibiogram_no_data(self, mock_request, hospital, antibiotico,
                                     antibiotico_hospital, microorganismo_hospital,
                                     sexo_hospital, tipo_muestra_hospital, eucast_version):
        """Test sin datos para el antibiótico"""
        view = CargarAntibiogramaView()
        view.request = mock_request

        row = pd.Series({})

        nombres_ab_dict = {
            antibiotico.id: ['amx']
        }

        antibioticos_dict = {
            antibiotico.id: antibiotico_hospital
        }

        with patch('CRUD.views.search_value_in_columns', return_value=(None, None)), \
                patch('CRUD.views.search_mic_in_columns', return_value=(None, None)), \
                patch('CRUD.views.search_halo_in_columns', return_value=(None, None)):
            result = view._get_antibiogram(
                row, nombres_ab_dict, antibioticos_dict, [],
                eucast_version, microorganismo_hospital, 45.0,
                sexo_hospital, tipo_muestra_hospital, set()
            )

        # No debe incluir el antibiótico, sin datos
        assert antibiotico.id not in result



# TESTS DE INTEGRACIÓN

@pytest.mark.django_db
class TestCargarAntibiogramaViewIntegration:
    """Tests de integración para el flujo completo"""

    def test_get_form_kwargs(self, mock_request, usuario, hospital):
        """Test que get_form_kwargs incluye el hospital"""
        view = CargarAntibiogramaView()
        view.request = mock_request

        kwargs = view.get_form_kwargs()

        assert 'hospital' in kwargs
        assert kwargs['hospital'] == hospital

    def test_get_form_kwargs_superuser(self, request_factory):
        """Test get_form_kwargs con superusuario"""
        superuser = User.objects.create_superuser(
            username='admin',
            password='admin123',
            email='admin@test.com'
        )

        request = request_factory.post('/cargar-antibiograma/')
        request.user = superuser

        view = CargarAntibiogramaView()
        view.request = request

        kwargs = view.get_form_kwargs()

        assert 'hospital' in kwargs
        assert kwargs['hospital'] is None # el superuser no tiene hospital

    def test_get_context_data(self, mock_request):
        """Test que get_context_data incluye campos demográficos y opcionales"""
        view = CargarAntibiogramaView()
        view.request = mock_request

        with patch.object(view, 'get_form'):
            context = view.get_context_data()

        # Verificaciones del contexto
        assert 'campos_demograficos' in context
        assert 'campos_opcionales' in context
        assert 'fecha' in context['campos_demograficos']
        assert 'microorganismo' in context['campos_demograficos']
        assert 'nh' in context['campos_opcionales']
