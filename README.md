# CGE - SP para Home Assistant

Traz para o Home Assistant os dados do [CGE](https://www.cgesp.org/v3/), o Centro de Gerenciamento de Emergências Climáticas da Prefeitura de São Paulo: clima das estações meteorológicas, pontos de alagamento e o estado de alerta de cada região da cidade.

## O que você ganha

- **Clima da estação mais perto de você:** temperatura, umidade, pressão, vento e previsão para os próximos dias.
- **Alagamentos por zona:** um sensor para cada zona (Norte, Sul, Leste, Oeste e Centro) que liga quando há alagamento ativo, com os bairros e as ruas afetadas.
- **Estado de alerta da sua região:** o mesmo estado que o CGE mostra no mapa da página inicial (Observação, Atenção, Iminência de transbordamento ou Alerta), com o horário da última atualização do mapa.

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
- **Alertas da cidade:** cria os sensores de alagamento das cinco zonas. Só precisa adicionar uma vez.

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
| `pontos` | Lista completa: bairro, local, horário de início, sentido, referência e se dá para passar |
| `data_referencia` | Data consultada no site do CGE |

Os dados vêm da página de [alagamentos do CGE](https://www.cgesp.org/v3/alagamentos.jsp), que é preenchida pelos agentes de trânsito da Prefeitura. Ela cobre principalmente o centro expandido e os grandes corredores, então pode não listar alagamentos em ruas menores.

## Exemplos de automação

Avisar quando alagar na Zona Sul, dizendo onde:

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

Avisar quando a sua região entrar em atenção ou alerta:

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

## Se o site do CGE sair do ar ou mudar

A integração depende do site do CGE, que não tem uma API oficial. Por isso ela foi feita para falhar de forma visível, nunca para mostrar uma informação errada:

- **Site fora do ar:** os sensores ficam *indisponíveis* e voltam sozinhos quando o site normalizar.
- **Só uma parte falhou:** a página de alagamentos e o mapa são lidos separadamente. Se um deles falhar, os sensores do outro continuam funcionando.
- **O CGE mudou a página:** se a integração não conseguir mais ler os alagamentos, os sensores de zona ficam *indisponíveis*. Eles não passam a dizer "sem alagamento". Também aparece um aviso em **Configurações → Reparos** explicando o que aconteceu. Esse aviso some sozinho quando a leitura volta a funcionar.

Se o aviso de Reparos não sumir, veja se há uma versão nova no HACS ou [abra uma issue](https://github.com/luyzfernando08/ha-cgesp/issues).

## Créditos

Todos os dados são do [CGE - Centro de Gerenciamento de Emergências Climáticas](https://www.cgesp.org/v3/) da Prefeitura de São Paulo. Esta integração não tem vínculo oficial com o CGE nem com a Prefeitura.
