import asyncio

import pytest
import requests

from custom_components.cgesp.cge_alertas import PontoAlagamento
from custom_components.cgesp.cge_geocodificacao import (
    INTERVALO_ENTRE_CONSULTAS,
    MAX_CONSULTAS_POR_RODADA,
    PRECISAO_APROXIMADO,
    PRECISAO_NUMERO,
    PRECISAO_REFERENCIA,
    PRECISAO_RUA,
    TTL_NAO_ENCONTRADO,
    Geocodificador,
    expandir_abreviacoes,
    extrair_numero,
    nomes_combinam,
)


def _ponto(local, referencia=None, ativo=True, zona="sul", bairro="Santo Amaro"):
    return PontoAlagamento(
        zona=zona,
        bairro=bairro,
        local=local,
        inicio="19:00",
        fim=None,
        sentido="AMBOS",
        referencia=referencia,
        ativo=ativo,
        transitavel=True,
    )


def _resultado(lat, lon, rua, cidade="São Paulo", numero=None):
    endereco = {"road": rua, "city": cidade}
    if numero:
        endereco["house_number"] = numero
    return {"lat": str(lat), "lon": str(lon), "name": rua, "address": endereco}


class _Nominatim:
    """Nominatim falso: respostas por texto consultado, e registro das consultas."""

    def __init__(self, respostas=None, erro=None):
        self.respostas = respostas or {}
        self.erro = erro
        self.consultas: list[str] = []

    def __call__(self, rua):
        self.consultas.append(rua)
        if self.erro:
            raise self.erro
        return self.respostas.get(rua, [])


class _Relogio:
    def __init__(self):
        self.agora = 1_000_000.0
        self.esperas: list[float] = []

    def __call__(self):
        return self.agora

    async def dormir(self, segundos):
        self.esperas.append(segundos)
        self.agora += segundos


async def _executar(func, *args):
    return func(*args)


def _geocodificador(nominatim, relogio=None):
    relogio = relogio or _Relogio()
    return Geocodificador(_executar, buscar=nominatim, dormir=relogio.dormir, relogio=relogio)


def _localizar(geo, pontos):
    return asyncio.run(geo.localizar(pontos))


class TestExpandirAbreviacoes:
    @pytest.mark.parametrize(
        ("via", "esperado"),
        [
            ("R STO ARCADIO", "Rua Santo ARCADIO"),
            ("AV MORVAN DIAS DE FIGUEIREDO", "Avenida MORVAN DIAS DE FIGUEIREDO"),
            ("R HONDURAS (JD PAULISTA)", "Rua HONDURAS"),
            ("AC RAPHAEL POTENZA", "Acesso RAPHAEL POTENZA"),
            ("PTE DA CASA VERDE-JORN.WALTER ABRAHAO", "Ponte DA CASA VERDE JORN.WALTER ABRAHAO"),
            ("Avenida Marechal Tito", "Avenida Marechal Tito"),
            ("AV PRES JUSCELINO KUBITSCHEK", "Avenida Presidente JUSCELINO KUBITSCHEK"),
        ],
    )
    def test_vias(self, via, esperado):
        assert expandir_abreviacoes(via) == esperado


class TestExtrairNumero:
    @pytest.mark.parametrize(
        ("referencia", "esperado"),
        [
            ("altura do número 7557", "7557"),
            ("ALTURA DO NUMERO 120", "120"),
            ("em frente ao nº 45", "45"),
            ("AV ROQUE PETRONI JUNIOR", None),
            (None, None),
        ],
    )
    def test_referencias(self, referencia, esperado):
        assert extrair_numero(referencia) == esperado


class TestNomesCombinam:
    @pytest.mark.parametrize(
        ("procurado", "encontrado"),
        [
            ("R STO ARCADIO", "Rua Santo Arcádio"),
            ("MARGINAL TIETE ASCB EXPRESSA", "Marginal Tietê (Expressa)"),
            ("AV MORVAN DIAS DE FIGUEIREDO", "Avenida Morvan Dias de Figueiredo (Local)"),
            ("R HONDURAS (JD PAULISTA)", "Rua Honduras"),
        ],
    )
    def test_mesma_via(self, procurado, encontrado):
        assert nomes_combinam(procurado, encontrado)

    @pytest.mark.parametrize(
        ("procurado", "encontrado"),
        [
            ("AC RAPHAEL POTENZA", "Rua Santo Arcádio"),  # caso real do Nominatim
            ("R HONDURAS", "Rua Canadá"),
            ("R HONDURAS", None),
        ],
    )
    def test_vias_diferentes(self, procurado, encontrado):
        assert not nomes_combinam(procurado, encontrado)


class TestLocalizar:
    def test_rua_encontrada(self):
        nominatim = _Nominatim(
            {"Rua Santo ARCADIO": [_resultado(-23.6234, -46.6910, "Rua Santo Arcádio")]}
        )
        ponto = _ponto("R STO ARCADIO", "AV ROQUE PETRONI JUNIOR")

        assert _localizar(_geocodificador(nominatim), [ponto]) is True

        assert (ponto.latitude, ponto.longitude) == (-23.6234, -46.6910)
        assert ponto.precisao_localizacao == PRECISAO_RUA
        assert nominatim.consultas == ["Rua Santo ARCADIO"]

    def test_com_numero(self):
        nominatim = _Nominatim(
            {
                "7557 Avenida Marechal Tito": [
                    _resultado(-23.4949, -46.4281, "Avenida Marechal Tito", numero="7557")
                ]
            }
        )
        ponto = _ponto("Avenida Marechal Tito", "altura do número 7557")
        _localizar(_geocodificador(nominatim), [ponto])
        assert ponto.precisao_localizacao == PRECISAO_NUMERO

    def test_numero_nao_achado_vira_rua(self):
        nominatim = _Nominatim(
            {"7557 Avenida Marechal Tito": [_resultado(-23.49, -46.42, "Avenida Marechal Tito")]}
        )
        ponto = _ponto("Avenida Marechal Tito", "altura do número 7557")
        _localizar(_geocodificador(nominatim), [ponto])
        assert ponto.precisao_localizacao == PRECISAO_RUA

    def test_usa_referencia_quando_a_rua_nao_combina(self):
        nominatim = _Nominatim(
            {
                # Caso real: o acesso não existe no OSM e o serviço devolve a vizinha.
                "Acesso RAPHAEL POTENZA": [_resultado(-23.6257, -46.6914, "Rua Santo Arcádio")],
                "Avenida ROQUE PETRONI JUNIOR": [
                    _resultado(-23.6220, -46.6990, "Avenida Roque Petroni Júnior")
                ],
            }
        )
        ponto = _ponto("AC RAPHAEL POTENZA", "AV ROQUE PETRONI JUNIOR")
        _localizar(_geocodificador(nominatim), [ponto])
        assert (ponto.latitude, ponto.precisao_localizacao) == (-23.6220, PRECISAO_REFERENCIA)

    def test_sem_referencia_util_fica_aproximado(self):
        nominatim = _Nominatim(
            {"Acesso RAPHAEL POTENZA": [_resultado(-23.6257, -46.6914, "Rua Santo Arcádio")]}
        )
        ponto = _ponto("AC RAPHAEL POTENZA", "próximo ao shopping")
        _localizar(_geocodificador(nominatim), [ponto])
        assert (ponto.latitude, ponto.precisao_localizacao) == (-23.6257, PRECISAO_APROXIMADO)

    def test_resultado_fora_de_sao_paulo_e_descartado(self):
        nominatim = _Nominatim(
            {"Rua HONDURAS": [_resultado(-22.9, -43.2, "Rua Honduras", cidade="Rio de Janeiro")]}
        )
        ponto = _ponto("R HONDURAS (JD PAULISTA)")
        _localizar(_geocodificador(nominatim), [ponto])
        assert not ponto.localizado

    def test_nao_encontrado(self):
        ponto = _ponto("R QUE NAO EXISTE")
        assert _localizar(_geocodificador(_Nominatim()), [ponto]) is True  # cacheou o "não achei"
        assert not ponto.localizado
        assert "latitude" not in ponto.como_atributo()


class TestCache:
    def _nominatim(self):
        return _Nominatim(
            {"Rua Santo ARCADIO": [_resultado(-23.6234, -46.6910, "Rua Santo Arcádio")]}
        )

    def test_mesmo_ponto_nao_e_consultado_de_novo(self):
        nominatim = self._nominatim()
        geo = _geocodificador(nominatim)

        _localizar(geo, [_ponto("R STO ARCADIO")])
        novo = _ponto("R STO ARCADIO")  # o mesmo ponto na consulta seguinte
        assert _localizar(geo, [novo]) is False

        assert len(nominatim.consultas) == 1
        assert novo.latitude == -23.6234

    def test_aplicar_cache_preenche_sem_consultar(self):
        nominatim = self._nominatim()
        geo = _geocodificador(nominatim)
        _localizar(geo, [_ponto("R STO ARCADIO")])

        cacheado, novo = _ponto("R STO ARCADIO"), _ponto("R HONDURAS")
        pendentes = geo.aplicar_cache([cacheado, novo])

        assert cacheado.localizado
        assert pendentes == [novo]
        assert len(nominatim.consultas) == 1

    def test_pontos_repetidos_na_mesma_rodada_consultam_uma_vez(self):
        nominatim = self._nominatim()
        pontos = [_ponto("R STO ARCADIO"), _ponto("R STO ARCADIO", zona="sul", bairro="Outro")]
        _localizar(_geocodificador(nominatim), pontos)
        assert len(nominatim.consultas) == 1
        assert all(p.localizado for p in pontos)

    def test_exportar_e_importar(self):
        geo = _geocodificador(self._nominatim())
        _localizar(geo, [_ponto("R STO ARCADIO"), _ponto("R QUE NAO EXISTE")])

        nominatim = _Nominatim()
        restaurado = _geocodificador(nominatim)
        restaurado.importar(geo.exportar())
        ponto = _ponto("R STO ARCADIO")
        assert _localizar(restaurado, [ponto, _ponto("R QUE NAO EXISTE")]) is False

        assert ponto.precisao_localizacao == PRECISAO_RUA
        assert nominatim.consultas == []

    def test_importar_ignora_lixo(self):
        geo = _geocodificador(_Nominatim())
        geo.importar({"x": "lixo", "y": {"quando": "ontem"}, "z": None})
        assert geo.exportar() == {}

    def test_nao_encontrado_e_tentado_de_novo_depois_de_um_dia(self):
        relogio = _Relogio()
        nominatim = _Nominatim()
        geo = _geocodificador(nominatim, relogio)

        _localizar(geo, [_ponto("R QUE NAO EXISTE")])
        _localizar(geo, [_ponto("R QUE NAO EXISTE")])
        assert len(nominatim.consultas) == 1

        relogio.agora += TTL_NAO_ENCONTRADO + 1
        _localizar(geo, [_ponto("R QUE NAO EXISTE")])
        assert len(nominatim.consultas) == 2

    def test_erro_de_rede_nao_e_cacheado(self):
        nominatim = _Nominatim(erro=requests.exceptions.ConnectionError("fora"))
        geo = _geocodificador(nominatim)
        ponto = _ponto("R STO ARCADIO")

        assert _localizar(geo, [ponto]) is False
        nominatim.erro = None
        nominatim.respostas = self._nominatim().respostas
        assert _localizar(geo, [ponto]) is True
        assert ponto.localizado


class TestLimiteDeConsultas:
    def test_espera_entre_consultas(self):
        relogio = _Relogio()
        geo = _geocodificador(_Nominatim(), relogio)
        _localizar(geo, [_ponto(f"R NUMERO {i}") for i in range(3)])
        assert relogio.esperas == [INTERVALO_ENTRE_CONSULTAS] * 2

    def test_maximo_por_rodada(self):
        nominatim = _Nominatim()
        geo = _geocodificador(nominatim)
        pontos = [_ponto(f"R NUMERO {i}") for i in range(MAX_CONSULTAS_POR_RODADA + 5)]

        _localizar(geo, pontos)
        assert len(nominatim.consultas) == MAX_CONSULTAS_POR_RODADA

        _localizar(geo, pontos)  # os que sobraram vão na rodada seguinte
        assert len(nominatim.consultas) == MAX_CONSULTAS_POR_RODADA + 5


class TestPontoAlagamento:
    def test_chave_estavel_entre_consultas(self):
        assert _ponto("R STO ARCADIO").chave == _ponto("R Sto Arcádio").chave

    def test_atributo_com_localizacao(self):
        ponto = _ponto("R STO ARCADIO")
        ponto.latitude, ponto.longitude, ponto.precisao_localizacao = -23.6, -46.6, PRECISAO_RUA
        atributo = ponto.como_atributo()
        assert atributo["latitude"] == -23.6
        assert atributo["precisao_localizacao"] == PRECISAO_RUA
