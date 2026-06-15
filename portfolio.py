import io
import re
from typing import BinaryIO

import pandas as pd

INVALID_ID_VALUES = {"", "-", "—", "n/a", "na", "none", "nan", "null"}

PREVIEW_COLUMNS = ["Denominación", "Registro", "Expediente"]


def _normalize_col_name(col: str) -> str:
    return re.sub(r"\s+", " ", str(col).strip().lower())


def _find_column(columns, pattern: str):
    for col in columns:
        if re.search(pattern, _normalize_col_name(col)):
            return col
    return None


def _find_header_row(raw: pd.DataFrame) -> int:
    for i in range(min(15, len(raw))):
        row = [_normalize_col_name(x) for x in raw.iloc[i]]
        if any("denominaci" in cell for cell in row):
            return i
    return 0


def _clean_text(value) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    text = str(value).strip()
    return "" if text.lower() == "nan" else text


def _clean_id(value) -> str:
    text = _clean_text(value)
    if _normalize_col_name(text) in INVALID_ID_VALUES:
        return ""
    if re.fullmatch(r"\d+\.0", text):
        return text[:-2]
    if re.fullmatch(r"\d+\.\d+", text):
        try:
            number = float(text)
            if number.is_integer():
                return str(int(number))
        except ValueError:
            pass
    return text


def _resolve_search_ids(registro: str, expediente: str) -> tuple[str, str]:
    registro = _clean_id(registro)
    expediente = _clean_id(expediente)
    if registro:
        return registro, ""
    return "", expediente


def _extract_brand_rows(df: pd.DataFrame, sheet_name: str) -> list[dict]:
    denom_col = _find_column(df.columns, r"denominaci")
    if not denom_col:
        return []

    reg_col = _find_column(df.columns, r"n[uú]mero de registro")
    exp_col = _find_column(df.columns, r"n[uú]mero de expediente")

    rows = []
    for row_num, row in df.iterrows():
        denominacion = _clean_text(row.get(denom_col, ""))
        registro_raw = _clean_text(row.get(reg_col, "")) if reg_col else ""
        expediente_raw = _clean_text(row.get(exp_col, "")) if exp_col else ""
        registro, expediente = _resolve_search_ids(registro_raw, expediente_raw)

        if not denominacion:
            continue
        if not registro and not expediente:
            continue

        rows.append({
            "hoja": sheet_name.strip(),
            "fila": int(row_num) + 1,
            "denominacion": denominacion,
            "registro": registro,
            "expediente": expediente,
        })
    return rows


def parse_excel(source: BinaryIO | bytes) -> dict[str, pd.DataFrame]:
    """
    Parse a portfolio Excel workbook into preview DataFrames keyed by sheet name.

    Each DataFrame contains Denominación, Registro, and Expediente columns.
    Sheets without a Denominación column are skipped.
    """
    if isinstance(source, bytes):
        source = io.BytesIO(source)

    workbook = pd.ExcelFile(source)
    previews: dict[str, pd.DataFrame] = {}

    for sheet_name in workbook.sheet_names:
        raw = pd.read_excel(workbook, sheet_name=sheet_name, dtype=str, header=None)
        if raw.empty:
            continue

        header_row = _find_header_row(raw)
        df = pd.read_excel(
            workbook,
            sheet_name=sheet_name,
            dtype=str,
            header=header_row,
        ).fillna("")

        brand_rows = _extract_brand_rows(df, sheet_name)
        if not brand_rows:
            continue

        previews[sheet_name.strip()] = pd.DataFrame(
            [
                {
                    "Denominación": row["denominacion"],
                    "Registro": row["registro"],
                    "Expediente": row["expediente"],
                }
                for row in brand_rows
            ],
            columns=PREVIEW_COLUMNS,
        )

    if not previews:
        raise ValueError(
            "No se encontraron hojas válidas. Cada hoja debe incluir Denominación y "
            "Número de registro o Número de expediente."
        )

    return previews


def excel_to_brand_batches(previews: dict[str, pd.DataFrame]) -> dict[str, list[dict]]:
    """Convert preview DataFrames into scraper input rows grouped by sheet."""
    batches: dict[str, list[dict]] = {}
    for sheet_name, df in previews.items():
        batches[sheet_name] = [
            {
                "hoja": sheet_name,
                "fila": index + 1,
                "denominacion": _clean_text(row["Denominación"]),
                "registro": _clean_id(row["Registro"]),
                "expediente": _clean_id(row["Expediente"]),
            }
            for index, row in df.iterrows()
        ]
    return batches


def parse_csv(source: BinaryIO | str) -> dict[str, pd.DataFrame]:
    """Parse a CSV file into a single-sheet preview dict."""
    df = pd.read_csv(source, dtype=str, keep_default_na=False)

    column_map = {_normalize_col_name(col): col for col in df.columns}
    denom_col = column_map.get("denominación") or column_map.get("denominacion")
    if not denom_col:
        denom_col = column_map.get("nombre")
    reg_col = next(
        (column_map[key] for key in column_map if re.search(r"registro", key)),
        None,
    )
    exp_col = next(
        (column_map[key] for key in column_map if re.search(r"expediente", key)),
        None,
    )

    if not denom_col:
        raise ValueError("El CSV debe incluir una columna Denominación (o nombre).")
    if not reg_col and not exp_col:
        raise ValueError("El CSV debe incluir columnas Registro y/o Expediente.")

    normalized = pd.DataFrame({
        "Denominación": df[denom_col],
        "Registro": df[reg_col] if reg_col else "",
        "Expediente": df[exp_col] if exp_col else "",
    }).fillna("")

    brand_rows = _extract_brand_rows(
        normalized.rename(columns={
            "Denominación": "Denominación",
            "Registro": "Número de registro",
            "Expediente": "Número de expediente",
        }),
        "CSV",
    )
    if not brand_rows:
        raise ValueError(
            "El CSV no contiene filas con Denominación y un ID de búsqueda."
        )

    preview = pd.DataFrame(
        [
            {
                "Denominación": row["denominacion"],
                "Registro": row["registro"],
                "Expediente": row["expediente"],
            }
            for row in brand_rows
        ],
        columns=PREVIEW_COLUMNS,
    )
    return {"CSV": preview}
