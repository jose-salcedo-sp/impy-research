# IMPI Marcanet Scraper

Batch scraper for [IMPI Marcanet](https://acervomarcas.impi.gob.mx:8181/marcanet/) trademark search. Reads a [Google Sheets portfolio](https://docs.google.com/spreadsheets/d/1FZH0VgdxXdmUqIKlxwDsnNeFNiyYdns_TD9U-jAPSGo/edit) — each sheet is parsed for **Denominación** plus **Registro** or **Expediente**, then trámites, oficios, and promociones are fetched as structured JSON.

Uses direct HTTP requests against IMPI's JSF partial-AJAX endpoints — no browser or Selenium required.

## Features

- Read multi-sheet portfolios from Google Sheets (`Denominación`, `Número de registro`, `Número de expediente`)
- Preview brands grouped by sheet name before running
- Select which workbook sheets to search before running the extractor
- Search by **Registro Nacional** or **Expediente** (Registro wins when both are present)
- Search the **phonetic database** by `Denominación` and `Clase`
- Extract trámite summaries from the results table
- Fetch **Oficios** and **Promociones** detail for each trámite
- CLI runner (`main.py`) and Streamlit web UI (`app.py`)
- Progress callbacks for batch runs

## Requirements

- Python 3.10+
- Network access to `acervomarcas.impi.gob.mx:8181`

## Setup

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Input format

### Google Sheets portfolio

The scraper reads from a shared Google Sheet (default: [portfolio workbook](https://docs.google.com/spreadsheets/d/1FZH0VgdxXdmUqIKlxwDsnNeFNiyYdns_TD9U-jAPSGo/edit)). Override the sheet with the `GOOGLE_SHEET_ID` environment variable. The sheet is re-fetched on every run.

Each tab should include:

| Denominación | Número de registro | Número de expediente |
|--------------|--------------------|----------------------|
| EL MOLINO ADITIVOS ALIMENTICIOS | 1284458 | |
| ETERIA | | 3326572 |

- **Denominación** — brand name (required)
- **Número de registro** or **Número de expediente** — provide at least one per row
- If both IDs are present, **Registro** is always used
- Sheets without a Denominación column are skipped

The Streamlit UI shows a **preview tab per selected sheet** before scraping. Use **Hojas a buscar** to include or exclude workbook tabs; only the selected sheets are sent to Marcanet.

## Usage

### CLI

```bash
python main.py
```

Fetches the Google Sheet portfolio and prints JSON results to stdout.

Phonetic search:

```bash
python main.py --fonetica eteria --clase 41
```

`--clase` defaults to `41`.

### Streamlit UI

```bash
streamlit run app.py
```

Loads the Google Sheet portfolio, lets you pick which sheets to search, then run the scraper, browse results, and download JSON. The **Búsqueda fonética** tab runs a phonetic search by denomination and class.

### Programmatic

```python
from main import IMPIMarcoScraper

scraper = IMPIMarcoScraper()
results = scraper.run_google_sheet()

# Phonetic search
hits = scraper.search_by_fonetica("eteria", "41")
```

## Phonetic search

`search_by_fonetica(denominacion, clase, ventana_dias=30)` returns the hits
that pass two filters. Each hit has `numero`, `tipo_solicitud`, `tipo_marca`,
`titular`, `expediente`, `denominacion`, `clase`, `numero_registro`,
`fecha_presentacion`, `fecha_publicacion`, and `fecha_publicacion_valida`.

| Filter | Rule |
|---|---|
| Registro | Drop every row whose `Registro` cell is not empty |
| Publication date | Drop every row whose `Fecha de publicación de la solicitud` is older than `ventana_dias` |

A row with no publication date is kept, because the absence of a date is not
evidence that the publication is old.

The date lives on the expediente detail page, not in the result table. The
method therefore loads one detail page per kept row. Each detail page carries
`Número de registro`, `Fecha de presentación`, and `Fecha de publicación de la
solicitud`.

### Protocol facts

1. Each search needs a new `GET` of the phonetic page. The server replays the
   previous result when the client reuses a `ViewState`.
2. The result table holds at most 300 rows.
3. IMPI answers a rate-limited request with HTTP 200 and an error page. The
   page holds the text `Has superado la cuota máxima de peticiones`. The code
   raises `CuotaExcedidaError` on this page. Wait about 10 minutes.
4. One search reads one page per row. A search on a common name reads about
   60 short pages.

## Output

Each brand produces a JSON object grouped by sheet:

```json
{
  "hojas": [
    {
      "hoja": "PORTAFOLIO REG",
      "marcas": [
        {
          "marca": {
            "denominacion": "EL MOLINO ADITIVOS ALIMENTICIOS",
            "hoja": "PORTAFOLIO REG",
            "busqueda": { "por": "registro", "registro": "1284458" }
          },
          "tramites": [...],
          "resumen": { "total_tramites": 4, "total_oficios": 5, "total_promociones": 4 }
        }
      ],
      "resumen": { "total_marcas": 10, "total_tramites": 30, "total_oficios": 45, "total_promociones": 12 }
    }
  ],
  "resumen": { "total_hojas": 7, "total_marcas": 39, "total_tramites": 120, "total_oficios": 200, "total_promociones": 50 }
}
```

## How it works

1. **GET** the Marcanet dashboard to obtain a session cookie and JSF `ViewState`
2. **POST** a partial-AJAX search (registro or expediente)
3. **GET** the detail page redirected after search
4. **POST** each trámite's detail button to load Oficios/Promociones modal data
5. Parse HTML/XML responses with BeautifulSoup

## Disclaimer

This tool automates public IMPI Marcanet lookups for research and internal use. Respect IMPI's terms of service and avoid excessive request rates.
