import io
import html
import json

import pandas as pd
import streamlit as st

from main import IMPIMarcoScraper

st.set_page_config(
    page_title="IMPI Marcanet Scraper",
    page_icon="®",
    layout="wide",
)

REQUIRED_COLUMNS = {"nombre", "registro", "expediente"}

APP_STYLES = """
<style>
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


def validate_csv(uploaded_file) -> tuple[pd.DataFrame | None, str | None]:
    try:
        df = pd.read_csv(uploaded_file, dtype=str, keep_default_na=False)
    except Exception as e:
        return None, f"Could not read CSV: {e}"

    missing = REQUIRED_COLUMNS - set(df.columns)
    if missing:
        return None, f"Missing required columns: {', '.join(sorted(missing))}"

    return df, None


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
        st.caption("No records.")
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
            st.caption("No oficios found.")

        st.markdown("##### Promociones")
        if promociones:
            render_table(pd.DataFrame(promociones))
        else:
            st.caption("No promociones found.")


def render_brand(brand: dict):
    marca = brand["marca"]
    nombre = marca["nombre"]
    busqueda = marca["busqueda"]
    resumen = brand.get("resumen", {})

    with st.container(border=True):
        st.subheader(nombre)
        render_search_pill(busqueda)

        if brand.get("error"):
            st.error(brand["error"])

        meta_cols = st.columns(3)
        meta_cols[0].metric("Trámites", resumen.get("total_tramites", 0))
        meta_cols[1].metric("Oficios", resumen.get("total_oficios", 0))
        meta_cols[2].metric("Promociones", resumen.get("total_promociones", 0))

        tramites = brand.get("tramites", [])
        if not tramites:
            st.info("No trámites with detail views were found for this brand.")
            return

        for tramite in tramites:
            render_tramite(tramite)


def render_results(results: list[dict]):
    st.header("Results")

    total_tramites = sum(r.get("resumen", {}).get("total_tramites", 0) for r in results)
    total_oficios = sum(r.get("resumen", {}).get("total_oficios", 0) for r in results)
    total_promociones = sum(r.get("resumen", {}).get("total_promociones", 0) for r in results)

    summary_cols = st.columns(4)
    summary_cols[0].metric("Brands", len(results))
    summary_cols[1].metric("Trámites", total_tramites)
    summary_cols[2].metric("Oficios", total_oficios)
    summary_cols[3].metric("Promociones", total_promociones)

    st.download_button(
        label="Download JSON",
        data=json.dumps(results, indent=2, ensure_ascii=False),
        file_name="impi_results.json",
        mime="application/json",
    )

    with st.expander("Raw JSON", expanded=False):
        st.json(results)

    st.divider()

    for brand in results:
        render_brand(brand)


def main():
    inject_styles()

    st.title("IMPI Marcanet Scraper")
    st.caption(
        "Upload a CSV with columns `nombre`, `registro`, and `expediente`. "
        "Provide either `registro` or `expediente` per row (not both)."
    )

    with st.sidebar:
        st.header("Options")
        st.caption("Uses direct HTTP requests to IMPI (no browser required).")
        st.markdown(
            "**CSV format**\n\n"
            "| nombre | registro | expediente |\n"
            "|--------|----------|------------|\n"
            "| EMPRESA A | 1284458 | |\n"
            "| EMPRESA B | | 3326572 |"
        )

    uploaded = st.file_uploader("Upload CSV", type=["csv"])

    if uploaded is None:
        st.info("Upload a CSV file to get started.")
        return

    df, error = validate_csv(uploaded)
    if error:
        st.error(error)
        return

    st.subheader("CSV preview")
    render_table(df)

    run_clicked = st.button("Run scraper", type="primary", use_container_width=True)

    if run_clicked:
        csv_text = uploaded.getvalue().decode("utf-8")
        csv_stream = io.StringIO(csv_text)

        progress_bar = st.progress(0, text="Starting…")
        status = st.empty()

        def on_progress(message: str, fraction: float):
            progress_bar.progress(min(max(fraction, 0.0), 1.0), text=message)
            status.caption(message)

        try:
            scraper = IMPIMarcoScraper()
            results = scraper.run(
                csv_stream,
                on_progress=on_progress,
            )
            st.session_state["results"] = results
            progress_bar.progress(1.0, text="Complete")
            status.success(f"Finished — {len(results)} brand(s) processed.")
        except Exception as e:
            progress_bar.empty()
            status.empty()
            st.error(f"Scraper failed: {e}")
            return

    if "results" in st.session_state:
        render_results(st.session_state["results"])


if __name__ == "__main__":
    main()
