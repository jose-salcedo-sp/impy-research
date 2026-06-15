# IMPI Marcanet Scraper

Batch scraper for [IMPI Marcanet](https://acervomarcas.impi.gob.mx:8181/marcanet/) trademark search. Upload a portfolio Excel workbook (e.g. `PORTAFOLIO F&F.xlsx`) or CSV — each sheet is parsed for **Denominación** plus **Registro** or **Expediente**, then trámites, oficios, and promociones are fetched as structured JSON.

Uses direct HTTP requests against IMPI's JSF partial-AJAX endpoints — no browser or Selenium required.

## Features

- Parse multi-sheet Excel portfolios (`Denominación`, `Número de registro`, `Número de expediente`)
- Preview brands grouped by sheet name before running
- Search by **Registro Nacional** or **Expediente** (Registro wins when both are present)
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

### Excel portfolio (recommended)

Upload a `.xlsx` workbook such as `PORTAFOLIO F&F.xlsx`. Each sheet should include:

| Denominación | Número de registro | Número de expediente |
|--------------|--------------------|----------------------|
| EL MOLINO ADITIVOS ALIMENTICIOS | 1284458 | |
| ETERIA | | 3326572 |

- **Denominación** — brand name (required)
- **Número de registro** or **Número de expediente** — provide at least one per row
- If both IDs are present, **Registro** is always used
- Sheets without a Denominación column are skipped

The Streamlit UI shows a **preview tab per sheet** before scraping.

### CSV

| denominacion | registro | expediente |
|--------------|----------|------------|
| EMPRESA A | 1284458 | |
| EMPRESA B | | 3326572 |

Also accepts `nombre` instead of `denominacion`. See `input.csv` for an example.

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
