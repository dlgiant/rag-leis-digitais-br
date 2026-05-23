// Centralized glossary of RAG/engineering terms used in the lawyer
// review UI. These are concepts a practicing lawyer would NOT recognize
// from day-to-day legal work — `chunk`, `embedding`, `gold`, `top-k`,
// etc. Legal terms (caput, parágrafo, inciso, vigência, infralegal)
// are intentionally absent — those are common knowledge for the target
// reviewer and need no help text.
//
// The header "GLOSS" toggle (Layout.astro) flips
// <html data-tooltips="on|off"> globally. When on, every <TermTip>
// gets a dotted underline and reveals its definition on hover/focus.
// When off, the wrapped text renders indistinguishably from prose —
// the toggle is purely additive UI.

export type GlossaryEntry = {
  /** Short canonical name shown as the tooltip header. */
  term: string;
  /** 1–2 sentence PT-BR definition. Keep concise — these render in a
   * ~320px popover and lose readability if they wrap many lines. */
  def: string;
};

export const GLOSSARY = {
  chunk: {
    term: "Chunk",
    def: "Unidade indexada do RAG. Aqui, cada chunk corresponde a uma subdivisão LCP-95 (artigo, §, inciso, alínea) — é o que o sistema recupera e cita.",
  },
  urn: {
    term: "URN",
    def: "Identificador estável (RFC 9676) de uma norma ou subdivisão. Ex.: urn:lex:br:federal:lei:2018-08-14;13709~art5;inc2. Serve como ID interno e como citação oficial.",
  },
  "eval-set": {
    term: "Eval set",
    def: "Conjunto curado de pares (pergunta → trechos relevantes) usado para medir se o RAG está recuperando as normas certas. É como o sistema sabe se regrediu ou melhorou.",
  },
  gold: {
    term: "Gold",
    def: "Os trechos legalmente corretos para responder a uma pergunta — o gabarito. O retriever tenta achar exatamente esses trechos.",
  },
  "core-supporting": {
    term: "Central vs auxiliar",
    def: "Gold central = norma indispensável para responder. Auxiliar = ajuda no enquadramento mas não é o fundamento principal.",
  },
  retriever: {
    term: "Retriever",
    def: "Componente que, dada uma pergunta, busca os chunks com maior probabilidade de conter a resposta — antes do LLM redigir o texto final.",
  },
  "top-k": {
    term: "Top-k",
    def: "Os k chunks mais bem pontuados que o retriever devolve. Padrão deste projeto: k = 10.",
  },
  refinement: {
    term: "Refinamento",
    def: "Reformulação experimental da pergunta para testar se vem mais gold no top-k. Não altera o eval set — só serve para explorar formulações alternativas.",
  },
  "classified-type": {
    term: "classified_type",
    def: "Como o LLM enquadrou a resposta: definição, paráfrase, citação literal, etc. Usado para auditar se o modelo respeita o tipo de pergunta.",
  },
  "corpus-drift": {
    term: "Drift do corpus",
    def: "URN listado no eval que não existe mais no corpus. Em geral indica que a norma foi alterada ou renumerada por emenda, ou que há erro de digitação.",
  },
  "rank-legal": {
    term: "Rank legal",
    def: "Hierarquia normativa codificada como 1 a 5 (1 = Constituição, 2 = Tratado, 3 = Lei ordinária/complementar, 4 = Decreto, 5 = infralegal/ANPD). Quanto menor o número, mais forte a norma.",
  },
  overlay: {
    term: "Overlay de vigência",
    def: "Anotação sobreposta a um chunk indicando que está sub judice, suspenso, vacatio legis, etc. — sem alterar o texto original da norma.",
  },
  "vigencia-coverage": {
    term: "Cobertura",
    def: "% de chunks do documento com overlay de vigência anotado. 0% = ninguém revisou; 100% = revisão completa.",
  },
  pii: {
    term: "PII",
    def: "Personally Identifiable Information — em pt-BR, dados pessoais identificáveis. Aqui designa CPF, CNPJ, e-mail, telefone e congêneres, que o redator remove antes de gravar a query no log.",
  },
  redactor: {
    term: "Redator de PII",
    def: "Função que reescreve a query antes de gravá-la, substituindo PII detectada por placeholders ([CPF], [EMAIL]…). Roda sempre, em todo log.",
  },
  regex: {
    term: "Regex",
    def: "Expressão regular — padrão de texto usado pelo redator para localizar CPF, e-mail, telefone, etc. Captura o que o padrão prevê; o que escapa do padrão precisa virar nova regra.",
  },
  "proposal-kind": {
    term: "Tipo da proposta (kind)",
    def: "Categoria da proposta enviada à fila do admin: review (revisão do gold), refinement (formulação alternativa), hierarchy (mascaramento normativo), pii_miss (PII não detectada), vigencia (overlay sugerido).",
  },
  verdict: {
    term: "Veredito",
    def: "Decisão do revisor sobre se o gold do eval está correto: correto, incorreto ou precisa de revisão. Alimenta a fila de propostas que o admin consolida.",
  },
  nav: {
    term: "nav",
    def: "Trilha hierárquica do chunk (livro → título → capítulo → seção). É prefixada ao texto antes do embedding para dar contexto ao retriever.",
  },
  "audit-log": {
    term: "Audit log",
    def: "Registro persistente de cada query processada pelo redator de PII. Permite revisão posterior para encontrar falsos negativos (PII que escapou do regex).",
  },
  proposal: {
    term: "Proposta",
    def: "Sugestão registrada pelo revisor que não altera o eval/corpus imediatamente. O admin consolida via CLI depois de validar.",
  },
  operator: {
    term: "Admin",
    def: "Conta única (variável de ambiente do backend) autorizada a consolidar propostas em alterações reais do eval e do corpus.",
  },
} satisfies Record<string, GlossaryEntry>;

export type GlossarySlug = keyof typeof GLOSSARY;
