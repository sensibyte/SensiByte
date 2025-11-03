import json
import numbers
import os
from datetime import datetime, timedelta

import numpy as np
import pandas as pd


def generar_antibiogramas(config_json: dict, n_registros: int, seed=123) -> pd.DataFrame:
    """
    Generador de bases de datos artificiales de antibiogramas basado en configuraciones JSON.
    Con el parámetro 'seed' fijamos una semilla para generar siempre los mismos datos.
    Otros parámetros de la función:

    - config_json (dict): configuración con los parámetros para generar los datos.
    - n_registros (int): número de registros a generar

    Devuelve pandas.DataFrame con los antibiotramas generados
    """

    # Fijamos una semilla de aleatoriedad con numpy.random.default_rng
    rng = np.random.default_rng(seed)

    # Diccionario de configuraciones JSON
    config = config_json

    # Inicializamos un diccionario base para generar el DataFrame
    data = {}

    # 1. Generamos fechas en el rango definido en el archivo de configurarión
    fecha_config = config["fecha"]
    fecha_inicio = datetime.strptime(fecha_config["inicio"], "%Y-%m-%d")
    fecha_fin = datetime.strptime(fecha_config["fin"], "%Y-%m-%d")
    dias_diferencia = (fecha_fin - fecha_inicio).days  # dias de diferencia entre las fechas

    # generamos periodos aleatorios de días (como enteros) en ese rango
    dias_random = rng.integers(0, dias_diferencia, size=n_registros, endpoint=True)  #
    # Pasamos el argumento endpoint=True para que lo incluya. Ref: https://numpy.org/doc/stable/reference/random/generator.html

    # ahora que tenemos esos periodos aleatorios se los sumamos a la fecha de inicio para
    # obtener las fechas en representación str
    fechas = [fecha_inicio + timedelta(days=int(d)) for d in
              dias_random]  # hay que pasar d a entero, es un np.int64 cuando llega

    # lo pasamos al diccionario con clave "Fecha"
    data["Fecha"] = [f.strftime("%Y-%m-%d") for f in fechas]

    # 2. Generamos números de historia (con duplicados controlados, definidos en el archivo)
    nh_config = config["n_historia"]
    nh_min = nh_config["min"]
    nh_max = nh_config["max"]
    duplicados = nh_config.get("duplicados", 0)  # tomamos el valor de duplicados de config

    # Generamos números únicos en base a la cantidad de registros, sin contar los duplicados
    numeros_unicos = n_registros - duplicados

    # Escogemos al azar los números de historia en el rango de estos números únicos
    historias_base = rng.integers(nh_min, nh_max + 1, size=numeros_unicos).tolist()

    # Escogemos los duplicados seleccionando aleatoriamente entre los existentes
    historias_duplicadas = rng.choice(historias_base, size=duplicados, replace=True).tolist()

    historias_base.extend(historias_duplicadas)  # añadimos los duplicados

    # Mezclamos para distribuir los duplicados aleatoriamente
    rng.shuffle(historias_base)

    # Lo pasamos al diccionario con clave "Historia"
    data["Historia"] = historias_base

    # 3. Generamos edades con distribución Weibull
    params = config["edad"]["parametros"]

    c = params["shape"]  # parámetro shape
    scale = params["scale"]  # paraámetro scale

    # distribución Weibull: https://numpy.org/doc/stable/reference/random/generator.html
    edades = scale * rng.weibull(c, size=n_registros)

    # redondeamos y limitamos a valores en rango 0-120 con np.clip
    # ref: https://numpy.org/doc/2.3/reference/generated/numpy.clip.html
    edades = np.clip(np.round(edades), 0, 120).astype(int)

    # Lo pasamos al diccionario con clave "Edad"
    data["Edad"] = edades

    # 4. Generamos la columna de los microorganismos (en el archivo JSON microorganismo)
    microorganismo = config["microorganismo"]
    categorias_micro = microorganismo["categorias"]
    porcentajes_micro = microorganismo["porcentajes"]

    # normalizamos los porcentajes (por si no lo están al pasarlo)
    total_micro = sum(porcentajes_micro)
    porcentajes_norm_micro = [p / total_micro for p in porcentajes_micro]

    # elegiomos al azar entre las categorías del microorganismo teniendo en cuenta
    # sus porcentajes con np.random.choice(lista, size=n_registros, p=porcentajes_norm_micro)
    # y se lo pasamos al diccionario en la clave "Gérmen"
    data["Gérmen"] = rng.choice(
        categorias_micro,
        size=n_registros,
        p=porcentajes_norm_micro
    )

    # 5. Generamos el resto de factores epidemiológicos (Sexo, Ámbito, Servicio, Muestra...)
    for campo, campo_config in config.items():
        if campo not in ["fecha", "n_historia", "edad", "microorganismo", "antibioticos"] and isinstance(campo_config,
                                                                                                         dict):
            # todos estos campos llevan claves de categorías y porcentajes
            categorias = campo_config["categorias"]
            porcentajes = campo_config["porcentajes"]

            # normalizamos sus porcentajes
            total = sum(porcentajes)
            porcentajes_norm = [p / total for p in porcentajes]

            # elegimos entre las categorías al azar siguiendo sus porcentajes
            data[campo] = rng.choice(
                categorias,
                size=n_registros,
                p=porcentajes_norm
            )

    # 6. Generamos los antibióticos con alias y CMI.
    antibioticos_config = config["antibioticos"]

    # Inicializamos todas las columnas como None
    for antibiotico_info in antibioticos_config:
        nombres = antibiotico_info["nombres"]
        # Creamos 2 columnas: una con el nombre pasado y otra con el "nombre_CMI"
        # La función de carga aceptará formatos "nombre CMI", "nombre - CMI" y "nombre_CMI"
        # para extraer el valor numérico de CMI
        for nombre in nombres:
            data[nombre] = [None] * n_registros
            data[f"{nombre}_CMI"] = [None] * n_registros

    # Asignación de valores por registro
    for idx in range(n_registros):
        for antibiotico_info in antibioticos_config:
            nombres = antibiotico_info["nombres"]
            probs = antibiotico_info["probabilidades"]

            # normalizamos las probabilidades
            total_prob = sum(probs.values())
            # diccionario de probabilidades normalizadas
            probs_norm = {k: v / total_prob for k, v in probs.items()}

            # decidimos la categoría al azar
            categorias_posibles = list(probs_norm.keys())
            probabilidades = list(probs_norm.values())
            categoria = rng.choice(categorias_posibles, p=probabilidades)

            # elegimos aleatoriamente uno de los sinónimos del antibiótico
            nombre_elegido = rng.choice(nombres)

            # si la categoría es 'blanco', asignamos string vacío
            if categoria in ["blanco", ]:
                data[nombre_elegido][idx] = ""
            else:
                # si la categoría no es 'blanco' le asignamos el string asociado a la categoría
                data[nombre_elegido][idx] = categoria

            # generamos la CMI según la categoría
            if "valores_cmi" in antibiotico_info and categoria in antibiotico_info["valores_cmi"]:
                cmi_info = antibiotico_info["valores_cmi"][categoria]
                valores = cmi_info["valores"]
                probs_cmi = cmi_info["probabilidades"]

                # normalizamos las probabilidades de resultado CMI
                total_cmi = sum(probs_cmi)
                probs_cmi_norm = [p / total_cmi for p in probs_cmi]

                # elegimos al azar los valores, según probabilidades normalizadas
                valor_cmi = rng.choice(valores, p=probs_cmi_norm)

                # creamos la columna "_CMI" con esos valores en el diccionario
                data[f"{nombre_elegido}_CMI"][idx] = valor_cmi

    # Crea el DataFrame a partir del diccionario data
    df = pd.DataFrame(data)
    # Ordenamos los registros por fecha
    df.sort_values("Fecha", inplace=True)

    # Intentamos convertir columnas de CMI a numéricas, si es posible
    for col in df.columns:
        if col.endswith("_CMI"):  # si la columna acaba en _CMI contiene esos valores
            df[col] = df[col].apply(  # aplicamos una función anónima
                lambda v: (
                    v if pd.isna(v)  # si el valor es nulo, no hacemos nada
                    else v if isinstance(v, numbers.Number)  # si es numérico, no hacemos nada, ya es numérico
                    else ( # si no es nulo ni numérico será cadena de texto
                        v.strip() # devolvemos la cadena de texto con espacios recortados
                        # si esa cadena recortada es una cadena vacía o contiene algún símbolo mayor, menor o igual
                        if (v.strip() == "" or any(s in v for s in ["/", ">", "<", "=", "≥", "≤"]))
                        # y si no se cumple esa condición se devuelve un entero o un float dependiendo de cómo esté
                        # formateada la cadena de texto para el numérico
                        else (
                            int(v.strip()) if "." not in v.strip() else float(v.strip())
                        )
                    )
                )
            )

    # Fechas en formato cadena de texto para pasárselo al nombre del archivo generado
    fecha_inicio_str = fecha_inicio.strftime("%Y-%m-%d")
    fecha_fin_str = fecha_fin.strftime("%Y-%m-%d")

    # Guardamos los archivos Excel y CSV
    csv_filename = f"{df["Gérmen"].iloc[0]} - {fecha_inicio_str} a {fecha_fin_str}.csv"
    df.to_csv(f"datos sinteticos/{csv_filename}", index=False, encoding='latin-1')
    print(f"Archivo CSV guardado: {csv_filename}")

    excel_filename = f"{df["Gérmen"].iloc[0]} - {fecha_inicio_str} a {fecha_fin_str}.xlsx"
    df.to_excel(f"datos sinteticos/{excel_filename}", index=False, engine='openpyxl')
    print(f"Archivo Excel guardado: {excel_filename}")

    return df


# Generamos los archivos con datos sintéticos para la base de datos
configs_path = "datos sinteticos/configs/"

# Iteramos por cada especie
for especie in os.listdir(configs_path):
    especie_path = os.path.join(configs_path, especie)

    # listdir nos devuelve tanto archivos como directorios, pero sólo queremos los directorios
    if not os.path.isdir(especie_path):
        continue  # ignoramos archivos sueltos, solo directorios

    # recorremos los años dentro de la especie
    for year in os.listdir(especie_path):
        # directorio del año
        year_path = os.path.join(especie_path, year)

        # nos quedamos sólo con los directorios
        if not os.path.isdir(year_path):
            continue

        # inicializamos variables
        config_json = None

        # buscamos el archivo JSON dentro de la carpeta del año
        for archivo in os.listdir(year_path):
            archivo_path = os.path.join(year_path, archivo)
            if archivo.lower().endswith("config.json"):
                with open(archivo_path, "r", encoding="utf-8") as f:
                    config_json = json.load(f)

        # validamos que el archivo de configuración exista
        if config_json is None:
            print(f"Faltan archivos en {year_path}, se omite.")
            continue

        generar_antibiogramas(config_json, n_registros=850)
