# Home Assistant - Centro de Gerenciamento de Emergências Climáticas SP

## Sobre

- Integração permite visualizar as condições climáticas de uma determinada estação meteorológica da Cidade de São Paulo (Brasil)

- Todos os dados são provenientes do site do <a href="https://www.cgesp.org/v3/">CGE - SP</a>

## Instalação
- [x] Necessário ter o HACS instalado: https://github.com/hacs/integration

Vá no HACS e clique em integrações:
Clique no menu e vá em Repositórios personalizados.
Preencha com o endereço do github do componente:

```markdown
https://github.com/luyzfernando08/ha-cgesp
```

* Selecione a categoria "Integração". Clique em Adicionar:
* Clique em Baixar
* Reinicie o Home Assistant

### Configuração Automática

A adição da integração à sua instância do Home Assistant pode ser feita através da interface do usuário, usando este botão:

<a href="https://my.home-assistant.io/redirect/config_flow_start?domain=cge" rel="CGE - SP">![Foo](https://my.home-assistant.io/badges/config_flow_start.svg)</a>

### Configuração Manual:

* Com ele reiniciado, navegue até sua instância do Home Assistant.
* Na barra lateral clique em Configuração .
* No menu de configuração selecione Dispositivos e Serviços .
* Vá no canto direito embaixo e clique em “+ Adicionar Integração”.
* Na lista, pesquise e selecione “CGE - SP” .
* Selecione a estação medidora mais próxima de você e clique em enviar

- [x] Pronto, agora você poderá ver a previsão do tempo da cidade de São Paulo