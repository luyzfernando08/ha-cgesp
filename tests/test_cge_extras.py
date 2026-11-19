import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

import custom_components.cgesp.cge_alertas as cge_alertas
from custom_components.cgesp.cge_alertas import (
    CgeAlertas,
    CgeAlertasData,
    CgeAlertasError,
    PontoAlagamento,
)
from custom_components.cgesp.cge_extras import (
    INTERVALO_COM_CHUVA,
    INTERVALO_SEM_CHUVA,
    PeriodoPrevisao,
    _data_rss,
    chuva_prevista,
    diferenca_pontos,
    distancia_km,
    escolher_intervalo,
    parse_boletim,
    parse_periodos,
    periodos_na_janela,
    pontos_proximos,
)

FIXTURES = Path(__file__).parent / "fixtures"
COMPONENTE = Path(__file__).parent.parent / "custom_components" / "cgesp"


def _texto(nome: str) -> str:
    return (FIXTURES / nome).read_bytes().decode("utf-8", errors="replace")


def _ponto(local="R TESTE", zona="sul", lat=None, lon=None, ativo=True, inicio="10:00"):
    return PontoAlagamento(
        zona=zona,
        bairro="Bairro",
        local=local,
        inicio=inicio,
        fim=None,
        sentido=None,
        referencia=None,
        ativo=ativo,
        transitavel=True,
        latitude=lat,
        longitude=lon,
    )


def _periodo(dia: datetime, hora: int, condicao: str, potencial: str | None = "Baixo"):
    inicio = dia.replace(hour=hora, minute=0)
    return PeriodoPrevisao(inicio, inicio + timedelta(hours=6), "x", condicao, potencial)


# --------------------------------------------------------------------------- #
# Previsão por período
# --------------------------------------------------------------------------- #


class TestParsePeriodos:
    def test_previsao_com_pancadas(self):
        periodos = parse_periodos(_texto("previsao_pancadas.html"))
        assert len(periodos) == 12  # 3 dias x 4 períodos
        tarde = periodos[2]
        assert tarde.inicio == datetime(2026, 11, 19, 12)
        assert tarde.fim == datetime(2026, 11, 19, 18)
        assert tarde.periodo == "tarde"
        assert tarde.condicao == "Pancadas isoladas"
        assert tarde.potencial_temporais == "Baixo"
        assert periodos[3].fim == datetime(2026, 11, 20, 0)
        assert periodos[6].condicao == "Pancadas de chuva"
        assert periodos[6].potencial_temporais == "Moderado"

    def test_fixture_antiga(self):
        periodos = parse_periodos(_texto("previsao.html"))
        assert periodos[0].inicio == datetime(2026, 8, 7, 0)
        assert periodos[3].condicao == "Pancadas de chuva"

    def test_layout_alterado(self):
        with pytest.raises(CgeAlertasError):
            parse_periodos("<html><body>outro layout</body></html>")


class TestChuvaPrevista:
    @pytest.mark.parametrize(
        ("condicao", "potencial", "esperado"),
        [
            ("Céu claro", "Baixo", False),
            ("Poucas nuvens", None, False),
            ("Nublado", "Baixo", False),
            ("Pancadas isoladas", "Baixo", True),
            ("Pancadas de chuva", "Moderado", True),
            ("Chuvisco", None, True),
            ("Garoa", None, True),
            ("Nublado com chuva", None, True),
            ("Nublado", "Moderado", True),  # potencial para temporais
            ("Nublado", "Alto", True),
        ],
    )
    def test_condicoes(self, condicao, potencial, esperado):
        dia = datetime(2026, 11, 19)
        assert _periodo(dia, 12, condicao, potencial).pode_chover is esperado

    def test_madrugada_olha_ate_a_tarde(self):
        periodos = parse_periodos(_texto("previsao_pancadas.html"))
        # 01:38: janela de 12 h chega até 13:38 e pega a tarde com pancadas
        assert chuva_prevista(periodos, datetime(2026, 11, 19, 1, 38)) is True

    def test_noite_sem_chuva(self):
        periodos = parse_periodos(_texto("previsao_pancadas.html"))
        # 19:00: noite e madrugada nubladas, manhã com poucas nuvens
        assert chuva_prevista(periodos, datetime(2026, 11, 19, 19, 0)) is False

    def test_janela(self):
        dia = datetime(2026, 11, 19)
        periodos = [_periodo(dia, h, "Nublado") for h in (0, 6, 12, 18)]
        nomes = [p.inicio.hour for p in periodos_na_janela(periodos, dia.replace(hour=7))]
        assert nomes == [6, 12, 18]

    def test_sem_previsao_ou_desatualizada(self):
        assert chuva_prevista(None, datetime(2026, 11, 19)) is None
        antigos = parse_periodos(_texto("previsao.html"))  # agosto
        assert chuva_prevista(antigos, datetime(2026, 11, 19, 10)) is None


class TestEscolherIntervalo:
    AGORA = datetime(2026, 11, 19, 19, 0)

    def _dados(self, pontos=(), estados=None):
        return CgeAlertasData(
            data_referencia="19/11/2026",
            alagamentos={"sul": list(pontos)},
            estados_areas=estados if estados is not None else {"se": "observacao"},
        )

    def _periodos(self, condicao):
        return [_periodo(datetime(2026, 11, 19), 18, condicao)]

    def test_sem_chuva_prevista_espaca(self):
        intervalo, motivo = escolher_intervalo(
            self._dados(), self._periodos("Nublado"), self.AGORA
        )
        assert intervalo == INTERVALO_SEM_CHUVA
        assert "sem chuva" in motivo

    def test_chuva_prevista(self):
        intervalo, _ = escolher_intervalo(
            self._dados(), self._periodos("Pancadas de chuva"), self.AGORA
        )
        assert intervalo == INTERVALO_COM_CHUVA

    def test_alagamento_ativo_mesmo_sem_previsao_de_chuva(self):
        intervalo, motivo = escolher_intervalo(
            self._dados(pontos=[_ponto()]), self._periodos("Nublado"), self.AGORA
        )
        assert intervalo == INTERVALO_COM_CHUVA
        assert "alagamentos" in motivo

    def test_regiao_em_atencao(self):
        intervalo, _ = escolher_intervalo(
            self._dados(estados={"se": "atencao"}), self._periodos("Nublado"), self.AGORA
        )
        assert intervalo == INTERVALO_COM_CHUVA

    @pytest.mark.parametrize("caso", ["sem_dados", "sem_previsao", "sem_mapa"])
    def test_na_duvida_fica_no_curto(self, caso):
        dados = self._dados()
        periodos = self._periodos("Nublado")
        if caso == "sem_dados":
            dados = None
        elif caso == "sem_previsao":
            periodos = None
        else:
            dados.estados_areas = None
        intervalo, _ = escolher_intervalo(dados, periodos, self.AGORA)
        assert intervalo == INTERVALO_COM_CHUVA


# --------------------------------------------------------------------------- #
# Boletim
# --------------------------------------------------------------------------- #


class TestBoletim:
    def test_feed_real(self):
        boletim = parse_boletim((FIXTURES / "feed_rss.xml").read_bytes())
        assert boletim.id == "56475"
        assert boletim.titulo == "Início de madrugada com céu encoberto e sem registro de chuva"
        assert boletim.publicado_em == datetime(2026, 11, 18, 23, 58, 21)
        assert boletim.link == "https://www.cgesp.org/v3/noticias.jsp?id=56475"
        assert boletim.texto.startswith("A madrugada de quinta-feira (19) começa com céu encoberto")
        assert "<" not in boletim.texto and "&lt;" not in boletim.texto
        assert "Tendência para os próximos dias:" in boletim.texto
        assert "\n\n" in boletim.texto  # parágrafos preservados

    def test_latin1(self):
        xml = (
            '<?xml version="1.0"?><rss><channel><item><title>Previsão</title>'
            "<pubDate>Sáb, 01 fev 2025 08:05:00 GMT</pubDate>"
            "<description>&lt;p&gt;Chuva forte&lt;/p&gt;</description></item></channel></rss>"
        ).encode("latin-1")
        boletim = parse_boletim(xml)
        assert boletim.titulo == "Previsão"
        assert boletim.publicado_em == datetime(2025, 2, 1, 8, 5)
        assert boletim.texto == "Chuva forte"
        assert boletim.link is None

    @pytest.mark.parametrize(
        "conteudo",
        [
            b"<html>erro</html",
            b"<rss><channel></channel></rss>",
            b"<rss><channel><item><title> </title></item></channel></rss>",
        ],
    )
    def test_feed_invalido(self, conteudo):
        with pytest.raises(CgeAlertasError):
            parse_boletim(conteudo)

    @pytest.mark.parametrize(
        ("texto", "esperado"),
        [
            ("Qua, 18 nov 2026 23:58:21 GMT", datetime(2026, 11, 18, 23, 58, 21)),
            ("Seg, 3 mar 2025 07:10 GMT", datetime(2025, 3, 3, 7, 10)),
            ("Ter, 01 dez 2026 00:00:00 GMT", datetime(2026, 12, 1)),
            ("Wed, 18 Nov 2026 23:58:21 GMT", datetime(2026, 11, 18, 23, 58, 21)),
            ("", None),
            (None, None),
            ("Qua, 31 fev 2026 10:00:00 GMT", None),
        ],
    )
    def test_data(self, texto, esperado):
        assert _data_rss(texto) == esperado


# --------------------------------------------------------------------------- #
# Distância e proximidade
# --------------------------------------------------------------------------- #


class TestDistancia:
    def test_mesmo_ponto(self):
        assert distancia_km(-23.55, -46.63, -23.55, -46.63) == 0

    def test_se_a_santo_amaro(self):
        # Praça da Sé -> Largo 13 de Maio: ~13,7 km em linha reta
        km = distancia_km(-23.5503, -46.6340, -23.6545, -46.7097)
        assert 13.5 < km < 14.0

    def test_pontos_proximos(self):
        pessoa = (-23.6500, -46.7100)
        perto = _ponto("R PERTO", lat=-23.6530, lon=-46.7100)  # ~0,33 km
        medio = _ponto("R MEDIO", lat=-23.6650, lon=-46.7100)  # ~1,67 km
        longe = _ponto("R LONGE", lat=-23.5500, lon=-46.6300)  # ~14 km
        sem_local = _ponto("R SEM LOCAL")
        resultado = pontos_proximos(*pessoa, [longe, medio, sem_local, perto], 2)
        assert [p.local for p, _ in resultado] == ["R PERTO", "R MEDIO"]
        assert resultado[0][1] == pytest.approx(0.33, abs=0.01)
        assert pontos_proximos(*pessoa, [medio], 1) == []


# --------------------------------------------------------------------------- #
# Eventos
# --------------------------------------------------------------------------- #


class TestDiferencaPontos:
    def test_novos_e_encerrados(self):
        a, b, c = _ponto("R A"), _ponto("R B"), _ponto("R C")
        anteriores = {a.chave: a, b.chave: b}
        atuais = {b.chave: b, c.chave: c}
        novos, encerrados = diferenca_pontos(anteriores, atuais)
        assert [p.local for p in novos] == ["R C"]
        assert [p.local for p in encerrados] == ["R A"]

    def test_mesma_rua_com_outro_inicio_e_outro_ponto(self):
        manha, tarde = _ponto("R A", inicio="08:00"), _ponto("R A", inicio="15:00")
        novos, encerrados = diferenca_pontos({manha.chave: manha}, {tarde.chave: tarde})
        assert len(novos) == 1 and len(encerrados) == 1

    def test_sem_mudanca(self):
        a = _ponto("R A")
        assert diferenca_pontos({a.chave: a}, {a.chave: a}) == ([], [])


# --------------------------------------------------------------------------- #
# Mapa de alertas guardado para a câmera
# --------------------------------------------------------------------------- #


class _Resposta:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.headers = {}


class _HassFalso:
    async def async_add_executor_job(self, func, *args):
        return func(*args)


def test_png_do_mapa_fica_nos_dados(monkeypatch):
    respostas = {
        cge_alertas.URL_ALAGAMENTOS: (FIXTURES / "alagamentos.html").read_bytes(),
        cge_alertas.URL_MAPA_AREAS: (FIXTURES / "mapa_alertas.html").read_bytes(),
        cge_alertas.URL_MAPA_PNG: (FIXTURES / "mapa_alertas.png").read_bytes(),
    }
    monkeypatch.setattr(cge_alertas, "_buscar", lambda url: _Resposta(respostas[url]))
    dados = asyncio.run(CgeAlertas(_HassFalso()).get())
    assert dados.mapa_png == respostas[cge_alertas.URL_MAPA_PNG]
    assert dados.boletim is None and dados.periodos_previsao is None


# --------------------------------------------------------------------------- #
# Traduções
# --------------------------------------------------------------------------- #


def _chaves(valor, prefixo=""):
    if isinstance(valor, dict):
        chaves = set()
        for chave, filho in valor.items():
            chaves |= _chaves(filho, f"{prefixo}.{chave}" if prefixo else chave)
        return chaves
    return {prefixo}


def _json(caminho: Path) -> dict:
    return json.loads(caminho.read_text(encoding="utf-8"))


@pytest.mark.parametrize("idioma", ["en", "pt-BR"])
def test_traducoes_tem_as_mesmas_chaves_que_strings(idioma):
    strings = _chaves(_json(COMPONENTE / "strings.json"))
    traducao = _chaves(_json(COMPONENTE / "translations" / f"{idioma}.json"))
    assert traducao == strings


def test_traducao_em_ingles_esta_em_ingles():
    en = _json(COMPONENTE / "translations" / "en.json")
    assert en["config"]["step"]["user"]["menu_options"]["estacao"] == "Weather station"
    assert en["entity"]["sensor"]["estado_alerta"]["state"]["alerta"] == "Alert"


def test_opcoes_do_fluxo_estao_traduzidas():
    """Toda opção da tela de configuração tem rótulo nas traduções."""
    from custom_components.cgesp import const

    strings = _json(COMPONENTE / "strings.json")
    rotulos = strings["options"]["step"]["init"]["data"]
    for opcao in (
        const.CONF_GEOCODIFICAR,
        const.CONF_ENTIDADES_PROXIMIDADE,
        const.CONF_RAIO_KM,
        const.CONF_INTERVALO_ADAPTATIVO,
    ):
        assert opcao in rotulos
