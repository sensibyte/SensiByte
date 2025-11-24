import base64
import io
from datetime import date
from dateutil.relativedelta import relativedelta

import numpy as np
import pandas as pd

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from statsmodels.graphics.tsaplots import plot_acf


def smape(y_true: pd.Series, y_pred:pd.Series)-> float:
    """
    Calcula Symmetric Mean Absolute Percentage Error (SMAPE).
    Métrica más robusta que MAPE para comparar modelos.

    SMAPE = 100 * |y_true - y_pred| / ((|y_true| + |y_pred|) / 2)

    Ventajas:
    - Simétrico (trata igual sobre/subestimaciones)
    - Acotado PORCENTUALMENTE entre 0% y 200%
    - Maneja mejor valores cercanos a cero que MAPE
    """
    # Convertir siempre a arrays 1D
    y_true = np.atleast_1d(y_true).astype(float)
    y_pred = np.atleast_1d(y_pred).astype(float)

    numerador = np.abs(y_true - y_pred)
    denominador = (np.abs(y_true) + np.abs(y_pred)) / 2

    # máscara de ceros (si ambos, y_true y_pred, son 0, el denominador es 0)
    mask = denominador == 0

    # Evitar dividir por cero -> cambiamos a 0/1 = 0
    denominador = np.where(mask, 1, denominador)
    numerador = np.where(mask, 0, numerador)

    smape = 100 * (numerador / denominador)

    # devolver promedio del vector
    return float(np.mean(smape))


def adaptative_config_gam(n_obs: int) -> tuple[int, int]:
    """
    Calcula n_splines y spline_order óptimos según el número de observaciones
    para un modelo GAM. Garantiza que siempre n_splines > spline_order
    """
    if n_obs <= 6:
        spline_order = 2  # Cuadrático
        n_splines = max(3, min(n_obs - 1, 5))
    elif n_obs <= 10:
        spline_order = 2  # Cuadrático
        n_splines = min(n_obs, 6)
    else:
        spline_order = 3  # Cúbico
        n_splines = min(n_obs, 10)

    # Verificación de seguridad
    if n_splines <= spline_order:
        n_splines = spline_order + 1

    return n_splines, spline_order


def fig_to_base64(fig:plt.Figure) -> str:
    """Convierte figura matplotlib a una cadena Base64 para pasarla a la UI
    y visualizar así los gráficos generados.
    """
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", dpi=100)
    plt.close(fig)
    buf.seek(0)
    return base64.b64encode(buf.read()).decode() # lee los bytes del PNG y conviértelos en cadena de texto


def calculate_y_axe_limits(valores_observados:list[float], valor_prediccion:float|None=None):
    """Calcula límites para el eje Y."""
    todos_valores = list(valores_observados)
    if valor_prediccion is not None:
        todos_valores.append(valor_prediccion)

    min_val = min(todos_valores)
    max_val = max(todos_valores)
    rango = max_val - min_val

    if rango < 5:
        margen = 5
    else:
        margen = max(3.0, rango * 0.15)

    y_min = max(0.0, min_val - margen)
    y_max = min(100.0, max_val + margen)

    y_min = (y_min // 5) * 5
    y_max = ((y_max // 5) + 1) * 5

    if y_max - y_min < 10:
        centro = (y_max + y_min) / 2
        y_min = max(0.0, centro - 5)
        y_max = min(100.0, centro + 5)

    return y_min, y_max


def calculate_next_period_label(fecha_fin_ultimo_periodo:date, agrupacion:str):
    """Calcula el label del siguiente periodo."""
    if agrupacion == "trimestre":
        nueva_fecha = fecha_fin_ultimo_periodo + relativedelta(months=3)
        trimestre = ((nueva_fecha.month - 1) // 3) + 1
        return f"Q{trimestre} {nueva_fecha.year}"
    elif agrupacion == "semestre":
        nueva_fecha = fecha_fin_ultimo_periodo + relativedelta(months=6)
        semestre = 1 if nueva_fecha.month <= 6 else 2
        return f"S{semestre} {nueva_fecha.year}"
    else:
        nueva_fecha = fecha_fin_ultimo_periodo + relativedelta(years=1)
        return str(nueva_fecha.year)

def build_acf_plot(residuals_gam: pd.Series, n:int, title:str=""):
    fig, ax = plt.subplots(figsize=(6, 4))
    plot_acf(residuals_gam, lags=min(20, n//2), ax=ax, zero=False)
    ax.set_title(title)
    fig.tight_layout()
    return fig_to_base64(fig)


def build_linear_regression_plot(df: pd.DataFrame, y_pred: np.ndarray,
                                 pred_siguiente: float,
                                 X_extended: np.ndarray,
                                 pred_lower: np.ndarray,
                                 pred_upper: np.ndarray,
                                 agrupacion: str, titulo:str, ylabel:str) -> str:
    """Genera gráfico de regresión lineal."""
    fig, ax = plt.subplots(figsize=(12, 7))

    todos_valores = df["porcentaje_si"].to_list()
    if pred_lower is not None and pred_upper is not None:
        todos_valores.extend([pred_lower[-1], pred_upper[-1]])
    else:
        todos_valores.append(pred_siguiente)

    y_min, y_max = calculate_y_axe_limits(todos_valores, pred_siguiente)

    ultimo_periodo = df["periodo_num"].max()
    periodo_pred = ultimo_periodo + 1

    mask_historico = X_extended.flatten() <= ultimo_periodo
    mask_proyeccion = X_extended.flatten() >= ultimo_periodo

    # Línea histórica (línea sólida)
    ax.plot(df["periodo_num"], y_pred,
            color="#dc2626", linewidth=3, label="Regresión lineal",
            zorder=2, linestyle="-", alpha=0.8)

    ax.fill_between(X_extended.flatten()[mask_historico],
                    pred_lower[mask_historico],
                    pred_upper[mask_historico],
                    alpha=0.25, color="#dc2626",
                    label="Intervalo de predicción 95%",
                    zorder=1)

    # Datos observados
    ax.scatter(df["periodo_num"], df["porcentaje_si"],
               color="#2563eb", s=120, label="Datos observados",
               zorder=3, edgecolors="white", linewidths=2)

    # Predicción
    ax.scatter([periodo_pred], [pred_siguiente],
               color="#16a34a", marker="*", s=400, label="Predicción",
               zorder=4, edgecolors="white", linewidths=2)

    # Proyección de la predicción (línea punteada)
    ax.plot([df["periodo_num"].max(), periodo_pred],
            [y_pred[-1], pred_siguiente],
            color="#dc2626", linewidth=3, linestyle="--", alpha=0.5)

    ax.fill_between(X_extended.flatten()[mask_proyeccion],
                    pred_lower[mask_proyeccion],
                    pred_upper[mask_proyeccion],
                    alpha=0.10, color="#dc2626",
                    zorder=1)

    ax.set_title(titulo, fontsize=16, fontweight="bold", pad=20)
    ax.set_xlabel("Periodo", fontsize=13, fontweight="bold")
    ax.set_ylabel(ylabel, fontsize=13, fontweight="bold")
    ax.set_ylim(y_min, y_max)
    ax.grid(True, alpha=0.2, linestyle="--")
    ax.legend(loc="best", fontsize=11, framealpha=0.9)

    # Etiquetas del eje X
    label_prediccion = calculate_next_period_label(df["fin"].iloc[-1], agrupacion)
    posiciones = list(df["periodo_num"]) + [periodo_pred]
    labels = list(df["periodo_label"]) + [label_prediccion]
    ax.set_xticks(posiciones)
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=10)

    # Etiqueta de predicción
    offset_texto = (y_max - y_min) * 0.03
    ax.text(periodo_pred, pred_siguiente + offset_texto,
            f"{pred_siguiente:.1f}%",
            ha="center", va="bottom" if pred_siguiente > y_min + 10 else "top", fontsize=11, fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.5", facecolor="#16a34a", alpha=0.7, edgecolor="white"))

    plt.tight_layout()
    return fig_to_base64(fig)


def build_gam_plot(df: pd.DataFrame, x_smooth: np.ndarray,
                   y_smooth: np.ndarray, periodo_siguiente: float,
                   pred_siguiente: float,
                   lower_pred, upper_pred,
                   agrupacion: str,
                   titulo: str = None, ylabel: str = None) -> str:
    """Genera gráfico GAM."""
    fig, ax = plt.subplots(figsize=(12, 7))

    todos_valores = df["porcentaje_si"].to_list() + list(y_smooth)
    todos_valores.extend([lower_pred[-1], upper_pred[-1]])

    y_min, y_max = calculate_y_axe_limits(todos_valores, pred_siguiente)

    # Separar curva histórica y proyección
    mask_historico = x_smooth <= df["periodo_num"].max()
    mask_proyeccion = x_smooth >= df["periodo_num"].max()

    # Curva GAM histórica (línea sólida)
    ax.plot(x_smooth[mask_historico], y_smooth[mask_historico],
            color="#7c3aed", linewidth=3, label="GAM (ajuste histórico)",
            zorder=2, alpha=0.9, linestyle="-")

    ax.fill_between(x_smooth[mask_historico],
                    lower_pred[mask_historico],
                    upper_pred[mask_historico],
                    label="Intervalo de predicción 95%",
                    alpha=0.25, color="#7c3aed")

    # Proyección GAM (línea punteada)
    ax.plot(x_smooth[mask_proyeccion], y_smooth[mask_proyeccion],
            color="#7c3aed", linewidth=3,
            zorder=2, alpha=0.7, linestyle="--")

    ax.fill_between(x_smooth[mask_proyeccion],
                    lower_pred[mask_proyeccion],
                    upper_pred[mask_proyeccion],
                    alpha=0.10, color="#7c3aed")

    # Datos observados
    ax.scatter(df["periodo_num"], df["porcentaje_si"],
               color="#2563eb", s=120, label="Datos observados",
               zorder=3, edgecolors="white", linewidths=2)

    # Predicción futura (donde termina la curva GAM)
    ax.scatter([periodo_siguiente], [pred_siguiente],
               color="#16a34a", marker="*", s=400, label="Predicción GAM",
               zorder=4, edgecolors="white", linewidths=2)

    ax.set_title(titulo,
                 fontsize=16, fontweight="bold", pad=20)
    ax.set_xlabel("Periodo", fontsize=13, fontweight="bold")
    ax.set_ylabel(ylabel, fontsize=13, fontweight="bold")
    ax.set_ylim(y_min, y_max)
    ax.grid(True, alpha=0.2, linestyle="--")
    ax.legend(loc="best", fontsize=11, framealpha=0.9)

    # Etiquetas del eje X
    label_prediccion = calculate_next_period_label(df["fin"].iloc[-1], agrupacion)
    posiciones = list(df["periodo_num"]) + [periodo_siguiente]
    labels = list(df["periodo_label"]) + [label_prediccion]
    ax.set_xticks(posiciones)
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=10)

    # Etiqueta de predicción
    offset_texto = (y_max - y_min) * 0.03
    ax.text(periodo_siguiente, pred_siguiente + offset_texto,
            f"{pred_siguiente:.1f}%",
            ha="center", va="bottom", fontsize=11, fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.5", facecolor="#16a34a",
                      alpha=0.7, edgecolor="white"))

    plt.tight_layout()
    return fig_to_base64(fig)
