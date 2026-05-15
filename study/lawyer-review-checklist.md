# Lawyer-Review Checklist

**Status**: aberto. Documento vivo. 2026-05-15.

Este doc consolida os itens que **precisam de validação jurídica
externa** antes que o RAG seja considerado production-grade pra usuário
final. Ele existe porque D7 (compliance budget + advogado consultor)
foi marcado como "vou conseguir antes de Phase 9 mas não agora" no
`study/post-review-plan.md`.

Quando o advogado for contratado, este doc é o **handoff list** —
priorizado por gravidade jurídica, não por esforço técnico.

## Gravidade — escala

- 🔴 **Bloqueador**: peça/parecer baseado nesta saída tem risco
  profissional ou processual real. Bloqueia launch.
- 🟡 **Importante**: degrada confiança da resposta mas não causa erro
  grave. Deve fechar antes de v1.0.
- 🟢 **Refinamento**: acerto editorial / qualidade. Ok ficar pra v1.1+.

## 🔴 Bloqueadores (não shippar v1.0 sem fechar)

### 1. Hierarquia normativa quando fontes secundárias mascaram primárias

**Caso canônico (validado empiricamente em Phase 5.2, 2026-05-15)**:

- Query: "quais sanções administrativas a ANPD pode aplicar por violação da LGPD?"
- Comportamento atual: o RAG cita Res. CD/ANPD nº 4/2023 art. 3º + 15
  filhos (resolução, rank infralegal) ao invés da LGPD art. 52 + incisos
  (lei ordinária — fonte primária).
- Razão técnica: Res. 4/2023 art. 3 mirrors LGPD art. 52 enumeração
  verbatim; cosine retriever surfacia ambos; LLM cita o lexicalmente
  mais próximo, que tende a ser a Resolução por ser mais recente e
  específica.
- Status pipeline: `RAGAnswer.hierarchy_warning` **dispara
  corretamente** alertando o usuário. Mas o answer text em si pode
  estar inadequado em peça processual.
- Eval impact: row 7 sanções caiu de faith 5/5 (Phase 4.2, sem Tier-3)
  pra faith 2/5 (Phase 5.2, com Tier-3). Documentado em
  `eval/runs/phase-5-2-legal-rank.json`.

**O que precisa de validação jurídica**:

1. **A warning em si é o tratamento adequado, ou o RAG deve recusar
   a resposta quando hierarquia está comprometida?** Análise: a
   warning preserva utilidade da resposta (advogado vê o conteúdo +
   sabe verificar); recusar perde valor sem ganho. Mas é decisão
   jurídica, não técnica.

2. **System prompt deve instruir "prefira fonte primária quando
   ambas disponíveis"?** Mudaria o comportamento do LLM
   estruturalmente. Risco: poderia esconder o problema (warning
   silenciado se modelo for instruído a evitar).

3. **Categoria de uso permitido**: este sistema gera material para:
   (a) consulta interna do advogado, (b) draft de peça/parecer,
   (c) resposta direta ao cliente final? Cada categoria tem
   tolerância diferente para o caso de hierarquia.

**Casos análogos esperados** (não testados ainda — depende de
expandir corpus + cross-doc gold):

- Decreto 8.771/2016 vs Marco Civil (lei) — quando perguntado sobre
  guarda de logs, qual fonte deve ser citada como principal?
- Súmulas STJ vs Lei Ordinária — quando jurisprudência pacificada
  contradiz interpretação literal da lei, qual prevalece no contexto
  da resposta?
- Resoluções ANPD vs LGPD em geral — Res. 1/2021 (fiscalização) e
  Res. 15/2024 (incidente) regulamentam disposições da lei.
  Como o RAG deve hierarquizar?

### 2. Vigência overlay — cobertura insuficiente

`data/vigencia/overlays.yaml` cobre 12 dispositivos (vide
`study/post-review-plan.md` Phase 3.1). Curadoria por mim, sem
validação jurídica. Casos confirmados:

- MCI art. 19 → sub_judice (STF Tema 987)
- LGPD art. 52 §1 → eficácia limitada pela ANPD Res. 4/2023
- CF art. 5 LXXIX → alterado por EC 115/2022
- CP art. 154-A → atualizado por Lei 14.155/2021
- Outros 8 dispositivos similares

**O que precisa de validação jurídica**:

1. **Lista exaustiva**: quais OUTROS dispositivos da Tier-1+2+3 estão
   em situação não-vigente padrão? Precisa de varredura sistemática
   por advogado.
2. **Versão do texto**: nosso parser captura o texto compilado do
   Planalto. Em casos de redação dada por lei posterior — qual
   versão deveria ser servida ao usuário? (Hoje: a vigente; mas a
   vigência overlay pode mudar isso.)
3. **Súmulas / jurisprudência vinculante** que efetivamente
   modificaram a aplicação de uma norma sem revogá-la formalmente.
   Hoje não capturado (Tier-4 deferred).

### 3. Cross-doc curation — gold incompleto

`eval/answer_queries.yaml` tem **1 row cross-doc apenas** (habeas
data). Reviewer round 2 (item 4) flagou que direito digital é
cross-doc por natureza:

- LGPD ↔ MCI (proteção de dados ↔ direitos do usuário)
- LGPD ↔ CDC (fornecedor ↔ controlador)
- CF ↔ LGPD (direitos fundamentais ↔ implementação)
- CP ↔ LGPD (crimes ↔ infrações administrativas)
- ANPD Resoluções ↔ LGPD (procedimento ↔ regra)

**Casos específicos identificados** (precisam gold curado):

1. *"Vazamento de dados de consumidor: responsabilidade do
   controlador"* — CDC art. 14 + LGPD art. 42 + STJ Súmula 479.
2. *"Direito ao esquecimento na internet"* — MCI art. 19 + CF art. 5
   X + STF Tema 786.
3. *"Tratamento de dados de crianças e adolescentes"* — LGPD art. 14
   + ECA art. 17 + CDC art. 39.
4. *"Notificação de incidente: prazo + conteúdo + casos especiais"*
   — Res. 15/2024 art. 6 + LGPD art. 48.
5. *"Sanções: dosimetria + procedimento + agentes pequeno porte"* —
   Res. 4/2023 + Res. 1/2021 + Res. 2/2022 + LGPD art. 52.

**O que precisa de validação jurídica**:

- Gold URNs por query (qual artigo é primário, qual é supporting)
- Relação entre as fontes (regulamenta / integra / contradiz /
  complementa) — schema sugerido em `study/post-review-plan.md`
  Phase 5.4

## 🟡 Importantes (fechar antes de v1.0)

### 4. 3rd precision tier — "judicial-acceptable" granularidade

Hoje `eval/answer_queries.yaml` tem 2 níveis: `gold_urns` (strict) +
`alternative_acceptable_urns` (lenient). Reviewer round 2 (item 5)
sugeriu 3º tier: granularidade que um juiz aceitaria em peça.

Exemplo do que isso captura:

- Strict: `art7;par6` (a regra exata da pergunta)
- Lenient: `art7;par6` + `art7` + `art8` (siblings defensáveis)
- **Judicial**: `art7;par6` apenas — nada de citar o caput quando a
  resposta está no parágrafo

**O que precisa de validação jurídica**:

- Para cada row, definir o conjunto judicial-acceptable
- Decisão sobre como tratar respostas que ficam no nível "lenient
  ok mas não judicial-strict"

### 5. OOS taxonomy — adversarial cases

`eval/answer_queries.yaml` tem 3 OOS rows, todas "outra área
inteira" (IRPF, divórcio, INPI). Reviewer round 2 (item 9) flagou
que o risco real é **adjacent OOS** — query que toca a vizinhança
do corpus mas não tem resposta:

- Subtypes (a-e): outra área / adjacent sem cobertura / projeto de
  lei não promulgado / matéria estadual-municipal / doutrina sem
  positivação

**O que precisa de validação jurídica**:

- Quais 12+ queries adversariais um advogado consideraria
  "armadilhas plausíveis"? Especialmente type (b) e (c) — o RAG é
  mais frágil aí.
- Para cada OOS, qual seria a refusal jurídica adequada (vs apenas
  "não há informação")?

### 6. PII redactor — coverage gaps

`rag_leis/pii.py` cobre 6 categorias regex (CPF, CNPJ, email,
phone, CEP, RG). NER pt-BR para nomes próprios deferred.

**O que precisa de validação jurídica**:

- A definição de "dado pessoal" da LGPD art. 5º I é mais ampla que
  os tipos cobertos. Quais categorias adicionais merecem redação?
  (Ex: número de cartão de crédito, IBAN, OAB, CRM, processo SEI,
  código eleitoral, NIS, PIS, registro CNJ, etc.)
- Política de retenção do audit log (`data/audit/pii-redactions.jsonl`)
  — quanto tempo guardar? LGPD art. 16 limita finalidade; precisa
  política expressa.

## 🟢 Refinamentos (ok pra v1.1+)

### 7. Citation prose check vs URN — Phase 5.3

Closes a gap entre "URN cited in JSON" e "Art. 5º, XII rendered in
answer prose". Quando o LLM diz "Art. 5º, **XII**" mas o URN é
`art5;inc10`, hoje passa silencioso. Phase 5.3 implementa regex
match. Precisa validação:

- Quais erros de prose são meramente cosméticos vs juridicamente
  significativos?
- Refusal sobre mismatch de prose deveria bloquear a resposta ou
  só anotar?

### 8. Source-as-of-date — Phase 5.5

Footer "consultado em DD/MM/AAAA" em cada answer. Mecânica
trivial. Precisa decisão jurídica:

- Versionamento por chunk (hash) ou por documento (data fetch)?
- Como tratar legislação alterada entre fetch e answer?

## Casos identificados pela auditoria automatizada

Quando o pipeline rodar em escala (Phase 7+ com observability), o
audit log do `RAGAnswer.hierarchy_warning` vai acumular casos
empíricos. Esses são prioridade pra revisão — reviewer-trigger
direto.

Recomendação: **toda response com hierarchy_warning deve ser
revisada pelo advogado consultor durante v0/v1**, não apenas
amostradas. Em volume alto (Phase 8+ deploy), amostragem com
base em qtype + warning combinations.

## Materiais de apoio para o advogado

- `study/lexml-urn-spec-resumo.md` — entender o esquema URN do
  projeto + escala normativa BR
- `study/post-review-plan.md` — roadmap completo, decisões D6-D10
  pendentes
- `eval/answer_queries.yaml` — 16 queries com expected_paragraph
- `eval/runs/phase-5-2-legal-rank.json` — última eval run com warning
- `data/vigencia/overlays.yaml` — overlays atuais
- `rag_leis/legal_rank.py` — escala numérica + mapeamento

## Histórico

- **2026-05-15** doc criado, item 1 (hierarquia normativa) com
  caso canônico empírico (row 7 sanções). Phase 5.2 implementou a
  warning; conteúdo deste doc capturou os casos a verificar.
