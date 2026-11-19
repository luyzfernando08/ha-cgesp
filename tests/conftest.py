"""Configuração dos testes.

Há dois tipos de teste:

- Leitura do site (test_cge_*.py): só precisam de pytest, bs4 e requests.
  Sem o Home Assistant instalado, registramos pacotes "vazios" para
  `custom_components` e `custom_components.cgesp`, de modo que módulos como
  `cge_alertas` e `cge_extras` possam ser importados sem executar o
  `__init__.py` da integração (que importa o HA).

- Integração com o HA (test_ha_*.py): rodam dentro de um Home Assistant de
  verdade, com `pytest-homeassistant-custom-component`
  (requirements_test_ha.txt). Sem esse plugin, são pulados.
"""
import sys
import types
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent
COMPONENT_DIR = REPO_ROOT / "custom_components" / "cgesp"

try:
    import pytest_homeassistant_custom_component  # noqa: F401
except ImportError:
    HA_DISPONIVEL = False
else:
    HA_DISPONIVEL = True


def _register_stub_package(name: str, path: Path) -> None:
    if name in sys.modules:
        return
    module = types.ModuleType(name)
    module.__path__ = [str(path)]
    sys.modules[name] = module


if HA_DISPONIVEL:
    # O plugin do HA (fixtures `hass`, `hass_storage` etc.).
    pytest_plugins = ["pytest_homeassistant_custom_component"]

    @pytest.fixture(autouse=True)
    def _habilitar_integracao(request):
        """Permite ao HA carregar custom_components/cgesp nos testes.

        O recorder precisa ser preparado antes do `hass`; nos testes que o usam
        (ex.: Diário de bordo), ele vem primeiro.
        """
        if "recorder_mock" in request.fixturenames:
            request.getfixturevalue("recorder_mock")
        request.getfixturevalue("enable_custom_integrations")

else:
    _register_stub_package("custom_components", REPO_ROOT / "custom_components")
    _register_stub_package("custom_components.cgesp", COMPONENT_DIR)


FIXTURES = Path(__file__).parent / "fixtures"

URL_ALAGAMENTOS = "https://www.cgesp.org/v3/alagamentos.jsp"
URL_MAPA_AREAS = "https://www.cgesp.org/v3/mapas.jsp?arq=alertas"
URL_MAPA_PNG = "https://www.cgesp.org/cgesp/mapa_sp_geoserver.png"
URL_PREVISAO = "https://www.cgesp.org/v3/previsao_estendida.jsp"
URL_BOLETIM = "https://www.cgesp.org/v3/feed_rss.jsp"
URL_ESTACAO = "https://www.cgesp.org/v3/estacao.jsp"


class SiteCge:
    """Site do CGE simulado: cada URL devolve o conteúdo de uma fixture.

    `paginas[url]` pode ser trocado durante o teste: bytes viram resposta
    200; None simula o site fora do ar (erro de conexão). Uma URL que não
    está em `paginas` falha o teste, para nenhuma consulta escapar.
    """

    def __init__(self) -> None:
        self.paginas: dict[str, bytes | None] = {
            URL_ALAGAMENTOS: self.fixture("alagamentos.html"),
            URL_MAPA_AREAS: self.fixture("mapa_alertas.html"),
            URL_MAPA_PNG: self.fixture("mapa_alertas.png"),
            URL_PREVISAO: self.fixture("previsao.html"),
            URL_BOLETIM: self.fixture("feed_rss.xml"),
            URL_ESTACAO: self.fixture("estacao.html"),
        }
        self.consultas: list[str] = []

    @staticmethod
    def fixture(nome: str) -> bytes:
        return (FIXTURES / nome).read_bytes()

    def fora_do_ar(self) -> None:
        for url in self.paginas:
            self.paginas[url] = None

    def get(self, url, params=None, headers=None, timeout=None, **_kwargs):
        import requests

        self.consultas.append(url)
        chave = url if url in self.paginas else url.split("?", 1)[0]
        if chave not in self.paginas:
            raise AssertionError(f"consulta inesperada nos testes: {url}")
        conteudo = self.paginas[chave]
        if conteudo is None:
            raise requests.exceptions.ConnectionError(f"fora do ar: {url}")
        resposta = requests.Response()
        resposta.status_code = 200
        resposta.url = url
        resposta._content = conteudo
        resposta.headers["Last-Modified"] = "Wed, 18 Nov 2026 16:49:09 GMT"
        return resposta


@pytest.fixture
def site_cge(monkeypatch) -> SiteCge:
    import requests

    site = SiteCge()
    monkeypatch.setattr(requests, "get", site.get)
    return site


def pytest_ignore_collect(collection_path, config):
    if not HA_DISPONIVEL and collection_path.name.startswith("test_ha_"):
        return True
    return None
