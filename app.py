import io
import html
import json

import pandas as pd
import streamlit as st

from main import IMPIMarcoScraper
from portfolio import excel_to_brand_batches, parse_csv, parse_excel

st.set_page_config(
    page_title="Extractor IMPI Marcanet",
    page_icon="®",
    layout="wide",
    initial_sidebar_state="collapsed",
)

APP_STYLES = """
<style>
[data-testid="stSidebar"] { display: none; }
[data-testid="stSidebarCollapsedControl"] { display: none; }
.search-pill {
    display: inline-block;
    padding: 0.35rem 0.9rem;
    border-radius: 999px;
    font-size: 0.875rem;
    font-weight: 600;
    margin: 0.25rem 0 0.75rem 0;
}
.stApp[data-theme="light"] .search-pill {
    background: #e8f0fe;
    color: #1557b0;
    border: 1px solid #c6dafc;
}
.stApp[data-theme="dark"] .search-pill {
    background: rgba(33, 102, 209, 0.22);
    color: #8ab4ff;
    border: 1px solid rgba(138, 180, 255, 0.35);
}
</style>
"""


def inject_styles():
    st.markdown(APP_STYLES, unsafe_allow_html=True)


def load_portfolio_previews(uploaded_file) -> tuple[dict[str, pd.DataFrame] | None, str | None]:
    filename = uploaded_file.name.lower()
    try:
        if filename.endswith(".xlsx"):
            return parse_excel(uploaded_file.getvalue()), None
        if filename.endswith(".csv"):
            text_stream = io.StringIO(uploaded_file.getvalue().decode("utf-8"))
            return parse_csv(text_stream), None
        return None, "Tipo de archivo no compatible. Sube un archivo .xlsx o .csv."
    except Exception as e:
        return None, str(e)


def render_search_pill(busqueda: dict):
    search_type = busqueda.get("por", "")
    value = busqueda.get(search_type, "—")
    if search_type == "registro":
        label = f"Registro: {value}"
    elif search_type == "expediente":
        label = f"Expediente: {value}"
    else:
        label = value
    st.markdown(
        f'<span class="search-pill">{html.escape(label)}</span>',
        unsafe_allow_html=True,
    )


def render_table(df: pd.DataFrame):
    if df.empty:
        st.caption("Sin registros.")
        return
    st.dataframe(df, use_container_width=True, hide_index=True)


def render_tramite(tramite: dict):
    resumen = tramite.get("resumen", {})
    label_parts = [
        resumen.get("tipo_tramite"),
        resumen.get("expediente"),
        resumen.get("fecha"),
    ]
    label = " · ".join(p for p in label_parts if p) or f"Trámite #{tramite.get('indice', '?')}"

    with st.expander(label, expanded=False):
        if tramite.get("error"):
            st.error(tramite["error"])

        cols = st.columns(4)
        cols[0].metric("Expediente", resumen.get("expediente", "—"))
        cols[1].metric("Año", resumen.get("ano", "—"))
        cols[2].metric("Fecha", resumen.get("fecha", "—"))
        cols[3].metric("Contacto", resumen.get("contacto", "—"))

        detalle = tramite.get("detalle", {})
        oficios = detalle.get("oficios", [])
        promociones = detalle.get("promociones", [])

        st.markdown("##### Oficios")
        if oficios:
            render_table(pd.DataFrame(oficios))
        else:
            st.caption("No se encontraron oficios.")

        st.markdown("##### Promociones")
        if promociones:
            render_table(pd.DataFrame(promociones))
        else:
            st.caption("No se encontraron promociones.")


def render_brand(brand: dict):
    marca = brand["marca"]
    denominacion = marca.get("denominacion") or marca.get("nombre", "—")
    busqueda = marca["busqueda"]
    resumen = brand.get("resumen", {})

    with st.container(border=True):
        st.subheader(denominacion)
        render_search_pill(busqueda)

        if brand.get("error"):
            st.error(brand["error"])

        meta_cols = st.columns(3)
        meta_cols[0].metric("Trámites", resumen.get("total_tramites", 0))
        meta_cols[1].metric("Oficios", resumen.get("total_oficios", 0))
        meta_cols[2].metric("Promociones", resumen.get("total_promociones", 0))

        tramites = brand.get("tramites", [])
        if not tramites:
            st.info("No se encontraron trámites con vista de detalle para esta marca.")
            return

        for tramite in tramites:
            render_tramite(tramite)


def render_sheet_preview(sheet_previews: dict[str, pd.DataFrame]):
    st.subheader("Vista previa por hoja")
    tabs = st.tabs(list(sheet_previews.keys()))
    for tab, sheet_name in zip(tabs, sheet_previews.keys()):
        with tab:
            df = sheet_previews[sheet_name]
            st.caption(f"{len(df)} marca(s) en `{sheet_name}`")
            render_table(df)


def render_results(results: dict):
    st.header("Resultados")

    overall = results.get("resumen", {})
    summary_cols = st.columns(5)
    summary_cols[0].metric("Hojas", overall.get("total_hojas", 0))
    summary_cols[1].metric("Marcas", overall.get("total_marcas", 0))
    summary_cols[2].metric("Trámites", overall.get("total_tramites", 0))
    summary_cols[3].metric("Oficios", overall.get("total_oficios", 0))
    summary_cols[4].metric("Promociones", overall.get("total_promociones", 0))

    st.download_button(
        label="Descargar JSON",
        data=json.dumps(results, indent=2, ensure_ascii=False),
        file_name="resultados_impi.json",
        mime="application/json",
    )

    with st.expander("JSON sin procesar", expanded=False):
        st.json(results)

    st.divider()

    for sheet in results.get("hojas", []):
        sheet_name = sheet["hoja"]
        sheet_summary = sheet.get("resumen", {})
        with st.container(border=True):
            st.subheader(sheet_name)
            meta_cols = st.columns(4)
            meta_cols[0].metric("Marcas", sheet_summary.get("total_marcas", 0))
            meta_cols[1].metric("Trámites", sheet_summary.get("total_tramites", 0))
            meta_cols[2].metric("Oficios", sheet_summary.get("total_oficios", 0))
            meta_cols[3].metric("Promociones", sheet_summary.get("total_promociones", 0))

            for brand in sheet.get("marcas", []):
                render_brand(brand)


def main():
    inject_styles()

    st.title("Extractor IMPI Marcanet")
    st.caption(
        "Sube un archivo Excel de portafolio (p. ej. `PORTAFOLIO F&F.xlsx`) o CSV. "
        "Cada hoja debe incluir `Denominación` y `Número de registro` o "
        "`Número de expediente` (si ambos están presentes, se usa Registro)."
    )

    uploaded = st.file_uploader("Subir archivo de portafolio", type=["xlsx", "csv"])

    if uploaded is None:
        st.info("Sube un archivo Excel o CSV para comenzar.")
        return

    previews, error = load_portfolio_previews(uploaded)
    if error:
        st.error(error)
        return

    render_sheet_preview(previews)

    total_brands = sum(len(df) for df in previews.values())
    run_clicked = st.button(
        f"Ejecutar extractor ({total_brands} marca(s) en {len(previews)} hoja(s))",
        type="primary",
        use_container_width=True,
    )

    if run_clicked:
        sheet_batches = excel_to_brand_batches(previews)

        progress_bar = st.progress(0, text="Iniciando…")
        status = st.empty()

        def on_progress(message: str, fraction: float):
            progress_bar.progress(min(max(fraction, 0.0), 1.0), text=message)
            status.caption(message)

        try:
            scraper = IMPIMarcoScraper()
            results = scraper.run_portfolio(
                sheet_batches,
                on_progress=on_progress,
            )
            st.session_state["results"] = results
            progress_bar.progress(1.0, text="Completado")
            status.success(
                f"Finalizado — {results['resumen']['total_marcas']} marca(s) "
                f"en {results['resumen']['total_hojas']} hoja(s)."
            )
        except Exception as e:
            progress_bar.empty()
            status.empty()
            st.error(f"Error en el extractor: {e}")
            return

    if "results" in st.session_state:
        render_results(st.session_state["results"])


if __name__ == "__main__":
    main()
