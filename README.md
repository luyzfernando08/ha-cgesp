# CGE - SP para Home Assistant

Traz para o Home Assistant os dados do [CGE](https://www.cgesp.org/v3/), o Centro de Gerenciamento de Emergências Climáticas da Prefeitura de São Paulo: clima das estações meteorológicas, pontos de alagamento e o estado de alerta de cada região da cidade.

## O que você ganha

- **Clima da estação mais perto de você:** temperatura, umidade, pressão, vento e previsão para os próximos dias.
- **Alagamentos por zona:** um sensor para cada zona (Norte, Sul, Leste, Oeste e Centro) que liga quando há alagamento ativo, com os bairros e as ruas afetadas.
- **Estado de alerta da sua região:** o mesmo estado que o CGE mostra no mapa da página inicial (Observação, Atenção, Iminência de transbordamento ou Alerta), com o horário da última atualização do mapa.
- **Alagamentos no mapa (opcional):** cada ponto alagado aparece no cartão de mapa do Home Assistant.
- **Chuva em casa, agora:** para cada pessoa, rastreador ou zona que você escolher, o radar diz se está chovendo no local, com qual intensidade e a que distância está a chuva mais próxima. Dá para avisar antes de a chuva chegar.
- **Alagamentos perto de quem você quiser:** um sensor por pessoa, rastreador ou zona, com quantos alagamentos estão a menos de X km. Ele acompanha a pessoa enquanto ela se move.
- **Contadores:** alagamentos ativos na cidade e em cada zona, e quantos houve no dia. Eles entram nas estatísticas do HA, então dá para fazer gráficos.
- **Boletim do CGE:** o texto mais recente publicado pelo CGE, com a tendência para os próximos dias.
- **Radar e mapa de alertas:** câmeras para colocar no painel com a chuva no radar (a imagem atual e uma animação da última hora) e o mapa de alertas do CGE.
- **Eventos:** `cgesp_alagamento_novo` e `cgesp_alagamento_encerrado`, para automações que reagem a cada ponto.

Os alertas são atualizados a cada 10 minutos quando pode chover e a cada 30 minutos quando não há chuva prevista (veja [Frequência de atualização](#frequência-de-atualização)).

## Instalação

A partir do Home Assistant 2026.11, o HACS virou o **Marketplace**, que já vem com o HA. Clique no botão para abrir a integração direto no seu Marketplace:

<a href="https://my.home-assistant.io/redirect/hacs_repository/?owner=luyzfernando08&repository=ha-cgesp&category=integration" rel="CGE - SP">![Abrir no Marketplace](https://my.home-assistant.io/badges/hacs_repository.svg)</a>

Ou faça pelo menu:

1. Vá em **Configurações → Marketplace**.
2. No canto superior direito, clique no botão para adicionar por link (*Add from link*).
3. Cole o endereço abaixo e clique em **Adicionar**:
   ```
   https://github.com/luyzfernando08/ha-cgesp
   ```
4. Siga a configuração que abre em seguida. No Marketplace, a integração já vai direto para a configuração, sem precisar reiniciar.

<details>
<summary>Home Assistant 2026.10 ou anterior (com HACS)</summary>

1. No [HACS](https://hacs.xyz/), abra o menu (⋮) e vá em **Repositórios personalizados**.
2. Cole o endereço `https://github.com/luyzfernando08/ha-cgesp`, escolha a categoria **Integração** e clique em **Adicionar**.
3. Procure por **CGE - SP**, clique em **Baixar** e reinicie o Home Assistant.

</details>

## Configuração

Clique no botão para abrir a configuração direto no seu Home Assistant:

<a href="https://my.home-assistant.io/redirect/config_flow_start?domain=cgesp" rel="CGE - SP">![Adicionar integração](https://my.home-assistant.io/badges/config_flow_start.svg)</a>

Ou vá em **Configurações → Dispositivos e serviços → Adicionar integração** e procure por **CGE - SP**.

A integração pergunta o que você quer adicionar:

- **Estação meteorológica:** escolha a estação mais próxima. Você pode adicionar quantas quiser, uma de cada vez.
- **Alertas da cidade:** cria os sensores de alagamento das cinco zonas, os contadores, o boletim e as câmeras. Só precisa adicionar uma vez. Depois, em **Configurar**, você escolhe:
  - **Mostrar os pontos de alagamento no mapa**;
  - **Acompanhar chuva e alagamentos em**: pessoas, rastreadores ou zonas (inclua `zone.home` para a sua casa), e o raio em km para os alagamentos;
  - **Atualizar com menos frequência quando não há previsão de chuva** (ligada por padrão).

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

### Contadores

| Entidade | O que mostra |
|---|---|
| `sensor.cgesp_alagamentos_ativos` | Pontos ativos na cidade toda. O atributo `por_zona` traz a divisão por zona |
| `sensor.cgesp_alagamentos_ativos_zona_sul` (e as outras zonas) | Pontos ativos na zona |
| `sensor.cgesp_alagamentos_hoje` | Todos os pontos registrados no dia, ativos e encerrados. Zera quando o CGE vira o dia |

Como são medições numéricas, o HA guarda o histórico de longo prazo. Um cartão de estatísticas mostra, por exemplo, o pico de alagamentos por dia no último mês.

### Boletim do CGE

`sensor.cgesp_boletim` tem como estado o título do boletim mais recente do CGE, como "Noite segue com chuva leve na cidade". O texto completo fica no atributo `texto`, que costuma trazer a tendência para os próximos dias. Também há `publicado_em` e `link`.

Para ler no painel, use um cartão Markdown:

```yaml
type: markdown
content: |
  ### {{ states('sensor.cgesp_boletim') }}
  {{ state_attr('sensor.cgesp_boletim', 'texto') }}
```

### Radar e mapa de alertas

| Entidade | O que mostra |
|---|---|
| `camera.cgesp_radar` | Chuva estimada pelo radar sobre a cidade, com a intensidade (fraca, moderada, forte, muito forte) |
| `camera.cgesp_radar_animacao` | Animação com as imagens do radar da última hora, para ver para onde a chuva está indo |
| `camera.cgesp_mapa_alertas` | O mapa "Situação das Áreas Monitoradas" do CGE, com as regiões coloridas pelo estado |

Para mostrar no painel, use um cartão de imagem de entidade (`picture-entity`) com a câmera. O mapa de alertas é o mesmo que a integração já baixa para ler o estado das regiões, então não gera consulta extra.

A animação é montada com as imagens que a integração vai baixando: logo depois de o HA iniciar ela tem um quadro só e completa a hora com o tempo. Quando a chuva não muda de uma imagem para a outra, fica só a mais recente.

### Eventos

A cada atualização, a integração dispara um evento para cada ponto que apareceu ou foi encerrado:

- `cgesp_alagamento_novo`
- `cgesp_alagamento_encerrado`

Os dados do evento são `zona`, `zona_id`, `bairro`, `local`, `inicio`, `fim`, `sentido`, `referencia` e `transitavel`. Com a opção de mapa ligada, também vêm `latitude` e `longitude`, se a rua já tiver sido localizada. Na primeira vez que uma rua aparece, a localização pode chegar só alguns segundos depois do evento.

Quando o Home Assistant inicia, a integração não dispara eventos para os pontos que já estavam ativos, só para as mudanças a partir dali.

Os eventos também aparecem no **Diário de bordo**, como frases (por exemplo, "novo alagamento: Avenida Marechal Tito, altura do número 7557 (Itaim Paulista, Zona Leste), intransitável"). Eles ficam ligados ao sensor de alagamento da zona, então dá para ver o histórico do dia abrindo esse sensor, sem criar automação.

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

## Chuva em casa e perto de pessoas

Em **Configurar**, no campo **Acompanhar chuva e alagamentos em**, escolha pessoas (`person`), rastreadores (`device_tracker`, como o do carro) ou zonas (`zone`). Para a sua casa, use `zone.home`.

A integração lê a imagem do radar e descobre a chuva no ponto exato de cada um. Para `zone.home`, por exemplo, são criados:

| Entidade | O que mostra |
|---|---|
| `binary_sensor.cgesp_chovendo_zone_home` | Ligado quando o radar mostra chuva no local |
| `sensor.cgesp_chuva_zone_home` | A intensidade no local: sem chuva, fraca, moderada, forte ou muito forte |
| `sensor.cgesp_chuva_mais_proxima_zone_home` | Distância em km até a chuva mais próxima (0 quando está chovendo no local) |

O sensor de distância também traz nos atributos a `intensidade` e a `direcao` dessa chuva (norte, nordeste, leste…), e `chuva_forte_km` e `chuva_forte_direcao` para a chuva forte ou muito forte mais próxima. Quando não há chuva em nenhum lugar da imagem, a distância fica *desconhecida*.

Para pessoas, o nome não leva o tipo: `person.joao` vira `binary_sensor.cgesp_chovendo_joao`. Os sensores são recalculados quando a pessoa se move e a cada imagem nova do radar.

Algumas observações:

- O radar mostra a chuva em blocos de cerca de 1 km, então "chovendo em casa" quer dizer "chovendo no quarteirão". A intensidade é a estimada pelo radar, não a medida por um pluviômetro.
- A imagem cobre a capital e um pouco dos arredores. Fora dela (em Campinas, por exemplo), os sensores ficam *desconhecidos* e o atributo `motivo` explica por quê.
- Se o CGE mudar o desenho da imagem do radar, os sensores ficam *indisponíveis* em vez de dizer "sem chuva", e aparece um aviso em Reparos.

## Alagamentos perto de pessoas e lugares

As mesmas pessoas, rastreadores e zonas também ganham um sensor de alagamentos por perto, com o raio em km escolhido em **Configurar**. Esse sensor só é criado com **Mostrar os pontos de alagamento no mapa** ligada, porque sem as coordenadas dos pontos não dá para medir a distância.

Cada um ganha um sensor. Para `person.joao`, ele se chama `sensor.cgesp_alagamentos_perto_joao`. Para rastreadores e zonas, o nome inclui o tipo, como `sensor.cgesp_alagamentos_perto_zone_trabalho`.

O estado é quantos alagamentos ativos estão dentro do raio, e os atributos trazem:

| Atributo | O que tem |
|---|---|
| `ruas` | As ruas com a distância, do mais perto ao mais longe: `R STO ARCADIO (0.4 km)` |
| `mais_proximo_km` | Distância do alagamento mais perto |
| `pontos` | Detalhes de cada ponto, com a distância |
| `pontos_sem_localizacao` | Alagamentos ativos que ainda não foram localizados e por isso ficaram fora da conta |

O sensor é recalculado quando a pessoa se move e a cada atualização do CGE. Se a pessoa estiver sem localização, por exemplo quando é rastreada só pelo roteador de casa, o estado fica *desconhecido* e o atributo `motivo` explica por quê.

Algumas observações:

- O raio é contado em linha reta, não pelo caminho de carro.
- A posição do alagamento é aproximada (veja a precisão em [Alagamentos no mapa](#alagamentos-no-mapa)). Em avenidas longas, um raio pequeno pode deixar alagamentos de fora. Comece com 2 ou 3 km.
- O raio vale para todas as entidades escolhidas.

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

### Começou a chover em casa

Precisa de `zone.home` em **Configurar → Acompanhar chuva e alagamentos em**:

```yaml
automation:
  - alias: Chuva em casa
    trigger:
      - platform: state
        entity_id: binary_sensor.cgesp_chovendo_zone_home
        to: "on"
    action:
      - service: notify.mobile_app_seu_celular
        data:
          title: Começou a chover em casa
          message: >
            Chuva {{ state_attr('binary_sensor.cgesp_chovendo_zone_home', 'intensidade') }}.
            Recolha a roupa do varal.
```

### Chuva forte chegando

Avisa quando há chuva forte ou muito forte a menos de 5 km de casa, antes de ela chegar:

```yaml
automation:
  - alias: Chuva forte chegando
    trigger:
      - platform: numeric_state
        entity_id: sensor.cgesp_chuva_mais_proxima_zone_home
        attribute: chuva_forte_km
        below: 5
    action:
      - service: notify.mobile_app_seu_celular
        data:
          title: Chuva forte chegando
          message: >
            Chuva forte a
            {{ state_attr('sensor.cgesp_chuva_mais_proxima_zone_home', 'chuva_forte_km') | round(1) }} km,
            na direção {{ state_attr('sensor.cgesp_chuva_mais_proxima_zone_home', 'chuva_forte_direcao') }}.
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

Primeiro, ligue o mapa e escolha a pessoa em **Configurar → Acompanhar chuva e alagamentos em** (veja [Alagamentos perto de pessoas e lugares](#alagamentos-perto-de-pessoas-e-lugares)). A automação avisa sempre que o número de alagamentos perto dela **aumenta**, ou seja, quando ela chega perto de um ponto alagado ou quando surge um novo perto dela:

```yaml
automation:
  - alias: Alagamento perto do João
    trigger:
      - platform: state
        entity_id: sensor.cgesp_alagamentos_perto_joao
    condition:
      - condition: template
        value_template: >
          {{ trigger.from_state is not none
             and trigger.to_state.state | int(0) > trigger.from_state.state | int(0) }}
    action:
      - service: notify.mobile_app_celular_do_joao
        data:
          title: Alagamento perto de você
          message: >
            {{ state_attr('sensor.cgesp_alagamentos_perto_joao', 'ruas') | join(', ') }}
```

Para acompanhar mais de uma pessoa, adicione todas na mesma opção e repita a automação trocando o sensor e o celular.

### Cada alagamento novo, com o local

Usa o evento `cgesp_alagamento_novo` e avisa só quando o ponto está intransitável:

```yaml
automation:
  - alias: Alagamento intransitável
    trigger:
      - platform: event
        event_type: cgesp_alagamento_novo
    condition:
      - condition: template
        value_template: "{{ not trigger.event.data.transitavel }}"
    action:
      - service: notify.notify
        data:
          title: "Alagamento intransitável - {{ trigger.event.data.zona }}"
          message: >
            {{ trigger.event.data.local }} ({{ trigger.event.data.bairro }}),
            desde {{ trigger.event.data.inicio }}
```

## Frequência de atualização

Com a opção **Atualizar com menos frequência quando não há previsão de chuva** ligada (é o padrão), os alertas são consultados:

- **a cada 10 minutos** quando a previsão do CGE indica chuva ou potencial para temporais nas próximas 12 horas, quando há alagamento ativo ou região fora de Observação, ou quando não foi possível ler a previsão;
- **a cada 30 minutos** no resto do tempo.

A previsão é a mesma da página de [previsão estendida](https://www.cgesp.org/v3/previsao_estendida.jsp) do CGE, que separa madrugada, manhã, tarde e noite, e é lida no máximo uma vez por hora. Na dúvida, a integração fica no intervalo curto. Se preferir 10 minutos sempre, desligue a opção.

O radar é consultado **a cada 5 minutos** quando mostra chuva ou quando os alertas estão no intervalo curto, e **a cada 15 minutos** no resto do tempo. Com a opção desligada, é sempre a cada 5 minutos. Cada imagem tem cerca de 700 KB: dá perto de 70 MB por dia sem chuva e até 200 MB num dia inteiro de chuva. Se a imagem não mudou desde a última consulta, o servidor não a envia de novo.

As entidades de clima das estações seguem como antes, atualizadas mais ou menos a cada hora.

## Se o site do CGE sair do ar ou mudar

A integração depende do site do CGE, que não tem uma API oficial. Por isso ela foi feita para falhar de forma visível, nunca para mostrar uma informação errada:

- **Site fora do ar:** os sensores ficam *indisponíveis* e voltam sozinhos quando o site normalizar.
- **Só uma parte falhou:** a página de alagamentos, o mapa e o radar são lidos separadamente. Se um deles falhar, os sensores dos outros continuam funcionando.
- **O CGE mudou a página:** se a integração não conseguir mais ler os alagamentos, os sensores de zona ficam *indisponíveis*. Eles não passam a dizer "sem alagamento". Também aparece um aviso em **Configurações → Reparos** explicando o que aconteceu. Esse aviso some sozinho quando a leitura volta a funcionar.

Se o aviso de Reparos não sumir, veja se há uma versão nova no Marketplace (ou no HACS, em versões antigas do HA) ou [abra uma issue](https://github.com/luyzfernando08/ha-cgesp/issues). Ajuda muito anexar o diagnóstico: em **Configurações → Dispositivos e serviços → CGE - SP**, abra o menu (⋮) da entrada **Alertas da cidade** e clique em **Baixar diagnóstico**. O arquivo traz o que a integração leu do site na última atualização. A localização de pessoas e zonas não vai junto.

## Créditos

Todos os dados são do [CGE - Centro de Gerenciamento de Emergências Climáticas](https://www.cgesp.org/v3/) da Prefeitura de São Paulo. Esta integração não tem vínculo oficial com o CGE nem com a Prefeitura.

A imagem do radar é do [SAISP](https://www.saisp.br/), operado pela [FCTH](https://www.fcth.br/), e é publicada pelo CGE.

A localização dos pontos no mapa usa o [Nominatim](https://nominatim.org/), com dados © [colaboradores do OpenStreetMap](https://www.openstreetmap.org/copyright).
