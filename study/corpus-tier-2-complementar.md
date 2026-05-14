# Corpus — Tier 2 (Complementar) — Auditoria 2026-05-14

Auditoria pós-feedback do reviewer + estado atual do Tier-1 (12 docs, 6399 chunks). Lista original do Tier-2 tinha 5 entradas; 2 são redundantes com o Tier-1 atual.

## Tier-1 atual (referência)

| Lei/Decreto | URN |
|---|---|
| CF/88 (compilada — inclui ECs até hoje, incl. EC 115/2022) | `…constituicao:1988-10-05;1988` |
| CP (Decreto-Lei 2.848/1940) | `…decreto.lei:1940-12-07;2848` |
| LAI (Lei 12.527/2011) | `…lei:2011-11-18;12527` |
| Marco Civil (Lei 12.965/2014) | `…lei:2014-04-23;12965` |
| Decreto 8.771/2016 (regulamenta MCI) | `…decreto:2016-05-11;8771` |
| Lei do Software (Lei 9.609/1998) | `…lei:1998-02-19;9609` |
| Lei de Direitos Autorais (Lei 9.610/1998) | `…lei:1998-02-19;9610` |
| Lei Carolina Dieckmann (Lei 12.737/2012) | `…lei:2012-11-30;12737` |
| Lei 14.155/2021 (Crimes Cibernéticos) | `…lei:2021-05-27;14155` |
| LGPD (Lei 13.709/2018) | `…lei:2018-08-14;13709` |
| Lei 13.853/2019 (cria ANPD) | `…lei:2019-07-08;13853` |
| **CDC (Lei 8.078/1990)** | `…lei:1990-09-11;8078` |

## Tier-2 — lista revisada

### Dropar (já cobertos pelo Tier-1)

| Item | Por quê |
|---|---|
| **CDC (Lei 8.078/1990)** | Adicionado ao Tier-1 em 2026-05-13 durante a expansão de gold da paráfrase. 471 chunks indexados. **Redundante**. |
| **EC 115/2022** | Inseriu art. 5º LXXIX na CF/88. Planalto serve versão **compilada** da CF que **já inclui** a alínea. Re-parsear como doc separado dupliciaria o chunk. Verificado: `CF~art5;inc79 → "é assegurado, nos termos da lei, o direito à proteção dos dados pessoais, inclusive nos meios digitais."` **Redundante**. |

### Manter — genuinamente aditivos (reviewer endossou)

| Lei | URN | Por quê |
|---|---|---|
| **Lei 14.063/2020** | `…lei:2020-09-23;14063` | Assinaturas eletrônicas em interações com entes públicos. Define níveis (simples / avançada / qualificada) e a base do gov.br. |
| **Lei 14.129/2021** | `…lei:2021-03-29;14129` | Lei do Governo Digital — princípios e diretrizes pra plataformas digitais públicas. Referencia LGPD/MCI/LAI. |
| **Lei 11.419/2006** | `…lei:2006-12-19;11419` | Informatização do processo judicial. Foundational pro PJe e demais sistemas judiciais eletrônicos. |

### Candidatos opcionais (não no plan do reviewer)

Worth considering, com tradeoffs:

| Documento | URN candidato | Por quê | Por que talvez não |
|---|---|---|---|
| **MP 2.200-2/2001 (ICP-Brasil)** | `…medida.provisoria:2001-08-24;2200-2` | Infraestrutura de chaves públicas — foundational pra assinatura digital qualificada (14.063 referencia). Sem ICP no corpus, queries sobre "certificado digital A3" / "ICP-Brasil" não têm resposta. | É MP, não Lei — URN com `medida.provisoria` (não testado ainda). Texto curto (~10 artigos) mas ainda em vigor permanentemente por força de EC 32/2001. |
| **Lei 9.296/1996 (interceptação)** | `…lei:1996-07-24;9296` | Marco Civil art.10 §2 *referencia* esta lei pra ordem judicial em comunicações digitais. Sem ela, queries sobre "ordem judicial pra grampear" terminam num pointer não-resolvido. | Pré-internet (1996). Texto curto. Possivelmente fora do escopo "leis digitais" stricto sensu. |
| **Lei 13.772/2018 (registro audiovisual de nudez)** | `…lei:2018-12-19;13772` | Tipifica registro não consentido de nudez/intimidade — parallel a CP art.218-C que já temos. | CP art.218-C já cobre divulgação; 13.772 cobre o REGISTRO. Cobertura marginal. |

### Não recomendado

- **Lei 14.197/2021** (crimes contra Estado Democrático): tangencial. Tipifica crimes digitais de Estado mas não é foco do corpus.
- **Lei 14.532/2023** (racismo em ambiente digital): tangencial, mais penal que estrutural.
- **PL 2630/2020 (fake news)**: projeto de lei, não law. Skip.

## Plano Tier-2 final (recomendação)

1. **Sempre adicionar**: 14.063, 14.129, 11.419 (3 leis, reviewer aprovou).
2. **Sob confirmação do user**: MP 2.200-2/2001 e/ou Lei 9.296/1996.
3. **Pular tudo o resto**.

Custo estimado por lei:
- Fetch HTML: ~30s (Planalto)
- Parse + chunk: ~5s (parser atual)
- Re-build voyage index (full corpus): ~30s + ~$0.30 em créditos voyage

Total pra 3 leis: ~$1.50 e ~5 minutos de wall clock. Adicionando MP 2.200-2 e 9.296: ~$2 e ~7 min.

## Impacto esperado no eval

**Sem queries novas**: nenhuma. A eval v3 (78 queries) **não tem nenhuma query** que naturalmente pegue Gov Digital ou processo eletrônico. Tier-2 adicionará chunks que aparecerão como "candidatos errados" no top-K se queries relacionadas existirem.

**Pra Tier-2 mover métrica**: precisa eval queries cobrindo:
- "como funciona assinatura digital?" → 14.063
- "diretrizes da Lei do Governo Digital?" → 14.129
- "processo eletrônico no Judiciário" → 11.419

Sugiro adicionar 5-10 queries de cobertura Tier-2 **junto com** o pull dos docs.
