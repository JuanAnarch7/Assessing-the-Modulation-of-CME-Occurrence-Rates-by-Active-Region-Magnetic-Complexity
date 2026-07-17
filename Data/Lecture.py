
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
# ---------------------------------------------------------------------------
# CME (.txt) Source
# ---------------------------------------------------------------------------

Ruta = "replace_by_your_source_file/Soho_Lasco_2026_02_28.txt"

# ---------------------------------------------------------------------------
# Conlumne setting
# ---------------------------------------------------------------------------

nombre_columnas = ["Fecha", "Hora", "Central", "Ancho", "Rapidez", "Col4", "Col5", "Col6", "Aceleracion", "Masa", "Energia", "MPA", "Comentarios"]

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
df = pd.read_csv(
    Ruta,
    delimiter=r"\s+",  # Usa cualquier cantidad de espacios como separador
    engine='python',  # Usa el motor de Python para manejar separadores regulares
    names=nombre_columnas,  # Usar los nombres de columna especificados
    index_col=False  # No tratar ninguna columna como índice
)

df['Fecha'] = pd.to_datetime(df['Fecha'], format='%Y/%m/%d', errors='coerce')

df[["Central", "Ancho", "Rapidez", "Aceleracion", "Masa", "Energia"]] = df[["Central", "Ancho", "Rapidez", "Aceleracion", "Masa", "Energia"]].apply(pd.to_numeric, errors="coerce")
# Processed data preview
print("Vista previa de los datos procesados:")
print(df.head())
print(df["Fecha"].size)

# Save CSV "datos_procesados_2026_02_28.csv"
df.to_csv("datos_procesados_2026_02_28.csv", index=False)
print("Archivo CSV guardado: 'datos_procesados_2026_02_28.csv'")

