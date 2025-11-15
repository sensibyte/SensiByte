import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from plotly.offline import plot
from plotly.subplots import make_subplots
from statsmodels.stats.proportion import proportion_confint
from statsmodels.stats.contingency_tables import Table2x2
from scipy.stats import fisher_exact

def calculate_ic95(x: int | np.ndarray, n: int | np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """
    Función que devuelve intervalos de confianza para %S usando:
    - Clopper-Pearson si n <= 30
    - Agresti-Coull si n > 30
    Vectorizada para arrays de x y n.
    """

    # pasamos los inputs a arrays float (si no se trunca el resultado)
    x = np.asarray(x, dtype=float)
    n = np.asarray(n, dtype=float)

    # inicializamos arrays de salida
    lower = np.zeros_like(x)
    upper = np.zeros_like(x)

    # máscaras para los dos métodos, dependiendo del tamaño de muestra
    mask_cp = n <= 30
    mask_ac = n > 30

    # Método exacto de Clopper-Pearson (beta)
    if np.any(mask_cp):
        low, up = proportion_confint(x[mask_cp], n[mask_cp],
                                     alpha=0.05, method="beta")
        lower[mask_cp], upper[mask_cp] = low, up

    # Método aproximado de Agresti-Coull
    if np.any(mask_ac):
        low, up = proportion_confint(x[mask_ac], n[mask_ac],
                                     alpha=0.05, method="agresti_coull")
        lower[mask_ac], upper[mask_ac] = low, up

    # Asigna 0 si no hay muestras
    lower[n == 0] = 0
    upper[n == 0] = 0

    return lower, upper


# Para los gráficos utilizaremos la librería Plotly.
# Existe mucha información en Internet sobre cómo utilizar esta librería. Entre otras fuentes, destacamos por su uso
# en el desarrollo de esta aplicación:
# https://plotly.com/python/creating-and-updating-figures/
# https://plotly.com/python/pie-charts/
# https://plotly.com/python/subplots/
# https://plotly.com/python/histograms/
# https://medium.com/@sawsanyusuf/data-visualization-with-python-11-plotly-express-59503cab2445
# https://medium.com/@drpa/plotly-data-visualization-comprehensive-guide-3fd7a0aeb85b
def build_antibiotics_bar_chart(antibioticos: list[str],
                                 porcentaje_s: list[float],
                                 porcentaje_i: list[float],
                                 porcentaje_r: list[float]) -> str:
    """
    Genera un gráfico de barras apiladas con la distribución de sensibilidad (S/I/R) por antibiótico.
    Devuelve HTML del gráfico Plotly listo para insertar en el template.

    """
    # Crear figura base
    fig = go.Figure()

    # Barras apiladas S / I / R
    fig.add_trace(go.Bar(name="S", x=antibioticos, y=porcentaje_s, marker_color="#2ca02c"))
    fig.add_trace(go.Bar(name="I", x=antibioticos, y=porcentaje_i, marker_color="#ff7f0e"))
    fig.add_trace(go.Bar(name="R", x=antibioticos, y=porcentaje_r, marker_color="#d62728"))

    # Configuración general del gráfico
    fig.update_layout(
        barmode="stack",
        title="Distribución de sensibilidad por antibiótico",
        xaxis_title="Antibiótico",
        yaxis_title="% de aislados",
        yaxis=dict(range=[0, 100]),
        margin=dict(b=150),  # margen inferior para etiquetas largas
    )

    # Exportar como HTML embebible -> incluye el cdn de Plotly
    return plot(fig, output_type="div", include_plotlyjs="cdn")

def build_piechart(datos, titulo):
    """Genera piechart a partir de datos ya procesados"""
    if not datos:
        return None

    # Gráfico de sectores
    fig = px.pie(
        names=[d.get("nombre") or "Desconocido" for d in datos],
        values=[d["cuenta"] for d in datos],
        title=titulo,
        hole=0.4
    )
    fig.update_traces(textposition="inside", textinfo="percent+label")
    return plot(fig, output_type="div", include_plotlyjs=False)


def build_mic_histogram(df_cmi, antibioticos_con_cmi):
    """Genera un histograma para las CMIs de antibióticos."""

    n_antibioticos = len(antibioticos_con_cmi)
    n_cols = min(3, n_antibioticos)
    n_rows = (n_antibioticos + n_cols - 1) // n_cols

    fig = make_subplots(
        rows=n_rows,
        cols=n_cols,
        subplot_titles=antibioticos_con_cmi,
        vertical_spacing=0.12,
        horizontal_spacing=0.1
    )

    # Un gráfico por cada antibiótico
    for idx, antibiotico in enumerate(antibioticos_con_cmi):
        row = (idx // n_cols) + 1
        col = (idx % n_cols) + 1

        df_antibio = df_cmi[df_cmi["antibiotico__antibiotico__nombre"] == antibiotico]

        # Histograma con las CMIs
        max_cmi = (float(df_antibio["cmi"].max())) * 1.05  # un 5% extra
        fig.add_trace(
            go.Histogram(
                x=df_antibio["cmi"],
                marker_color="#b46199",
                opacity=0.7,
            ),
            row=row,
            col=col
        )

        fig.update_xaxes(title_text="CMI (mg/L)", row=row, col=col, range=[0, max_cmi])
        fig.update_yaxes(title_text="N", row=row, col=col)

    fig.update_layout(
        title_text="Distribución de Concentración Mínima Inhibitoria (CMI) por antibiótico",
        height=300 * n_rows,
        showlegend=False,
    )

    return plot(fig, output_type="div", include_plotlyjs=False)


def proportions_test(sensibles_actual: int, total_actual: int, sensibles_anterior: int,
                     total_anterior: int, alpha=0.05) -> str:
        """
        Compara proporciones entre dos períodos, eligiendo automáticamente entre el test de Fisher o el Chi-cuadrado
        según las frecuencias esperadas.
        Devuelve una flecha ('↑' o '↓') si hay un cambio significativo en la proporción de sensibles respecto al periodo
        anterior, o una cadena vacía si no hay diferencia significativa (nivel de significación α=0.05).
        ref: https://ai.plainenglish.io/unlocking-pythons-statsmodels-a-comprehensive-guide-00c5cf08b7bf
        """
        # Valida si hay datos suficientes
        if total_actual < 10 or total_anterior < 10:
            return ""

        resistentes_actual = total_actual - sensibles_actual
        resistentes_anterior = total_anterior - sensibles_anterior

        tabla = np.array([
            [sensibles_actual, resistentes_actual],
            [sensibles_anterior, resistentes_anterior]
        ])

        if np.any(tabla < 0):
            return ""

        # Calcula frecuencias esperadas con chi2
        try:
            t = Table2x2(tabla)
        except Exception as e:
            print(f"Error calculando frecuencias esperadas: {e}")
            return ""

        # Frecuencias esperadas
        expected = t.fittedvalues

        # Test según frecuencias
        if np.any(expected < 5):
            # Fisher exacto (ideal para celdas pequeñas)
            try:
                _, res = fisher_exact(tabla)
            except Exception as e:
                print(f"Error en Fisher exact: {e}")
                return ""
        else:
            # Chi-cuadrado (aproximación normal)
            try:
                res = t.test_nominal_association().pvalue
            except Exception as e:
                print(f"Error en Chi-cuadrado: {e}")
                return ""

        p_value = res

        # Decidir dirección si hay diferencia significativa
        if p_value >= alpha:
            return ""

        prop_actual = sensibles_actual / total_actual
        prop_anterior = sensibles_anterior / total_anterior

        if prop_actual > prop_anterior:
            return "↑"
        else:
            return "↓"

