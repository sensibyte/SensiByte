<p>
  <img src="static/img/logo_sensibyte_red.png" alt="Logo SensiByte" width="120">
</p>

# SensiByte
![Python](https://img.shields.io/badge/Python-3.13-blue)
![Django](https://img.shields.io/badge/Django-5.2.8-green)
![Status](https://img.shields.io/badge/status-TFM-success)
![Reproducibility](https://img.shields.io/badge/reproducibility-yes-brightgreen)
![License](https://img.shields.io/badge/license-CC%20BY--NC--ND%203.0-lightgrey)


SensiByte es una aplicación web desarrollada en Django para la gestión,
análisis y generación automática de informes de sensibilidad antimicrobiana,
alineada con las recomendaciones del COESANT y el estándar CLSI M39.

## Contexto

La resistencia antimicrobiana es un problema crítico de salud pública.
Los informes de antibiograma acumulado son una herramienta esencial
para los programas PROA, pero su elaboración manual es costosa,
poco reproducible y dependiente de herramientas cerradas de los SIL.

## Arquitectura

- Framework: Django (Modelo–Vista–Template)
- Lenguaje: Python
- Base de datos: SQL (datos sintéticos)
- Visualización: Plotly
- Informes: PDF (ReportLab)
- Seguridad: autenticación, permisos y anonimización

## Flujo de trabajo

1. Importación de datos desde el SIL
2. Anonimización automática de identificadores
3. Procesamiento según recomendaciones COESANT / CLSI M39
4. Generación de informes de sensibilidad acumulada
5. Análisis temporal y visualización de tendencias

## Reproducibilidad

Este proyecto ha sido diseñado siguiendo principios de reproducibilidad:

- Uso de datos sintéticos incluidos en el repositorio
- Dependencias controladas mediante `requirements.txt`
- Separación clara entre lógica de negocio, datos y visualización
- Procesamiento determinista de los datos
- Generación automática de informes a partir de los mismos inputs

Cualquier usuario puede clonar el repositorio y reproducir los resultados
siguiendo los pasos de instalación descritos.

## Consideraciones éticas

- El proyecto no contiene datos clínicos reales
- Los datos utilizados son sintéticos
- La arquitectura está preparada para cumplir con normativas
  de protección de datos en entornos reales

## Notas de instalación

El repositorio está listo para clonar. Sin embargo, ha de crearse un archivo `.env`
en la raíz del sistema con la siguiente información:

```{txt}
SECRET_KEY={Tu clave secreta}
DEBUG={True/False}
HASH_SALT_PRE={SALT PRE}
HASH_SALT_POST={SALT POST}
```
donde:

- `SECRET_KEY`: es una cadena de texto con la clave secreta.
- `DEBUG`: es una variable `boolean` que determina si accedemos en modo DEBUG (`True`) o PRODUCCIÓN (`False`).
- `HASH_SALT_PRE`: es una cadena de texto con la SALT PRE
- `HASH_SALT_POST`: es una cadena de texto con la SALT POST

Una vez configurado, desde la carpeta con `manage.py` iniciamos el servidor:

```{sh}
python manage.py runserver
```
Listo

## Licencia

Esta obra está sujeta a una licencia de  
**Reconocimiento–NoComercial–SinObraDerivada 3.0 España (CC BY-NC-ND 3.0 ES)**  
de Creative Commons.

© Jesús Martínez López

Reservados todos los derechos.  
Queda prohibida la reproducción total o parcial de esta obra por cualquier
medio o procedimiento, comprendidos la impresión, la reprografía, el microfilme,
el tratamiento informático o cualquier otro sistema, así como la distribución de
ejemplares mediante alquiler o préstamo, sin la autorización escrita del autor o
dentro de los límites que autorice la Ley de Propiedad Intelectual.