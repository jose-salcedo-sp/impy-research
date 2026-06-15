import csv
import re
import subprocess
import json
import requests
from bs4 import BeautifulSoup
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

USER_AGENT = (
    'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
    'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36'
)


class IMPIMarcoScraper:
    def __init__(self):
        self.dashboard_url = (
            "https://acervomarcas.impi.gob.mx:8181/marcanet/vistas/common/"
            "dashboard/marcanetDashboardBusquedas.pgi"
        )
        self.detail_url = (
            "https://acervomarcas.impi.gob.mx:8181/marcanet/vistas/common/"
            "busquedas/detalleExpedienteParcial.pgi"
        )
        self.session = None
        self._detail_view_state = None
        self._on_progress = None
        self._progress_current = 0
        self._progress_total = 1

    def _init_progress(self, on_progress, num_brands):
        self._on_progress = on_progress
        self._progress_current = 0
        # Each brand: session bootstrap, search, results summary, then one step per trámite
        self._progress_total = max(num_brands * 3, 1)

    def _report_progress(self, message, extra_total=0):
        if extra_total:
            self._progress_total += extra_total
        self._progress_current += 1
        if self._on_progress:
            fraction = min(self._progress_current / max(self._progress_total, 1), 1.0)
            self._on_progress(message, fraction)

    def _get_session(self):
        if self.session is None:
            self.session = requests.Session()
            self.session.headers.update({'User-Agent': USER_AGENT})
            logger.info("HTTP session initialized")
        return self.session

    @staticmethod
    def _extract_view_state(html):
        match = re.search(
            r'name="javax\.faces\.ViewState"[^>]*value="([^"]+)"', html
        )
        if not match:
            match = re.search(
                r'value="([^"]+)"[^>]*name="javax\.faces\.ViewState"', html
            )
        return match.group(1) if match else None

    def _ajax_headers(self, referer):
        return {
            'Accept': 'application/xml, text/xml, */*; q=0.01',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'Faces-Request': 'partial/ajax',
            'X-Requested-With': 'XMLHttpRequest',
            'Referer': referer,
            'Origin': 'https://acervomarcas.impi.gob.mx:8181',
        }

    def _fetch_dashboard_view_state(self):
        session = self._get_session()
        logger.info(f"Fetching session from {self.dashboard_url}")
        response = session.get(self.dashboard_url, timeout=60)
        response.raise_for_status()
        view_state = self._extract_view_state(response.text)
        if not view_state:
            raise RuntimeError("Could not extract javax.faces.ViewState from dashboard page")
        logger.info("Dashboard session ready")
        return view_state

    def _post_jsf_search(self, form_data, referer=None):
        session = self._get_session()
        referer = referer or self.dashboard_url
        response = session.post(
            self.dashboard_url,
            data=form_data,
            headers=self._ajax_headers(referer),
            timeout=60,
        )
        response.raise_for_status()
        if '<redirect url=' not in response.text:
            logger.warning("Search response did not include expected redirect")
        return response

    def _load_detail_page(self):
        session = self._get_session()
        response = session.get(
            self.detail_url,
            headers={'Referer': self.dashboard_url},
            timeout=60,
        )
        response.raise_for_status()
        self._detail_view_state = self._extract_view_state(response.text)
        if not self._detail_view_state:
            raise RuntimeError("Could not extract ViewState from detail page")
        logger.info("Detail page loaded")
        return response.text

    def search_by_registro(self, nombre, registro):
        """
        Search using registro field via JSF partial AJAX request.

        Args:
            nombre (str): Name to search (for reference)
            registro (str): Registro ID to search

        Returns:
            list: List of detail button info dicts found in results
        """
        try:
            logger.info(f"Searching for nombre='{nombre}', registro='{registro}'")
            view_state = self._fetch_dashboard_view_state()
            self._post_jsf_search({
                'javax.faces.partial.ajax': 'true',
                'javax.faces.source': 'frmBsqReg:busquedaId',
                'javax.faces.partial.execute': '@all',
                'javax.faces.partial.render': (
                    'frmBsqReg:pnlBsqRegistro frmBsqReg:dlgListaRegNac'
                ),
                'frmBsqReg:busquedaId': 'frmBsqReg:busquedaId',
                'frmBsqReg': 'frmBsqReg',
                'frmBsqReg:registroId': registro,
                'javax.faces.ViewState': view_state,
            })
            detail_html = self._load_detail_page()
            detail_buttons = self._parse_results_table(detail_html)
            logger.info(f"Found {len(detail_buttons)} detail buttons in results")
            return detail_buttons
        except Exception as e:
            logger.error(f"Error in search_by_registro: {e}")
            raise

    def search_by_expediente(self, nombre, expediente):
        """
        Search using expediente field via JSF partial AJAX request.

        Args:
            nombre (str): Name to search (for reference)
            expediente (str): Expediente ID to search

        Returns:
            list: List of detail button info dicts found in results
        """
        try:
            logger.info(f"Searching for nombre='{nombre}', expediente='{expediente}'")
            view_state = self._fetch_dashboard_view_state()
            self._post_jsf_search({
                'javax.faces.partial.ajax': 'true',
                'javax.faces.source': 'frmBsqExp:busquedaId2',
                'javax.faces.partial.execute': '@all',
                'javax.faces.partial.render': (
                    'frmBsqExp:pnlBsqExp frmBsqExp:dlgListaExpedientes'
                ),
                'frmBsqExp:busquedaId2': 'frmBsqExp:busquedaId2',
                'frmBsqExp': 'frmBsqExp',
                'frmBsqExp:expedienteId': expediente,
                'javax.faces.ViewState': view_state,
            })
            detail_html = self._load_detail_page()
            detail_buttons = self._parse_results_table(detail_html)
            logger.info(f"Found {len(detail_buttons)} detail buttons in results")
            return detail_buttons
        except Exception as e:
            logger.error(f"Error in search_by_expediente: {e}")
            raise

    def _parse_results_table(self, html):
        """
        Parse the detail page HTML and extract viewDetailBtn rows.

        Returns:
            list: List of dictionaries containing button info {id, row_index, row_data}
        """
        soup = BeautifulSoup(html, 'html.parser')
        results_div = soup.find(id='frmDetalleExp:dtTblTramitesId')
        if not results_div:
            raise RuntimeError("Results table frmDetalleExp:dtTblTramitesId not found")

        detail_buttons = []

        for row in results_div.find_all('tr'):
            button = row.find(id=re.compile(r'viewDetailBtn$'))
            if not button:
                continue

            button_id = button['id']
            index_match = re.search(r':(\d+):viewDetailBtn$', button_id)
            row_index = int(index_match.group(1)) if index_match else len(detail_buttons)

            cells = row.find_all('td')
            cell_texts = [c.get_text(strip=True) for c in cells]
            logger.info(f"Results row {row_index}: {[t for t in cell_texts if t]}")
            detail_buttons.append({
                'id': button_id,
                'row_index': row_index,
                'row_data': self._parse_result_row(cell_texts),
            })
            logger.info(f"Found viewDetailBtn at row {row_index}")

        logger.info(f"Total viewDetailBtn elements extracted: {len(detail_buttons)}")
        return detail_buttons

    def extract_detail_data(self, button_info, nombre):
        """
        Request modal data for a trámite via JSF partial AJAX.

        Args:
            button_info (dict): Dictionary with button info {id, row_index}
            nombre (str): Brand name for reference

        Returns:
            dict: Dictionary containing extracted modal data
        """
        row_index = button_info['row_index']
        source = button_info['id']

        try:
            logger.info(f"Fetching detail for viewDetailBtn at row {row_index}")
            if not self._detail_view_state:
                raise RuntimeError("Detail page ViewState not available; run a search first")

            session = self._get_session()
            response = session.post(
                self.detail_url,
                data={
                    'javax.faces.partial.ajax': 'true',
                    'javax.faces.source': source,
                    'javax.faces.partial.execute': '@all',
                    'javax.faces.partial.render': 'dlgListaDicProm frmDlgDicProm',
                    source: source,
                    'frmDetalleExp': 'frmDetalleExp',
                    'javax.faces.ViewState': self._detail_view_state,
                },
                headers=self._ajax_headers(self.detail_url),
                timeout=60,
            )
            response.raise_for_status()
            extracted_data = self._parse_modal_from_partial(response.text)
            logger.info(f"Successfully extracted data from row {row_index}")
            return extracted_data
        except Exception as e:
            logger.error(f"Error extracting detail data from row {row_index}: {e}")
            raise

    @staticmethod
    def _parse_modal_from_partial(xml_text):
        match = re.search(
            r'<update id="dlgListaDicProm"><!\[CDATA\[(.*)\]\]></update>',
            xml_text,
            re.DOTALL,
        )
        if not match:
            raise RuntimeError("Modal content not found in partial AJAX response")
        return IMPIMarcoScraper._parse_modal_data(match.group(1))

    def _parse_result_row(self, cell_texts):
        """Map results-table cells into a structured tramite summary."""
        non_empty = [t for t in cell_texts if t]
        row = {'celdas': cell_texts}
        if len(non_empty) >= 4:
            row.update({
                'expediente': non_empty[0],
                'ano': non_empty[1],
                'tipo_tramite': non_empty[2],
                'fecha': non_empty[3],
            })
            if len(non_empty) >= 5:
                row['contacto'] = non_empty[4]
        return row

    def _compile_brand_result(self, nombre, registro, expediente, tramites):
        """Compile all tramite records for one brand into a hierarchical dict."""
        search_type = 'registro' if registro else 'expediente'
        search_value = registro or expediente
        total_oficios = sum(len(t.get('detalle', {}).get('oficios', [])) for t in tramites)
        total_promociones = sum(
            len(t.get('detalle', {}).get('promociones', [])) for t in tramites
        )

        return {
            'marca': {
                'nombre': nombre,
                'busqueda': {
                    'por': search_type,
                    search_type: search_value,
                },
            },
            'tramites': tramites,
            'resumen': {
                'total_tramites': len(tramites),
                'total_oficios': total_oficios,
                'total_promociones': total_promociones,
            },
        }

    def _print_with_jq(self, data):
        """Pretty-print JSON to stdout using jq."""
        payload = json.dumps(data, ensure_ascii=False)
        try:
            result = subprocess.run(
                ['jq', '.'],
                input=payload,
                text=True,
                capture_output=True,
                check=True,
            )
            print(result.stdout, end='')
        except FileNotFoundError:
            logger.warning("jq not found, falling back to json.dumps")
            print(json.dumps(data, indent=2, ensure_ascii=False))
        except subprocess.CalledProcessError as e:
            logger.error(f"jq failed: {e.stderr}")
            print(json.dumps(data, indent=2, ensure_ascii=False))

    @staticmethod
    def _parse_modal_data(modal_html):
        """
        Parse modal HTML to extract Oficios and Promociones data.

        Args:
            modal_html (str): HTML content of the modal

        Returns:
            dict: Structured data with Oficios and Promociones
        """
        try:
            soup = BeautifulSoup(modal_html, 'html.parser')

            result = {
                'oficios': [],
                'promociones': []
            }

            oficios_tbody = soup.find('tbody', {'id': 'frmDlgDicProm:idTramitesSeltbl1_data'})
            if oficios_tbody:
                for row in oficios_tbody.find_all('tr', {'data-ri': True}):
                    cells = row.find_all('td')
                    if len(cells) >= 4:
                        oficio = {
                            'descripcion': cells[0].get_text(strip=True),
                            'numero_oficio': cells[1].get_text(strip=True),
                            'fecha_oficio': cells[2].get_text(strip=True),
                            'estado_notificacion': cells[3].get_text(strip=True)
                        }
                        result['oficios'].append(oficio)
                        logger.info(
                            f"Extracted oficio: {oficio['numero_oficio']} - {oficio['descripcion']}"
                        )

            promociones_tbody = soup.find('tbody', {'id': 'frmDlgDicProm:idTramitesSeltbl2_data'})
            if promociones_tbody:
                for row in promociones_tbody.find_all('tr', {'data-ri': True}):
                    cells = row.find_all('td')
                    if len(cells) >= 5:
                        promocion = {
                            'folio_entrada': cells[0].get_text(strip=True),
                            'ano_recepcion': cells[1].get_text(strip=True),
                            'fecha_presentacion': cells[2].get_text(strip=True),
                            'numero_oficio_relacionado': cells[3].get_text(strip=True),
                            'descripcion': cells[4].get_text(strip=True)
                        }
                        result['promociones'].append(promocion)
                        logger.info(
                            f"Extracted promocion: {promocion['folio_entrada']} - "
                            f"{promocion['descripcion']}"
                        )

            return result

        except Exception as e:
            logger.error(f"Error parsing modal data: {e}")
            raise

    def process_csv(self, csv_source, on_progress=None):
        """
        Process the input CSV file or file-like object.

        Args:
            csv_source: Path to CSV file or readable text stream
            on_progress: Optional callback(message: str, fraction: float)

        Returns:
            list: Compiled brand result dicts
        """
        results = []
        try:
            if isinstance(csv_source, str):
                csv_file = open(csv_source, 'r', encoding='utf-8')
                close_after = True
            else:
                csv_file = csv_source
                if hasattr(csv_file, 'seek'):
                    csv_file.seek(0)
                close_after = False

            try:
                reader = list(csv.DictReader(csv_file))
                valid_rows = [
                    r for r in reader
                    if r.get('nombre', '').strip()
                    and (r.get('registro', '').strip() or r.get('expediente', '').strip())
                ]
                self._init_progress(on_progress, len(valid_rows))

                for row_num, row in enumerate(reader, start=2):
                    nombre = row.get('nombre', '').strip()
                    registro = row.get('registro', '').strip()
                    expediente = row.get('expediente', '').strip()

                    try:
                        if not nombre:
                            logger.warning(f"Row {row_num}: 'nombre' is empty, skipping")
                            continue

                        if registro and expediente:
                            logger.warning(
                                f"Row {row_num}: Both 'registro' and 'expediente' present, "
                                "using 'registro'"
                            )

                        if not registro and not expediente:
                            logger.warning(
                                f"Row {row_num}: Neither 'registro' nor 'expediente' present, "
                                "skipping"
                            )
                            continue

                        self._report_progress(f"{nombre}: connecting to IMPI")

                        detail_buttons = []
                        if registro:
                            self._report_progress(f"{nombre}: searching registro {registro}")
                            detail_buttons = self.search_by_registro(nombre, registro)
                        else:
                            self._report_progress(f"{nombre}: searching expediente {expediente}")
                            detail_buttons = self.search_by_expediente(nombre, expediente)

                        self._report_progress(
                            f"{nombre}: found {len(detail_buttons)} trámite(s)",
                            extra_total=len(detail_buttons),
                        )

                        logger.info(
                            f"Row {row_num}: Found {len(detail_buttons)} detail buttons to process"
                        )

                        tramites = []
                        for i, button_info in enumerate(detail_buttons):
                            tipo = button_info['row_data'].get('tipo_tramite', 'trámite')
                            self._report_progress(
                                f"{nombre}: extracting trámite {i + 1}/{len(detail_buttons)} — "
                                f"{tipo}"
                            )
                            tramite = {
                                'indice': button_info['row_index'],
                                'resumen': button_info['row_data'],
                                'detalle': {'oficios': [], 'promociones': []},
                            }
                            try:
                                detail_data = self.extract_detail_data(button_info, nombre)
                                tramite['detalle'] = {
                                    'oficios': detail_data['oficios'],
                                    'promociones': detail_data['promociones'],
                                }
                            except Exception as e:
                                logger.error(
                                    f"Row {row_num}, Button {button_info['row_index']}: "
                                    f"Error extracting detail - {e}"
                                )
                                tramite['error'] = str(e)
                            tramites.append(tramite)

                        brand_result = self._compile_brand_result(
                            nombre, registro, expediente, tramites
                        )
                        results.append(brand_result)

                        logger.info(
                            f"Row {row_num}: Compiled brand result — "
                            f"{brand_result['resumen']['total_tramites']} trámite(s), "
                            f"{brand_result['resumen']['total_oficios']} oficio(s), "
                            f"{brand_result['resumen']['total_promociones']} promoción(es)"
                        )
                        print(f"\n{'='*80}")
                        print(f"BRAND: {nombre}")
                        print(f"{'='*80}")
                        self._print_with_jq(brand_result)
                        print(f"{'='*80}\n")

                    except Exception as e:
                        logger.error(f"Row {row_num}: Error processing row - {e}")
                        results.append({
                            'marca': {
                                'nombre': nombre or f'Row {row_num}',
                                'busqueda': {
                                    'por': 'registro' if registro else 'expediente',
                                    **(
                                        {'registro': registro}
                                        if registro
                                        else {'expediente': expediente}
                                    ),
                                },
                            },
                            'tramites': [],
                            'resumen': {
                                'total_tramites': 0,
                                'total_oficios': 0,
                                'total_promociones': 0,
                            },
                            'error': str(e),
                        })
                        continue
            finally:
                if close_after:
                    csv_file.close()

            if on_progress:
                on_progress("Done", 1.0)

            return results

        except FileNotFoundError:
            logger.error(f"Input file not found: {csv_source}")
            raise
        except Exception as e:
            logger.error(f"Error reading CSV file: {e}")
            raise

    def run(self, csv_file='input.csv', headless=False, on_progress=None):
        """
        Main method to run the scraper.

        Args:
            csv_file: Path to the input CSV file
            headless: Deprecated, kept for API compatibility (ignored)
            on_progress: Optional progress callback

        Returns:
            list: Compiled brand result dicts
        """
        if headless:
            logger.debug("headless parameter is ignored; scraper uses direct HTTP requests")
        try:
            if on_progress:
                on_progress("Connecting to IMPI…", 0.0)
            return self.process_csv(csv_file, on_progress=on_progress)
        except Exception as e:
            logger.error(f"Scraper error: {e}")
            raise


if __name__ == "__main__":
    scraper = IMPIMarcoScraper()
    scraper.run('input.csv')
