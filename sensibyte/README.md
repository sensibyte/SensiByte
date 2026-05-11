<p>
  <img src="static/img/logo.png" alt="SensiByte Logo" height="65">
</p>

![Python](https://img.shields.io/badge/Python-3.13-blue)
![Django](https://img.shields.io/badge/Django-5.2.8-green)
![Status](https://img.shields.io/badge/status-Master's%20Thesis-success)
![Reproducibility](https://img.shields.io/badge/reproducibility-yes-brightgreen)
![License](https://img.shields.io/badge/license-CC_BY--NC--ND_4.0-lightgrey)

SensiByte is a Django-based web application designed for the management,
analysis, and automated reporting of antimicrobial susceptibility data,
following COESANT recommendations and the CLSI M39 standard.

## Background

Antimicrobial resistance is a critical public health issue.
Cumulative antibiogram reports are an essential tool for antimicrobial
stewardship programs, although their manual generation is often time-consuming,
poorly reproducible, and dependent on proprietary laboratory information systems.

## Architecture

- Framework: Django (Model–View–Template architecture)
- Programming language: Python
- Database: SQL (synthetic data)
- Visualization: Plotly
- Reporting: PDF generation with ReportLab
- Security: authentication, authorization, and data anonymization

## Workflow

1. Import of laboratory information system data
2. Automatic anonymization of identifiers
3. Data processing according to COESANT / CLSI M39 recommendations
4. Generation of cumulative antimicrobial susceptibility reports
5. Temporal trend analysis and data visualization

## Reproducibility

This project was developed following reproducibility principles:

- Use of synthetic datasets included in the repository
- Controlled dependencies through `requirements.txt`
- Clear separation between business logic, data, and visualization layers
- Deterministic data processing
- Automated report generation from identical input data

Any user can clone the repository and reproduce the results
by following the installation steps described below.

## Ethical Considerations

- The project does not contain real clinical data
- All included datasets are synthetic
- The system architecture is designed to support compliance with
  data protection regulations in real-world environments

## Installation Notes

The repository is ready to clone. However, a `.env` file must be created
at the project root containing the following variables:

```{txt}
SECRET_KEY={your_secret_key}
DEBUG={True/False}
HASH_SALT_PRE={PRE_SALT}
HASH_SALT_POST={POST_SALT}
```

Where:

- `SECRET_KEY`: secret key string used by Django.
- `DEBUG`: boolean variable indicating DEBUG (True) or PRODUCTION (False) mode.
- `HASH_SALT_PRE`: string containing the pre-hash salt.
- `HASH_SALT_POST`: string containing the post-hash salt.

Once configured, start the development server from the directory containing manage.py:

```{sh}
python manage.py runserver
```

Done.

## License

This work is licensed under the
Creative Commons Attribution–NonCommercial–NoDerivatives 4.0 International License (CC BY-NC-ND 4.0).

© 2026 Jesús Martínez López

You may copy and redistribute the material in any medium or format
for non-commercial purposes only, provided that appropriate credit is given.
Distribution of modified versions is not permitted.