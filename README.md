# Sofá Duo

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

## Frontend

HTML/CSS/JavaScript sem build. Filtros por consola, modo, género e jogadores, pesquisa, favoritos locais e escolha aleatória. Os favoritos são guardados apenas no navegador, sem sincronização. A cópia estática é usada se a exportação no GitHub estiver indisponível e é identificada como cópia de segurança. O site mostra a data real dos dados e sinaliza dados antigos.

O site começa privado por predefinição do Sites. Para permitir acesso a outra pessoa, partilhe-o nas definições do Sites. O catálogo GitHub é público; não contém dados pessoais.
