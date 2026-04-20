#!/usr/bin/env python3
"""
Script de entrenamiento para modelo de predicción de disponibilidad de bicicletas EcoBici.

Este script:
1. Carga datos de viajes del sistema EcoBici desde un CSV
2. Preprocesa fechas y extrae features temporales
3. Crea una variable objetivo (disponibilidad) basada en retiros por estación/hora
4. Entrena un modelo XGBoost para regresión
5. Evalúa el modelo con MAE y RMSE
6. Exporta el modelo entrenado a model.pkl

Autor: Senior Data Scientist
Fecha: 2026-04-20
"""

import pandas as pd
import numpy as np
import pickle
from datetime import datetime
from sklearn.model_selection import train_test_split
from sklearn.metrics import mean_absolute_error, mean_squared_error


# Intentar importar XGBoost - instalar si no está disponible
def instalar_depencencias():
    """Instala las dependencias necesarias."""
    import subprocess
    import sys

    # Intentar primero sin --break-system-packages
    try:
        subprocess.check_call(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "xgboost",
                "pandas",
                "scikit-learn",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        # Si falla, intentar con --break-system-packages
        subprocess.check_call(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "xgboost",
                "pandas",
                "scikit-learn",
                "--break-system-packages",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )


try:
    import xgboost as xgb
    from xgboost import XGBRegressor
except ImportError:
    print("XGBoost no está instalado. Instalando dependencias...")
    instalar_depencencias()
    import xgboost as xgb
    from xgboost import XGBRegressor


# ============================================================================
# CONFIGURACIÓN
# ============================================================================

# Rutas de archivos
INPUT_CSV = "2026-03.csv"
OUTPUT_MODEL = "model.pkl"

# Semilla para reproducibilidad
RANDOM_STATE = 42


# ============================================================================
# ETAPA 1: CARGA DE DATOS
# ============================================================================


def cargar_datos(ruta_csv: str) -> pd.DataFrame:
    """
    Carga los datos del archivo CSV de EcoBici.

    Parámetros:
        ruta_csv: Ruta al archivo CSV con los datos de viajes.

    Retorna:
        DataFrame con los datos cargados.
    """
    print(f"[1] Cargando datos desde {ruta_csv}...")

    # Especificar tipos de datos para optimizar memoria
    tipos = {
        "Genero_Usuario": "category",
        "Edad_Usuario": "Int64",
        "Bici": "Int64",
        "Ciclo_Estacion_Retiro": "category",
        "Ciclo_EstacionArribo": "category",
    }

    df = pd.read_csv(ruta_csv, dtype=tipos, low_memory=False)

    print(f"    - Filas cargadas: {len(df):,}")
    print(f"    - Columnas: {list(df.columns)}")

    return df


# ============================================================================
# ETAPA 2: PREPROCESAMIENTO
# ============================================================================


def preprocesar_datos(df: pd.DataFrame) -> pd.DataFrame:
    """
    Preprocesa los datos:
    - Convierte columnas de fecha/hora a datetime
    - Extrae variables temporales (hora, día de semana, mes)
    - Maneja valores nulos

    Parámetros:
        df: DataFrame con los datos crudos.

    Retorna:
        DataFrame preprocesado.
    """
    print("\n[2] Preprocesando datos...")

    # Copia parano modificar original
    df = df.copy()

    # Combinar Fecha_Retiro y Hora_Retiro para crear datetime
    df["Fecha_Retiro"] = pd.to_datetime(
        df["Fecha_Retiro"] + " " + df["Hora_Retiro"],
        format="%d/%m/%Y %H:%M:%S",
        errors="coerce",
    )

    # Manejar valores nulos en datetime
    nulos_iniciales = df["Fecha_Retiro"].isna().sum()
    df = df.dropna(subset=["Fecha_Retiro"])
    print(f"    - Nulos en Fecha_Retiro removidos: {nulos_iniciales:,}")

    # Extraer variables temporales
    df["hora"] = df["Fecha_Retiro"].dt.hour
    df["dia_semana"] = df["Fecha_Retiro"].dt.dayofweek  # 0=Lunes, 6=Domingo
    df["mes"] = df["Fecha_Retiro"].dt.month
    df["dia_mes"] = df["Fecha_Retiro"].dt.day

    # Convertir estaciones a entero (manejar valores nulos)
    df["estacion_retiro"] = pd.to_numeric(df["Ciclo_Estacion_Retiro"], errors="coerce")
    df["estacion_arribo"] = pd.to_numeric(df["Ciclo_EstacionArribo"], errors="coerce")

    # Eliminar filas con estación inválida
    df = df.dropna(subset=["estacion_retiro", "estacion_arribo"])
    df["estacion_retiro"] = df["estacion_retiro"].astype(int)
    df["estacion_arribo"] = df["estacion_arribo"].astype(int)

    # Manejar Edad_Usuario nula - imputar con mediana
    nulos_edad = df["Edad_Usuario"].isna().sum()
    if nulos_edad > 0:
        mediana_edad = df["Edad_Usuario"].median()
        df["Edad_Usuario"] = df["Edad_Usuario"].fillna(mediana_edad)
        print(
            f"    - Edades nulas imputadas con mediana ({mediana_edad}): {nulos_edad:,}"
        )

    print(f"    - Variables temporales extraídas: hora, dia_semana, mes, dia_mes")
    print(f"    - Filas después de preprocesamiento: {len(df):,}")

    return df


# ============================================================================
# ETAPA 3: INGENIERÍA DE CARACTERÍSTICAS
# ============================================================================


def crear_features_y_target(df: pd.DataFrame) -> pd.DataFrame:
    """
    Crea las features y la variable objetivo.

    La variable objetivo es el número de retiros por estación y hora.
    Esto es un proxy de demanda/disponibilidad:
    - Muchos retiros = bike disponible (usuarios la ocupan)
    - Pocos retiros = bike disponible (queda en estación)

    Parámetros:
        df: DataFrame preprocesado.

    Retorna:
        DataFrame con features y target.
    """
    print("\n[3] Creando features y variable objetivo...")

    # Agregar retiros por estación, hora y día
    retiros = (
        df.groupby(["estacion_retiro", "dia_mes", "hora", "dia_semana", "mes"])
        .size()
        .reset_index(name="retiros")
    )

    # Agregar retiros por estación y hora (para todos los días)
    retiros_por_estacion_hora = (
        df.groupby(["estacion_retiro", "hora"])
        .size()
        .reset_index(name="retiros_promedio_hist")
    )

    # Merge: agregar promedio histórico a cada registro
    retiros = retiros.merge(
        retiros_por_estacion_hora, on=["estacion_retiro", "hora"], how="left"
    )

    # Fill NaN con 0 (estaciones/horas sin retiros)
    retiros["retiros_promedio_hist"] = retiros["retiros_promedio_hist"].fillna(0)

    # Variable objetivo = retiros actuales (proxy de demanda)
    target_col = "retiros"

    # Features finales
    features = [
        "estacion_retiro",
        "hora",
        "dia_semana",
        "mes",
        "dia_mes",
        "retiros_promedio_hist",
    ]

    # Filtrar outliers en Edad_Usuario (valores extremos)
    # Esto viene deljoin con datos originales para agregar como feature
    edad_promedio = df.groupby("estacion_retiro")["Edad_Usuario"].mean().reset_index()
    edad_promedio.columns = ["estacion_retiro", "edad_promedio"]

    retiros = retiros.merge(edad_promedio, on="estacion_retiro", how="left")
    retiros["edad_promedio"] = retiros["edad_promedio"].fillna(
        df["Edad_Usuario"].median()
    )

    features.append("edad_promedio")

    print(f"    - Target: '{target_col}' (retiros por estación/hora)")
    print(f"    - Features: {features}")
    print(f"    - Muestras para entrenamiento: {len(retiros):,}")

    return retiros, features, target_col


# ============================================================================
# ETAPA 4: MODELO - ENTRENAMIENTO
# ============================================================================


def entrenar_modelo(X: pd.DataFrame, y: pd.Series, test_size: float = 0.2) -> tuple:
    """
    Entrena el modelo XGBoost.

    Parámetros:
        X: DataFrame con features.
        y: Series con variable objetivo.
        test_size: Proporción para test.

    Retorna:
        Tupla con (modelo, X_train, X_test, y_train, y_test).
    """
    print("\n[4] Entrenando modelo XGBoost...")

    # División train/test
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=test_size, random_state=RANDOM_STATE
    )

    print(f"    - Train: {len(X_train):,} muestras")
    print(f"    - Test: {len(X_test):,} muestras")

    # Configuración del modelo optimizada para Lambda (peso ligero)
    modelo = XGBRegressor(
        n_estimators=100,  # número de árboles
        max_depth=5,  # profundidad máxima (controla complejidad)
        learning_rate=0.1,  # tasa de aprendizaje
        subsample=0.8,  # muestra de filas por árbol
        colsample_bytree=0.8,  # muestra de columnas por árbol
        random_state=RANDOM_STATE,
        n_jobs=-1,  # tutti los cores
        verbosity=1,
    )

    # Entrenamiento
    print("    - Entrenando XGBRegressor (esto puede tomar unos minutos)...")
    modelo.fit(X_train, y_train)

    print("    - Entrenamiento completado!")

    return modelo, X_train, X_test, y_train, y_test


# ============================================================================
# ETAPA 5: EVALUACIÓN
# ============================================================================


def evaluar_modelo(modelo, X_train, X_test, y_train, y_test) -> dict:
    """
    Evalúa el modelo con métricas.

    Parámetros:
        modelo: Modelo entrenado.
        Datos de train y test.

    Retorna:
        Diccionario con métricas.
    """
    print("\n[5] Evaluando modelo...")

    # Predicciones
    y_train_pred = modelo.predict(X_train)
    y_test_pred = modelo.predict(X_test)

    # Métricas en conjunto de entrenamiento
    mae_train = mean_absolute_error(y_train, y_train_pred)
    rmse_train = np.sqrt(mean_squared_error(y_train, y_train_pred))

    # Métricas en conjunto de test
    mae_test = mean_absolute_error(y_test, y_test_pred)
    rmse_test = np.sqrt(mean_squared_error(y_test, y_test_pred))

    print(f"\n    ========== MÉTRICAS ==========")
    print(f"    Entrenamiento:")
    print(f"        MAE:  {mae_train:.4f}")
    print(f"        RMSE: {rmse_train:.4f}")
    print(f"    Test:")
    print(f"        MAE:  {mae_test:.4f}")
    print(f"        RMSE: {rmse_test:.4f}")
    print(f"    ===========================\n")

    # Feature importance
    print("    Top 5 Features más importantes:")
    importance = modelo.feature_importances_
    feature_names = X_train.columns

    # Ordenar por importancia
    indices = np.argsort(importance)[::-1][:5]
    for i, idx in enumerate(indices, 1):
        print(f"        {i}. {feature_names[idx]}: {importance[idx]:.4f}")

    metricas = {
        "mae_train": mae_train,
        "rmse_train": rmse_train,
        "mae_test": mae_test,
        "rmse_test": rmse_test,
    }

    return metricas


# ============================================================================
# ETAPA 6: EXPORTACIÓN DEL MODELO
# ============================================================================


def guardar_modelo(modelo, ruta: str) -> None:
    """
    Guarda el modelo entrenado usando pickle.

    Parámetros:
        modelo: Modelo entrenado.
        ruta: Ruta donde guardar el archivo .pkl.
    """
    print(f"\n[6] Guardando modelo en {ruta}...")

    with open(ruta, "wb") as f:
        pickle.dump(modelo, f)

    print(f"    - Modelo guardado exitosamente!")

    # Verificar tamaño del archivo
    import os

    tamano_mb = os.path.getsize(ruta) / (1024 * 1024)
    print(f"    - Tamaño del archivo: {tamano_mb:.2f} MB")


# ============================================================================
# FUNCION PRINCIPAL
# ============================================================================


def main():
    """
    Función principal que orquesta todo el pipeline.
    """
    print("=" * 60)
    print("TRAINING PIPELINE - EcoBici Bike Availability Prediction")
    print("=" * 60)

    inicio = datetime.now()
    print(f"Inicio: {inicio.strftime('%Y-%m-%d %H:%M:%S')}")

    # Step 1: Cargar datos
    df = cargar_datos(INPUT_CSV)

    # Step 2: Preprocesar
    df = preprocesar_datos(df)

    # Step 3: Features y target
    df_model, features, target_col = crear_features_y_target(df)

    # Preparar X e y
    X = df_model[features]
    y = df_model[target_col]

    # Step 4: Entrenar
    modelo, X_train, X_test, y_train, y_test = entrenar_modelo(X, y)

    # Step 5: Evaluar
    metricas = evaluar_modelo(modelo, X_train, X_test, y_train, y_test)

    # Step 6: Guardar modelo
    guardar_modelo(modelo, OUTPUT_MODEL)

    fin = datetime.now()
    duracion = fin - inicio

    print("\n" + "=" * 60)
    print(f"PIPELINE COMPLETADO")
    print(f"Duración total: {duracion}")
    print(f"Modelo guardado en: {OUTPUT_MODEL}")
    print("=" * 60)

    return modelo, metricas


# ============================================================================
# PUNTO DE ENTRADA
# ============================================================================

if __name__ == "__main__":
    modelo, metricas = main()
