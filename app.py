# ============================================================
# BLOQUE 1 — Imports y configuración
# ============================================================
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import unicodedata

st.set_page_config(page_title="nONO Dashboard", layout="wide")

MONTHS_ORDER = [
    "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
    "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
]


# ============================================================
# BLOQUE 2 — Utilidades
# ============================================================
def format_eur(value: float) -> str:
    """Formatea un número como euros: 1.234,56 €"""
    return f"{value:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def validate_columns(df: pd.DataFrame, required: list, sheet: str):
    """Lanza ValueError si faltan columnas esperadas."""
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Hoja '{sheet}': faltan columnas {missing}")


# ============================================================
# BLOQUE 3 — Funciones de carga
# ============================================================
@st.cache_data(ttl=600)
def load_cartera_actual() -> pd.DataFrame:
    try:
        df = pd.read_excel("nONO.xlsx", sheet_name="informe cartera").copy()
        df.columns = df.columns.str.strip()
        validate_columns(
            df,
            ["Fondo", "ISIN", "Tipo de activo", "Importe inicial", "Importe actual",
             "Rentabilidad %", "Rentabilidad en Euros"],
            "informe cartera",
        )
        for col in ["Importe inicial", "Importe actual", "Rentabilidad %", "Rentabilidad en Euros"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df[pd.notna(df["ISIN"])].copy()
        return df
    except Exception as e:
        st.error(f"Error al cargar la hoja 'informe cartera': {e}")
        st.stop()


@st.cache_data(ttl=600)
def load_cartera_objetivo() -> pd.DataFrame:
    try:
        df = pd.read_excel("nONO.xlsx", sheet_name="Cartera objetivo").copy()
        df.columns = df.columns.str.strip()
        validate_columns(df, ["Fondo", "ISIN", "Tipo de activo", "Importe", "Peso"], "Cartera objetivo")
        for col in ["Peso", "Importe"]:
            df[col] = pd.to_numeric(df[col], errors="coerce")
        df = df[pd.notna(df["ISIN"])].copy()
        return df
    except Exception as e:
        st.error(f"Error al cargar la hoja 'Cartera objetivo': {e}")
        st.stop()


@st.cache_data(ttl=600)
def load_patrimonio() -> pd.DataFrame:
    try:
        df = pd.read_excel("nONO.xlsx", sheet_name="Patrimonio actual").copy()
        df.columns = df.columns.str.strip()
        validate_columns(df, ["Banco", "Importe"], "Patrimonio actual")
        df["Importe"] = pd.to_numeric(df["Importe"], errors="coerce")
        df = df[df["Banco"] != "Total"].copy()
        return df
    except Exception as e:
        st.error(f"Error al cargar la hoja 'Patrimonio actual': {e}")
        st.stop()


@st.cache_data(ttl=600)
def load_presupuesto() -> pd.DataFrame:
    try:
        df = pd.read_excel("nONO.xlsx", sheet_name="Presupuesto").copy()
        return df
    except Exception as e:
        st.error(f"Error al cargar la hoja 'Presupuesto': {e}")
        st.stop()


# ============================================================
# BLOQUE 4 — Funciones de cálculo puro
# ============================================================
def calc_patrimonio_total(patrimonio_df: pd.DataFrame) -> float:
    return patrimonio_df["Importe"].sum()


MAPA_TIPOS = {
    "Monetario": "Liquidez / Monetario",
    "Renta fija corto plazo": "Liquidez / Monetario",
    "Renta fija IA": "Renta Fija",
    "Renta fija HY": "Renta Fija",
    "Renta fija IG": "Renta Fija",
    "Renta fija Yield": "Renta Fija",
    "Renta fija yeld": "Renta Fija",
    "Renta fija high yield": "Renta Fija",
    "Renta fija high-yield": "Renta Fija",
    "Renta fija flexible": "Renta Fija",
    "Renta fija": "Renta Fija",
    "Mixto flexible Conservador": "Mixto",
    "Mixto flexible Agresivo": "Mixto",
    "Mixto": "Mixto",
    "Renta variable global": "Renta Variable",
    "Renta variable USA": "Renta Variable",
    "Renta variable Europa": "Renta Variable",
    "Renta variable small caps": "Renta Variable",
    "Renta variable emergente": "Renta Variable",
    "Renta variable": "Renta Variable",
}


def normalize_tipo_activo(tipo: str) -> str:
    if pd.isna(tipo):
        return "Otros"
    tipo_txt = str(tipo).strip()
    return MAPA_TIPOS.get(tipo_txt, "Otros")


def calc_resumen_cartera(cartera_df: pd.DataFrame) -> dict:
    """Devuelve dict con: total_inicial, total_actual, rentabilidad_eur, rentabilidad_pct, por_tipo, por_tipo_agrupado"""
    total_inicial = cartera_df["Importe inicial"].sum()
    total_actual = cartera_df["Importe actual"].sum()
    rent_eur = cartera_df["Rentabilidad en Euros"].sum()
    rent_pct = (total_actual - total_inicial) / total_inicial if total_inicial > 0 else 0
    por_tipo = cartera_df.groupby("Tipo de activo")["Importe actual"].sum().reset_index()
    tmp = cartera_df.copy()
    tmp["tipo_agrupado"] = tmp["Tipo de activo"].map(MAPA_TIPOS).fillna("Otros")
    por_tipo_agrupado = tmp.groupby("tipo_agrupado")["Importe actual"].sum().reset_index()
    por_tipo_agrupado.columns = ["Tipo agrupado", "Importe actual"]
    return {
        "total_inicial": total_inicial,
        "total_actual": total_actual,
        "rentabilidad_eur": rent_eur,
        "rentabilidad_pct": rent_pct,
        "por_tipo": por_tipo,
        "por_tipo_agrupado": por_tipo_agrupado,
    }


def calc_comparacion_cartera(
    actual_df: pd.DataFrame,
    objetivo_df: pd.DataFrame,
    patrimonio_total: float,
    pct_objetivo: float = 0.60,
) -> pd.DataFrame:
    """
    Merge actual vs objetivo por ISIN.
    - peso_actual: recalculado desde cero (importe_actual / total_actual)
    - importe_objetivo: peso_objetivo × (patrimonio_total × pct_objetivo)
    - Los importes del Excel de Cartera objetivo se ignoran, solo se usan sus pesos
    """
    total_actual = actual_df["Importe actual"].sum()
    cartera_objetivo_eur = patrimonio_total * pct_objetivo

    act = actual_df[["ISIN", "Fondo", "Tipo de activo", "Importe actual"]].copy()
    act.columns = ["ISIN", "Fondo", "Tipo", "importe_actual"]

    obj = objetivo_df[["ISIN", "Peso"]].copy()
    obj.columns = ["ISIN", "peso_objetivo"]

    merged = act.merge(obj, on="ISIN", how="outer")
    merged["importe_actual"] = merged["importe_actual"].fillna(0)
    merged["peso_objetivo"] = merged["peso_objetivo"].fillna(0)

    # Recalcular peso_actual desde cero
    merged["peso_actual"] = (
        merged["importe_actual"] / total_actual if total_actual > 0 else 0.0
    )

    # Para fondos solo en objetivo, recuperar nombre y tipo
    for idx, row in merged[merged["Fondo"].isna()].iterrows():
        match = objetivo_df[objetivo_df["ISIN"] == row["ISIN"]]
        if not match.empty:
            merged.at[idx, "Fondo"] = match.iloc[0]["Fondo"]
            merged.at[idx, "Tipo"] = match.iloc[0]["Tipo de activo"]

    merged["desviacion"] = merged["peso_actual"] - merged["peso_objetivo"]
    # Importe objetivo basado en 60% del patrimonio total, no en el Excel
    merged["importe_objetivo"] = merged["peso_objetivo"] * cartera_objetivo_eur
    merged["accion_eur"] = merged["importe_objetivo"] - merged["importe_actual"]

    return merged.sort_values("peso_objetivo", ascending=False).reset_index(drop=True)


def _merge_actual_objetivo(actual_df: pd.DataFrame, objetivo_df: pd.DataFrame) -> pd.DataFrame:
    act = actual_df[
        ["ISIN", "Fondo", "Tipo de activo", "Importe actual", "Rentabilidad %", "Rentabilidad en Euros"]
    ].copy()
    act.columns = [
        "ISIN",
        "Fondo",
        "Tipo",
        "importe_actual",
        "rentabilidad_pct",
        "rentabilidad_eur",
    ]

    obj = objetivo_df[["ISIN", "Fondo", "Tipo de activo", "Peso"]].copy()
    obj.columns = ["ISIN", "Fondo_obj", "Tipo_obj", "peso_objetivo"]

    merged = act.merge(obj, on="ISIN", how="outer")
    merged["importe_actual"] = pd.to_numeric(merged["importe_actual"], errors="coerce").fillna(0.0)
    merged["peso_objetivo"] = pd.to_numeric(merged["peso_objetivo"], errors="coerce").fillna(0.0)
    merged["rentabilidad_pct"] = pd.to_numeric(merged["rentabilidad_pct"], errors="coerce").fillna(0.0)
    merged["rentabilidad_eur"] = pd.to_numeric(merged["rentabilidad_eur"], errors="coerce").fillna(0.0)
    merged["Fondo"] = merged["Fondo"].fillna(merged["Fondo_obj"]).fillna("Sin nombre")
    merged["Tipo"] = merged["Tipo"].fillna(merged["Tipo_obj"]).fillna("Otros")
    merged["Tipo agrupado"] = merged["Tipo"].apply(normalize_tipo_activo)
    return merged[
        [
            "ISIN",
            "Fondo",
            "Tipo",
            "Tipo agrupado",
            "importe_actual",
            "peso_objetivo",
            "rentabilidad_pct",
            "rentabilidad_eur",
        ]
    ].copy()


def calc_rebalanceo_actual_vs_objetivo(actual_df: pd.DataFrame, objetivo_df: pd.DataFrame) -> pd.DataFrame:
    merged = _merge_actual_objetivo(actual_df, objetivo_df)
    total_actual = merged["importe_actual"].sum()
    merged["peso_actual"] = merged["importe_actual"] / total_actual if total_actual > 0 else 0.0
    merged["gap_pp"] = (merged["peso_actual"] - merged["peso_objetivo"]) * 100
    merged["importe_objetivo_rebalanceo"] = merged["peso_objetivo"] * total_actual
    merged["accion_rebalanceo"] = merged["importe_objetivo_rebalanceo"] - merged["importe_actual"]

    merged["estado"] = "En rango"
    merged.loc[merged["gap_pp"] >= 1.0, "estado"] = "Sobreponderado"
    merged.loc[merged["gap_pp"] <= -1.0, "estado"] = "Infraponderado"
    return merged.sort_values("gap_pp", ascending=False).reset_index(drop=True)


def calc_plan_aportaciones_60(
    actual_df: pd.DataFrame,
    objetivo_df: pd.DataFrame,
    patrimonio_total: float
) -> pd.DataFrame:
    merged = _merge_actual_objetivo(actual_df, objetivo_df)
    total_actual = merged["importe_actual"].sum()
    cartera_objetivo_total = patrimonio_total * 0.60

    merged["peso_actual"] = merged["importe_actual"] / total_actual if total_actual > 0 else 0.0
    merged["gap_pp"] = (merged["peso_actual"] - merged["peso_objetivo"]) * 100
    merged["importe_objetivo_aportacion"] = merged["peso_objetivo"] * cartera_objetivo_total
    merged["aportacion_necesaria"] = merged["importe_objetivo_aportacion"] - merged["importe_actual"]

    merged["prioridad"] = "Baja"
    positivos_idx = merged[merged["aportacion_necesaria"] > 0].sort_values(
        "aportacion_necesaria", ascending=False
    ).index.tolist()
    n = len(positivos_idx)
    if n > 0:
        top_cut = max(1, int(round(n / 3)))
        mid_cut = max(top_cut + 1, int(round((2 * n) / 3)))
        for i, idx in enumerate(positivos_idx):
            if i < top_cut:
                merged.at[idx, "prioridad"] = "Alta"
            elif i < mid_cut:
                merged.at[idx, "prioridad"] = "Media"
            else:
                merged.at[idx, "prioridad"] = "Baja"

    return merged.sort_values("aportacion_necesaria", ascending=False).reset_index(drop=True)


def calc_presupuesto(presupuesto_df: pd.DataFrame) -> dict:
    """
    Extrae ingresos y gastos del DataFrame de Presupuesto.
    Devuelve dict con listas y totales anuales/mensuales.
    Nómina mensual × 12, pagas extra × 1 cada una.
    Gastos mensuales × 12.
    """
    ingresos = presupuesto_df[["Ingresos", "Importe"]].dropna(subset=["Ingresos"])
    ingresos = ingresos[ingresos["Ingresos"].astype(str).str.strip() != ""].copy()
    ingresos.columns = ["concepto", "importe"]

    if "Importe.1" in presupuesto_df.columns:
        importe1_col = "Importe.1"
    else:
        candidates = [c for c in presupuesto_df.columns if c.startswith("Importe") and c != "Importe"]
        if candidates:
            importe1_col = candidates[0]
        else:
            raise ValueError(
                "No se encontró la columna de importes de gastos (esperada 'Importe.1' o similar). "
                f"Columnas disponibles: {list(presupuesto_df.columns)}"
            )

    gastos = presupuesto_df[["Gastos", importe1_col]].dropna(subset=["Gastos"])
    gastos = gastos[gastos["Gastos"].astype(str).str.strip() != ""].copy()
    gastos.columns = ["concepto", "importe"]

    def _normaliza_concepto(texto: str) -> str:
        txt = unicodedata.normalize("NFKD", str(texto))
        txt = "".join(ch for ch in txt if not unicodedata.combining(ch))
        return " ".join(txt.lower().strip().split())

    # Anualizar: nómina ×12, pagas extra junio/diciembre ×1, gastos ×12
    nomina_anual = 0.0
    paga_extra_junio = 0.0
    paga_extra_diciembre = 0.0
    for _, r in ingresos.iterrows():
        concepto_norm = _normaliza_concepto(r["concepto"])
        importe = pd.to_numeric(r["importe"], errors="coerce")
        if pd.isna(importe):
            continue

        if "nomina" in concepto_norm:
            nomina_anual += float(importe) * 12
        elif "junio" in concepto_norm:
            paga_extra_junio += float(importe)
        elif "diciembre" in concepto_norm:
            paga_extra_diciembre += float(importe)

    gasto_mensual = pd.to_numeric(gastos["importe"], errors="coerce").fillna(0.0).sum()
    gasto_anual = gasto_mensual * 12
    nomina_mensual = nomina_anual / 12
    pagas_anual = paga_extra_junio + paga_extra_diciembre
    ingreso_anual = nomina_anual + paga_extra_junio + paga_extra_diciembre
    ahorro_anual = ingreso_anual - gasto_anual
    ahorro_mensual_base = nomina_mensual - gasto_mensual
    ahorro_junio = nomina_mensual + paga_extra_junio - gasto_mensual
    ahorro_diciembre = nomina_mensual + paga_extra_diciembre - gasto_mensual
    ahorro_mensual_medio = ahorro_anual / 12

    detalle_rows = []
    for mes in MONTHS_ORDER:
        es_mes_paga = mes in {"Junio", "Diciembre"}
        paga_extra = 0.0
        if mes == "Junio":
            paga_extra = paga_extra_junio
        elif mes == "Diciembre":
            paga_extra = paga_extra_diciembre

        ingreso_mes = nomina_mensual + paga_extra
        ahorro_mes = ingreso_mes - gasto_mensual
        detalle_rows.append({
            "Mes": mes,
            "Ingreso del mes": ingreso_mes,
            "Gasto del mes": gasto_mensual,
            "Ahorro del mes": ahorro_mes,
            "Tipo de mes": "Mes con paga extra" if es_mes_paga else "Mes normal",
        })

    detalle_mensual_df = pd.DataFrame(detalle_rows)
    detalle_mensual_df["Mes"] = pd.Categorical(
        detalle_mensual_df["Mes"], categories=MONTHS_ORDER, ordered=True
    )
    detalle_mensual_df = detalle_mensual_df.sort_values("Mes").reset_index(drop=True)

    return {
        "ingresos_df": ingresos,
        "gastos_df": gastos,
        "nomina_anual": nomina_anual,
        "pagas_anual": pagas_anual,
        "ingreso_anual": ingreso_anual,
        "gasto_anual": gasto_anual,
        "ahorro_anual": ahorro_anual,
        "nomina_mensual": nomina_mensual,
        "gasto_mensual": gasto_mensual,
        "ahorro_mensual_base": ahorro_mensual_base,
        "paga_extra_junio": paga_extra_junio,
        "paga_extra_diciembre": paga_extra_diciembre,
        "ahorro_junio": ahorro_junio,
        "ahorro_diciembre": ahorro_diciembre,
        "ahorro_mensual_medio": ahorro_mensual_medio,
        "detalle_mensual_df": detalle_mensual_df,
        "ahorro_mensual": ahorro_mensual_medio,
    }


def calc_ahorro_mensual_real(presupuesto_dict: dict) -> list:
    """
    Devuelve una lista de 12 floats con el ahorro neto real de cada mes.
    Junio (índice 5) y Diciembre (índice 11) incluyen paga extra.
    Gastos fijos son iguales todos los meses.
    """
    if "detalle_mensual_df" in presupuesto_dict:
        return presupuesto_dict["detalle_mensual_df"]["Ahorro del mes"].tolist()

    nomina_mensual = presupuesto_dict.get("nomina_mensual", presupuesto_dict["nomina_anual"] / 12)
    gasto_mensual = presupuesto_dict.get("gasto_mensual", presupuesto_dict["gasto_anual"] / 12)
    paga_extra_junio = presupuesto_dict.get("paga_extra_junio", 0.0)
    paga_extra_diciembre = presupuesto_dict.get("paga_extra_diciembre", 0.0)

    return [
        nomina_mensual - gasto_mensual,  # Enero
        nomina_mensual - gasto_mensual,  # Febrero
        nomina_mensual - gasto_mensual,  # Marzo
        nomina_mensual - gasto_mensual,  # Abril
        nomina_mensual - gasto_mensual,  # Mayo
        nomina_mensual + paga_extra_junio - gasto_mensual,  # Junio
        nomina_mensual - gasto_mensual,  # Julio
        nomina_mensual - gasto_mensual,  # Agosto
        nomina_mensual - gasto_mensual,  # Septiembre
        nomina_mensual - gasto_mensual,  # Octubre
        nomina_mensual - gasto_mensual,  # Noviembre
        nomina_mensual + paga_extra_diciembre - gasto_mensual,  # Diciembre
    ]


def calc_proyeccion_patrimonio(
    patrimonio_inicial: float,
    cartera_inicial: float,
    ahorros_mensuales: list,
    pct_ahorro_invertido: float,
    rentabilidad_anual_pct: float,
    años: int = 10,
) -> pd.DataFrame:
    """
    Proyecta el patrimonio total mes a mes.
    - patrimonio_inicial: total cuentas + cartera
    - cartera_inicial: solo la parte invertida (sobre la que se aplica rentabilidad)
    - ahorros_mensuales: lista de 12 floats con ahorro real por mes (se repite cada año)
    - pct_ahorro_invertido: fracción del ahorro que va a cartera (0.0 a 1.0)
    - rentabilidad_anual_pct: rentabilidad anual esperada sobre la cartera
    """
    r_mensual = (1 + rentabilidad_anual_pct / 100) ** (1 / 12) - 1
    registros = []

    cartera = cartera_inicial
    liquidez = patrimonio_inicial - cartera_inicial
    aportaciones_acum = 0.0

    for m in range(1, años * 12 + 1):
        mes_del_año = ((m - 1) % 12)  # 0=enero, 5=junio, 11=diciembre
        ahorro_mes = ahorros_mensuales[mes_del_año]

        # Rentabilidad solo sobre cartera
        interes = cartera * r_mensual
        cartera += interes

        # Aportación: % del ahorro va a cartera, resto a liquidez
        aportacion_cartera = ahorro_mes * pct_ahorro_invertido
        aportacion_liquidez = ahorro_mes * (1 - pct_ahorro_invertido)
        cartera += aportacion_cartera
        liquidez += aportacion_liquidez
        aportaciones_acum += ahorro_mes

        patrimonio_total = cartera + liquidez
        capital_propio = patrimonio_inicial + aportaciones_acum
        rentabilidad_generada = patrimonio_total - capital_propio

        registros.append({
            "mes": m,
            "año": round(m / 12, 4),
            "patrimonio": patrimonio_total,
            "cartera": cartera,
            "liquidez": liquidez,
            "capital_propio": capital_propio,
            "rentabilidad_generada": rentabilidad_generada,
        })

    return pd.DataFrame(registros)


# ============================================================
# BLOQUE 5 — Navegación
# ============================================================
pagina = st.sidebar.radio(
    "Navegación",
    ["🏦 Patrimonio", "📊 Cartera actual vs objetivo", "💶 Presupuesto y cash flow", "📈 Proyección / escenarios"],
)


# ============================================================
# BLOQUE 6 — Página: Patrimonio
# ============================================================
if pagina == "🏦 Patrimonio":
    st.title("🏦 Patrimonio")
    try:
        cartera_actual_df = load_cartera_actual()
        cartera_objetivo_df = load_cartera_objetivo()
        patrimonio_df = load_patrimonio()
        presupuesto_df = load_presupuesto()

        resumen = calc_resumen_cartera(cartera_actual_df)
        patrimonio_total = calc_patrimonio_total(patrimonio_df)

        cartera_val = resumen["total_actual"]
        liquidez = patrimonio_total - cartera_val
        rent_eur = resumen["rentabilidad_eur"]
        rent_pct = resumen["rentabilidad_pct"] * 100

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric(
                "Total patrimonio",
                format_eur(patrimonio_total),
                help="Suma de todas las cuentas bancarias más el valor actual de la cartera de inversión",
            )
        with col2:
            st.metric(
                "Patrimonio invertido",
                format_eur(cartera_val),
                help="Valor de mercado actual de todos los fondos",
            )
        with col3:
            st.metric(
                "Liquidez",
                format_eur(liquidez),
                help="Efectivo en cuentas bancarias no invertido",
            )
        with col4:
            delta_label = f"{rent_pct:+.2f}%"
            st.metric(
                "Rentabilidad cartera",
                format_eur(rent_eur),
                delta=delta_label,
                delta_color="normal",
                help="Ganancia/pérdida total desde el importe inicial invertido",
            )

        objetivo_inversion = patrimonio_total * 0.60
        progreso = min(cartera_val / objetivo_inversion, 1.0) if objetivo_inversion > 0 else 0.0
        pct_actual = (cartera_val / patrimonio_total * 100) if patrimonio_total > 0 else 0.0
        st.markdown(f"**Objetivo: tener el 60% del patrimonio invertido ({format_eur(objetivo_inversion)})**")
        st.progress(progreso)
        st.caption(
            f"Actualmente tienes invertido el {pct_actual:.1f}% de tu patrimonio — "
            f"llevas el {progreso*100:.1f}% del camino · "
            f"te faltan {format_eur(max(objetivo_inversion - cartera_val, 0))} por invertir"
        )

        st.markdown("---")
        col_donut, col_barras = st.columns(2)

        with col_donut:
            st.subheader("Distribución del patrimonio")

            cuentas_total = patrimonio_df["Importe"].sum() - resumen["total_actual"]
            por_tipo_agrupado = resumen["por_tipo_agrupado"].copy()
            fila_liquidez = pd.DataFrame([{
                "Tipo agrupado": "Liquidez en cuentas",
                "Importe actual": cuentas_total
            }])
            por_tipo_completo = pd.concat([fila_liquidez, por_tipo_agrupado], ignore_index=True)
            por_tipo_completo = por_tipo_completo[por_tipo_completo["Importe actual"] > 0]

            fig_donut = px.pie(
                por_tipo_completo,
                names="Tipo agrupado",
                values="Importe actual",
                hole=0.4,
                color_discrete_sequence=["#aec7e8", "#1f77b4", "#2ca02c", "#ff7f0e", "#9467bd"],
            )
            fig_donut.update_traces(textinfo="percent+label")
            fig_donut.update_layout(showlegend=True, margin=dict(t=30, b=30, l=30, r=30))
            st.plotly_chart(fig_donut, use_container_width=True)

        with col_barras:
            st.subheader("Saldo por cuenta bancaria")
            fig_bar = go.Figure(
                go.Bar(
                    x=patrimonio_df["Importe"],
                    y=patrimonio_df["Banco"],
                    orientation="h",
                    marker_color="#1f77b4",
                    text=[format_eur(v) for v in patrimonio_df["Importe"]],
                    textposition="outside",
                )
            )
            fig_bar.update_layout(
                xaxis_title="Importe (€)",
                margin=dict(t=30, b=30, l=30, r=80),
                yaxis=dict(autorange="reversed"),
            )
            st.plotly_chart(fig_bar, use_container_width=True)

    except Exception as e:
        st.error(f"Error inesperado: {e}")
        st.stop()


# ============================================================
# BLOQUE 7 — Página: Cartera actual vs objetivo
# ============================================================
elif pagina == "📊 Cartera actual vs objetivo":
    st.title("📊 Cartera actual vs objetivo")
    try:
        cartera_actual_df = load_cartera_actual()
        cartera_objetivo_df = load_cartera_objetivo()
        patrimonio_df = load_patrimonio()
        patrimonio_total = calc_patrimonio_total(patrimonio_df)
        modo = st.radio(
            "Modo de análisis",
            ["Rebalanceo sobre cartera actual", "Plan de aportaciones hasta 60% del patrimonio"],
            horizontal=True,
        )

        if modo == "Rebalanceo sobre cartera actual":
            rebalanceo_df = calc_rebalanceo_actual_vs_objetivo(cartera_actual_df, cartera_objetivo_df)

            total_actual = rebalanceo_df["importe_actual"].sum()
            fondos_sobre = int((rebalanceo_df["estado"] == "Sobreponderado").sum())
            fondos_infra = int((rebalanceo_df["estado"] == "Infraponderado").sum())
            rotacion_total = abs(
                rebalanceo_df.loc[rebalanceo_df["accion_rebalanceo"] < 0, "accion_rebalanceo"]
            ).sum()

            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Total cartera actual", format_eur(total_actual))
            col2.metric("Fondos sobreponderados", fondos_sobre)
            col3.metric("Fondos infraponderados", fondos_infra)
            col4.metric(
                "Rotación necesaria total (€)",
                format_eur(rotacion_total),
                help="Importe total que habría que reducir en fondos sobreponderados para rebalancear la cartera manteniendo su tamaño actual.",
            )

            tabla = rebalanceo_df.copy()
            tabla["Peso actual %"] = tabla["peso_actual"] * 100
            tabla["Peso objetivo %"] = tabla["peso_objetivo"] * 100
            tabla["Rentabilidad %"] = tabla["rentabilidad_pct"] * 100
            tabla["Rentabilidad €"] = tabla["rentabilidad_eur"]
            tabla["Gap pp"] = tabla["gap_pp"]
            tabla["Importe actual €"] = tabla["importe_actual"]
            tabla["Importe objetivo €"] = tabla["importe_objetivo_rebalanceo"]
            tabla["Acción rebalanceo"] = tabla.apply(
                lambda r: "Mantener"
                if abs(r["gap_pp"]) < 1.0
                else (
                    f"Aumentar {format_eur(abs(r['accion_rebalanceo']))}"
                    if r["accion_rebalanceo"] > 0
                    else f"Reducir {format_eur(abs(r['accion_rebalanceo']))}"
                ),
                axis=1,
            )
            tabla["Fondo"] = tabla["Fondo"].astype(str)
            tabla = tabla[
                [
                    "Fondo", "Tipo", "Importe actual €", "Rentabilidad €", "Rentabilidad %",
                    "Peso actual %", "Peso objetivo %", "Gap pp", "estado",
                    "Importe objetivo €", "Acción rebalanceo"
                ]
            ].rename(columns={"estado": "Estado"})

            st.subheader("Tabla principal de rebalanceo")
            st.dataframe(
                tabla,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Importe actual €": st.column_config.NumberColumn(format="%.2f"),
                    "Rentabilidad €": st.column_config.NumberColumn(format="%+.2f"),
                    "Rentabilidad %": st.column_config.NumberColumn(format="%+.2f%%"),
                    "Peso actual %": st.column_config.NumberColumn(format="%.2f"),
                    "Peso objetivo %": st.column_config.NumberColumn(format="%.2f"),
                    "Gap pp": st.column_config.NumberColumn(format="%+.2f"),
                    "Importe objetivo €": st.column_config.NumberColumn(format="%.2f"),
                },
            )

            st.subheader("Gap por fondo (pp)")
            gaps = rebalanceo_df.sort_values("gap_pp", ascending=False).copy()
            fig_gaps = go.Figure(
                go.Bar(
                    x=gaps["gap_pp"],
                    y=gaps["Fondo"],
                    orientation="h",
                    marker_color=["#d62728" if v > 0 else "#2ca02c" for v in gaps["gap_pp"]],
                    text=[f"{v:+.2f} pp" for v in gaps["gap_pp"]],
                    textposition="outside",
                )
            )
            fig_gaps.update_layout(
                xaxis_title="Gap (pp)",
                yaxis_title="Fondo",
                margin=dict(t=30, b=30, l=30, r=30),
                yaxis=dict(autorange="reversed"),
            )
            st.plotly_chart(fig_gaps, use_container_width=True)

            st.subheader("Comparativa agregada por categoría")
            agregado = rebalanceo_df.groupby("Tipo agrupado", as_index=False).agg(
                importe_actual=("importe_actual", "sum"),
                peso_objetivo=("peso_objetivo", "sum"),
            )
            agregado["peso_actual"] = agregado["importe_actual"] / total_actual if total_actual > 0 else 0.0
            agregado["peso_actual_pct"] = agregado["peso_actual"] * 100
            agregado["peso_objetivo_pct"] = agregado["peso_objetivo"] * 100
            orden = ["Liquidez / Monetario", "Renta Fija", "Mixto", "Renta Variable", "Otros"]
            agregado["orden"] = agregado["Tipo agrupado"].apply(lambda x: orden.index(x) if x in orden else 99)
            agregado = agregado.sort_values("orden")

            fig_agregado = go.Figure()
            fig_agregado.add_trace(
                go.Bar(name="Peso actual agregado", x=agregado["Tipo agrupado"], y=agregado["peso_actual_pct"])
            )
            fig_agregado.add_trace(
                go.Bar(name="Peso objetivo agregado", x=agregado["Tipo agrupado"], y=agregado["peso_objetivo_pct"])
            )
            fig_agregado.update_layout(
                barmode="group",
                xaxis_title="Categoría",
                yaxis_title="Peso (%)",
                margin=dict(t=30, b=30, l=30, r=30),
            )
            st.plotly_chart(fig_agregado, use_container_width=True)
        else:
            plan_df = calc_plan_aportaciones_60(cartera_actual_df, cartera_objetivo_df, patrimonio_total)
            cartera_objetivo_total = patrimonio_total * 0.60
            aportacion_total = plan_df.loc[plan_df["aportacion_necesaria"] > 0, "aportacion_necesaria"].sum()
            fondos_reforzar = int((plan_df["aportacion_necesaria"] > 0).sum())

            st.caption(
                f"Objetivo de cartera invertida = 60% del patrimonio total ({format_eur(cartera_objetivo_total)}), "
                "coherente con la pestaña 🏦 Patrimonio."
            )

            col1, col2, col3, col4 = st.columns(4)
            col1.metric("Patrimonio total", format_eur(patrimonio_total))
            col2.metric("Objetivo invertido (60%)", format_eur(cartera_objetivo_total))
            col3.metric(
                "Aportación nueva necesaria total",
                format_eur(aportacion_total),
                help="Este modo no representa un rebalanceo puro, sino un plan de asignación del capital adicional necesario para que la cartera invertida alcance el 60% del patrimonio.",
            )
            col4.metric("Fondos a reforzar", fondos_reforzar)

            mostrar_solo_reforzar = st.checkbox(
                "Mostrar solo fondos con aportación necesaria positiva",
                value=True
            )

            tabla_plan = plan_df.copy()
            tabla_plan["Peso actual %"] = tabla_plan["peso_actual"] * 100
            tabla_plan["Peso objetivo %"] = tabla_plan["peso_objetivo"] * 100
            tabla_plan["Rentabilidad %"] = tabla_plan["rentabilidad_pct"] * 100
            tabla_plan["Rentabilidad €"] = tabla_plan["rentabilidad_eur"]
            tabla_plan["Importe actual €"] = tabla_plan["importe_actual"]
            tabla_plan["Importe objetivo €"] = tabla_plan["importe_objetivo_aportacion"]
            tabla_plan["Aportación necesaria €"] = tabla_plan["aportacion_necesaria"]

            if mostrar_solo_reforzar:
                tabla_plan = tabla_plan[tabla_plan["Aportación necesaria €"] > 0].copy()

            tabla_plan = tabla_plan[
                [
                    "Fondo", "Tipo", "Importe actual €", "Rentabilidad €", "Rentabilidad %",
                    "Peso actual %", "Peso objetivo %", "Importe objetivo €",
                    "Aportación necesaria €", "prioridad"
                ]
            ].rename(columns={"prioridad": "Prioridad"})

            st.subheader("Tabla principal de aportaciones")
            st.dataframe(
                tabla_plan,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Importe actual €": st.column_config.NumberColumn(format="%.2f"),
                    "Rentabilidad €": st.column_config.NumberColumn(format="%+.2f"),
                    "Rentabilidad %": st.column_config.NumberColumn(format="%+.2f%%"),
                    "Peso actual %": st.column_config.NumberColumn(format="%.2f"),
                    "Peso objetivo %": st.column_config.NumberColumn(format="%.2f"),
                    "Importe objetivo €": st.column_config.NumberColumn(format="%.2f"),
                    "Aportación necesaria €": st.column_config.NumberColumn(format="%.2f"),
                },
            )

            st.subheader("Ranking de aportación necesaria")
            ranking = plan_df.sort_values("aportacion_necesaria", ascending=False).copy()
            if mostrar_solo_reforzar:
                ranking = ranking[ranking["aportacion_necesaria"] > 0].copy()
            fig_rank = go.Figure(
                go.Bar(
                    x=ranking["aportacion_necesaria"],
                    y=ranking["Fondo"],
                    orientation="h",
                    marker_color="#1f77b4",
                    text=[format_eur(v) for v in ranking["aportacion_necesaria"]],
                    textposition="outside",
                )
            )
            fig_rank.update_layout(
                xaxis_title="Aportación necesaria (€)",
                yaxis_title="Fondo",
                margin=dict(t=30, b=30, l=30, r=30),
                yaxis=dict(autorange="reversed"),
            )
            st.plotly_chart(fig_rank, use_container_width=True)

    except Exception as e:
        st.error(f"Error inesperado: {e}")
        st.stop()


# ============================================================
# BLOQUE 8 — Página: Presupuesto y cash flow
# ============================================================
elif pagina == "💶 Presupuesto y cash flow":
    st.title("💶 Presupuesto y cash flow")
    try:
        presupuesto_df = load_presupuesto()
        pres = calc_presupuesto(presupuesto_df)

        # BLOQUE 1 — KPIs principales (rejilla 3x2 para mantener alineación visual)
        tasa = (pres["ahorro_anual"] / pres["ingreso_anual"] * 100) if pres["ingreso_anual"] > 0 else 0.0

        fila_1 = st.columns(3)
        with fila_1[0]:
            st.metric("Ingreso anual", format_eur(pres["ingreso_anual"]))
        with fila_1[1]:
            st.metric("Gasto anual", format_eur(pres["gasto_anual"]))
        with fila_1[2]:
            st.metric("Ahorro anual", format_eur(pres["ahorro_anual"]))

        fila_2 = st.columns(3)
        with fila_2[0]:
            st.metric(
                "Ahorro mensual base",
                format_eur(pres["ahorro_mensual_base"]),
                help="Ahorro típico de un mes ordinario sin pagas extra.",
            )
        with fila_2[1]:
            st.metric(
                "Ahorro mensual medio anual",
                format_eur(pres["ahorro_mensual_medio"]),
                help=(
                    "Se calcula como: ahorro anual ÷ 12 "
                    "(incluye el efecto de las pagas extra repartido en todo el año)."
                ),
            )
        with fila_2[2]:
            st.metric(
                "Tasa de ahorro",
                f"{tasa:.1f}%",
                help="Porcentaje de tus ingresos anuales que ahorras. Objetivo recomendado: >20%",
            )

        # BLOQUE 2 — Tablas de ingresos y gastos
        st.markdown("---")
        col_ing, col_gas = st.columns(2)

        with col_ing:
            st.subheader("Ingresos")
            st.dataframe(
                pres["ingresos_df"].rename(columns={"concepto": "Concepto", "importe": "Importe (€)"}),
                use_container_width=True,
                hide_index=True,
            )

        with col_gas:
            st.subheader("Gastos mensuales")
            st.dataframe(
                pres["gastos_df"].rename(columns={"concepto": "Concepto", "importe": "Importe (€)"}),
                use_container_width=True,
                hide_index=True,
            )

        # BLOQUE 5 — Waterfall anual
        st.subheader("Waterfall: flujo anual de caja")
        fig_wf = go.Figure(
            go.Waterfall(
                name="Cash flow anual",
                orientation="v",
                measure=["relative", "relative", "relative", "total"],
                x=["Nómina anual", "Pagas extra", "Gastos fijos anuales", "Ahorro neto anual"],
                y=[pres["nomina_anual"], pres["pagas_anual"], -pres["gasto_anual"], 0],
                text=[
                    format_eur(pres["nomina_anual"]),
                    format_eur(pres["pagas_anual"]),
                    f'-{format_eur(pres["gasto_anual"])}',
                    format_eur(pres["ahorro_anual"]),
                ],
                textposition="outside",
                increasing={"marker": {"color": "#2ca02c"}},
                decreasing={"marker": {"color": "#d62728"}},
                totals={"marker": {"color": "#1f77b4"}},
                connector={"line": {"color": "rgb(63, 63, 63)"}},
            )
        )
        fig_wf.update_layout(
            yaxis_title="Euros (€)",
            margin=dict(t=40, b=40, l=40, r=40),
            waterfallgap=0.3,
        )
        st.plotly_chart(fig_wf, use_container_width=True)

        # BLOQUE 6 — Tabla de ahorro mensual real
        st.subheader("Ahorro real de cada mes del año")
        st.dataframe(
            pres["detalle_mensual_df"],
            use_container_width=True,
            hide_index=True,
            column_config={
                "Ingreso del mes": st.column_config.NumberColumn(format="%.2f"),
                "Gasto del mes": st.column_config.NumberColumn(format="%.2f"),
                "Ahorro del mes": st.column_config.NumberColumn(format="%.2f"),
            },
        )

        # BLOQUE 7 — Gráfico mensual de ahorro real
        st.subheader("Gráfico mensual de ahorro real")
        fig_ahorro_mes = px.bar(
            pres["detalle_mensual_df"],
            x="Mes",
            y="Ahorro del mes",
            color="Tipo de mes",
            category_orders={"Mes": MONTHS_ORDER},
            color_discrete_map={
                "Mes normal": "#1f77b4",
                "Mes con paga extra": "#2ca02c",
            },
            labels={"Ahorro del mes": "Ahorro del mes (€)"},
        )
        fig_ahorro_mes.update_layout(margin=dict(t=30, b=30, l=30, r=30), legend_title_text="")
        st.plotly_chart(fig_ahorro_mes, use_container_width=True)

        # BLOQUE 8 — Texto de apoyo
        st.caption(
            "El ahorro mensual base refleja un mes ordinario sin pagas extra. "
            "Junio y diciembre incluyen su paga extra correspondiente. "
            "El ahorro mensual medio anual es solo una media y no representa la disponibilidad real de todos los meses."
        )

    except Exception as e:
        st.error(f"Error inesperado: {e}")
        st.stop()


# ============================================================
# BLOQUE 9 — Página: Proyección / escenarios
# ============================================================
elif pagina == "📈 Proyección / escenarios":
    st.title("📈 Proyección / escenarios")

    try:
        cartera_actual_df = load_cartera_actual()
        patrimonio_df = load_patrimonio()
        presupuesto_df = load_presupuesto()

        pres = calc_presupuesto(presupuesto_df)
        patrimonio_total = calc_patrimonio_total(patrimonio_df)
        cartera_inicial = cartera_actual_df["Importe actual"].sum()
        ahorros_mensuales = calc_ahorro_mensual_real(pres)

        # Controles en sidebar
        with st.sidebar:
            st.markdown("---")
            st.subheader("Parámetros de proyección")
            rent_base = st.slider(
                "Rentabilidad anual esperada sobre cartera (%)",
                min_value=0.0,
                max_value=15.0,
                step=0.1,
                value=3.0,
                help="Se aplica solo sobre el dinero invertido en fondos, no sobre la liquidez en cuentas"
            )
            pct_invertido = st.slider(
                "% del ahorro mensual que inviertes",
                min_value=0,
                max_value=100,
                step=5,
                value=50,
                format="%d%%",
                help="El resto del ahorro se acumula como liquidez en cuentas"
            ) / 100.0

        horizonte = st.radio(
            "Horizonte temporal",
            [5, 10, 20],
            format_func=lambda x: f"{x} años",
            horizontal=True,
        )

        # Mostrar ahorro mensual real por mes como referencia
        with st.expander("Ver ahorro mensual estimado por mes"):
            nombres_meses = ["Ene","Feb","Mar","Abr","May","Jun","Jul","Ago","Sep","Oct","Nov","Dic"]
            df_ahorros = pd.DataFrame({
                "Mes": nombres_meses,
                "Ahorro estimado": [format_eur(a) for a in ahorros_mensuales],
            })
            st.dataframe(df_ahorros, hide_index=True, use_container_width=True)
            st.caption(f"Ahorro medio mensual: {format_eur(sum(ahorros_mensuales)/12)} · "
                      f"De ese ahorro, inviertes el {pct_invertido*100:.0f}% "
                      f"({format_eur(sum(ahorros_mensuales)/12 * pct_invertido)}/mes de media)")

        rent_opt = rent_base + 2.0
        rent_pes = max(rent_base - 2.0, 0.0)

        df_base = calc_proyeccion_patrimonio(patrimonio_total, cartera_inicial, ahorros_mensuales, pct_invertido, rent_base, horizonte)
        df_opt  = calc_proyeccion_patrimonio(patrimonio_total, cartera_inicial, ahorros_mensuales, pct_invertido, rent_opt, horizonte)
        df_pes  = calc_proyeccion_patrimonio(patrimonio_total, cartera_inicial, ahorros_mensuales, pct_invertido, rent_pes, horizonte)

        # Gráfico escenarios
        st.subheader("Evolución del patrimonio total")
        fig_proy = go.Figure()

        fig_proy.add_trace(go.Scatter(
            x=df_opt["año"].tolist() + df_pes["año"].tolist()[::-1],
            y=df_opt["patrimonio"].tolist() + df_pes["patrimonio"].tolist()[::-1],
            fill="toself",
            fillcolor="rgba(128,128,128,0.1)",
            line=dict(color="rgba(255,255,255,0)"),
            showlegend=False,
            hoverinfo="skip",
        ))
        fig_proy.add_trace(go.Scatter(
            x=df_pes["año"], y=df_pes["patrimonio"],
            mode="lines", name=f"Pesimista ({rent_pes:.1f}%)",
            line=dict(color="#d62728", dash="dash"),
        ))
        fig_proy.add_trace(go.Scatter(
            x=df_base["año"], y=df_base["patrimonio"],
            mode="lines", name=f"Base ({rent_base:.1f}%)",
            line=dict(color="#1f77b4", width=2),
        ))
        fig_proy.add_trace(go.Scatter(
            x=df_opt["año"], y=df_opt["patrimonio"],
            mode="lines", name=f"Optimista ({rent_opt:.1f}%)",
            line=dict(color="#2ca02c", dash="dash"),
        ))
        fig_proy.update_layout(
            xaxis_title="Años",
            yaxis_title="Patrimonio total (€)",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(t=60, b=40, l=40, r=40),
        )
        st.plotly_chart(fig_proy, use_container_width=True)

        # Tabla resumen escenarios
        st.subheader("Patrimonio final por escenario")
        resumen_rows = []
        for h in [5, 10, 20]:
            d_b = calc_proyeccion_patrimonio(patrimonio_total, cartera_inicial, ahorros_mensuales, pct_invertido, rent_base, h)
            d_o = calc_proyeccion_patrimonio(patrimonio_total, cartera_inicial, ahorros_mensuales, pct_invertido, rent_opt, h)
            d_p = calc_proyeccion_patrimonio(patrimonio_total, cartera_inicial, ahorros_mensuales, pct_invertido, rent_pes, h)
            resumen_rows.append({
                "Horizonte": f"{h} años",
                f"Pesimista ({rent_pes:.1f}%)": format_eur(d_p.iloc[-1]["patrimonio"]),
                f"Base ({rent_base:.1f}%)": format_eur(d_b.iloc[-1]["patrimonio"]),
                f"Optimista ({rent_opt:.1f}%)": format_eur(d_o.iloc[-1]["patrimonio"]),
            })
        st.dataframe(pd.DataFrame(resumen_rows), hide_index=True, use_container_width=True)

        # Gráfico desglose capital propio vs rentabilidad
        st.subheader("¿De dónde viene el crecimiento?")
        st.caption("Escenario base — capital que tú aportas vs rentabilidad generada por la inversión")

        fig_desglose = go.Figure()
        fig_desglose.add_trace(go.Scatter(
            x=df_base["año"], y=df_base["capital_propio"],
            mode="lines", name="Capital propio (inicial + ahorros)",
            line=dict(color="#1f77b4", width=0),
            fill="tozeroy", fillcolor="rgba(31,119,180,0.4)",
            stackgroup="uno",
        ))
        fig_desglose.add_trace(go.Scatter(
            x=df_base["año"], y=df_base["rentabilidad_generada"],
            mode="lines", name="Rentabilidad generada",
            line=dict(color="#2ca02c", width=0),
            fill="tonexty", fillcolor="rgba(44,160,44,0.4)",
            stackgroup="uno",
        ))
        fig_desglose.update_layout(
            xaxis_title="Años",
            yaxis_title="Patrimonio (€)",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(t=60, b=40, l=40, r=40),
            hovermode="x unified",
        )
        st.plotly_chart(fig_desglose, use_container_width=True)

        # KPIs finales
        ultimo = df_base.iloc[-1]
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Patrimonio final (base)", format_eur(ultimo["patrimonio"]),
                help=f"Valor total al cabo de {horizonte} años en escenario base")
        with col2:
            st.metric("Capital propio aportado", format_eur(ultimo["capital_propio"]),
                help="Tu patrimonio inicial más todos los ahorros acumulados")
        with col3:
            st.metric("Rentabilidad generada", format_eur(ultimo["rentabilidad_generada"]),
                help="Lo que ha crecido tu dinero gracias al interés compuesto")

        # Años hasta objetivo
        st.subheader("¿Cuándo alcanzarás tu objetivo?")
        objetivo_val = st.number_input(
            "Patrimonio objetivo (€)",
            min_value=0.0,
            value=float(int(patrimonio_total * 2 / 1000) * 1000),
            step=1000.0,
            format="%.0f",
        )
        superado = df_base[df_base["patrimonio"] >= objetivo_val]
        if patrimonio_total >= objetivo_val:
            st.success("¡Ya has alcanzado ese objetivo!")
        elif not superado.empty:
            mes_objetivo = int(superado.iloc[0]["mes"])
            anos_obj = mes_objetivo // 12
            meses_obj = mes_objetivo % 12
            st.metric(
                f"Años hasta {format_eur(objetivo_val)} (escenario base)",
                f"{anos_obj} años y {meses_obj} meses",
            )
        else:
            st.warning(f"No se alcanza {format_eur(objetivo_val)} en {horizonte} años con estos parámetros.")

    except Exception as e:
        st.error(f"Error inesperado en Proyección: {e}")
        st.stop()
