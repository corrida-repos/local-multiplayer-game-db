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

`python scripts/ratings.py --limit 60` é uma ferramenta de diagnóstico/compatibilidade. A recolha automática usa agora a fila contínua descrita abaixo. Guarda os dados em `data/ratings.json` e na tabela SQLite `ratings`.

- Críticos: Metacritic, **0–100**, da versão exata da consola. Não se usam notas de outras plataformas.
- Utilizadores Switch: Metacritic, **0–10**, com pelo menos quatro avaliações nessa plataforma (o mínimo para apresentar uma média).
- Utilizadores PS5: PlayStation Store Portugal (PSN), **0–5**. Certos produtos partilham a classificação PS4/PS5; o detalhe está no título da ligação.
- Cada nota tem fonte e data de consulta próprias. Falhas temporárias mantêm a última nota obtida. Ausência de avaliações ou falta de correspondência segura aparece como **Sem nota**.
- URLs Metacritic são descobertas a partir do nome, com exceções explícitas para edições; conceitos PSN são obtidos nas páginas oficiais ou mapeados para URLs oficiais confirmadas. Jogos sem correspondência ficam sem nota até haver uma fonte válida.

## Frontend

Os cartões mostram apenas imagem, plataforma, título, género, modo e ratings. Clicar na imagem, no título ou no cartão abre uma vista de detalhe com sinopse, experiência cooperativa, jogadores locais, data de lançamento, botão para a loja oficial, trailer YouTube e flags. As sinopses e a descrição da cooperação são recolhidas das páginas públicas do Co-Optimus no idioma original e limitadas a excertos curtos; os jogos da seleção manual têm sinopses em português. Os campos `synopsis` e `coop_description` são persistidos em SQLite e exportados no catálogo. A migração acrescenta apenas as colunas em falta e preserva os registos existentes.

A ordenação fica sempre visível. A pesquisa, os filtros e “Limpar filtros” ficam numa secção recolhida por defeito, aberta pelo botão “Mostrar Pesquisa e Filtros”; recolher mantém as escolhas e os resultados atuais.

Catálogo simples em HTML/CSS/JavaScript, sem build: imagens, ligações diretas às fontes, pesquisa e filtros por consola, modo, género, jogadores e estado. Consola, Modo, Género e Estado permitem escolha múltipla, sem opção “Todos”: nenhuma seleção significa sem restrição nesse filtro. Género inclui “Qualquer Género”, que limpa as escolhas específicas; selecionar géneros específicos desmarca essa opção. As opções dentro de um filtro combinam-se com OU; filtros diferentes combinam-se com E. Os valores por defeito, também repostos por “Limpar filtros”, são PS5, Cooperação, 2 ou mais jogadores, Qualquer Género e os estados Por descobrir e Quero jogar. Permite ordenar por nome, lançamento, critic score e user score. A ordenação por user score compara a proporção da escala (PSN 0–5 e Metacritic 0–10). Os filtros de mínimo critic score (0–100) e mínimo user score (0–10, PSN convertido) ficam vazios por defeito; sem mínimo, jogos sem nota continuam elegíveis. Com um mínimo definido, jogos sem essa nota são excluídos. “Limpar filtros” volta a deixar os dois mínimos vazios. Arte de jogos com ligação ao fornecedor: Wikipedia, Steam ou Nintendo. As notas são lidas diretamente do GitHub, com cópia de segurança na publicação.

**Quero jogar**, **Já joguei** e **Não me interessa** retiram o jogo da vista predefinida **Por descobrir**, em ambas as consolas. O filtro Estado inclui a lista **Quero jogar**, além de Já jogados e Sem interesse, e permite rever e restaurar escolhas. É possível passar um jogo de Quero jogar para Já jogado ou Sem interesse. Estas preferências ficam em `localStorage` neste navegador, sem partilha entre dispositivos ou pessoas. Não são publicadas no GitHub.

O site é **público**, por pedido do proprietário. O catálogo GitHub também é público e não contém dados pessoais.

## Lojas oficiais e vídeos

- `python scripts/stores.py --limit 60` mantém `data/stores.json` e a tabela SQLite `stores`. Os endereços PS5 são páginas oficiais da PlayStation Store Portugal, reaproveitando correspondências verificadas da recolha de notas. Para Nintendo Switch, verifica o título exato na página da loja Nintendo dos EUA; não usa páginas de pesquisa nem edições Switch 2. Jogos SNES do Nintendo Switch Online apontam para a aplicação oficial que os inclui. O link PS5 de It Takes Two usa o produto especificado pelo proprietário.
- `python -m scripts.trailers --limit 60` mantém `data/trailers.json` e a tabela SQLite `trailers`. Prefere gameplay oficial; na ausência desse vídeo, usa outro trailer oficial identificado do mesmo jogo. Recolhe vídeos estruturados nas páginas oficiais PlayStation e usa correspondências verificadas em `data/trailers-curated.json` para Nintendo, outras editoras e jogos antigos. Estas correspondências também preservam as fontes. Não inventa IDs de vídeos nem mostra vídeos de outros jogos como alternativa.
- Estes comandos continuam disponíveis para diagnóstico. A execução automática usa a fila contínua, sem o limite antigo de 60 jogos. A descoberta não é exaustiva para futuros jogos: quando não há correspondência oficial segura, a interface indica que o link ou vídeo ainda não foi identificado.
- O leitor usa `youtube-nocookie.com`, com controlos e ecrã inteiro. A iframe só é criada após clicar em Reproduzir. Fecha e interrompe o leitor ao sair do detalhe; mudar uma flag não reinicia o vídeo. Há ligação direta ao YouTube caso a incorporação esteja indisponível.
- A vista de detalhe não mostra datas internas de verificação/atualização, a nota PSN partilhada PS4/PS5, o título/descrição de estado, links ao Co-Optimus ou a nota final sobre armazenamento. Os dados continuam guardados para manutenção; as flags continuam funcionais e locais ao navegador.

## Catálogo PS Plus (Portugal)

`python scripts/psplus.py --limit 60` consulta apenas páginas `store.playstation.com/pt-pt/` dos jogos PS5 e guarda `data/psplus.json` e a tabela SQLite `psplus`. Exige uma oferta gratuita de jogo completo do tipo PS_PLUS_GAME_CATALOG ou PS_PLUS_CLASSICS_CATALOG, associada ao produto PS5 correto e a Extra/Premium. Não confunde descontos, jogos mensais, experimentações de jogos, EA Play, requisitos de jogo online ou ofertas de outra edição com inclusão no catálogo. Ofertas expiradas são excluídas.

O filtro **No catálogo PS Plus** fica desligado por defeito, aplica-se apenas a PS5 e desaparece quando só Nintendo Switch está selecionada. Usa verificações de Portugal com menos de 48 horas; a recolha diária atualiza a disponibilidade. Erros de rede preservam o último registo, que deixa de ser usado pelo filtro se ficar antigo. “Limpar filtros” desliga esta opção. A disponibilidade pode mudar: a loja oficial é a fonte de confirmação final.

## Coverage and full backfill

The initial catalogue was only a sample: 63 of 3,246 discovered Co-Optimus PS5/Switch pages had been checked. An old franchise-priority list delayed other games, including Baldur’s Gate III. That list has been removed. Scheduling now handles unseen pages before previously attempted failures and old successful checks, without franchise preferences.

The daily run remains bounded to 300 pages. The separate **Backfill complete catalogue coverage** Actions workflow processes all pending discovered pages in one run with a 180-minute budget, observes the source crawl interval, and checkpoints SQLite and the public JSON to Git every 100 successful checks. Its concurrency group is shared with the daily workflow to prevent competing SQLite writes. A cancelled or timed-out run resumes from the persisted checkpoints.

`catalog.json` reports `checked`, `pending` and `coverage_complete`; checked pages include both eligible and excluded games. These measure coverage of the discovered source, not every game in existence. Co-Optimus concentrates on cooperative games; the small competitive selection remains manual, so this is not an exhaustive competitive-multiplayer catalogue. Native PS5 and Switch 1 editions are checked separately; PS4-only games are not inferred as PS5-native releases.

Search accepts Roman or Arabic numerals, punctuation and apostrophe variations: “Baldur’s Gate III”, “Baldur’s Gate 3” and “Baldurs Gate 3” match the same entry. Enabling PS Plus or score/state filters can still legitimately hide a game.

`data/verified-local.json` contains explicitly verified primary-source corrections. They are applied at every export/checkpoint so a conflicting secondary-source record cannot silently remove the game. Borderlands 4 PS5 is one such correction: the Portuguese PlayStation Store lists two local players although Co-Optimus says local co-op is unsupported.

### Composite scores (console-specific)

`python -m scripts.composites` collects every page of Metacritic's public, platform-specific critic index and normalizes scores to 0–100. Each publication domain counts once (latest review if repeated), with equal weight. Push Square PS5 and Nintendo Life Switch editorial scores are also included when exact game and console identities match, deduplicated against the index. If the index fails midway, its top-scoring prefix is discarded: a verified legacy Metacritic aggregate is shown alone as a labelled fallback. No PC or other-console critic aggregate fills a gap.

User scores combine the console-specific Metacritic user average, Push Square (PS5) or Nintendo Life (Switch) community, and the verified PS5-listed PSN product where available. PSN products shared with PS4 are identified in the breakdown. Scores are normalized to 0–10; each community's weight is `sqrt(min(votes, 1000))`. This reduces domination by very large communities without pretending to remove all bias or duplicate voters across sites. A single source is labelled; no verified votes means no invented score. Original scores, counts, links, and weights are exported in `data/composites.json` and displayed when clicking a score.

The unified `enrichment.yml` workflow now runs all enrichment stages; `scripts.composites` remains available for diagnostics. Its historical results remain valid fallback data. OpenCritic's API requires a separate key and is not silently substituted with a cross-platform aggregate. These scores combine the accessible verified sources; they do not claim exhaustive coverage of every review site.

The upper-right **Quero jogar** button shows all saved titles across consoles, independent of the catalogue filters. Remove a title directly or open its detail view to change its state. Returning preserves the catalogue filters. Preferences remain stored in this browser.


### Continuous enrichment and completeness audit

`python -m scripts.enrichment --minutes 50 --workers 8 --checkpoint-push` fills the minimum required data for **every** newly discovered game before spending requests on extra scores and trailers. The minimum is an image, an exact official store page, and at least one verified user **or** critic score. A zero-vote source, unpublished average, age rating, unrelated edition, PC score, or different console cannot satisfy the requirement. No entries are deleted or silently hidden to improve these counts.

The collector queries the same public Portugal PSN search operation as the store, verifies exact title and PS5 identity on the product page, and merges product fields split across rendered data blocks. This avoids depending on a marketing page existing at a guessed PlayStation.com slug. A store lookup supplies its image, user score/vote count, and PS Plus verification together. Nintendo pages supply exact Switch links and images; rating lookups try both Nintendo Life retail and eShop paths, then platform-specific Metacritic. Existing verified data are retained when a later source is unavailable.

`data/enrichment.json` and `data/enrichment.sqlite` contain results and provenance; `data/enrichment-audit.json` lists **every** incomplete entry, attempted time, missing fields, and source failures. Counts include verified legacy data and are never labelled complete while requirements are missing. Games with no published console-specific score remain visible and explicitly unresolved.

The hourly workflow also triggers after daily discovery or a backfill run. Eight I/O workers share one request-start interval of 1.1 seconds per host. Checkpoints every ten games close SQLite before rebasing, retry concurrent Git pushes, and reload the latest catalog; games discovered during the run enter the same queue. Later runs resume unattempted fields. After minimum enrichment, the queue collects all platform-specific critic pages, additional user communities, and official gameplay/trailer fallbacks. The app refreshes enrichment every five minutes without interrupting an already playing trailer.

Default sorting is **Melhor nota: maior primeiro**: `max(critic / 100, user / user_scale)`, descending, with unrated games last and title as the tie-breaker. This compares each game's best available aggregate score on an equal scale.

Additional fallbacks: the official Nintendo Europe product index is queried in Portuguese then English when a US slug is unavailable; Switch 2 products and similarly named sequels are rejected. Nindie Spotlight's own scored Switch reviews are collected directly and deduplicated by publication. A single platform-specific Metacritic critic review also qualifies even when its aggregate is still TBD. Failed lookups retry at most daily; extra composite sources refresh weekly. There is no Steam or cross-console fallback.

Nindie Spotlight profiles are resolved through its public Switch 1 sitemap as well as exact title slugs. The index refreshes weekly. Verified official Nintendo product names also supply aliases for reviewer lookups (including Arcade Archives / ACA NeoGeo prefixes); sequels and other consoles remain excluded.

Gap recovery also resolves English PSN product names against the same Portuguese product IDs; star ratings and PS Plus inclusion are still fetched from Portugal. Trademark suffixes, standard editions, cross-generation bundles, Arcade Archives 2, and Console Archives naming are normalized without permitting PS4-only substitutes. Explicit edition and spelling aliases carry official product URLs in `data/source-aliases.json`. Fuzzy search suggestions are reviewed rather than imported automatically.

Metacritic JSON redirects are followed only when they supply a unique canonical slug on the requested console. Existing verified store pages are reused during refreshes, and a precise Wikipedia video-game article can supply missing artwork; ambiguous titles, franchise articles, and non-game images are rejected. Remaining unrated entries are checked for full critic indexes before extra sources for already-rated games.

Manual enrichment runs accept an optional `game_ids` input (for example `PS5:13370,Switch:6085`) to finish a verified recovery and its complete score/trailer stages without reprocessing unrelated entries. The same writer lock protects targeted and full runs.

The Game Slush Pile is another direct scored-review fallback. Its public search locates an exact Switch-review title, and the collector reads only the article's own structured overall rating; PC reviews, other consoles, comments, and unrelated games cannot fill a Switch score. Publication domains deduplicate against other review indexes. Explicitly verified critic sources in the alias manifest are also console-bound. Opaque Metacritic aggregate fallbacks are never mixed with potentially overlapping individual reviews.

Verified investigation batches are stored in `data/verified-recoveries.json` and applied once under the same enrichment writer lock. Their receipt in `data/recovery-state.json` records actual fields gained and newly complete entries. The merge retains existing valid store pages, combines and deduplicates individual publications/communities, preserves richer scores and full-stage progress, and refuses cross-game or cross-console records. Publishing a recovery therefore cannot overwrite newer background results.
