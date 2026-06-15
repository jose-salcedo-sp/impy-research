# IMPI Marcanet Scraper

Batch scraper for [IMPI Marcanet](https://acervomarcas.impi.gob.mx:8181/marcanet/) trademark search. Given a CSV of brand names with either a **registro** or **expediente** ID, it fetches trámites, oficios, and promociones and returns structured JSON.

Uses direct HTTP requests against IMPI's JSF partial-AJAX endpoints — no browser or Selenium required.

## Features

- Search by **Registro Nacional** or **Expediente**
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

## CSV format

| nombre    | registro | expediente |
|-----------|----------|------------|
| EMPRESA A | 1284458  |            |
| EMPRESA B |          | 3326572    |

- **nombre** — brand or company name (required, for labeling results)
- **registro** or **expediente** — provide one per row, not both (if both are present, registro is used)

See `input.csv` for an example.

## Usage

### CLI

```bash
python main.py
```

Reads `input.csv` by default and prints JSON results to stdout.

### Streamlit UI

```bash
streamlit run app.py
```

Upload a CSV, run the scraper, browse results, and download JSON.

### Programmatic

```python
from main import IMPIMarcoScraper

scraper = IMPIMarcoScraper()
results = scraper.run("input.csv")
```

## Output

Each brand produces a JSON object like:

```json
{
  "marca": {
    "nombre": "EMPRESA A",
    "busqueda": { "por": "registro", "registro": "1284458" }
  },
  "tramites": [
    {
      "indice": 0,
      "resumen": {
        "expediente": "123567",
        "ano": "2025",
        "tipo_tramite": "TRAMITE MIXTO",
        "fecha": "28/03/2025"
      },
      "detalle": {
        "oficios": [...],
        "promociones": [...]
      }
    }
  ],
  "resumen": {
    "total_tramites": 4,
    "total_oficios": 5,
    "total_promociones": 4
  }
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
