# Programações Concretagem - NSA

Aplicação em Python com Streamlit para planejamento operacional de concretagens, simulação de ciclos e dimensionamento de betoneiras com verificação de prazo e continuidade.

## O que o sistema faz

- cadastra cenários com data, turno e múltiplas programações;
- calcula número de viagens e volumes por viagem;
- simula o ciclo completo das BTs, com reuso após a volta;
- dimensiona a frota mínima em modo automático;
- simula operação com frota fixa;
- considera mistura, dosagem, bomba/frente e compartilhamento de recursos;
- verifica prazo pelo término da descarga;
- verifica continuidade operacional pelo intervalo máximo entre descargas;
- gera resumo executivo, tabela detalhada, gantt operacional e gráfico de disponibilidade de BT;
- exporta resultados e programação em CSV e gráficos em PNG.

## Stack

- Python
- Streamlit
- pandas
- matplotlib
- dataclasses

## Estrutura

```text
app.py
calculator/
  models.py
  engine.py
  scheduling.py
  gantt.py
  utils.py
exports/
  csv_export.py
sample_data/
  example_scenarios.json
  saved_scenarios.json
requirements.txt
README.md
```

## Instalação

1. Crie e ative um ambiente virtual.
2. Instale as dependências:

```bash
pip install -r requirements.txt
```

## Execução

Rode a aplicação localmente com:

```bash
streamlit run app.py
```

## Fluxo de uso

1. Na página inicial, crie um novo cenário ou carregue/duplique um cenário existente.
2. Na página de planejamento, cadastre uma ou mais programações na `Seção 1`.
3. Defina o modo de cálculo na `Seção 2`:
   - `Simulação com BT fixa`: usa exatamente a quantidade de BTs informada.
   - `Dimensionamento automático`: procura a menor composição de frota que atenda o cenário.
4. Clique em `Calcular`.
5. Analise os resultados na `Seção 3`.

## Como usar

### Cadastro do cenário

- criar cenário com `Nome`, `Data` e `Turno`;
- carregar cenário salvo;
- duplicar cenário para novas simulações;
- excluir cenário;
- importar programação por CSV exportado pelo próprio sistema.

### Cadastro das programações

Cada programação permite informar:

- identificação da frente;
- local, elemento, usina, cimento e observações;
- volume total e capacidade da BT;
- BT fixa opcional;
- início da 1ª mistura e prazo de descarga;
- prioridade opcional;
- operação com ou sem bomba;
- simultaneidades de frente, mistura e dosagem;
- intervalo entre misturas;
- intervalo máximo entre descargas;
- 1ª viagem customizada;
- última viagem parcial proporcional;
- BTs dedicadas ou compartilhadas;
- tempos de mistura, dosagem, ida, slump, descarga, lavagem e volta.

### Resultados

O sistema entrega:

- cards executivos com prazo, continuidade, BTs e gargalos;
- resumo executivo por programação;
- tabela detalhada filtrável;
- gantt operacional;
- gráfico de disponibilidade de BT no tempo;
- aba de premissas consideradas;
- recomendações de ajuste quando prazo e/ou continuidade não forem atendidos.

### Exportações

- CSV do detalhamento operacional;
- CSV da programação do cenário;
- PNG do gantt;
- PNG do gráfico de disponibilidade.

## Premissas principais

- O prazo é avaliado pelo término da descarga.
- O término da volta é mostrado, mas não define atendimento ao prazo.
- A simulação é determinística.
- A mesma BT só volta a ficar disponível após terminar a etapa de volta.
- A carga mínima considerada por BT é de `3 m³`.
- Mistura e dosagem podem ser compartilhadas por concretagens da mesma usina.
- A descarga respeita fila na bomba ou na frente, conforme a configuração.
- O início da viagem pode ser ajustado para reduzir esperas excessivas antes da mistura, da dosagem e, quando aplicável, da bomba.
- Se houver divergência de capacidades compartilhadas na mesma usina, a engine adota a opção mais conservadora e informa um aviso.
- Opcionalmente, programações em conflito operacional podem ser sequenciadas por horário de início e prioridade.
- Quando a continuidade operacional estiver configurada, o sistema avalia o intervalo entre o fim de uma descarga e o início da próxima na mesma frente.

## Arquivo de exemplo

O arquivo [sample_data/example_scenarios.json](/Users/matheussaggioro/VS Code/Programação_Concretagens/sample_data/example_scenarios.json) traz dois cenários prontos:

- operação compartilhada com duas frentes na mesma usina;
- frente simples com uma BT e última viagem parcial.

## Observações sobre o algoritmo

- A distribuição de volumes permite 1ª viagem customizada e última viagem parcial.
- Quando a descarga proporcional está ativada, a duração da descarga é ajustada proporcionalmente ao volume da viagem.
- O dimensionamento automático busca a menor configuração viável por combinações exatas de frota, sem aproximações heurísticas.
- O resultado distingue `gargalo por espera` de `recurso mais ocupado`, para separar fila real de simples ocupação do cronograma.

## Exemplos práticos

- `Operação com BT fixa`: simular exatamente `3 BTs` dedicadas para uma frente e verificar prazo, continuidade e horários das viagens.
- `Dimensionamento automático`: encontrar a menor frota que atende uma concretagem com prazo e continuidade entre descargas.
- `Operação com bomba 1x1`: o sistema ajusta o início das viagens para reduzir esperas antes da mistura, dosagem e descarga.
- `Usina compartilhada`: duas ou mais programações podem disputar mistura e dosagem, com fila e gargalo identificados no resultado.
- `BTs compartilhadas`: o sistema distribui a frota entre programações em conflito e pode sequenciar a operação por horário e prioridade.
