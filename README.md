# CGE - SP para Home Assistant

Traz para o Home Assistant os dados do [CGE](https://www.cgesp.org/v3/), o Centro de Gerenciamento de Emergências Climáticas da Prefeitura de São Paulo: clima das estações meteorológicas, pontos de alagamento e o estado de alerta de cada região da cidade.

## O que você ganha

- **Clima da estação mais perto de você:** temperatura, umidade, pressão, vento e previsão para os próximos dias.
- **Alagamentos por zona:** um sensor para cada zona (Norte, Sul, Leste, Oeste e Centro) que liga quando há alagamento ativo, com os bairros e as ruas afetadas.
- **Estado de alerta da sua região:** o mesmo estado que o CGE mostra no mapa da página inicial (Observação, Atenção, Iminência de transbordamento ou Alerta), com o horário da última atualização do mapa.
- **Alagamentos no mapa (opcional):** cada ponto alagado aparece no cartão de mapa do Home Assistant, e você pode criar automações do tipo "avise se alagar perto do trabalho".

Os alertas são atualizados a cada 10 minutos.

## Instalação

Você precisa ter o [HACS](https://hacs.xyz/) instalado.

1. No HACS, abra o menu (⋮) e vá em **Repositórios personalizados**.
2. Cole o endereço abaixo, escolha a categoria **Integração** e clique em **Adicionar**:
   ```
   https://github.com/luyzfernando08/ha-cgesp
   ```
3. Procure por **CGE - SP**, clique em **Baixar** e reinicie o Home Assistant.

## Configuração

Clique no botão para abrir a configuração direto no seu Home Assistant:

<a href="https://my.home-assistant.io/redirect/config_flow_start?domain=cgesp" rel="CGE - SP">![Adicionar integração](https://my.home-assistant.io/badges/config_flow_start.svg)</a>

Ou vá em **Configurações → Dispositivos e serviços → Adicionar integração** e procure por **CGE - SP**.

A integração pergunta o que você quer adicionar:

- **Estação meteorológica:** escolha a estação mais próxima. Você pode adicionar quantas quiser, uma de cada vez.
- **Alertas da cidade:** cria os sensores de alagamento das cinco zonas. Só precisa adicionar uma vez. Aqui também dá para ligar a opção **Mostrar os pontos de alagamento no mapa**, que pode ser alterada depois em **Configurar**.

Tudo fica agrupado num único dispositivo chamado **CGE - SP**.

## Estação meteorológica

Cada estação cria uma entidade de clima (`weather`) com temperatura, umidade, pressão, velocidade do vento e a previsão diária do CGE. Esses dados são atualizados mais ou menos a cada hora.

Nas estações da capital, você também ganha dois sensores com o estado de alerta da região da estação. Usando Santo Amaro como exemplo:

| Entidade | O que mostra |
|---|---|
| `sensor.cgesp_santo_amaro_estado_alerta` | Observação, Atenção, Iminência de transbordamento ou Alerta |
| `binary_sensor.cgesp_santo_amaro_atencao` | Fica ligado sempre que a região sai de Observação, o que é prático para automações |

Os dois trazem como atributos a estação, a zona, a área monitorada e `atualizado_em`, que é o horário que aparece no mapa do CGE ("Atualizado em").

O CGE só publica esse estado como imagem, no mapa "Situação das Áreas Monitoradas" da página inicial. A integração lê a cor de cada região do mapa. Mauá, Riacho Grande e Santana do Parnaíba ficam fora do mapa da capital, então essas estações não têm os sensores de alerta.

<details>
<summary>Zona e área monitorada de cada estação</summary>

| Estação | Zona | Área no mapa do CGE |
|---|---|---|
| Butantã | Oeste | Butantã |
| Lapa | Oeste | Lapa |
| Pinheiros | Oeste | Pinheiros |
| Freguesia do Ó | Norte | Freguesia do Ó |
| Perus | Norte | Perus |
| Pirituba | Norte | Pirituba/Jaraguá |
| Santana/Tucuruvi | Norte | Santana |
| Tremembé | Norte | Jaçanã/Tremembé |
| Vila Maria / Guilherme | Norte | Vila Maria/Vila Guilherme |
| Itaim Paulista | Leste | Itaim Paulista |
| Itaquera | Leste | Itaquera |
| Miguel Paulista | Leste | São Miguel Paulista |
| Móoca | Leste | Mooca |
| Penha | Leste | Penha |
| São Mateus | Leste | São Mateus |
| Vila Formosa | Leste | Aricanduva/Vila Formosa |
| Vila Prudente | Leste | Vila Prudente |
| Campo Limpo | Sul | Campo Limpo |
| Capela do Socorro | Sul | Cidade Dutra/Socorro |
| Socorro | Sul | Cidade Dutra/Socorro |
| Cidade Ademar | Sul | Cidade Ademar |
| Ipiranga | Sul | Ipiranga |
| Jabaquara | Sul | Jabaquara |
| M Boi Mirim | Sul | M'Boi Mirim |
| Marsilac | Sul | Parelheiros |
| Parelheiros | Sul | Parelheiros |
| Santo Amaro | Sul | Santo Amaro |
| Vila Mariana | Sul | Vila Mariana |
| Sé | Centro | Sé |
| Mauá, Riacho Grande, Santana do Parnaíba | — | fora do mapa |

</details>

## Alertas da cidade: alagamentos por zona

Ao adicionar **Alertas da cidade**, você ganha um sensor por zona:

- `binary_sensor.cgesp_alagamento_zona_norte`
- `binary_sensor.cgesp_alagamento_zona_sul`
- `binary_sensor.cgesp_alagamento_zona_leste`
- `binary_sensor.cgesp_alagamento_zona_oeste`
- `binary_sensor.cgesp_alagamento_centro`

O sensor liga quando a zona tem pelo menos um ponto de alagamento **ativo** e desliga quando todos forem encerrados. Os detalhes ficam nos atributos:

| Atributo | O que tem |
|---|---|
| `bairros` | Bairros com alagamento ativo |
| `ruas` | Ruas e avenidas alagadas agora |
| `pontos_ativos` | Quantos pontos estão ativos |
| `pontos_intransitaveis` | Quantos desses estão intransitáveis |
| `pontos_encerrados_hoje` | Pontos que já foram encerrados hoje |
| `pontos` | Lista completa: bairro, local, horário de início, sentido, referência e se dá para passar (com a opção de mapa ligada, também latitude e longitude) |
| `data_referencia` | Data consultada no site do CGE |

Os dados vêm da página de [alagamentos do CGE](https://www.cgesp.org/v3/alagamentos.jsp), que é preenchida pelos agentes de trânsito da Prefeitura. Ela cobre principalmente o centro expandido e os grandes corredores, então pode não listar alagamentos em ruas menores.

## Alagamentos no mapa

O CGE informa só o nome da rua e uma referência, sem coordenadas. Com a opção **Mostrar os pontos de alagamento no mapa** ligada, a integração consulta cada rua no [OpenStreetMap](https://www.openstreetmap.org/) para descobrir a posição aproximada.

Cada alagamento ativo vira uma entidade `geo_location`. Ela aparece quando o CGE registra o ponto e some quando ele é encerrado. O estado é a distância até a sua casa, em km, e os atributos trazem rua, bairro, zona, referência, horário de início e se dá para passar.

Para ver no mapa, crie um cartão de mapa com a fonte `cgesp`:

```yaml
type: map
geo_location_sources:
  - cgesp
entities:
  - zone.home
```

**Sobre a precisão:** o nome que o CGE publica nem sempre bate com o do OpenStreetMap. Por isso cada ponto traz o atributo `precisao_localizacao`:

| Valor | O que significa |
|---|---|
| `numero` | Achou a rua e o número ("altura do número 7557") |
| `rua` | Achou a rua certa, mas não o trecho. Em avenidas longas, o ponto pode estar a quilômetros do alagamento real |
| `referencia` | Não achou a rua e usou a via da referência |
| `aproximado` | O serviço devolveu uma rua vizinha, com outro nome |

Cada rua é consultada uma única vez e o resultado fica guardado, então o OpenStreetMap não é consultado a cada 10 minutos. Se o serviço estiver fora do ar ou não achar a rua, o ponto só não aparece no mapa: os sensores de alagamento continuam funcionando normalmente.

Com a opção ligada, os nomes das ruas alagadas são enviados do seu Home Assistant para os servidores do OpenStreetMap. Nenhum dado seu vai junto, mas, se preferir evitar isso, deixe a opção desligada (é o padrão).

## Exemplos de automação

### Alagamento numa zona

Avisa quando alagar na Zona Sul, dizendo onde:

```yaml
automation:
  - alias: Alagamento na Zona Sul
    trigger:
      - platform: state
        entity_id: binary_sensor.cgesp_alagamento_zona_sul
        to: "on"
    action:
      - service: notify.notify
        data:
          title: Alagamento na Zona Sul
          message: >
            {{ state_attr('binary_sensor.cgesp_alagamento_zona_sul', 'ruas') | join(', ') }}
```

### Sua região em atenção ou alerta

Avisa quando a região da estação sair de Observação:

```yaml
automation:
  - alias: Estado de alerta em Santo Amaro
    trigger:
      - platform: state
        entity_id: sensor.cgesp_santo_amaro_estado_alerta
    condition:
      - condition: template
        value_template: "{{ trigger.to_state.state not in ['observacao', 'unavailable', 'unknown'] }}"
    action:
      - service: notify.notify
        data:
          title: CGE - Santo Amaro
          message: >
            {% set nomes = {'atencao': 'Atenção', 'iminencia_transbordamento': 'Iminência de transbordamento', 'alerta': 'Alerta'} %}
            {% set atualizado = state_attr('sensor.cgesp_santo_amaro_estado_alerta', 'atualizado_em') %}
            Região em {{ nomes[trigger.to_state.state] }}
            (mapa atualizado às {{ as_timestamp(atualizado) | timestamp_custom('%H:%M') }}).
```

### Alagamento perto de um lugar fixo

Avisa quando aparecer um alagamento perto do trabalho. Precisa da opção de mapa ligada e de uma zona `zone.trabalho`, criada em **Configurações → Áreas e zonas**. O tamanho da zona define o que é "perto".

```yaml
automation:
  - alias: Alagamento perto do trabalho
    trigger:
      - platform: geo_location
        source: cgesp
        zone: zone.trabalho
        event: enter
    action:
      - service: notify.notify
        data:
          title: Alagamento perto do trabalho
          message: >
            {{ trigger.to_state.attributes.rua }} ({{ trigger.to_state.attributes.bairro }}),
            desde {{ trigger.to_state.attributes.inicio }}
```

### Alagamento a menos de X km de uma pessoa

O exemplo anterior serve para lugares fixos. Para saber se há alagamento perto de **alguém**, onde quer que a pessoa esteja, é preciso que ela tenha localização no Home Assistant (por exemplo, pelo app do celular) e da opção de mapa ligada.

Primeiro, crie um sensor que conta os alagamentos perto da pessoa. Ele é recalculado sozinho quando a pessoa se move ou quando um alagamento aparece ou some. Coloque no `configuration.yaml` e troque `person.joao` e o raio:

```yaml
template:
  - sensor:
      - name: Alagamentos perto do João
        unique_id: alagamentos_perto_joao
        icon: mdi:home-flood
        unit_of_measurement: pontos
        state: >
          {% set pessoa = 'person.joao' %}
          {% set raio_km = 2 %}
          {% set ns = namespace(total=0) %}
          {% for ponto in states.geo_location | selectattr('attributes.source', 'eq', 'cgesp') %}
            {% set km = distance(pessoa, ponto.entity_id) %}
            {% if km is not none and km <= raio_km %}
              {% set ns.total = ns.total + 1 %}
            {% endif %}
          {% endfor %}
          {{ ns.total }}
        attributes:
          ruas: >
            {% set pessoa = 'person.joao' %}
            {% set raio_km = 2 %}
            {% set ns = namespace(ruas=[]) %}
            {% for ponto in states.geo_location | selectattr('attributes.source', 'eq', 'cgesp') %}
              {% set km = distance(pessoa, ponto.entity_id) %}
              {% if km is not none and km <= raio_km %}
                {% set ns.ruas = ns.ruas + [ponto.attributes.rua ~ ' (' ~ (km | round(1)) ~ ' km)'] %}
              {% endif %}
            {% endfor %}
            {{ ns.ruas }}
```

Depois, a automação. Ela avisa sempre que o número de alagamentos perto da pessoa **aumenta**, ou seja, quando ela chega perto de um ponto alagado ou quando surge um novo perto dela:

```yaml
automation:
  - alias: Alagamento perto do João
    trigger:
      - platform: state
        entity_id: sensor.alagamentos_perto_do_joao
    condition:
      - condition: template
        value_template: >
          {{ trigger.from_state is not none
             and trigger.to_state.state | int(0) > trigger.from_state.state | int(0) }}
    action:
      - service: notify.mobile_app_celular_do_joao
        data:
          title: Alagamento a menos de 2 km
          message: >
            {{ state_attr('sensor.alagamentos_perto_do_joao', 'ruas') | join(', ') }}
```

Algumas observações:

- O raio é contado em linha reta, não pelo caminho de carro.
- A posição do alagamento é aproximada (veja a precisão em [Alagamentos no mapa](#alagamentos-no-mapa)). Em avenidas longas, um raio pequeno pode deixar alagamentos de fora. Comece com 2 ou 3 km.
- Para acompanhar mais de uma pessoa, repita o sensor e a automação para cada uma.

## Se o site do CGE sair do ar ou mudar

A integração depende do site do CGE, que não tem uma API oficial. Por isso ela foi feita para falhar de forma visível, nunca para mostrar uma informação errada:

- **Site fora do ar:** os sensores ficam *indisponíveis* e voltam sozinhos quando o site normalizar.
- **Só uma parte falhou:** a página de alagamentos e o mapa são lidos separadamente. Se um deles falhar, os sensores do outro continuam funcionando.
- **O CGE mudou a página:** se a integração não conseguir mais ler os alagamentos, os sensores de zona ficam *indisponíveis*. Eles não passam a dizer "sem alagamento". Também aparece um aviso em **Configurações → Reparos** explicando o que aconteceu. Esse aviso some sozinho quando a leitura volta a funcionar.

Se o aviso de Reparos não sumir, veja se há uma versão nova no HACS ou [abra uma issue](https://github.com/luyzfernando08/ha-cgesp/issues).

## Créditos

Todos os dados são do [CGE - Centro de Gerenciamento de Emergências Climáticas](https://www.cgesp.org/v3/) da Prefeitura de São Paulo. Esta integração não tem vínculo oficial com o CGE nem com a Prefeitura.

A localização dos pontos no mapa usa o [Nominatim](https://nominatim.org/), com dados © [colaboradores do OpenStreetMap](https://www.openstreetmap.org/copyright).
