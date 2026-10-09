import re
import subprocess
import json
import datetime
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

# Drop a phonetic result when its publication date is older than this window.
FONETICA_VENTANA_DIAS = 30
FECHA_PUBLICACION_FORMATO = '%d/%m/%Y'

# IMPI answers a rate-limited request with HTTP 200 and this text in the page
# body. The page is an error page, not a result page.
CUOTA_MENSAJE = 'Has superado la cuota máxima de peticiones permitidas'
ERROR_HANDLER_MARCADOR = 'errorHandler/busquedaApp.pgi'


class CuotaExcedidaError(RuntimeError):
    """Raised when IMPI rejects a request because the request quota is used up."""


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
        self.fonetica_url = (
            "https://acervomarcas.impi.gob.mx:8181/marcanet/vistas/common/"
            "datos/bsqFoneticaCompleta.pgi"
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

    def search_by_fonetica(self, denominacion, clase, ventana_dias=FONETICA_VENTANA_DIAS,
                           on_progress=None):
        """
        Search the phonetic database by denomination and class.

        The page replays the previous result when the client reuses a
        ViewState. This method therefore requests a new page for each search.

        Two filters run on the results:

        1. Drop every hit that already has a Registro Nacional.
        2. Drop every hit whose "Fecha de publicación de la solicitud" is
           older than `ventana_dias`. A hit with no publication date is kept.

        Args:
            denominacion (str): Brand name to search.
            clase (str): Nice class number, 1 to 45.
            ventana_dias (int): Maximum age of the publication date in days.
            on_progress: Optional callback(message: str, fraction: float)

        Returns:
            list: Result dicts with the detail fields and the publication date.
        """
        try:
            logger.info(
                f"Phonetic search: denominacion='{denominacion}', clase='{clase}', "
                f"ventana_dias={ventana_dias}"
            )
            html = self._fetch_fonetica_page()
            view_state = self._extract_view_state(html)
            if not view_state:
                raise RuntimeError(
                    "Could not extract javax.faces.ViewState from phonetic page"
                )

            response = self._get_session().post(
                self.fonetica_url,
                data={
                    'javax.faces.partial.ajax': 'true',
                    'javax.faces.source': 'frmBsqFonetica:busquedaId2',
                    'javax.faces.partial.execute': '@all',
                    'javax.faces.partial.render': 'frmBsqFonetica',
                    'frmBsqFonetica:busquedaId2': 'frmBsqFonetica:busquedaId2',
                    'frmBsqFonetica': 'frmBsqFonetica',
                    'frmBsqFonetica:clases': str(clase),
                    'frmBsqFonetica:denominacion': denominacion,
                    'javax.faces.ViewState': view_state,
                },
                headers=self._ajax_headers(self.fonetica_url),
                timeout=120,
            )
            response.raise_for_status()
            self._check_respuesta_valida(response.text)

            resultados, descartados = self._parse_fonetica_response(response.text)
            logger.info(
                f"Phonetic search '{denominacion}' class {clase}: "
                f"{len(resultados)} result(s) without Registro, "
                f"{descartados} with Registro dropped"
            )

            resultados = self._filter_fonetica_by_date(
                resultados, ventana_dias, on_progress=on_progress
            )
            return resultados
        except Exception as e:
            logger.error(f"Error in search_by_fonetica: {e}")
            raise

    def _filter_fonetica_by_date(self, resultados, ventana_dias, on_progress=None):
        """
        Load each result's detail page and drop it when its date is too old.

        A result with no publication date is kept. A result with an
        unparseable date is kept and marked. A failed detail request stops the
        filter, because a partial answer would mix two different rules.

        Args:
            resultados (list): Kept results from the result table.
            ventana_dias (int): Maximum age of the publication date in days.
            on_progress: Optional callback(message: str, fraction: float)

        Returns:
            list: Results that pass the date filter.
        """
        limite = datetime.date.today() - datetime.timedelta(days=ventana_dias)
        total = len(resultados)
        conservados = []
        descartados_por_fecha = 0
        sin_fecha = 0
        consultados = 0

        for indice, resultado in enumerate(resultados, start=1):
            if on_progress:
                on_progress(
                    f"Consultando detalle {indice}/{total} — "
                    f"{resultado.get('expediente', '?')}",
                    indice / max(total, 1),
                )

            detalle = self._fetch_expediente_detalle(resultado.get('detalle_url'))
            consultados += 1
            fecha_texto = detalle.get('fecha_publicacion') or ''
            resultado['numero_registro'] = detalle.get('numero_registro') or ''
            resultado['fecha_presentacion'] = detalle.get('fecha_presentacion') or ''
            resultado['fecha_publicacion'] = fecha_texto or None
            resultado['fecha_publicacion_valida'] = bool(self._parse_fecha(fecha_texto))

            fecha = self._parse_fecha(fecha_texto)
            if fecha is None:
                sin_fecha += 1
                conservados.append(resultado)
                continue
            if fecha < limite:
                descartados_por_fecha += 1
                continue
            conservados.append(resultado)

        logger.info(
            f"Date filter ({ventana_dias} days, limit {limite.isoformat()}): "
            f"{len(conservados)} kept, {descartados_por_fecha} older dropped, "
            f"{sin_fecha} without date kept, {consultados}/{total} details read"
        )
        return conservados

    @staticmethod
    def _parse_fecha(texto):
        """Parse a DD/MM/YYYY date string. Return None when it is not a date."""
        if not texto:
            return None
        try:
            return datetime.datetime.strptime(
                texto.strip(), FECHA_PUBLICACION_FORMATO
            ).date()
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _check_respuesta_valida(texto):
        """
        Raise when a response is an IMPI error page that arrived with HTTP 200.

        IMPI answers a rate-limited request with the normal page shell and the
        quota message in the body. Without this check the caller reads the
        error page as an empty result.
        """
        if CUOTA_MENSAJE in texto or ERROR_HANDLER_MARCADOR in texto:
            raise CuotaExcedidaError(
                "IMPI rechazó la petición: se superó la cuota máxima de "
                "peticiones. Espera unos 10 minutos y vuelve a intentar."
            )

    def _fetch_expediente_detalle(self, detalle_url):
        """
        GET an expediente partial detail page and read its fields.

        Returns:
            dict: Field name to value, with the keys
            ``numero_registro``, ``fecha_presentacion`` and
            ``fecha_publicacion``.

        Raises:
            CuotaExcedidaError: IMPI rejected the request.
            requests.RequestException: The request failed.
        """
        if not detalle_url:
            raise RuntimeError("Result has no detail URL")
        if detalle_url.startswith('/'):
            detalle_url = 'https://acervomarcas.impi.gob.mx:8181' + detalle_url
        response = self._get_session().get(
            detalle_url,
            headers={'Referer': self.fonetica_url},
            timeout=60,
        )
        response.raise_for_status()
        self._check_respuesta_valida(response.text)
        detalle = self._parse_detalle_page(response.text)
        if not detalle['fecha_publicacion_presente']:
            raise RuntimeError(
                "Detail page does not hold 'Fecha de publicación de la solicitud'"
            )
        return detalle

    @staticmethod
    def _parse_detalle_page(html):
        """
        Read the detail page fields into a dict with internal key names.

        The page labels each field in Spanish. ``fecha_publicacion_presente``
        reports whether the label exists at all, which is not the same as an
        empty value.
        """
        pares = IMPIMarcoScraper._parse_detalle_pares(html)
        etiqueta_fecha = 'Fecha de publicación de la solicitud'
        return {
            'numero_registro': pares.get('Número de registro', ''),
            'fecha_presentacion': pares.get('Fecha de presentación', ''),
            'fecha_publicacion': pares.get(etiqueta_fecha, ''),
            'fecha_publicacion_presente': etiqueta_fecha in pares,
        }

    @staticmethod
    def _parse_detalle_pares(html):
        """
        Parse the detail page into a label-to-value dict.

        The page holds the fields in a table. Each row has a label cell and a
        value cell.
        """
        soup = BeautifulSoup(html, 'html.parser')
        pares = {}
        for fila in soup.find_all('tr'):
            celdas = fila.find_all(['td', 'th'])
            textos = [c.get_text(' ', strip=True) for c in celdas]
            textos = [t for t in textos if t]
            if len(textos) >= 2:
                pares[textos[0]] = textos[1]
            elif len(textos) == 1:
                pares.setdefault(textos[0], '')
        return pares

    def _fetch_fonetica_page(self):
        """GET the phonetic page to obtain a session cookie and a fresh ViewState."""
        session = self._get_session()
        response = session.get(self.fonetica_url, timeout=60)
        response.raise_for_status()
        return response.text

    @staticmethod
    def _parse_fonetica_response(xml_text):
        """
        Parse a phonetic partial-AJAX response.

        Returns:
            tuple: (kept_results, dropped_count). A result is dropped when its
            Registro cell is not empty.
        """
        match = re.search(
            r'<update id="frmBsqFonetica"><!\[CDATA\[(.*?)\]\]></update>',
            xml_text,
            re.DOTALL,
        )
        if not match:
            raise RuntimeError("Phonetic results update not found in response")

        soup = BeautifulSoup(match.group(1), 'html.parser')
        tbody = soup.find(id='frmBsqFonetica:resultadoExpediente_data')
        if not tbody:
            return [], 0

        resultados = []
        descartados = 0
        for row in tbody.find_all('tr'):
            cells = row.find_all('td')
            if len(cells) < 8:
                continue
            texts = [c.get_text(' ', strip=True) for c in cells]
            if texts[5]:
                descartados += 1
                continue
            resultados.append({
                'numero': texts[0],
                'tipo_solicitud': texts[1],
                'tipo_marca': texts[2],
                'titular': texts[3],
                'expediente': texts[4],
                'denominacion': texts[6],
                'clase': texts[7],
                'detalle_url': IMPIMarcoScraper._extract_detalle_url(row),
            })
        return resultados, descartados

    @staticmethod
    def _extract_detalle_url(row):
        """Read the expediente detail URL from a result row's anchor."""
        anchor = row.find('a', id=re.compile(r'linkToDetail$'))
        if not anchor:
            return None
        match = re.search(r"window\.open\('([^']+)'", anchor.get('onclick', ''))
        return match.group(1) if match else None

    def run_fonetica(self, denominacion, clase, on_progress=None):
        """
        Run one phonetic search and print the kept results as JSON.

        Args:
            denominacion (str): Brand name to search.
            clase (str): Nice class number, 1 to 45.
            on_progress: Optional callback(message: str, fraction: float)

        Returns:
            dict: Search parameters, results, and counts.
        """
        if on_progress:
            on_progress("Conectando con IMPI…", 0.0)
        resultados = self.search_by_fonetica(
            denominacion, clase, on_progress=on_progress
        )
        if on_progress:
            on_progress(
                f"{len(resultados)} resultado(s) vigentes", 1.0
            )
        salida = {
            'busqueda': {
                'denominacion': denominacion,
                'clase': str(clase),
                'ventana_dias': FONETICA_VENTANA_DIAS,
            },
            'resultados': resultados,
            'resumen': {'total_resultados': len(resultados)},
        }
        self._print_with_jq(salida)
        return salida

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

    def _compile_brand_result(self, denominacion, registro, expediente, tramites, hoja=None):
        """Compile all tramite records for one brand into a hierarchical dict."""
        search_type = 'registro' if registro else 'expediente'
        search_value = registro or expediente
        total_oficios = sum(len(t.get('detalle', {}).get('oficios', [])) for t in tramites)
        total_promociones = sum(
            len(t.get('detalle', {}).get('promociones', [])) for t in tramites
        )

        marca = {
            'denominacion': denominacion,
            'busqueda': {
                'por': search_type,
                search_type: search_value,
            },
        }
        if hoja:
            marca['hoja'] = hoja

        return {
            'marca': marca,
            'tramites': tramites,
            'resumen': {
                'total_tramites': len(tramites),
                'total_oficios': total_oficios,
                'total_promociones': total_promociones,
            },
        }

    @staticmethod
    def _summarize_brands(marcas: list[dict]) -> dict:
        return {
            'total_marcas': len(marcas),
            'total_tramites': sum(m.get('resumen', {}).get('total_tramites', 0) for m in marcas),
            'total_oficios': sum(m.get('resumen', {}).get('total_oficios', 0) for m in marcas),
            'total_promociones': sum(
                m.get('resumen', {}).get('total_promociones', 0) for m in marcas
            ),
        }

    def _process_brand_row(self, row, row_label):
        denominacion = row['denominacion']
        registro = row.get('registro', '')
        expediente = row.get('expediente', '')
        hoja = row.get('hoja')

        self._report_progress(f"{denominacion}: conectando con IMPI")

        detail_buttons = []
        if registro:
            self._report_progress(f"{denominacion}: buscando registro {registro}")
            detail_buttons = self.search_by_registro(denominacion, registro)
        else:
            self._report_progress(f"{denominacion}: buscando expediente {expediente}")
            detail_buttons = self.search_by_expediente(denominacion, expediente)

        self._report_progress(
            f"{denominacion}: {len(detail_buttons)} trámite(s) encontrado(s)",
            extra_total=len(detail_buttons),
        )

        logger.info(f"{row_label}: Found {len(detail_buttons)} detail buttons to process")

        tramites = []
        for i, button_info in enumerate(detail_buttons):
            tipo = button_info['row_data'].get('tipo_tramite', 'trámite')
            self._report_progress(
                f"{denominacion}: extrayendo trámite {i + 1}/{len(detail_buttons)} — {tipo}"
            )
            tramite = {
                'indice': button_info['row_index'],
                'resumen': button_info['row_data'],
                'detalle': {'oficios': [], 'promociones': []},
            }
            try:
                detail_data = self.extract_detail_data(button_info, denominacion)
                tramite['detalle'] = {
                    'oficios': detail_data['oficios'],
                    'promociones': detail_data['promociones'],
                }
            except Exception as e:
                logger.error(
                    f"{row_label}, Button {button_info['row_index']}: "
                    f"Error extracting detail - {e}"
                )
                tramite['error'] = str(e)
            tramites.append(tramite)

        brand_result = self._compile_brand_result(
            denominacion, registro, expediente, tramites, hoja=hoja
        )

        logger.info(
            f"{row_label}: Compiled brand result — "
            f"{brand_result['resumen']['total_tramites']} trámite(s), "
            f"{brand_result['resumen']['total_oficios']} oficio(s), "
            f"{brand_result['resumen']['total_promociones']} promoción(es)"
        )
        print(f"\n{'='*80}")
        print(f"BRAND: {denominacion}")
        print(f"{'='*80}")
        self._print_with_jq(brand_result)
        print(f"{'='*80}\n")
        return brand_result

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

    def process_portfolio(self, sheet_batches: dict[str, list[dict]], on_progress=None):
        """
        Process brands grouped by Excel sheet.

        Args:
            sheet_batches: Mapping of sheet name to brand row dicts
            on_progress: Optional callback(message: str, fraction: float)

        Returns:
            dict: Results grouped by sheet with overall summary
        """
        valid_rows = [row for rows in sheet_batches.values() for row in rows]
        self._init_progress(on_progress, len(valid_rows))

        hojas = []
        all_marcas = []

        for sheet_name, rows in sheet_batches.items():
            marcas = []
            for row in rows:
                row_label = f"{sheet_name}, fila {row.get('fila', '?')}"
                try:
                    marcas.append(self._process_brand_row(row, row_label))
                except Exception as e:
                    logger.error(f"{row_label}: Error processing row - {e}")
                    marcas.append({
                        'marca': {
                            'denominacion': row.get('denominacion', row_label),
                            'hoja': sheet_name,
                            'busqueda': {
                                'por': 'registro' if row.get('registro') else 'expediente',
                                **(
                                    {'registro': row['registro']}
                                    if row.get('registro')
                                    else {'expediente': row.get('expediente', '')}
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

            sheet_result = {
                'hoja': sheet_name,
                'marcas': marcas,
                'resumen': self._summarize_brands(marcas),
            }
            hojas.append(sheet_result)
            all_marcas.extend(marcas)

        if on_progress:
            on_progress("Completado", 1.0)

        return {
            'hojas': hojas,
            'resumen': {
                'total_hojas': len(hojas),
                **self._summarize_brands(all_marcas),
            },
        }

    def process_csv(self, csv_source, on_progress=None):
        """
        Process the input CSV file or file-like object.

        Args:
            csv_source: Path to CSV file or readable text stream
            on_progress: Optional callback(message: str, fraction: float)

        Returns:
            dict: Portfolio-style results with a single CSV sheet
        """
        from portfolio import parse_csv, excel_to_brand_batches

        try:
            if isinstance(csv_source, str):
                with open(csv_source, 'r', encoding='utf-8') as csv_file:
                    previews = parse_csv(csv_file)
            else:
                if hasattr(csv_source, 'seek'):
                    csv_source.seek(0)
                previews = parse_csv(csv_source)

            return self.process_portfolio(
                excel_to_brand_batches(previews),
                on_progress=on_progress,
            )
        except FileNotFoundError:
            logger.error(f"Input file not found: {csv_source}")
            raise
        except Exception as e:
            logger.error(f"Error reading CSV file: {e}")
            raise

    def run_portfolio(self, sheet_batches, on_progress=None):
        """Run the scraper on Excel portfolio batches grouped by sheet."""
        try:
            if on_progress:
                on_progress("Conectando con IMPI…", 0.0)
            return self.process_portfolio(sheet_batches, on_progress=on_progress)
        except Exception as e:
            logger.error(f"Scraper error: {e}")
            raise

    def run_google_sheet(self, on_progress=None):
        """Fetch the portfolio Google Sheet and run the scraper."""
        from portfolio import excel_to_brand_batches, load_google_sheet_previews

        previews, error = load_google_sheet_previews()
        if error:
            raise RuntimeError(error)
        return self.run_portfolio(
            excel_to_brand_batches(previews),
            on_progress=on_progress,
        )

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
                on_progress("Conectando con IMPI…", 0.0)
            return self.process_csv(csv_file, on_progress=on_progress)
        except Exception as e:
            logger.error(f"Scraper error: {e}")
            raise


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="IMPI Marcanet scraper")
    parser.add_argument("--fonetica", metavar="DENOMINACION",
                        help="Run a phonetic search for this denomination")
    parser.add_argument("--clase", default="41",
                        help="Nice class for the phonetic search (default: 41)")
    args = parser.parse_args()

    scraper = IMPIMarcoScraper()
    if args.fonetica:
        scraper.run_fonetica(args.fonetica, args.clase)
    else:
        scraper.run_google_sheet()
