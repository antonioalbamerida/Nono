# ============================================================
# BLOQUE 1 — Imports y configuración
# ============================================================
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

st.set_page_config(page_title="nONO Dashboard", layout="wide")


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
        validate_columns(
            df,
            ["Fondo", "ISIN", "Tipo de activo", "Importe inicial ", "Importe actual",
             "Rentabilidad %", "Rentabilidad en Euros"],
            "informe cartera",
        )
        for col in ["Importe inicial ", "Importe actual", "Rentabilidad %", "Rentabilidad en Euros"]:
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
    "Mixto flexible Conservador": "Mixto",
    "Mixto flexible Agresivo": "Mixto",
    "Renta variable global": "Renta Variable",
    "Renta variable USA": "Renta Variable",
    "Renta variable Europa": "Renta Variable",
    "Renta variable small caps": "Renta Variable",
}


def calc_resumen_cartera(cartera_df: pd.DataFrame) -> dict:
    """Devuelve dict con: total_inicial, total_actual, rentabilidad_eur, rentabilidad_pct, por_tipo, por_tipo_agrupado"""
    total_inicial = cartera_df["Importe inicial "].sum()
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


def calc_comparacion_cartera(actual_df: pd.DataFrame, objetivo_df: pd.DataFrame) -> pd.DataFrame:
    """
    Merge actual vs objetivo por ISIN.
    peso_actual se recalcula desde cero (importe_actual / total_actual).
    No se usa la columna Peso actual del Excel para evitar inconsistencias.
    """
    total_actual = actual_df["Importe actual"].sum()

    act = actual_df[["ISIN", "Fondo", "Tipo de activo", "Importe actual"]].copy()
    act.columns = ["ISIN", "Fondo", "Tipo", "importe_actual"]

    obj = objetivo_df[["ISIN", "Peso"]].copy()
    obj.columns = ["ISIN", "peso_objetivo"]

    merged = act.merge(obj, on="ISIN", how="outer")
    merged["importe_actual"] = merged["importe_actual"].fillna(0)
    merged["peso_objetivo"] = merged["peso_objetivo"].fillna(0)

    # Recalcular peso_actual desde cero
    merged["peso_actual"] = merged["importe_actual"] / total_actual if total_actual > 0 else 0.0

    # Para fondos solo en objetivo, recuperar nombre y tipo
    for idx, row in merged[merged["Fondo"].isna()].iterrows():
        match = objetivo_df[objetivo_df["ISIN"] == row["ISIN"]]
        if not match.empty:
            merged.at[idx, "Fondo"] = match.iloc[0]["Fondo"]
            merged.at[idx, "Tipo"] = match.iloc[0]["Tipo de activo"]

    merged["desviacion"] = merged["peso_actual"] - merged["peso_objetivo"]
    merged["importe_objetivo"] = merged["peso_objetivo"] * total_actual
    merged["accion_eur"] = merged["importe_objetivo"] - merged["importe_actual"]

    return merged.sort_values("peso_objetivo", ascending=False).reset_index(drop=True)


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

    # Anualizar: nómina ×12, pagas ×1, gastos ×12
    nomina_anual = 0.0
    pagas_anual = 0.0
    for _, r in ingresos.iterrows():
        c = str(r["concepto"]).lower()
        if "nomina" in c or "nómina" in c:
            nomina_anual += r["importe"] * 12
        else:
            pagas_anual += r["importe"]

    ingreso_anual = nomina_anual + pagas_anual
    gasto_anual = gastos["importe"].sum() * 12
    ahorro_anual = ingreso_anual - gasto_anual
    ahorro_mensual = ahorro_anual / 12

    return {
        "ingresos_df": ingresos,
        "gastos_df": gastos,
        "nomina_anual": nomina_anual,
        "pagas_anual": pagas_anual,
        "ingreso_anual": ingreso_anual,
        "gasto_anual": gasto_anual,
        "ahorro_anual": ahorro_anual,
        "ahorro_mensual": ahorro_mensual,
    }


def calc_ahorro_mensual_real(presupuesto_dict: dict) -> list:
    """
    Devuelve una lista de 12 floats con el ahorro neto real de cada mes.
    Junio (índice 5) y Diciembre (índice 11) incluyen paga extra.
    Gastos fijos son iguales todos los meses.
    """
    nomina = presupuesto_dict["nomina_anual"] / 12
    paga_junio = presupuesto_dict["pagas_anual"] / 2   # asume 2 pagas iguales
    gasto_mensual = presupuesto_dict["gasto_anual"] / 12

    ahorros = []
    for mes in range(1, 13):
        ingreso = nomina
        if mes == 6:
            ingreso += paga_junio
        if mes == 12:
            ingreso += paga_junio
        ahorros.append(ingreso - gasto_mensual)
    return ahorros


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

            # Construir DataFrame combinando liquidez en cuentas + tipos de cartera
            cuentas_total = patrimonio_df["Importe"].sum() - resumen["total_actual"]

            por_tipo_agrupado = resumen["por_tipo_agrupado"].copy()

            # Añadir fila de liquidez en cuentas
            fila_liquidez = pd.DataFrame([{
                "Tipo agrupado": "Liquidez en cuentas",
                "Importe actual": cuentas_total
            }])
            por_tipo_completo = pd.concat([fila_liquidez, por_tipo_agrupado], ignore_index=True)
            # Filtrar categorías con importe > 0
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

        comp = calc_comparacion_cartera(cartera_actual_df, cartera_objetivo_df)

        # Preparar tabla de visualización
        tabla = comp.copy()
        tabla["Fondo_corto"] = tabla["Fondo"].astype(str).str[:35]
        tabla["Peso actual %"] = (tabla["peso_actual"] * 100).round(2)
        tabla["Peso objetivo %"] = (tabla["peso_objetivo"] * 100).round(2)
        tabla["Desviación pp"] = (tabla["desviacion"] * 100).round(2)
        tabla["Importe actual €"] = tabla["importe_actual"].round(2)
        tabla["Acción"] = tabla["accion_eur"].apply(
            lambda x: f"Comprar {format_eur(abs(x))}" if x > 0 else (f"Vender {format_eur(abs(x))}" if x < 0 else "—")
        )

        display_cols = ["Fondo_corto", "Tipo", "Peso actual %", "Peso objetivo %", "Desviación pp", "Importe actual €", "Acción"]
        display_df = tabla[display_cols].rename(columns={"Fondo_corto": "Fondo"})

        st.subheader("Comparativa de pesos")
        st.dataframe(
            display_df,
            use_container_width=True,
            column_config={
                "Desviación pp": st.column_config.NumberColumn(
                    "Desviación pp",
                    format="%.2f",
                    help="> +2pp: sobreponderar | < -2pp: infraponderar",
                ),
            },
            hide_index=True,
        )

        n_sobre = int((comp["desviacion"] > 0.02).sum())
        n_infra = int((comp["desviacion"] < -0.02).sum())
        total_comprar = comp.loc[comp["accion_eur"] > 0, "accion_eur"].sum()
        total_vender = comp.loc[comp["accion_eur"] < 0, "accion_eur"].abs().sum()
        st.info(
            f"📊 **Resumen de rebalanceo:** {n_sobre} fondos sobreponderados · "
            f"{n_infra} infraponderados  \n"
            f"💰 Necesitas aportar **{format_eur(total_comprar)}** y "
            f"rotar **{format_eur(total_vender)}** para llegar al objetivo"
        )

        # Gráfico barras agrupadas
        st.subheader("Peso actual vs objetivo por fondo")
        fondos_cortos = tabla["Fondo_corto"].tolist()
        fig_comp = go.Figure()
        fig_comp.add_trace(
            go.Bar(
                name="Peso actual",
                x=fondos_cortos,
                y=(tabla["peso_actual"] * 100).tolist(),
                marker_color="#1f77b4",
            )
        )
        fig_comp.add_trace(
            go.Bar(
                name="Peso objetivo",
                x=fondos_cortos,
                y=(tabla["peso_objetivo"] * 100).tolist(),
                marker_color="#ff7f0e",
            )
        )
        fig_comp.update_layout(
            barmode="group",
            xaxis_title="Fondo",
            yaxis_title="Peso (%)",
            xaxis_tickangle=-45,
            margin=dict(t=30, b=120, l=40, r=40),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        )
        st.plotly_chart(fig_comp, use_container_width=True)

        st.subheader("Simulador: ¿cuánto necesitas para llegar al objetivo?")
        st.caption(
            "Calcula cuánto deberías tener en cada fondo según los pesos objetivo, "
            "para un tamaño de cartera determinado."
        )

        cartera_objetivo_total = cartera_objetivo_df["Importe"].sum()
        total_actual = cartera_actual_df["Importe actual"].sum()

        patrimonio_slider = st.slider(
            "Cartera objetivo total (€)",
            min_value=int(round(total_actual / 500) * 500),
            max_value=50000,
            step=500,
            value=int(round(cartera_objetivo_total / 500) * 500),
            help="Tamaño total de cartera al que quieres llegar. Por defecto, el objetivo definido en el Excel."
        )

        sim = comp.copy()
        sim["importe_objetivo_sim"] = sim["peso_objetivo"] * patrimonio_slider
        sim["aportacion_necesaria"] = sim["importe_objetivo_sim"] - sim["importe_actual"]
        sim["Fondo_corto"] = sim["Fondo"].astype(str).str[:35]

        sim_display = sim[["Fondo_corto", "Tipo", "importe_actual", "importe_objetivo_sim", "aportacion_necesaria"]].copy()
        sim_display.columns = ["Fondo", "Tipo", "Importe actual €", "Importe objetivo €", "Necesitas (€)"]
        sim_display = sim_display.round(2)

        total_necesario = sim["aportacion_necesaria"].clip(lower=0).sum()
        st.dataframe(sim_display, use_container_width=True, hide_index=True)
        st.info(
            f"Para llegar a una cartera de **{format_eur(patrimonio_slider)}** "
            f"necesitas aportar un total de **{format_eur(total_necesario)}** adicionales."
        )

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

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Ingreso anual", format_eur(pres["ingreso_anual"]))
        with col2:
            st.metric("Gasto anual", format_eur(pres["gasto_anual"]))
        with col3:
            st.metric("Ahorro anual", format_eur(pres["ahorro_anual"]))
        with col4:
            st.metric("Ahorro mensual", format_eur(pres["ahorro_mensual"]))

        tasa = (pres["ahorro_anual"] / pres["ingreso_anual"] * 100) if pres["ingreso_anual"] > 0 else 0.0
        _, col_tasa, _ = st.columns(3)
        with col_tasa:
            st.metric(
                "Tasa de ahorro",
                f"{tasa:.1f}%",
                help="Porcentaje de tus ingresos anuales que ahorras. Objetivo recomendado: >20%",
            )

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

        # Waterfall
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

        # Proyección ahorro acumulado 12 meses
        st.subheader("Proyección de ahorro acumulado (12 meses)")
        meses = list(range(1, 13))
        ahorro_acum = [pres["ahorro_mensual"] * m for m in meses]

        fig_area = px.area(
            x=meses,
            y=ahorro_acum,
            labels={"x": "Mes", "y": "Ahorro acumulado (€)"},
            color_discrete_sequence=["#1f77b4"],
        )
        fig_area.add_hline(
            y=pres["ahorro_anual"],
            line_dash="dot",
            line_color="#d62728",
            annotation_text=f"Objetivo anual: {format_eur(pres['ahorro_anual'])}",
            annotation_position="top right",
        )
        fig_area.update_layout(margin=dict(t=40, b=40, l=40, r=40))
        st.plotly_chart(fig_area, use_container_width=True)

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
