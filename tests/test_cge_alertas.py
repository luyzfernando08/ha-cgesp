import asyncio
import logging
import struct
import zlib
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pytest
import requests

import custom_components.cgesp.cge_alertas as cge_alertas
from custom_components.cgesp.cge_alertas import (
    AreaMapa,
    CgeAlertas,
    CgeAlertasData,
    CgeAlertasError,
    _classificar_cor,
    _decodificar_png,
    _decodificar_texto,
    _horario_do_header,
    _parse_alagamentos,
    _parse_areas_mapa,
    _parse_estados_areas,
    normalizar,
)
from custom_components.cgesp.const import (
    ESTACOES,
    ESTACOES_REGIAO,
    ESTADO_ALERTA,
    ESTADO_ATENCAO,
    ESTADO_IMINENCIA,
    ESTADO_OBSERVACAO,
    ZONAS,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _fixture_bytes(nome: str) -> bytes:
    return (FIXTURES / nome).read_bytes()


def _fixture_texto(nome: str) -> str:
    return _decodificar_texto(_fixture_bytes(nome))


def _areas_reais() -> list[AreaMapa]:
    return _parse_areas_mapa(_fixture_texto("mapa_alertas.html"))


def _png(largura, altura, cor_em, tempo=None, filtro=0) -> bytes:
    """Gera um PNG RGBA simples; cor_em(x, y) -> (r, g, b)."""

    def chunk(tipo, dados):
        return (
            struct.pack(">I", len(dados))
            + tipo
            + dados
            + struct.pack(">I", zlib.crc32(tipo + dados) & 0xFFFFFFFF)
        )

    bruto = bytearray()
    anterior = bytes(largura * 4)
    for y in range(altura):
        linha = bytearray()
        for x in range(largura):
            linha.extend((*cor_em(x, y), 255))
        if filtro == 2:  # "Up": grava a diferença para a linha anterior
            codificada = bytes((linha[i] - anterior[i]) & 0xFF for i in range(len(linha)))
        else:
            codificada = bytes(linha)
        bruto.append(filtro)
        bruto.extend(codificada)
        anterior = bytes(linha)

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", largura, altura, 8, 6, 0, 0, 0))
    if tempo:
        png += chunk(b"tIME", struct.pack(">HBBBBB", *tempo))
    png += chunk(b"IDAT", zlib.compress(bytes(bruto)))
    png += chunk(b"IEND", b"")
    return png


def _html_ponto(status_classe: str, local: str = "AV PRESTES MAIA") -> str:
    return f"""
      <tr><td><div class="ponto-de-alagamento"><ul>
        <li class="{status_classe}"></li>
        <li class="arial-descr-alag col-local">De 08:00 a <br/>{local}</li>
        <li class="arial-descr-alag">Sentido: CENTRO<br/>Referência: VD STA IFIGENIA</li>
      </ul></div></td></tr>
    """


def _html_zona(zona: str, *pontos: str) -> str:
    return f"""
    <h1 class="tit-bairros">{zona}</h1>
    <table class="tb-pontos-de-alagamentos">
      <tr><td class="bairro">Sé <hr/></td><td>1 pts.</td></tr>
      {''.join(pontos)}
    </table>
    """


class TestNormalizar:
    def test_remove_acentos_e_caixa(self):
        assert normalizar("  Freguesia do  Ó ") == "freguesia do o"

    def test_nomes_iguais_com_e_sem_acento(self):
        assert normalizar("Jaçanã/Tremembé") == normalizar("Jacana/Tremembe")


class TestDecodificarTexto:
    def test_utf8(self):
        assert _decodificar_texto("Sé".encode("utf-8")) == "Sé"

    def test_latin1_quando_utf8_invalido(self):
        assert _decodificar_texto("Referência".encode("latin-1")) == "Referência"


class TestParseAlagamentos:
    @pytest.fixture
    def resultado(self):
        return _parse_alagamentos(_fixture_texto("alagamentos.html"))

    def test_data_referencia(self, resultado):
        assert resultado.data_referencia == "15/11/2026"

    def test_zonas_encontradas(self, resultado):
        assert set(resultado.pontos) == {"norte", "oeste", "leste", "sul"}
        assert set(resultado.pontos) <= set(ZONAS)

    def test_quantidade_de_pontos_por_zona(self, resultado):
        assert {z: len(p) for z, p in resultado.pontos.items()} == {
            "norte": 2,
            "oeste": 1,
            "leste": 1,
            "sul": 2,
        }
        assert resultado.avisos == []

    def test_ponto_ativo_sem_horario_de_fim(self, resultado):
        (ponto,) = resultado.pontos["leste"]
        assert ponto.ativo is True
        assert ponto.transitavel is False
        assert ponto.bairro == "Itaim Paulista"
        assert ponto.local == "Avenida Marechal Tito"
        assert ponto.inicio == "19:40"
        assert ponto.fim is None
        assert ponto.sentido == "ambos"
        assert ponto.referencia == "altura do número 7557"

    def test_ponto_inativo(self, resultado):
        ponto = resultado.pontos["norte"][0]
        assert ponto.ativo is False
        assert ponto.transitavel is True
        assert ponto.bairro == "Casa Verde"
        assert ponto.local == "MARGINAL TIETE ASCB EXPRESSA"
        assert (ponto.inicio, ponto.fim) == ("19:15", "20:17")
        assert ponto.sentido == "A SENNA/CASTELO B"
        assert ponto.referencia == "PTE DA CASA VERDE-JORN.WALTER ABRAHAO"

    def test_varios_pontos_no_mesmo_bairro(self, resultado):
        assert [p.bairro for p in resultado.pontos["sul"]] == ["Santo Amaro", "Santo Amaro"]
        assert [p.local for p in resultado.pontos["sul"]] == [
            "R STO ARCADIO",
            "AC RAPHAEL POTENZA",
        ]

    def test_pagina_sem_alagamentos(self):
        resultado = _parse_alagamentos(_fixture_texto("alagamentos_vazio.html"))
        assert resultado.data_referencia == "18/11/2026"
        assert resultado.pontos == {}

    def test_zona_centro_e_normalizada(self):
        resultado = _parse_alagamentos(_html_zona("Centro", _html_ponto("ativo-transitavel")))
        (ponto,) = resultado.pontos["centro"]
        assert ponto.ativo and ponto.transitavel
        assert ponto.bairro == "Sé"


class TestLayoutAlagamentosAlterado:
    def test_sem_zonas_e_sem_mensagem_de_vazio_e_erro(self):
        # Ex.: CGE renomeia a classe "tit-bairros" -> não pode virar "sem alagamento".
        html = _fixture_texto("alagamentos.html").replace("tit-bairros", "titulo-zona")
        with pytest.raises(CgeAlertasError, match="Layout"):
            _parse_alagamentos(html)

    def test_pagina_de_erro_qualquer_e_erro(self):
        with pytest.raises(CgeAlertasError, match="Layout"):
            _parse_alagamentos("<html><body><h1>Manutenção</h1></body></html>")

    def test_zonas_sem_blocos_de_ponto_e_erro(self):
        html = _fixture_texto("alagamentos.html").replace(
            "ponto-de-alagamento", "item-alagamento"
        )
        with pytest.raises(CgeAlertasError, match="nenhum ponto"):
            _parse_alagamentos(html)

    def test_todos_os_status_desconhecidos_e_erro(self):
        html = _fixture_texto("alagamentos.html")
        for classe in ("inativo-transitavel", "ativo-intransitavel"):
            html = html.replace(f'class="{classe}"', 'class="status-novo"')
        with pytest.raises(CgeAlertasError, match="nenhum ponto"):
            _parse_alagamentos(html)

    def test_status_desconhecido_isolado_gera_aviso(self):
        html = _html_zona(
            "Centro",
            _html_ponto("ativo-transitavel", "AV PRESTES MAIA"),
            _html_ponto("status-novo", "R 25 DE MARCO"),
        )
        resultado = _parse_alagamentos(html)
        assert [p.local for p in resultado.pontos["centro"]] == ["AV PRESTES MAIA"]
        (aviso,) = resultado.avisos
        assert "R 25 DE MARCO" in aviso


class TestDadosAlertas:
    def test_estado_da_area_ignora_acentos(self):
        dados = CgeAlertasData(estados_areas={"freguesia do o": ESTADO_ATENCAO})
        assert dados.estado_da_area("Freguesia do Ó") == ESTADO_ATENCAO

    def test_parte_que_falhou_fica_indisponivel(self):
        dados = CgeAlertasData()
        assert not dados.alagamentos_disponiveis
        assert not dados.mapa_disponivel
        assert dados.pontos_da_zona("sul") == []
        assert dados.estado_da_area("Sé") is None

    def test_sem_alagamentos_e_diferente_de_indisponivel(self):
        dados = CgeAlertasData(alagamentos={})
        assert dados.alagamentos_disponiveis
        assert dados.pontos_da_zona("sul") == []


class TestParseAreasMapa:
    def test_lista_32_areas(self):
        areas = _areas_reais()
        assert len(areas) == 32
        assert areas[0] == AreaMapa(nome="Perus", x=45, y=58, raio=10)

    def test_toda_estacao_da_capital_tem_area_no_mapa(self):
        areas = {normalizar(a.nome) for a in _areas_reais()}
        for estacao_id, regiao in ESTACOES_REGIAO.items():
            if regiao is None:
                continue
            zona, area = regiao
            assert zona in ZONAS
            assert normalizar(area) in areas, ESTACOES[estacao_id]

    def test_toda_estacao_tem_regiao_definida(self):
        assert set(ESTACOES_REGIAO) == set(ESTACOES)


class TestClassificarCor:
    @pytest.mark.parametrize(
        ("rgb", "esperado"),
        [
            # Preenchimento das áreas (cor com transparência sobre o branco)
            ((225, 225, 225), ESTADO_OBSERVACAO),
            ((255, 255, 102), ESTADO_ATENCAO),
            ((255, 194, 102), ESTADO_IMINENCIA),
            ((254, 203, 108), ESTADO_IMINENCIA),  # laranja medido no mapa de 11/03/2025
            ((255, 102, 102), ESTADO_ALERTA),
            ((255, 255, 103), ESTADO_ATENCAO),  # amarelo medido no mapa de 25/04/2025
            # Cores puras da legenda
            ((213, 213, 213), ESTADO_OBSERVACAO),
            ((255, 255, 0), ESTADO_ATENCAO),
            ((255, 153, 0), ESTADO_IMINENCIA),
            ((255, 151, 0), ESTADO_IMINENCIA),
            ((255, 0, 0), ESTADO_ALERTA),
            # Bordas com antialias
            ((216, 216, 0), ESTADO_ATENCAO),
            ((223, 0, 0), ESTADO_ALERTA),
            # Texto, bordas e outras cores: ignorados
            ((0, 0, 0), None),
            ((69, 69, 69), None),
            ((40, 40, 140), None),  # sigla azul-marinho
            ((52, 152, 219), None),  # azul
            ((128, 128, 0), None),  # amarelo escuro demais
        ],
    )
    def test_cores(self, rgb, esperado):
        assert _classificar_cor(*rgb) == esperado


class TestEstadosAreas:
    def test_mapa_atual_tudo_em_observacao(self):
        resultado = _parse_estados_areas(_fixture_bytes("mapa_alertas.png"), _areas_reais())
        assert len(resultado.estados) == 32
        assert set(resultado.estados.values()) == {ESTADO_OBSERVACAO}
        assert resultado.avisos == []
        # Mesmo horário escrito no mapa: 2026-11-18 13:49 (UTC-3)
        assert resultado.horario == datetime(2026, 11, 18, 16, 49, 9, tzinfo=timezone.utc)

    def test_mapa_real_com_estado_de_atencao(self):
        """Mapa do CGE de 28/01/2020 (captura publicada pelo G1), ampliado ~2,05x.

        Norte, Leste e Sé em Atenção; Oeste e Sul em Observação.
        """
        areas = [
            AreaMapa(a.nome, round(a.x * 2.05 + 16), round(a.y * 2.05 + 17), 20)
            for a in _areas_reais()
        ]
        resultado = _parse_estados_areas(
            _fixture_bytes("mapa_alertas_atencao_2020.png"), areas
        )

        em_atencao = {
            "Perus", "Pirituba/Jaraguá", "Freguesia do Ó", "Casa Verde", "Santana",
            "Jaçanã/Tremembé", "Vila Maria/Vila Guilherme", "Sé", "Mooca", "Penha",
            "Ermelino Matarazzo", "São Miguel Paulista", "Itaim Paulista", "Guaianases",
            "Itaquera", "Cidade Tiradentes", "Aricanduva/Vila Formosa", "Vila Prudente",
            "Sapopemba", "São Mateus",
        }
        esperado = {
            normalizar(a.nome): ESTADO_ATENCAO if a.nome in em_atencao else ESTADO_OBSERVACAO
            for a in _areas_reais()
        }
        assert resultado.estados == esperado
        assert Counter(resultado.estados.values()) == {
            ESTADO_ATENCAO: 20,
            ESTADO_OBSERVACAO: 12,
        }
        assert resultado.horario is None  # imagem convertida, sem chunk tIME

    @pytest.mark.parametrize(
        ("escala", "dx", "dy"),
        [(1.21, 5.5, 5.8), (1.20, 7, 7), (1.22, 4, 5)],
    )
    def test_mapa_real_com_alerta_e_atencao(self, escala, dx, dy):
        """Mapa do CGE de 25/04/2025 15:39 (captura publicada pelo Estadão, JPEG), ~1,21x.

        Itaim Paulista em Alerta, demais áreas da Zona Leste em Atenção e o
        resto em Observação. Varia o encaixe para garantir folga na amostragem.
        """
        areas = [
            AreaMapa(a.nome, round(a.x * escala + dx), round(a.y * escala + dy), 12)
            for a in _areas_reais()
        ]
        resultado = _parse_estados_areas(
            _fixture_bytes("mapa_alertas_alerta_2025.png"), areas
        )

        em_alerta = {"Itaim Paulista"}
        em_atencao = {
            "Mooca", "Penha", "Ermelino Matarazzo", "São Miguel Paulista",
            "Aricanduva/Vila Formosa", "Itaquera", "Guaianases", "Cidade Tiradentes",
            "Vila Prudente", "Sapopemba", "São Mateus",
        }

        def esperado(nome):
            if nome in em_alerta:
                return ESTADO_ALERTA
            if nome in em_atencao:
                return ESTADO_ATENCAO
            return ESTADO_OBSERVACAO

        assert resultado.estados == {
            normalizar(a.nome): esperado(a.nome) for a in _areas_reais()
        }
        assert Counter(resultado.estados.values()) == {
            ESTADO_ALERTA: 1,
            ESTADO_ATENCAO: 11,
            ESTADO_OBSERVACAO: 20,
        }
        assert resultado.avisos == []

    @pytest.mark.parametrize(
        ("escala", "dx", "dy"),
        [(1.88, 8, 9), (1.87, 10, 11), (1.89, 6, 7)],
    )
    def test_mapa_real_com_iminencia_de_transbordamento(self, escala, dx, dy):
        """Mapa do CGE de 11/03/2025 16:15 (captura publicada pela CNN Brasil), ~1,88x.

        Itaim Paulista em Iminência de transbordamento (laranja real:
        (254, 203, 108), matiz 39°), seis áreas da Zona Sul em Observação e o
        resto da cidade em Atenção.
        """
        areas = [
            AreaMapa(a.nome, round(a.x * escala + dx), round(a.y * escala + dy), 19)
            for a in _areas_reais()
        ]
        resultado = _parse_estados_areas(
            _fixture_bytes("mapa_alertas_iminencia_2025.png"), areas
        )

        em_iminencia = {"Itaim Paulista"}
        em_observacao = {
            "Campo Limpo", "Santo Amaro", "Cidade Ademar", "M'Boi Mirim",
            "Cidade Dutra/Socorro", "Parelheiros",
        }

        def esperado(nome):
            if nome in em_iminencia:
                return ESTADO_IMINENCIA
            if nome in em_observacao:
                return ESTADO_OBSERVACAO
            return ESTADO_ATENCAO

        assert resultado.estados == {
            normalizar(a.nome): esperado(a.nome) for a in _areas_reais()
        }
        assert Counter(resultado.estados.values()) == {
            ESTADO_IMINENCIA: 1,
            ESTADO_ATENCAO: 25,
            ESTADO_OBSERVACAO: 6,
        }
        assert resultado.avisos == []

    @pytest.mark.parametrize("filtro", [0, 2])
    def test_cada_area_com_sua_cor(self, filtro):
        cores = {
            0: (225, 225, 225),
            1: (255, 255, 102),
            2: (255, 194, 102),
            3: (255, 102, 102),
        }

        def cor_em(x, y):
            # Quatro faixas verticais com um "texto" preto no centro de cada uma.
            if y in (9, 10, 11) and x % 20 in (9, 10, 11):
                return (0, 0, 0)
            return cores[x // 20]

        png = _png(80, 20, cor_em, tempo=(2026, 1, 2, 3, 4, 5), filtro=filtro)
        areas = [AreaMapa(nome=f"Área {i}", x=10 + 20 * i, y=10, raio=8) for i in range(4)]

        resultado = _parse_estados_areas(png, areas)

        assert resultado.estados == {
            "area 0": ESTADO_OBSERVACAO,
            "area 1": ESTADO_ATENCAO,
            "area 2": ESTADO_IMINENCIA,
            "area 3": ESTADO_ALERTA,
        }
        assert resultado.horario == datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)

    def test_area_com_cor_desconhecida_gera_aviso(self):
        png = _png(40, 20, lambda x, y: (225, 225, 225) if x < 20 else (52, 152, 219))
        areas = [AreaMapa("Sé", 10, 10, 8), AreaMapa("Mooca", 30, 10, 8)]
        resultado = _parse_estados_areas(png, areas)
        assert resultado.estados == {"se": ESTADO_OBSERVACAO}
        (aviso,) = resultado.avisos
        assert "Mooca" in aviso

    def test_nenhuma_cor_reconhecida_e_erro(self):
        png = _png(20, 20, lambda x, y: (52, 152, 219))
        with pytest.raises(CgeAlertasError, match="mudou"):
            _parse_estados_areas(png, [AreaMapa("Sé", 10, 10, 8)])

    def test_png_sem_tIME(self):
        png = _png(4, 4, lambda x, y: (225, 225, 225))
        assert _decodificar_png(png).horario is None

    def test_conteudo_que_nao_e_png(self):
        with pytest.raises(ValueError):
            _decodificar_png(b"<html>erro</html>")


class TestHorarioDoHeader:
    def test_last_modified(self):
        assert _horario_do_header("Wed, 18 Nov 2026 16:55:37 GMT") == datetime(
            2026, 11, 18, 16, 55, 37, tzinfo=timezone.utc
        )

    @pytest.mark.parametrize("valor", [None, "", "lixo"])
    def test_invalido(self, valor):
        assert _horario_do_header(valor) is None


# --------------------------------------------------------------------------- #
# Coleta com falhas parciais
# --------------------------------------------------------------------------- #


class _Resposta:
    def __init__(self, content: bytes, headers: dict | None = None) -> None:
        self.content = content
        self.headers = headers or {}


class _HassFalso:
    async def async_add_executor_job(self, func, *args):
        return func(*args)


@pytest.fixture
def site(monkeypatch):
    """Simula o site do CGE; cada URL pode devolver bytes ou uma exceção."""
    respostas = {
        cge_alertas.URL_ALAGAMENTOS: _fixture_bytes("alagamentos.html"),
        cge_alertas.URL_MAPA_AREAS: _fixture_bytes("mapa_alertas.html"),
        cge_alertas.URL_MAPA_PNG: _fixture_bytes("mapa_alertas.png"),
    }

    def buscar(url):
        resposta = respostas[url]
        if isinstance(resposta, Exception):
            raise resposta
        return _Resposta(resposta)

    monkeypatch.setattr(cge_alertas, "_buscar", buscar)
    return respostas


def _get(alertas: CgeAlertas) -> CgeAlertasData:
    return asyncio.run(alertas.get())


class TestCgeAlertasColeta:
    def test_tudo_ok(self, site):
        dados = _get(CgeAlertas(_HassFalso()))
        assert dados.alagamentos_disponiveis and dados.mapa_disponivel
        assert dados.data_referencia == "15/11/2026"
        assert dados.estado_da_area("Sé") == ESTADO_OBSERVACAO

    def test_mapa_fora_do_ar_mantem_alagamentos(self, site, caplog):
        site[cge_alertas.URL_MAPA_PNG] = requests.exceptions.ConnectionError("fora do ar")
        alertas = CgeAlertas(_HassFalso())

        with caplog.at_level(logging.WARNING):
            dados = _get(alertas)
            _get(alertas)

        assert dados.alagamentos_disponiveis
        assert len(dados.pontos_da_zona("sul")) == 2
        assert not dados.mapa_disponivel
        # Logado uma vez, não a cada atualização
        assert caplog.text.count("falha ao obter mapa de alertas") == 1

    def test_layout_de_alagamentos_alterado_mantem_mapa(self, site):
        site[cge_alertas.URL_ALAGAMENTOS] = b"<html><body>novo layout</body></html>"
        dados = _get(CgeAlertas(_HassFalso()))
        assert not dados.alagamentos_disponiveis
        assert dados.mapa_disponivel

    def test_png_invalido_e_tratado(self, site):
        site[cge_alertas.URL_MAPA_PNG] = b"<html>erro 502</html>"
        dados = _get(CgeAlertas(_HassFalso()))
        assert dados.alagamentos_disponiveis
        assert not dados.mapa_disponivel

    def test_tudo_fora_do_ar_e_erro(self, site):
        erro = requests.exceptions.Timeout("timeout")
        for url in list(site):
            site[url] = erro
        with pytest.raises(CgeAlertasError) as excinfo:
            _get(CgeAlertas(_HassFalso()))
        assert "alagamentos" in str(excinfo.value)
        assert "mapa de alertas" in str(excinfo.value)

    def test_recuperacao_e_logada(self, site, caplog):
        original = site[cge_alertas.URL_MAPA_PNG]
        site[cge_alertas.URL_MAPA_PNG] = requests.exceptions.ConnectionError("fora")
        alertas = CgeAlertas(_HassFalso())
        _get(alertas)

        site[cge_alertas.URL_MAPA_PNG] = original
        with caplog.at_level(logging.INFO):
            dados = _get(alertas)
        assert dados.mapa_disponivel
        assert "mapa de alertas voltou a funcionar" in caplog.text

    def test_layout_quebrado_abre_e_fecha_conforme_a_leitura(self, site):
        """layout_quebrado alimenta os avisos em Configurações > Reparos."""
        original = site[cge_alertas.URL_ALAGAMENTOS]
        alertas = CgeAlertas(_HassFalso())

        _get(alertas)
        assert alertas.layout_quebrado == {}

        site[cge_alertas.URL_ALAGAMENTOS] = b"<html><body>novo layout</body></html>"
        _get(alertas)
        assert set(alertas.layout_quebrado) == {cge_alertas.PARTE_ALAGAMENTOS}
        assert "Layout" in alertas.layout_quebrado[cge_alertas.PARTE_ALAGAMENTOS]

        # Site fora do ar: não dá para saber se o layout voltou; mantém o aviso.
        site[cge_alertas.URL_ALAGAMENTOS] = requests.exceptions.ConnectionError("fora")
        _get(alertas)
        assert set(alertas.layout_quebrado) == {cge_alertas.PARTE_ALAGAMENTOS}

        site[cge_alertas.URL_ALAGAMENTOS] = original
        _get(alertas)
        assert alertas.layout_quebrado == {}

    def test_site_fora_do_ar_nao_e_layout_quebrado(self, site):
        for url in list(site):
            site[url] = requests.exceptions.ConnectionError("fora")
        alertas = CgeAlertas(_HassFalso())
        with pytest.raises(CgeAlertasError):
            _get(alertas)
        assert alertas.layout_quebrado == {}

    def test_layout_quebrado_registrado_mesmo_com_falha_total(self, site):
        site[cge_alertas.URL_ALAGAMENTOS] = b"<html>novo layout</html>"
        site[cge_alertas.URL_MAPA_PNG] = b"<html>nao e png</html>"
        alertas = CgeAlertas(_HassFalso())
        with pytest.raises(CgeAlertasError):
            _get(alertas)
        assert set(alertas.layout_quebrado) == set(cge_alertas.PARTES)

    def test_avisos_de_leitura_nao_se_repetem(self, site, caplog):
        site[cge_alertas.URL_ALAGAMENTOS] = _html_zona(
            "Centro",
            _html_ponto("ativo-transitavel", "AV PRESTES MAIA"),
            _html_ponto("status-novo", "R 25 DE MARCO"),
        ).encode("utf-8")
        alertas = CgeAlertas(_HassFalso())
        with caplog.at_level(logging.WARNING):
            _get(alertas)
            _get(alertas)
        assert caplog.text.count("R 25 DE MARCO") == 1
