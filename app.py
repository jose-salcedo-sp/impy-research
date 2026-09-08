import html
import json

import pandas as pd
import streamlit as st

from main import IMPIMarcoScraper
from portfolio import GOOGLE_SHEET_URL, excel_to_brand_batches, load_google_sheet_previews

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
            st.info("No se encontraron promociones u oficios para esta marca.")
            return

        for tramite in tramites:
            render_tramite(tramite)


def fetch_sheet_previews() -> tuple[dict[str, pd.DataFrame] | None, str | None]:
    """Load previews from Google Sheets and store them in session state."""
    previews, error = load_google_sheet_previews()
    if not error and previews is not None:
        st.session_state["sheet_previews"] = previews
    return previews, error


def sync_sheet_selection(available: list[str]) -> None:
    """Keep selected sheets valid when the workbook is first loaded or refreshed."""
    known = st.session_state.get("preview_sheet_names")
    if known is None:
        st.session_state.selected_sheets = available
        st.session_state.preview_sheet_names = available
        return
    if known == available:
        return

    kept = [
        name
        for name in st.session_state.get("selected_sheets", [])
        if name in available
    ]
    added = [name for name in available if name not in known]
    st.session_state.selected_sheets = kept + added or list(available)
    st.session_state.preview_sheet_names = available


def render_sheet_selector(available: list[str]) -> list[str]:
    sync_sheet_selection(available)

    st.markdown("**Hojas a buscar**")
    st.caption("Elige las pestañas del portafolio que se enviarán al extractor.")

    select_col, all_col, none_col = st.columns([4, 1, 1])
    with all_col:
        st.button(
            "Todas",
            key="select_all_sheets",
            use_container_width=True,
            on_click=lambda: st.session_state.update(selected_sheets=list(available)),
        )
    with none_col:
        st.button(
            "Ninguna",
            key="select_no_sheets",
            use_container_width=True,
            on_click=lambda: st.session_state.update(selected_sheets=[]),
        )
    with select_col:
        selected = st.multiselect(
            "Hojas a buscar",
            options=available,
            key="selected_sheets",
            label_visibility="collapsed",
            help="Solo las hojas seleccionadas se buscan en Marcanet.",
        )

    if not selected:
        st.warning("Selecciona al menos una hoja para ejecutar el extractor.")
    return selected


def render_sheet_preview(sheet_previews: dict[str, pd.DataFrame]):
    if not sheet_previews:
        st.info("No hay hojas seleccionadas para previsualizar.")
        return
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
        "Lee el portafolio desde "
        f"[Google Sheets]({GOOGLE_SHEET_URL}). "
        "Cada hoja debe incluir `Denominación` y `Número de registro` o "
        "`Número de expediente` (si ambos están presentes, se usa Registro)."
    )

    header_col, refresh_col = st.columns([5, 1])
    with header_col:
        st.subheader("Vista previa por hoja")
    with refresh_col:
        refresh_clicked = st.button(
            "Actualizar hoja",
            use_container_width=True,
            help="Vuelve a leer el Google Sheet si hubo cambios.",
        )

    if refresh_clicked:
        with st.spinner("Actualizando portafolio desde Google Sheets…"):
            previews, error = fetch_sheet_previews()
    elif "sheet_previews" not in st.session_state:
        with st.spinner("Cargando portafolio desde Google Sheets…"):
            previews, error = fetch_sheet_previews()
    else:
        previews = st.session_state["sheet_previews"]
        error = None

    if error:
        st.error(error)
        if "sheet_previews" not in st.session_state:
            return

    previews = st.session_state["sheet_previews"]
    selected_names = render_sheet_selector(list(previews.keys()))
    selected_previews = {
        name: previews[name] for name in selected_names if name in previews
    }
    render_sheet_preview(selected_previews)

    total_brands = sum(len(df) for df in selected_previews.values())
    run_clicked = st.button(
        f"Ejecutar extractor ({total_brands} marca(s) en {len(selected_previews)} hoja(s))",
        type="primary",
        use_container_width=True,
        disabled=not selected_previews,
    )

    if run_clicked:
        sheet_batches = excel_to_brand_batches(selected_previews)

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
