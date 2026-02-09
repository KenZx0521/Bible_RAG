const fs = require("fs");
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  AlignmentType, BorderStyle, WidthType, ShadingType, SectionType,
  HeadingLevel, TabStopPosition, TabStopType,
} = require("docx");

// ── Constants ──────────────────────────────────────────────────────────
const FONT = "Times New Roman";
const PT10 = 20;   // 10pt in half-points
const PT9 = 18;
const PT8 = 16;
const PT7 = 14;
const PT14 = 28;
const PT12 = 24;
const PT11 = 22;

const PAGE_W = 12240;  // US Letter 8.5"
const PAGE_H = 15840;  // US Letter 11"
const MARGIN_TOP = 720;    // 0.5"
const MARGIN_BOT = 720;
const MARGIN_LR = 810;     // ~0.56"
const CONTENT_W = PAGE_W - 2 * MARGIN_LR; // 10620 DXA
const COL_GAP = 432;  // ~0.3"
const COL_W = Math.floor((CONTENT_W - COL_GAP) / 2); // ~5094

// ── Helpers ────────────────────────────────────────────────────────────
function p(texts, opts = {}) {
  const children = texts.map(t => {
    if (typeof t === "string") return new TextRun({ text: t, font: FONT, size: opts.size || PT10 });
    return new TextRun({ font: FONT, size: opts.size || PT10, ...t });
  });
  return new Paragraph({
    alignment: opts.alignment || AlignmentType.JUSTIFIED,
    spacing: { after: opts.after !== undefined ? opts.after : 60, before: opts.before || 0, line: opts.line || 228 },
    indent: opts.indent,
    children,
  });
}

function sectionHead(text) {
  return new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 160, after: 80, line: 228 },
    children: [new TextRun({ text, font: FONT, size: PT10, bold: true, allCaps: true })],
  });
}

function subHead(text) {
  return new Paragraph({
    spacing: { before: 100, after: 40, line: 228 },
    children: [new TextRun({ text, font: FONT, size: PT10, italics: true })],
  });
}

// ── Table helper ──────────────────────────────────────────────────────
const thinBorder = { style: BorderStyle.SINGLE, size: 1, color: "000000" };
const noBorder = { style: BorderStyle.NONE, size: 0 };
const topBottomBorders = {
  top: thinBorder, bottom: thinBorder,
  left: noBorder, right: noBorder,
};
const bottomOnlyBorders = {
  top: noBorder, bottom: thinBorder,
  left: noBorder, right: noBorder,
};
const noAllBorders = {
  top: noBorder, bottom: noBorder,
  left: noBorder, right: noBorder,
};

function tableCell(text, opts = {}) {
  return new TableCell({
    width: { size: opts.width || 1000, type: WidthType.DXA },
    borders: opts.borders || noAllBorders,
    margins: { top: 20, bottom: 20, left: 40, right: 40 },
    shading: opts.shading ? { fill: opts.shading, type: ShadingType.CLEAR } : undefined,
    children: [new Paragraph({
      alignment: opts.alignment || AlignmentType.LEFT,
      spacing: { after: 0, before: 0, line: 200 },
      children: [new TextRun({
        text, font: FONT,
        size: opts.size || PT8,
        bold: opts.bold || false,
        italics: opts.italics || false,
      })],
    })],
  });
}

// Metrics table column widths (5 columns: category, metric, claude, gemma, delta)
const T1_COLS = [820, 1500, 820, 820, 1040];

function t1Row(cat, metric, claude, gemma, delta, opts = {}) {
  const borders = opts.borders || noAllBorders;
  return new TableRow({
    children: [
      tableCell(cat, { width: T1_COLS[0], borders, bold: opts.headerBold, size: opts.size || PT7, italics: opts.catItalics }),
      tableCell(metric, { width: T1_COLS[1], borders, bold: opts.headerBold, size: opts.size || PT7 }),
      tableCell(claude, { width: T1_COLS[2], borders, bold: opts.headerBold, alignment: AlignmentType.CENTER, size: opts.size || PT7 }),
      tableCell(gemma, { width: T1_COLS[3], borders, bold: opts.headerBold, alignment: AlignmentType.CENTER, size: opts.size || PT7 }),
      tableCell(delta, { width: T1_COLS[4], borders, bold: opts.headerBold, alignment: AlignmentType.CENTER, size: opts.size || PT7 }),
    ],
  });
}

// Per-type table column widths (4 columns)
const T2_COLS = [1800, 1000, 1000, 1200];

function t2Row(type, claude, gemma, delta, opts = {}) {
  const borders = opts.borders || noAllBorders;
  return new TableRow({
    children: [
      tableCell(type, { width: T2_COLS[0], borders, bold: opts.headerBold, size: opts.size || PT7, italics: opts.typeItalics }),
      tableCell(claude, { width: T2_COLS[1], borders, bold: opts.headerBold, alignment: AlignmentType.CENTER, size: opts.size || PT7 }),
      tableCell(gemma, { width: T2_COLS[2], borders, bold: opts.headerBold, alignment: AlignmentType.CENTER, size: opts.size || PT7 }),
      tableCell(delta, { width: T2_COLS[3], borders, bold: opts.headerBold, alignment: AlignmentType.CENTER, size: opts.size || PT7 }),
    ],
  });
}

// Route table column widths (6 columns: route, signal, SQL, Sem., Graph, XRef)
const RT_COLS = [450, 1350, 600, 600, 600, 600];

function rtRow(route, signal, sql, sem, graph, xref, opts = {}) {
  const borders = opts.borders || noAllBorders;
  const ctr = AlignmentType.CENTER;
  return new TableRow({
    children: [
      tableCell(route, { width: RT_COLS[0], borders, bold: opts.headerBold, size: opts.size || PT7 }),
      tableCell(signal, { width: RT_COLS[1], borders, bold: opts.headerBold, size: opts.size || PT7 }),
      tableCell(sql, { width: RT_COLS[2], borders, bold: opts.headerBold, alignment: ctr, size: opts.size || PT7 }),
      tableCell(sem, { width: RT_COLS[3], borders, bold: opts.headerBold, alignment: ctr, size: opts.size || PT7 }),
      tableCell(graph, { width: RT_COLS[4], borders, bold: opts.headerBold, alignment: ctr, size: opts.size || PT7 }),
      tableCell(xref, { width: RT_COLS[5], borders, bold: opts.headerBold, alignment: ctr, size: opts.size || PT7 }),
    ],
  });
}

// ── Section I content (single-column: title, authors, abstract) ──────
const titleSection = [
  // Title
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 80, before: 0, line: 260 },
    children: [new TextRun({
      text: "Signal-Driven Graph RAG for Domain QA: Design, Deployment, and Evaluation",
      font: FONT, size: PT14, bold: true,
    })],
  }),
  // Authors placeholder
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 40, line: 228 },
    children: [new TextRun({ text: "Author Name", font: FONT, size: PT12 })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 160, line: 228 },
    children: [new TextRun({ text: "Department, University", font: FONT, size: PT10, italics: true })],
  }),
  // Abstract heading
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 40, before: 60, line: 228 },
    children: [new TextRun({ text: "Abstract", font: FONT, size: PT10, bold: true, italics: true })],
  }),
  // Abstract body
  p([{
    text: "Can a small, locally-deployed language model match a commercial large model on domain-specific question answering when supported by well-designed retrieval? We investigate this question through a signal-driven Graph RAG architecture for Traditional Chinese Bible QA, integrating PostgreSQL, Qdrant, and Neo4j with a 6-route retrieval system that selects optimal engine combinations based on six query signal features. On a 100-question benchmark spanning five question types and 19 metrics, Gemma 3 4B (local, zero API cost) achieves comparable performance to Claude Haiku 4.5 (commercial API): 9 of 12 generation metrics differ by less than 4 percentage points, with complementary strengths\u2014Claude leads on faithfulness (0.887 vs. 0.849) while Gemma leads on answer relevancy (0.658 vs. 0.592). Our results demonstrate that retrieval architecture design, rather than model scale, is the primary determinant of domain QA quality, simultaneously reducing cost and compensating for the limited domain knowledge of smaller models.",
    italics: true,
  }], { after: 60, line: 216, size: PT9 }),
];

// ── Body content (double-column) ─────────────────────────────────────

// I. INTRODUCTION
const introContent = [
  sectionHead("I. Introduction"),
  p([
    "Large language models (LLMs) achieve impressive performance on general question answering, yet deploying them for domain-specific tasks presents two challenges: (1) commercial API costs scale linearly with query volume\u2014making small, locally-deployed models attractive\u2014and (2) non-English specialized corpora such as Traditional Chinese biblical texts receive limited coverage during pre-training, leaving both large and small models with factual gaps that cannot be resolved by scaling alone. This raises a practical question: ",
    { text: "can a well-designed retrieval pipeline close the quality gap between a 4B-parameter local model and a commercial large model?", italics: true },
  ], { after: 60 }),
  p([
    "Retrieval-Augmented Generation (RAG) [1] supplements LLM generation with retrieved evidence, reducing hallucination and enabling domain adaptation without fine-tuning. Knowledge graph-enhanced RAG [2] further captures entity relationships that complement dense passage retrieval [9] and lexical methods [10]. While recent surveys [3] catalogue diverse RAG architectures, most evaluations compare retrieval strategies under a single model, leaving a critical gap: ",
    { text: "when the retrieval component is held constant, how much does model scale actually affect answer quality?", italics: true },
  ], { after: 60 }),
  p(["Our contributions are threefold:"], { after: 20 }),
  p([
    { text: "1) ", bold: true },
    "A signal-driven 6-route Graph RAG architecture integrating PostgreSQL, Qdrant, and Neo4j, where a decision-tree router selects optimal engine combinations based on six query signal features.",
  ], { after: 20, indent: { left: 180 } }),
  p([
    { text: "2) ", bold: true },
    "Empirical evidence that Gemma 3 4B [6] (locally deployed, zero API cost) achieves comparable performance to Claude Haiku 4.5 [7], with complementary strengths across 12 generation metrics.",
  ], { after: 20, indent: { left: 180 } }),
  p([
    { text: "3) ", bold: true },
    "A 19-metric evaluation framework spanning retrieval, reference-based, semantic, and LLM-judged dimensions [5] over 100 curated questions in 5 types.",
  ], { after: 60, indent: { left: 180 } }),
];

// II. SYSTEM ARCHITECTURE
const archContent = [
  sectionHead("II. System Architecture"),

  // Figure 1 - updated architecture diagram
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 60, after: 0, line: 200 },
    children: [new TextRun({ text: "Query \u2192 Verse Parser (regex) + Intent Classifier", font: "Courier New", size: PT7 })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 0, line: 200 },
    children: [new TextRun({ text: "\u2193 Signal Detector (6 boolean signals)", font: "Courier New", size: PT7 })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 0, line: 200 },
    children: [new TextRun({ text: "\u2193 Decision Tree: R1>R2>R5>R3>R4>R6>FB", font: "Courier New", size: PT7 })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 0, line: 200 },
    children: [new TextRun({ text: "PostgreSQL | Qdrant(BGE-M3) | Neo4j(KG)", font: "Courier New", size: PT7 })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 20, line: 200 },
    children: [new TextRun({ text: "Dedup \u2192 BGE-Reranker-v2-M3 \u2192 LLM \u2192 Answer", font: "Courier New", size: PT7 })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 80, line: 200 },
    children: [
      new TextRun({ text: "Fig. 1. ", font: FONT, size: PT8, bold: true }),
      new TextRun({ text: "Signal-driven 6-route RAG pipeline.", font: FONT, size: PT8 }),
    ],
  }),

  // A. Data Processing
  subHead("A. Data Processing Pipeline"),
  p([
    "The 66 books of the Traditional Chinese Bible are processed through hierarchical chunking: Book (66) \u2192 Chapter (1,189) \u2192 Pericope (2,779) \u2192 Chunk (438), with token-aware splitting (512\u20131024 tokens) respecting verse boundaries. CKIP Transformers [8] perform Chinese NER with LLM validation, extracting 14,845 entities across 6 types (Person, Place, Event, Theme, Object, Group) linked to text via 49,668 MENTIONS edges. BGE-M3 [4] generates 1024-dim embeddings for 3,041 vectors stored in Qdrant.",
  ]),

  // B. Triple-Database
  subHead("B. Triple-Database Architecture"),
  p([
    "PostgreSQL stores structured verse/chapter/book data (100,222 records) for exact lookup. Qdrant provides dense vector search via cosine similarity over 3,041 embedding points. Neo4j maintains a knowledge graph with 19,317 nodes and 58,031 relationships across 5 edge types: MENTIONS (49,668), CONTAINS (4,406), NEXT (2,980), CROSS_REFERENCES (912), and NEXT_BOOK (65).",
  ]),

  // C. Signal-Driven 6-Route Retrieval
  subHead("C. Signal-Driven 6-Route Retrieval"),
  p([
    "Each query first undergoes verse reference parsing (regex) and LLM intent classification to extract entity names and keywords. A ",
    { text: "signal detector", italics: true },
    " then analyzes the query for six boolean features: (1) book+chapter:verse reference, (2) book+chapter-only reference, (3) \u22652 book names, (4) \u22652 person entities, (5) event keyword, and (6) place name\u2014detected via regex patterns and dictionary substring matching against person, place, and event entity lists derived from the knowledge graph.",
  ], { after: 40 }),
  p([
    "A priority-ordered decision tree (Table I) selects among seven routes. ",
    { text: "R1 (Exact Verse)", bold: true },
    " performs a direct SQL lookup by book+chapter:verse and returns the match without reranking, falling back to R2 if empty. ",
    { text: "R2 (Chapter + Semantic)", bold: true },
    " combines SQL chapter-filtered pericopes (weight 0.9) with Qdrant dense vector search (0.6) for chapter-level references. ",
    { text: "R3 (Person Graph)", bold: true },
    " launches parallel Neo4j Person\u2192MENTIONS traversal (0.9) and semantic search (0.7) when \u22652 person entities are detected, supplemented by SQL chapter pericopes (0.5). ",
    { text: "R4 (Event Graph)", bold: true },
    " traverses Event\u2192MENTIONS edges (0.85) in parallel with semantic search (0.7) upon event keyword detection, aggregating multi-chapter narratives across graph hops. ",
    { text: "R5 (Cross-Reference)", bold: true },
    " activates when \u22652 books are mentioned or the LLM classifies the intent as cross-reference, employing a two-phase strategy: semantic search first produces seed passages (0.65), whose IDs then feed parallel CROSS_REFERENCES traversal (0.85) and entity graph retrieval (0.75). ",
    { text: "R6 (Place Graph)", bold: true },
    " triggers parallel Place\u2192MENTIONS traversal (0.85) and semantic search (0.7) for place-name queries. The ",
    { text: "Fallback", bold: true },
    " route defaults to pure semantic search when no signal fires. After retrieval, all routes except R1 undergo ID-based deduplication (highest-weight retention) and BGE-Reranker-v2-M3 [4] cross-encoder reranking.",
  ]),

  // Table I caption - Route Overview
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 60, after: 30, line: 200 },
    children: [new TextRun({ text: "TABLE I", font: FONT, size: PT8, bold: true })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 0, after: 30, line: 200 },
    children: [new TextRun({ text: "Signal-Driven Route Overview and Engine Weight Matrix", font: FONT, size: PT8 })],
  }),

  // Table I - Route Overview (weight matrix)
  new Table({
    width: { size: RT_COLS.reduce((a, b) => a + b, 0), type: WidthType.DXA },
    columnWidths: RT_COLS,
    rows: [
      rtRow("Route", "Signal", "SQL", "Sem.", "Graph", "XRef", { borders: topBottomBorders, headerBold: true }),
      rtRow("R1", "book+ch:v", "1.00", "\u2014", "\u2014", "\u2014"),
      rtRow("R2", "book+ch", "0.90", "0.60", "\u2014", "\u2014"),
      rtRow("R3", "\u22652 persons", "0.50", "0.70", "0.90", "\u2014"),
      rtRow("R4", "event kw", "0.50", "0.70", "0.85", "\u2014"),
      rtRow("R5", "\u22652 books/xref", "0.40", "0.65", "0.75", "0.85"),
      rtRow("R6", "place", "0.50", "0.70", "0.85", "\u2014"),
      rtRow("FB", "(else)", "\u2014", "1.00", "\u2014", "\u2014", { borders: bottomOnlyBorders }),
    ],
  }),

  // D. Pluggable LLM
  subHead("D. Pluggable LLM Generation"),
  p([
    "A factory pattern supports multiple providers (Claude, Gemini, OpenAI, Ollama). An identical evidence-first system prompt enforces strict citation. Note that the LLM also performs intent classification (Step 1), so switching models can introduce minor routing differences for complex query types\u2014a design trade-off we analyze in Section IV.",
  ]),
];

// III. EXPERIMENTS
const expContent = [
  sectionHead("III. Experiments"),
  p([
    { text: "Setup. ", bold: true },
    "We curated 100 questions across 5 types (20 each): VERSE_LOOKUP, TOPIC, PERSON, EVENT, and GENERAL, mapped to routes R1\u2013R5 respectively. We compare Claude Haiku 4.5 (commercial API) [7] against Gemma 3 4B (local Ollama) [6] sharing the same retrieval codebase (temperature=0.1, top_k=5). We employ 19 metrics in 4 categories: retrieval (7), reference-based (5), semantic (1), and LLM-judged (6, via RAGAS [5]).",
  ], { after: 40 }),

  // Table II caption
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 40, after: 30, line: 200 },
    children: [new TextRun({ text: "TABLE II", font: FONT, size: PT8, bold: true })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 0, after: 30, line: 200 },
    children: [new TextRun({ text: "Overall Performance Comparison (Selected Metrics)", font: FONT, size: PT8 })],
  }),

  // Table II
  new Table({
    width: { size: T1_COLS.reduce((a, b) => a + b, 0), type: WidthType.DXA },
    columnWidths: T1_COLS,
    rows: [
      t1Row("Category", "Metric", "Claude", "Gemma", "\u0394", { borders: topBottomBorders, headerBold: true }),
      t1Row("Retrieval", "Hit Rate", "0.790", "0.820", "+0.030", { catItalics: true }),
      t1Row("", "Recall@5", "0.746", "0.761", "+0.015"),
      t1Row("", "MRR", "0.753", "0.782", "+0.029", { borders: bottomOnlyBorders }),
      t1Row("LLM Judge", "Faithfulness", "0.887", "0.849", "\u22120.039", { catItalics: true }),
      t1Row("", "Ans. Relevancy", "0.592", "0.658", "+0.066"),
      t1Row("", "Ctx. Recall", "0.678", "0.712", "+0.034"),
      t1Row("", "Ans. Correctness", "0.572", "0.557", "\u22120.015", { borders: bottomOnlyBorders }),
      t1Row("Semantic", "Similarity", "0.738", "0.729", "\u22120.009", { catItalics: true, borders: bottomOnlyBorders }),
      t1Row("Ref-based", "BERTScore", "0.663", "0.685", "+0.022", { catItalics: true, borders: bottomOnlyBorders }),
    ],
  }),

  // Table III caption
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 60, after: 30, line: 200 },
    children: [new TextRun({ text: "TABLE III", font: FONT, size: PT8, bold: true })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 0, after: 30, line: 200 },
    children: [new TextRun({ text: "Answer Correctness by Question Type (Route)", font: FONT, size: PT8 })],
  }),

  // Table III
  new Table({
    width: { size: T2_COLS.reduce((a, b) => a + b, 0), type: WidthType.DXA },
    columnWidths: T2_COLS,
    rows: [
      t2Row("Type (Route)", "Claude", "Gemma", "\u0394", { borders: topBottomBorders, headerBold: true }),
      t2Row("VERSE (R1)", "0.841", "0.886", "+0.044", { typeItalics: false }),
      t2Row("TOPIC (R2)", "0.657", "0.622", "\u22120.036"),
      t2Row("PERSON (R3)", "0.440", "0.418", "\u22120.022"),
      t2Row("EVENT (R4)", "0.457", "0.440", "\u22120.017"),
      t2Row("GENERAL (R5)", "0.416", "0.370", "\u22120.047", { borders: bottomOnlyBorders }),
    ],
  }),
];

// IV. RESULTS AND DISCUSSION
const resultsContent = [
  sectionHead("IV. Results and Discussion"),

  subHead("Finding 1: Complementary Model Strengths"),
  p([
    "Table II shows that 9 of 12 generation metrics differ by less than 4 percentage points. The models exhibit complementary strengths: Claude achieves higher faithfulness (0.887 vs. 0.849), indicating stricter citation behavior, while Gemma leads on answer relevancy (0.658 vs. 0.592), suggesting more comprehensive responses. Retrieval metrics are identical for signal-deterministic routes (R1, R2) but diverge slightly for R3\u2013R5, where LLM-dependent intent classification affects entity extraction and thus graph traversal inputs. This confirms that when high-quality context is provided, model differences manifest as generation style rather than fundamental quality gaps.",
  ]),

  subHead("Finding 2: Route-Specific Analysis"),
  p([
    "Table III reveals clear route-dependent patterns. VERSE (R1) scores highest (0.841/0.886) because SQL direct match provides exact evidence; Gemma\u2019s stronger BLEU (0.547 vs. 0.173) on this route suggests closer lexical alignment with reference answers. GENERAL (R5) scores lowest (0.416/0.370) as the cross-reference path\u2014the most complex 4-engine route\u2014faces sparser CROSS_REFERENCES edges (912 total). EVENT (R4) also challenges both models (0.457/0.440) since multi-chapter narratives strain fixed-window chunking. Claude leads on TOPIC and GENERAL; Gemma leads on VERSE, indicating complementary biases tied to route complexity.",
  ]),

  subHead("Finding 3: Cost-Quality Tradeoff"),
  p([
    "Gemma 3 4B runs locally via Ollama with zero API cost and full data privacy\u2014critical for sensitive corpora. Despite moderate per-metric gaps, neither model dominates overall, making the local option viable for production deployment. This finding reframes the cost-quality tradeoff: the key investment shifts from model scale to retrieval infrastructure, where the signal-driven router ensures each query type receives an optimized engine combination rather than a one-size-fits-all strategy. Moreover, RAG compensates for the smaller model\u2019s limited domain knowledge by supplying structured evidence that both models lack from pre-training. Low ROUGE (<0.03) reflects paraphrased generation; semantic similarity (0.738/0.729) and BERTScore (0.663/0.685) confirm that retrieval design\u2014not model scale\u2014is the primary determinant of answer quality.",
  ]),
];

// V. CONCLUSION
const conclusionContent = [
  sectionHead("V. Conclusion"),
  p([
    "We designed, deployed, and evaluated a signal-driven Graph RAG architecture for Traditional Chinese Bible QA, featuring a 6-route decision-tree router that selects optimal engine combinations from PostgreSQL, Qdrant, and Neo4j based on query signal features. A locally-deployed Gemma 3 4B achieves comparable performance to Claude Haiku 4.5, with 9 of 12 generation metrics within 4 percentage points and complementary model strengths. These results affirm that a well-designed retrieval architecture can close the quality gap between a small local model and a commercial large model, simultaneously eliminating API costs and compensating for limited domain knowledge in pre-training. Future work includes hybrid dense-sparse retrieval [10], adaptive route weight tuning, and multilingual evaluation across Bible translations.",
  ]),
];

// REFERENCES
function ref(num, text) {
  return p([
    { text: `[${num}] `, bold: false, size: PT8 },
    { text, size: PT8 },
  ], { after: 20, line: 200, size: PT8, indent: { left: 280, hanging: 280 } });
}

const referencesContent = [
  sectionHead("References"),
  ref(1, 'P. Lewis et al., "Retrieval-augmented generation for knowledge-intensive NLP tasks," NeurIPS, 2020.'),
  ref(2, 'D. Edge et al., "From local to global: A graph RAG approach to query-focused summarization," arXiv:2404.16130, 2024.'),
  ref(3, 'Y. Gao et al., "Retrieval-augmented generation for large language models: A survey," arXiv:2312.10997, 2024.'),
  ref(4, 'J. Chen et al., "BGE M3-embedding: Multi-lingual, multi-functionality, multi-granularity text embeddings through self-knowledge distillation," arXiv:2402.03216, 2024.'),
  ref(5, 'S. Es et al., "RAGAS: Automated evaluation of retrieval augmented generation," arXiv:2309.15217, 2024.'),
  ref(6, 'Google DeepMind, "Gemma 3 technical report," arXiv:2503.19786, 2025.'),
  ref(7, 'Anthropic, "The Claude model family," 2024.'),
  ref(8, 'W.-Y. Ma and K.-J. Chen, "CKIP Transformers: An NLP toolkit for traditional Chinese," in Proc. ROCLING, 2021.'),
  ref(9, 'V. Karpukhin et al., "Dense passage retrieval for open-domain question answering," EMNLP, 2020.'),
  ref(10, 'S. Robertson and H. Zaragoza, "The probabilistic relevance framework: BM25 and beyond," Found. Trends Inf. Retr., 2009.'),
];

// ── Build Document ───────────────────────────────────────────────────
const pageProps = {
  page: {
    size: { width: PAGE_W, height: PAGE_H },
    margin: { top: MARGIN_TOP, bottom: MARGIN_BOT, left: MARGIN_LR, right: MARGIN_LR },
  },
};

const doc = new Document({
  styles: {
    default: {
      document: {
        run: { font: FONT, size: PT10 },
      },
    },
  },
  sections: [
    // Section 1: single-column (title + abstract)
    {
      properties: {
        ...pageProps,
      },
      children: titleSection,
    },
    // Section 2: double-column (body)
    {
      properties: {
        ...pageProps,
        type: SectionType.CONTINUOUS,
        column: {
          space: COL_GAP,
          count: 2,
        },
      },
      children: [
        ...introContent,
        ...archContent,
        ...expContent,
        ...resultsContent,
        ...conclusionContent,
        ...referencesContent,
      ],
    },
  ],
});

// ── Generate ─────────────────────────────────────────────────────────
Packer.toBuffer(doc).then(buffer => {
  const outPath = "paper.docx";
  fs.writeFileSync(outPath, buffer);
  console.log(`Generated ${outPath} (${buffer.length} bytes)`);
});
