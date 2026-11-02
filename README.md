# 2-Player Games Finder

Catálogo em português de jogos lançados com pelo menos dois jogadores na mesma consola/ecrã para PS5 e Nintendo Switch (primeira geração). Inclui ecrã dividido. Site publicado através de Sites; fontes da interface em `website/`.

## Dados e atualização

- `data/games.sqlite`: base de dados SQLite com jogos e fila persistente de páginas.
- `data/catalog.json`: exportação pública lida pelo site diretamente do ramo `main`, sem novo deploy.
- `scripts/scrape.py`: Python 3.12, sem dependências. Descobre páginas através dos sitemaps públicos do Co-Optimus e exige Local Co-Op >= 2 e data de lançamento passada. Respeita robots.txt e intervalo mínimo de 1,1 segundos entre pedidos.
- `.github/workflows/daily.yml`: execução diária às **06:23 UTC** (06:23 em Lisboa no inverno, 07:23 no verão), com execução manual via Actions. O GitHub pode atrasar tarefas agendadas.
- Até 300 páginas por execução, primeiro as não verificadas, depois as mais antigas. Novas descobertas entram na fila diariamente. A primeira pesquisa é parcial; a cobertura cresce progressivamente. Só as versões PS5 e Switch 1 são elegíveis; não são incluídos automaticamente títulos PS4 retrocompatíveis.
- `data/competitive.json`: seleção manual de jogos competitivos locais, com fonte oficial. Não é apresentada como scrape automático.
- Se uma página falhar, mantém-se a última informação e a execução é marcada como falhada; `last-run.json` lista erros. Uma página validamente lida mas inelegível é retirada. Não se apaga o catálogo por falhas de rede.
- “Lançado” usa a data da fonte; não garante stock, disponibilidade em todas as lojas/regiões nem inclui uma verificação diária de compras. Títulos retro podem precisar de subscrição. Consulte os modos e requisitos na fonte antes de comprar.

## Executar

```sh
python -m unittest discover -s tests
python scripts/scrape.py --limit 300
```

Os workflows agendados correm no ramo predefinido. `contents: write` permite atualizar apenas os ficheiros do catálogo. As definições da organização devem permitir GitHub Actions. O GitHub pode desativar agendamentos após 60 dias sem atividade num repositório público; reativar em Actions se necessário.

## Notas e avaliações

`python scripts/ratings.py --limit 60` atualiza até 60 jogos por execução diária, dando prioridade aos ainda não consultados e depois aos mais antigos. Guarda os dados em `data/ratings.json` e na tabela SQLite `ratings`.

- Críticos: Metacritic, **0–100**, da versão exata da consola. Não se usam notas de outras plataformas.
- Utilizadores Switch: Metacritic, **0–10**, com pelo menos quatro avaliações nessa plataforma (o mínimo para apresentar uma média).
- Utilizadores PS5: PlayStation Store Portugal (PSN), **0–5**. Certos produtos partilham a classificação PS4/PS5; o detalhe está no título da ligação.
- Cada nota tem fonte e data de consulta próprias. Falhas temporárias mantêm a última nota obtida. Ausência de avaliações ou falta de correspondência segura aparece como **Sem nota**.
- URLs Metacritic são descobertas a partir do nome, com exceções explícitas para edições; conceitos PSN são obtidos nas páginas oficiais ou mapeados para URLs oficiais confirmadas. Jogos sem correspondência ficam sem nota até haver uma fonte válida.

## Frontend

Catálogo simples em HTML/CSS/JavaScript, sem build: imagens, ligações diretas às fontes, pesquisa e filtros por consola, modo, género, jogadores e estado. Consola, Modo, Género e Estado permitem escolha múltipla, sem opção “Todos”: nenhuma seleção significa sem restrição nesse filtro. Género inclui “Qualquer Género”, que limpa as escolhas específicas; selecionar géneros específicos desmarca essa opção. As opções dentro de um filtro combinam-se com OU; filtros diferentes combinam-se com E. Os valores por defeito, também repostos por “Limpar filtros”, são PS5, Cooperação, 2 ou mais jogadores, Qualquer Género e os estados Por descobrir e Quero jogar. Permite ordenar por nome, lançamento e nota dos críticos. Arte de jogos com ligação ao fornecedor: Wikipedia, Steam ou Nintendo. As notas são lidas diretamente do GitHub, com cópia de segurança na publicação.

**Quero jogar**, **Já joguei** e **Não me interessa** retiram o jogo da vista predefinida **Por descobrir**, em ambas as consolas. O filtro Estado inclui a lista **Quero jogar**, além de Já jogados e Sem interesse, e permite rever e restaurar escolhas. É possível passar um jogo de Quero jogar para Já jogado ou Sem interesse. Estas preferências ficam em `localStorage` neste navegador, sem partilha entre dispositivos ou pessoas. Não são publicadas no GitHub.

O site é **público**, por pedido do proprietário. O catálogo GitHub também é público e não contém dados pessoais.
