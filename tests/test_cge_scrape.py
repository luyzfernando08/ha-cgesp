from datetime import datetime
from pathlib import Path

import pytest

from custom_components.cgesp.cge_scrape import (
    _de_para_ceu,
    _parse_estacao,
    _parse_previsao,
    _pega_periodo_dia,
    _texto_para_numero,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _read_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class TestTextoParaNumero:
    def test_extrai_decimal(self):
        assert _texto_para_numero("Atual:23.3 °C") == 23.3

    def test_extrai_inteiro_quando_nao_ha_decimal(self):
        assert _texto_para_numero("24°") == 24.0

    def test_ignora_texto_antes_do_numero(self):
        assert _texto_para_numero("Rajada:20.3 km/h") == 20.3


class TestDeParaCeu:
    @pytest.mark.parametrize(
        ("ceu", "esperado"),
        [
            ("Céu claro", "sunny"),
            ("Poucas nuvens", "partlycloudy"),
            ("Chuva", "rainy"),
            ("Nublado com chuva", "rainy"),
            ("Chuvisco", "rainy"),
            ("Pancadas isoladas", "rainy"),
            ("Pancadas de chuva", "rainy"),
            ("Nublado", "cloudy"),
            ("Encoberto", "cloudy"),
        ],
    )
    def test_mapeamentos_conhecidos(self, ceu, esperado):
        assert _de_para_ceu(ceu) == esperado

    def test_condicao_desconhecida_retorna_none_e_loga(self, caplog):
        with caplog.at_level("WARNING"):
            assert _de_para_ceu("Trovoadas") is None
        assert "Trovoadas" in caplog.text


class TestPegaPeriodoDia:
    @pytest.mark.parametrize(
        ("hora", "esperado"),
        [
            (0, ".prev-madrug"),
            (5, ".prev-madrug"),
            (6, ".prev-manha"),
            (11, ".prev-manha"),
            (12, ".prev-tarde"),
            (17, ".prev-tarde"),
            (18, ".prev-noite"),
            (23, ".prev-noite"),
        ],
    )
    def test_periodos_por_hora(self, hora, esperado):
        agora = datetime(2026, 8, 7, hora)
        assert _pega_periodo_dia(agora) == esperado


class TestParseEstacao:
    def test_extrai_dados_da_estacao(self):
        estacao = _parse_estacao(_read_fixture("estacao.html"))

        assert estacao.temperatura == 23.3
        assert estacao.umidade == 59.6
        assert estacao.vento == 20.3
        assert estacao.pressaoDoAr == 913.6


class TestParsePrevisao:
    def test_numero_de_dias_previstos(self):
        forecasts = _parse_previsao(_read_fixture("previsao.html"))
        assert len(forecasts) == 3

    def test_primeiro_dia(self):
        forecasts = _parse_previsao(
            _read_fixture("previsao.html"), agora=datetime(2026, 8, 7, 8)
        )
        primeiro = forecasts[0]

        assert primeiro.datetime == datetime(2026, 8, 7)
        assert primeiro.temperaturaMaxima == 24.0
        assert primeiro.temperaturaMinima == 18.0
        assert primeiro.umidade == 50.0
        assert primeiro.condicaoTempo == "rainy"  # Pancadas isoladas (manhã)

    @pytest.mark.parametrize(
        ("hora", "esperado"),
        [
            (3, "cloudy"),  # madrugada: Nublado
            (8, "rainy"),  # manhã: Pancadas isoladas
            (14, "rainy"),  # tarde: Pancadas isoladas
            (20, "rainy"),  # noite: Pancadas de chuva
        ],
    )
    def test_condicao_varia_por_periodo_do_dia(self, hora, esperado):
        forecasts = _parse_previsao(
            _read_fixture("previsao.html"), agora=datetime(2026, 8, 7, hora)
        )
        assert forecasts[0].condicaoTempo == esperado

    def test_terceiro_dia(self):
        forecasts = _parse_previsao(
            _read_fixture("previsao.html"), agora=datetime(2026, 8, 7, 8)
        )
        terceiro = forecasts[2]

        assert terceiro.datetime == datetime(2026, 8, 9)
        assert terceiro.temperaturaMaxima == 27.0
        assert terceiro.temperaturaMinima == 17.0
        assert terceiro.umidade == 45.0
