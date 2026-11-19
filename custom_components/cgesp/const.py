"""Constants for the Centro de Gerenciamento de Emergências Climáticas da Prefeitura de São Paulo integration."""

from datetime import timedelta

DOMAIN = "cgesp"
ENTRADA_ESTACAO_METEOROLOGICA = "ESTACAO_METEOROLOGICA"
CONF_ESTACAO_ID = "ESTACAO_ID"

# Tipo da entrada de configuração. Entradas antigas (sem CONF_TIPO) são estações.
CONF_TIPO = "TIPO"
TIPO_ESTACAO = "estacao"
TIPO_ALERTAS_CIDADE = "alertas_cidade"
UNIQUE_ID_ALERTAS_CIDADE = "cge_alertas_cidade"

# Opções de "Alertas da cidade".
CONF_GEOCODIFICAR = "geocodificar"  # localizar os pontos no OpenStreetMap
CONF_ENTIDADES_PROXIMIDADE = "entidades_proximidade"  # person/device_tracker/zone
CONF_RAIO_KM = "raio_km"
RAIO_KM_PADRAO = 2.0
CONF_INTERVALO_ADAPTATIVO = "intervalo_adaptativo"  # 30 min quando não há chuva prevista

EVENTO_ALAGAMENTO_NOVO = "cgesp_alagamento_novo"
EVENTO_ALAGAMENTO_ENCERRADO = "cgesp_alagamento_encerrado"

ALERTAS_UPDATE_INTERVAL = timedelta(minutes=10)
# Radar de chuva: 5 min; 15 min sem chuva no radar nem na previsão.
INTERVALO_RADAR = timedelta(minutes=5)
INTERVALO_RADAR_SEM_CHUVA = timedelta(minutes=15)
DATA_RADAR_COORDINATOR = "radar_coordinator"
DATA_ALERTAS_COORDINATOR = "alertas_coordinator"
DATA_ALERTAS_USUARIOS = "alertas_usuarios"

ZONAS = {
    "norte": "Zona Norte",
    "sul": "Zona Sul",
    "leste": "Zona Leste",
    "oeste": "Zona Oeste",
    "centro": "Centro",
}

ESTADO_OBSERVACAO = "observacao"
ESTADO_ATENCAO = "atencao"
ESTADO_IMINENCIA = "iminencia_transbordamento"
ESTADO_ALERTA = "alerta"
# Em ordem de gravidade.
ESTADOS_ALERTA = [ESTADO_OBSERVACAO, ESTADO_ATENCAO, ESTADO_IMINENCIA, ESTADO_ALERTA]

# Estação -> (zona, área monitorada no mapa de alertas do CGE).
# Estações fora da capital não têm área no mapa: None.
ESTACOES_REGIAO: dict[int, tuple[str, str] | None] = {
    1000842: ("oeste", "Butantã"),
    1000854: ("sul", "Campo Limpo"),
    846: ("sul", "Cidade Dutra/Socorro"),
    592: ("sul", "Cidade Ademar"),
    509: ("norte", "Freguesia do Ó"),
    1000882: ("leste", "Itaim Paulista"),
    1000840: ("sul", "Ipiranga"),
    1000864: ("leste", "Itaquera"),
    634: ("sul", "Jabaquara"),
    1000848: ("oeste", "Lapa"),
    1000300: ("sul", "Parelheiros"),
    1000850: ("sul", "M'Boi Mirim"),
    1000862: ("leste", "São Miguel Paulista"),
    1000876: None,  # Mauá
    1000860: ("leste", "Mooca"),
    507: ("sul", "Parelheiros"),
    1000887: ("leste", "Penha"),
    504: ("norte", "Perus"),
    515: ("norte", "Pirituba/Jaraguá"),
    1000635: ("oeste", "Pinheiros"),
    400: None,  # Riacho Grande (São Bernardo do Campo)
    1000852: ("sul", "Santo Amaro"),
    1000857: ("sul", "Cidade Dutra/Socorro"),
    510: ("norte", "Santana"),
    1000844: ("leste", "São Mateus"),
    503: ("centro", "Sé"),
    1000880: None,  # Santana do Parnaíba
    1000944: ("norte", "Jaçanã/Tremembé"),
    1000859: ("leste", "Aricanduva/Vila Formosa"),
    524: ("leste", "Vila Prudente"),
    540: ("norte", "Vila Maria/Vila Guilherme"),
    495: ("sul", "Vila Mariana"),
}
ESTACOES = {
    1000842: "Butantã",
    1000854: "Campo Limpo",
    846: "Capela do Socorro",
    592: "Cidade Ademar",
    509: "Freguesia do Ó",
    1000882: "Itaim Paulista",
    1000840: "Ipiranga",
    1000864: "Itaquera",
    634: "Jabaquara",
    1000848: "Lapa",
    1000300: "Marsilac",
    1000850: "M Boi Mirim",
    1000862: "Miguel Paulista",
    1000876: "Mauá - Paço Municipal",
    1000860: "Móoca",
    507: "Parelheiros",
    1000887: "Penha",
    504: "Perus",
    515: "Pirituba",
    1000635: "Pinheiros",
    400: "Riacho Grande",
    1000852: "Santo Amaro",
    1000857: "Socorro",
    510: "Santana/Tucuruvi",
    1000844: "São Mateus",
    503: "Sé",
    1000880: "Santana do Parnaíba",
    1000944: "Tremembé",
    1000859: "Vila Formosa",
    524: "Vila Prudente",
    540: "Vila Maria / Guilherme",
    495: "Vila Mariana",
}
