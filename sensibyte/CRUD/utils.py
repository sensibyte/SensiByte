import hashlib
import numbers
import os
import re
from datetime import datetime, date, timedelta

import pandas
import pandas as pd
import unicodedata

from Base.models import MecanismoResistenciaHospital, SubtipoMecanismoResistenciaHospital, \
    MecResValoresPositivosHospital

# Cargamos las salt desde variables de entorno
SALT_PRE = os.environ.get("HASH_SALT_PRE")
SALT_POST = os.environ.get("HASH_SALT_POST")

NEGACIONES = ["no", "ausencia", "sin", "negativo", "no se detecta"]
SEPARADORES = re.compile(r"[.;$]+") # detecta uno o más caracteres de tipo: "." , ";" o "$"

if not SALT_PRE or not SALT_POST:
    raise ValueError("Debes definir HASH_SALT_PRE y HASH_SALT_POST en el entorno")


def code_nh(nh: str | None) -> str | None:
    """Codifica un número de historia usando el algoritmo SHA-256 con salt.
     ref: https://docs.python.org/3/library/hashlib.html"""
    # No codificar si pasa un valor nulo
    if nh is None:
        return None

    entrada = f"{SALT_PRE}{nh}{SALT_POST}"  # flanquear por las salt
    return hashlib.sha256(entrada.encode("utf-8")).hexdigest()  # devuelve el hash


def gen_automatic_nh_hash(timestamp_carga: int, contador_fila: int, microorganismo_id: int) -> str:
    """
    Genera un hash único combinando timestamp, contador y microorganismo
    con el algoritmo MD5
    """
    base_string = f"{timestamp_carga}_{contador_fila}_{microorganismo_id}"
    return hashlib.sha256(base_string.encode("utf-8")).hexdigest()[:16]  # hash truncado


def normalize_text(s: str | None) -> str:
    """Normaliza a minúsculas y sin caracteres especiales una cadena de texto"""
    if not s:
        return ""  # devuelve cadena vacía si es nulo

    s = s.replace(" ", "").lower()  # elimina espacios y normaliza a minúsculas
    # normaliza eliminando caracteres con acentos: https://guimi.net/blogs/hiparco/funcion-para-eliminar-acentos-en-python/
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def build_alias_cache(queryset) -> dict:
    """
    Construye un diccionario {clave_normalizada: instancia_hospitalaria}.
    - queryset: QuerySet de modelos *específicos de hospital* (Ej: SexoHospital.objects.filter(hospital=h))
    - Tiene en cuenta:
       * nombre principal en el modelo base (atributos 'nombre' o 'descripcion')
       * campo JSON 'alias' del objeto hospitalario (AliasMixin.alias)
    La primera entrada para una clave se mantiene (no sobrescribe).
    """
    import unicodedata  # para normalizar acentos y caracteres especiales

    cache = {}  # variable de tipo diccionario que será devuelta

    # Recorremos los objetos del queryset
    for obj in queryset:
        # 1) detecta el FK al modelo base (primera relación FK que no sea 'hospital')

        # Nota: todos los modelos con sufijo Hospital tienen un campo relacionado con el modelo genérico, que tiene un
        # campo 'nombre' (o 'descripcion', en caso de Sexo). Podemos iterar en los campos del objeto con un generador next()
        # a través de _meta.fields buscando aquellos que tienen el atributo 'is_relation'=True (es un FK o un OneToOne) y apunten
        # a un modelo distinto del modelo Hospital. Nos devuelve el objeto, con un fallback None.
        # Basado en la respuesta de zymud: https://stackoverflow.com/questions/34082832/django-rest-framework-serialize-verbose-name
        fk_field = next(
            (f for f in obj._meta.fields if
             getattr(f, "is_relation", False) and f.related_model.__name__ != "Hospital"),
            None
        )
        base_obj = getattr(obj, fk_field.name) if fk_field else None  # obtiene la instancia del modelo base

        # 2) obtener el nombre principal del modelo base
        main_name = None

        # comprobamos entre los dos posibles campos que contienen el nombre
        for attr in ("nombre", "descripcion"):
            if hasattr(base_obj, attr):  # si el objeto tiene ese campo
                val = getattr(base_obj, attr)  # recupera el valor

                if val:  # si no es nulo asígnalo a la variable main_name y sal del bucle for
                    main_name = val
                    break

        # 3) añadir 'main_name' a la cache
        if main_name:
            # normalizamos la cadena de texto
            key_string = main_name.strip().lower()
            key = "".join(c for c in unicodedata.normalize("NFD", key_string) if unicodedata.category(c) != "Mn")
            if key and key not in cache:  # se lo pasamos al caché con ese nombre como clave
                cache[key] = obj

        # 4) añadir alias del objeto hospitalario (campo JSON 'alias' en AliasMixin)
        if hasattr(obj, "alias"):
            for alias in obj.alias or []:  # para los alias contenidos en el modelo
                if not alias:  # salimos del bucle si no hay alias asociado
                    continue
                # normalizamos la cadena de texto
                k_string = alias.strip().lower()
                k = "".join(c for c in unicodedata.normalize("NFD", k_string) if unicodedata.category(c) != "Mn")
                if k and k not in cache:  # si no está en caché, la añadimos
                    cache[k] = obj

    return cache  # devolvemos el diccionario con el caché final


def get_str(row: pandas.Series, key: str) -> str:
    """Obtiene el valor de un diccionario y lo normaliza a string limpio.
    'row' es el diccionario con los datos de la fila y 'key' la clave a buscar
    en el diccionario.
    Devuelve el valor convertido a string, sin espacios.
    """
    val = row.get(key, "")
    if val is None:
        return ""
    return str(val).strip().lower()


def get_from_cache(cache, value):
    """
    Devuelve el objeto correspondiente al valor (nombre o alias) buscado.
    """
    if not value:
        return None
    key = value.strip().lower()
    if key in cache:
        return cache[key]

    return None


def numeric_column_transformer(col: pd.Series) -> pd.Series:
    """
    Función que intenta convertir los valores numéricos de la columna a int o float.
    Si algún valor no se puede convertir (por ejemplo, '>4/76'), se deja como texto.
    Si pasa un valor nulo se devuelve el valor nulo.
    """

    def value_converter(v):
        """
        Función anidada de conversión de valores. Sólo tiene un argumento, el valor que se le pasa 'v'
        """
        # Si es nulo, devuelve el nulo, no se procesa
        if pd.isna(v):
            return v

        # Si ya es numérico, lo dejamos también tal cual
        # hago la comprobación con numbers.Number porque no sé si entrará
        # un entero o un float, aseguro que sea el numérico que entre valga
        if isinstance(v, numbers.Number):
            return v
        # Si es texto que puede convertirse, lo intentamos
        if isinstance(v, str):  # si es una cadena de texto
            v = v.strip()  # recortamos espacios
            if v == "":
                return v
            # Evitamos valores con signos especiales tipo '>4/76',
            # tenemos el método parse_cmi para lidiar con estos valores
            # más adelante en el flujo
            if any(s in v for s in ["/", ">", "<", "=", "≥", "≤"]):
                return v
            # Si parece que efectivamente el valor es numérico,
            # devolvemos int o float según corresponda (si hay o no punto)
            try:
                v = v.replace(",", ".")
                return int(v) if "." not in v else float(v)
            except ValueError:
                return v  # fallback si no puede convertir
        return v  # cualquier otro tipo se devuelve tal cual

    # Aplicamos la función al pd.Series para transformar sus valores
    return col.apply(value_converter)


# Mapeo de meses en español a números
MESES_ES = {
    "ene": "01", "enero": "01",
    "feb": "02", "febrero": "02",
    "mar": "03", "marzo": "03",
    "abr": "04", "abril": "04",
    "may": "05", "mayo": "05",
    "jun": "06", "junio": "06",
    "jul": "07", "julio": "07",
    "ago": "08", "agosto": "08",
    "sep": "09", "sept": "09", "septiembre": "09",
    "oct": "10", "octubre": "10",
    "nov": "11", "noviembre": "11",
    "dic": "12", "diciembre": "12"
}


def parse_fecha(fecha_raw: str | int | float | None) -> date | None:
    """
    Intenta convertir un valor (numérico o cadena) en un objeto datetime.date
    que representa la fecha. Devuelve None si el valor no es convertible o es nulo.
    """

    # si el objeto pasado es nulo o ausente, devolvemos None
    if pd.isna(fecha_raw):
        return None

    # normalizamos a cadena de texto el valor de 'fecha_raw'
    fecha_str = str(fecha_raw).strip().lower()

    # reemplazamos meses en español por su número
    # Ejemplo: "12 mar 2024" -> "12/03/2024"
    for mes_txt, mes_num in MESES_ES.items(): # Para casos con signos delimitadores
        for delimitador in ["/", "-", "."]:
            patron = f"{delimitador}{mes_txt}{delimitador}"
            if patron in fecha_str:
                fecha_str = fecha_str.replace(patron, f"{delimitador}{mes_num}{delimitador}")
                break

        patron_texto = f" de {mes_txt} de " # Para casos con "de"
        if patron_texto in fecha_str:
            fecha_str = fecha_str.replace(patron_texto, f"/{mes_num}/")
            break

        #  Para casos con mes en texto
        if f" {mes_txt} " in fecha_str:
            fecha_str = fecha_str.replace(f" {mes_txt} ", f"/{mes_num}/")
            break

    # intentamos con varios formatos
    formatos = [
        "%Y-%m-%d",  # 2024-12-31
        "%d/%m/%y",  # 31/12/24
        "%Y/%m/%d",  # 2024/12/31
        "%Y.%m.%d",  # 2024.12.31
        "%Y-%m-%d %H:%M:%S",  # 2024-12-31 15:42:00
        "%d/%m/%Y %H:%M:%S", # 31/12/2024 15:42:00
        "%d/%m/%Y",  # 31/12/2024
        "%d-%m-%Y",  # 31-12-2024
        "%d.%m.%Y",  # 31.12.2024

        "%d-%m-%y",  # 31-12-24
        "%d.%m.%y",  # 31.12.24
        "%d %m %Y",  # 31 12 2024
        "%d %m %y",  # 31 12 24
        "%m/%d/%Y",  # 12/31/2024
    ]

    # intentamos convertir por los formatos posibles, si no hay error ValueError, devolvemos el objeto datetime.date,
    # y si no pasamos a probar con el siguiente formato
    for fmt in formatos:
        try:
            return datetime.strptime(fecha_str, fmt).date()  # devuelve el objeto datetime.date
        except ValueError:
            continue  # si no coincide el formato, probamos con el siguiente formato

    # fallback formato ISO
    try:
        return datetime.fromisoformat(fecha_str).date()
    except Exception:
        return None

    return None  # si no se consiguió formar el objeto datetime.date, devuelve None


def parse_age(edad: int | float | str | None) -> float | None:
    """
    Intenta convertir un valor (numérico o cadena) en un número decimal (float)
    que representa la edad. Devuelve None si el valor no es convertible o es nulo.
    """
    try:
        # si es nulo
        if pd.isna(edad):
            return None
        # si ya es numérico, devolver como float
        if isinstance(edad, numbers.Number):
            return float(edad)
        # si es una cadena: normalizar y convertir a número
        edad = str(edad).replace(",", ".").strip()
        return float(edad)  # devuelve el float

    # si hay algún error en la conversión, devuelve None
    except (ValueError, TypeError):
        return None


def search_value_in_columns(row: pandas.Series, alias: list[str]) -> tuple[str | None, str | None]:
    """Busca en las columnas de un DataFrame el primer valor no vacío que coincida
    con alguno de los alias de AntibioticoHospital normalizados para extraer su columna de interpretación."""
    for nombre in alias:
        for col in row.index:
            # normalizamos los nombres de columnas
            if normalize_text(col) == nombre:
                valor = row[col]
                # si el valor no es nulo ni cadena vacía, devolvemos la tupla de cadenas (columna, valor)
                if pd.notna(valor) and str(valor).strip() != "":
                    return col, str(valor).strip()
    return None, None  # si no se encuentra coincidencia entre los alias, se devuelve la tupla (None, None)


def search_mic_in_columns(row: pandas.Series, alias: list[str]) -> tuple[str | None, str | None]:
    """Busca en las columnas de un DataFrame el primer valor no vacío que coincida
    con alguno de los alias de AntibioticoHospital normalizados para extraer su columna de CMI.

    Se aceptan nombres de columna 'Antibiotico CMI', 'Antibiotico-CMI', 'Antibiotico_CMI'.
    """
    for nombre in alias:
        for col in row.index:

            # aceptaremos "Antibiotico CMI", "Antibiotico - CMI" y "Antibiotico_CMI"
            col_normalizada = normalize_text(col).replace("-", "").replace("_", "")
            if col_normalizada.endswith("cmi"):  # detectamos la columna por sufijo
                antibiotico = col_normalizada[:-3].strip()  # retiramos el sufijo para quedarnos con el
                # nombre del AntibioticoHospital

                # si el nombre de la columna coincide con el alias
                if antibiotico == nombre:
                    valor = row[col]
                    # si no es nulo o cadena vacía, devolvemos la tupla (columna, valor)
                    if pd.notna(valor) and str(valor).strip() != "":
                        return col, str(valor).strip()

    return None, None  # si no hay coincidencias, devolvemos tupla (None, None)


def search_halo_in_columns(row: pandas.Series, alias: list[str]) -> tuple[str | None, str | None]:
    """Busca en las columnas de un DataFrame el primer valor no vacío que coincida
    con alguno de los alias de AntibioticoHospital normalizados para extraer su columna de halo.

    Se aceptan nombres de columna 'Antibiotico MM', 'Antibiotico-MM', 'Antibiotico_MM'.
    """
    for nombre in alias:
        for col in row.index:
            # aceptaremos "Antibiotico MM", "Antibiotico - MM" y "Antibiotico_MM"
            col_normalizada = normalize_text(col).replace("-", "").replace("_", "")

            if col_normalizada.endswith("mm"):  # detectamos la columna por sufijo
                antibiotico = col_normalizada[:-2].strip()  # retiramos el sufijo para quedarnos con el
                # nombre del AntibioticoHospital

                # si el nombre de la columna coincide con el alias
                if antibiotico == nombre:
                    valor = row[col]
                    # si no es nulo o cadena vacía, devolvemos la tupla (columna, valor)
                    if pd.notna(valor) and str(valor).strip() != "":
                        return col, str(valor).strip()

    return None, None  # si no encontramos la columna, devuelve tupla (None, None)


def parse_mic(valor: str) -> float | None:
    """ Toma el valor en cadena de una CMI para traducirlo en un valor float
    Existen 3 posibilidades:
    - Un antibiótico combinado (por ejemplo: cotrimoxazol o amoxicilina-clavulánico) ha sido guardado en Excel
     como una fecha (4/79 -> abr-79 -> 27851). En este caso hay que localizar el error y devolver la CMI original.
    - Es un número en una cadena de texto. Solo hay que transformarlo a float.
    - Es una composición de un número en cadena de texto. Por ejemplo, con antibióticos combinados hay un signo '/',
     o puede haber signos de mayor, meno o igual (<, ≤, ≥, >, =). Habrá que limpiar la cadena para devolver el valor
     float de la CMI"""

    # limpiamos y normalizamos
    valor_str = valor.strip().replace(",", ".")

    # Probamos con un valor numérico
    try:
        valor_float = float(valor_str)
    except ValueError:
        # No es un número -> seguimos con parseo textual (por ejemplo "<=1")
        pass
    else:
        # Es un número, comprobamos si podría ser una fecha
        fecha_base = datetime(1899, 12, 30)
        posible_fecha = fecha_base + timedelta(days=int(valor_float))

        if 1950 <= posible_fecha.year <= 1980:  # si está entre estas fechas puede ser un error de Excel
            # Ojo! Posible error de Excel: era algo como "4/79"
            return float(posible_fecha.month)  # devuelve el mes que es el que contiene la CMI
        if valor_float > 1024:  # valor exageradamente elevado para CMI
            return None
        return valor_float  # si es menor de 1024, devuelve el valor

    # No es fecha, ni valor numérico en sí mismo: procesamos cadena de texto

    # if not valor_str:
    #    return None

    # eliminamos un posible signo "=" inicial
    if valor_str.startswith("="):
        valor_str = valor_str[1:].strip()  # desechamos el "="

    # pasamos a notación con 1 char:
    valor_str = valor_str.replace("<=", "≤").replace(">=", "≥")

    # intentar si es sólo el número
    try:
        return float(valor_str)
    except ValueError:
        pass

    # para casos sensibles
    if valor_str.startswith("<") or valor_str.startswith("≤"):
        try:
            num_part = valor_str[1:].strip()  # extraemos la parte numérica
            # para antibióticos compuestos, que incorporan "/" como sígno de separación
            if "/" in num_part:
                num_part = num_part.split("/")[0].strip()  # nos quedamos con el "numerador" para devolverlo
            return float(num_part)
        except ValueError:
            return None  # si hay error, devuelve None

    # para casos resistentes
    if valor_str.startswith(">") or valor_str.startswith("≥"):
        try:
            num_part = valor_str[1:].strip()  # extraemos la parte numérica
            if "/" in num_part:  # para antibióticos compuestos
                num_part = num_part.split("/")[0].strip()
            return float(num_part) * 2  # Habitualmente no hay ≥, solo >. Esto quiere decir que está por encima, pero no
            # se conoce la CMI real. Le asignaremos el doble de la dilución que tiene marcada
            # finalmente (son diluciones seriadas en base 2)
        except ValueError:
            return None  # si hay error, devuelve None

    # para casos con un resultado de antibiótico combinado no extremo
    if "/" in valor_str:
        try:
            return float(valor_str.split("/")[0].strip())  # devolvemos el "numerador"
        except ValueError:  # si hay error devuelve None
            return None

    return None  # si no hay otra forma de parsearlo devolver None


def parse_halo(valor: str) -> float | None:
    """ Toma el valor en cadena de un halo en milímetros para traducirlo en un valor float
    Existen 2 posibilidades
    - Es un número en una cadena de texto. Solo hay que transformarlo a float.
    - Es una composición de un número en cadena de texto. Por ejemplo, puede haber signos de mayor,
     meno o igual (<, ≤, ≥, >, =). Habrá que limpiar la cadena para devolver el valor float de la CMI"""

    # limpiamos y normalizamos
    valor_str = str(valor).strip().replace(",", ".")

    # eliminamos un posible "=" inicial
    if valor_str.startswith("="):
        valor_str = valor_str[1:].strip()

    # pasamos a notación con 1 char:
    valor_str = valor_str.replace("<=", "≤").replace(">=", "≥")

    # intentamos de forma directa por si es un número en una cadena
    try:
        return float(valor_str)
    except ValueError:
        pass

    # para casos sensibles
    if valor_str.startswith("<") or valor_str.startswith("≤"):
        try:
            num_part = valor_str[1:].strip()  # extraemos la parte numérica
            return float(num_part)
        except ValueError:
            return None  # si hay error, devuelve None

    # para casos resistentes
    if valor_str.startswith(">") or valor_str.startswith("≥"):
        try:
            num_part = valor_str[1:].strip()  # extraemos la parte numérica
            return float(num_part)
        except ValueError:
            return None  # si hay error, devuelve None

    return None  # si no hay otra forma de parsearlo devolver None


def detect_arm(row: pandas.Series, mapping: dict, mecanismos: list[MecanismoResistenciaHospital],
               subtipos: list[SubtipoMecanismoResistenciaHospital], pos_vals: list[MecResValoresPositivosHospital]) \
        -> tuple[set[MecanismoResistenciaHospital], set[SubtipoMecanismoResistenciaHospital]]:
    """Infiere si existe algún mecanismo o subtipo de mecanismo de resistencia en base a:
    - Columnas específicas del DataFrame
    - Columna de Observaciones / Comentarios
    Devuelve una tupla con dos sets:
    - mecanismos_detectados: conjunto de objetos MecanismoResistenciaHospital detectados
    - subtipos_detectados: conjunto de objetos de MecResValoresPositivosHospital detectados
    """
    # Inicializamos sets de almacenamiento
    mecanismos_detectados = set()
    subtipos_detectados = set()

    pos_vals = [normalize_text(a) for obj in pos_vals for a in obj.alias]  # obtenemos la lista de alias de valores de
    # mecanismo detectado

    # diccionario auxiliar para vincular id de mecanismo base con su objeto hospitalario
    mec_map = {m.mecanismo.id: m for m in mecanismos}

    # 1. Detección por columnas específicas
    # recorremos los objetos de MecanismoResistenciaHospital del diccionario
    for m in mecanismos:
        # creamos un set de cadenas de texto de alias con el operador |
        mecs = {normalize_text(m.mecanismo.nombre)} | {normalize_text(a) for a in m.alias}

        # recorremos por cada uno de los alias del set
        for mec in mecs:
            # recorremos las columnas de la fila
            for col in row.index:

                # si encontramos el alias en una de las columnas de la fila en cuestión
                if mec in normalize_text(col):
                    valor = normalize_text(str(row[col]))  # el valor será el de esa columna
                    print(f"Columna: {col}, valor: '{row[col]}'")  # log a consola de la columna y valor encontrados

                    if valor in pos_vals:  # si ese valor está en la lista de alias de valores de mecanismos detectados
                        mecanismos_detectados.add(m)  # Añadimos el MecanismoResistenciaHospital al set
                        print(f"✓ Mecanismo por columna: {m.mecanismo.nombre}")  # log a consola, mecanismo encontrado
                        break  # pasamos al siguiente alias
                    else:
                        # si no está entre los valores de mecanismos detectados no se incluye y se manda log a consola
                        print(f"✗ Mecanismo negativo por columna: {m.mecanismo.nombre}")

    # 2. Detección de subtipos por columnas específicas
    # Procede de forma similar a la detección de mecanismos
    for subtipo in subtipos:

        # set de cadenas de texto de alias de subtipos de mecanismo
        submecs = {normalize_text(subtipo.subtipo_mecanismo.nombre)} | {normalize_text(a) for a in subtipo.alias}

        # para cada una de las columnas de la fila en cuestión
        for col in row.index:
            col_norm = normalize_text(col)

            # si alguno de los alias de subtipo está entre los nombres de columna de la fila, incorporamos el objeto
            # SubtipoMecanismoResistenciaHospital al set de subtipos
            if any(submec in col_norm for submec in submecs):
                valor = normalize_text(str(row[col]))

                # si ese valor está en la lista de alias de valores de mecanismos detectados
                if valor in pos_vals:
                    subtipos_detectados.add(subtipo)  # Añadimos el subtipo de mecanismo al set

                    # Un subtipo siempre está ligado a un mecanismo-> añadimos el mecanismo al set si no lo está ya
                    base_mec_id = subtipo.subtipo_mecanismo.mecanismo.id  # obtenemos el id del mecanismo del subtipo
                    mec_hosp = mec_map.get(base_mec_id)  # encontramos el objeto MecanismoResitenciaHospital asociado

                    # si lo encontramos, lo añadimos al set de mecanismos con log en consola
                    if mec_hosp:
                        mecanismos_detectados.add(mec_hosp)
                    print(
                        f"✓ Subtipo por columna: {subtipo.subtipo_mecanismo.nombre} (-> {subtipo.subtipo_mecanismo.mecanismo.nombre})")

                # si el valor no está en la lista de alias de valores de mecanismos detectados -> log en consola y pasamos
                # al siguiente alias
                else:
                    print(f"✗ Subtipo negativo por columna: {subtipo.subtipo_mecanismo.nombre}")
                break

    # 3. Detección en observaciones (texto libre)
    observaciones_col = mapping.get("observaciones")

    # Si se asignó la columna de observaciones en el proceso de carga
    if observaciones_col:
        # obtenemos el texto en crudo
        texto = str(row.get(observaciones_col, ""))

        # separamos las frases por nuestra constante lista de separadores
        frases = SEPARADORES.split(texto)
        for frase in frases:  # buscamos entre las frases
            frase_norm = normalize_text(frase)  # normalizamos la frase

            # realizamos la búsqueda de mecanismos
            for m in mecanismos:
                mecs = {normalize_text(m.mecanismo.nombre)} | {normalize_text(a) for a in m.alias}

                if any(mec in frase_norm for mec in mecs):
                    # si algún tipo de negación en la frase se infiere que NO se detecta el mecanismo ->
                    # log a consola y pasamos al siguiente mecanismo
                    if any(neg in frase_norm for neg in NEGACIONES):
                        print(f"✗ Mecanismo negado: {m.mecanismo.nombre} -> {frase.strip()}")
                        continue

                    mecanismos_detectados.add(m)  # si no está en las negaciones se añade al set de mecanismos
                    print(f"✓ Mecanismo por observación: {m.mecanismo.nombre}")  # log en consola

            # realizamos la misma operación de búsqueda en subtipos de mecanismos
            for subtipo in subtipos:
                submecs = {normalize_text(subtipo.subtipo_mecanismo.nombre)} | {normalize_text(a) for a in
                                                                                subtipo.alias}
                if any(submec in frase_norm for submec in submecs):
                    if any(neg in frase_norm for neg in NEGACIONES):
                        print(f"✗ Subtipo negado: {subtipo.subtipo_mecanismo.nombre} -> {frase.strip()}")
                        continue
                    subtipos_detectados.add(subtipo)  # añadimos el mecanismo al set de subtipos de mecanismos

                    # si encontramos un subtipo -> añadimos también el mecanismo al set de mecanismos
                    base_mec_id = subtipo.subtipo_mecanismo.mecanismo_id
                    mec_hosp = mec_map.get(base_mec_id)
                    if mec_hosp:
                        mecanismos_detectados.add(mec_hosp)
                    print(
                        f"✓ Subtipo por observación: {subtipo.subtipo_mecanismo.nombre} (-> {subtipo.subtipo_mecanismo.mecanismo.nombre})")

    return mecanismos_detectados, subtipos_detectados  # devolvemos la tupla de resultados
