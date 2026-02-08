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

// Table 1 column widths (fits single column ~5094 DXA)
const T1_W = 5000;
const T1_COL = [720, 1280, 780, 780, 640]; // category, metric, claude, gemma, delta = 4200 total
// Adjust to fit: sum = 4200, but we have 5000 total width
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

// Table 2 column widths (4 columns for per-type breakdown)
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

// ── Section I content (single-column: title, authors, abstract) ──────
const titleSection = [
  // Title
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 80, before: 0, line: 260 },
    children: [new TextRun({
      text: "LLM Graph RAG Design, Deployment, and Evaluation \u2014 Bible as an Example",
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
    text: "Domain-specific question answering with large language models (LLMs) incurs high API costs and raises data-privacy concerns, while smaller models often lack sufficient domain knowledge. We design, deploy, and evaluate a multi-strategy Graph RAG architecture for Traditional Chinese Bible QA, integrating PostgreSQL, Qdrant, and Neo4j with four parallel retrieval strategies. On a 100-question benchmark spanning five question types and 19 metrics, a locally-deployed Gemma 3 4B model matches Claude Haiku 4.5 within <1% on all 12 generation metrics. These results demonstrate that a well-designed RAG pipeline effectively decouples answer quality from model scale, enabling cost-free, privacy-preserving deployment with no measurable quality loss.",
    italics: true,
  }], { after: 60, line: 216, size: PT9 }),
];

// ── Body content (double-column) ─────────────────────────────────────

// I. INTRODUCTION
const introContent = [
  sectionHead("I. Introduction"),
  // P1 - Problem motivation
  p([
    "Large language models (LLMs) achieve impressive performance on general question answering, yet deploying them for domain-specific tasks presents two challenges: (1) commercial API costs scale linearly with query volume, and (2) non-English specialized corpora\u2014such as Traditional Chinese biblical texts\u2014receive limited coverage during pre-training, leading to factual gaps regardless of model size. This raises a practical question: ",
    { text: "can a well-designed retrieval pipeline make the choice of LLM nearly irrelevant?", italics: true },
  ], { after: 60 }),
  // P2 - Related work and gap
  p([
    "Retrieval-Augmented Generation (RAG) [1] supplements LLM generation with retrieved evidence, reducing hallucination and enabling domain adaptation without fine-tuning. Knowledge graph-enhanced RAG [2] further captures entity relationships, offering complementary signals to dense passage retrieval [9] and lexical methods [10]. Recent surveys [3] catalogue diverse RAG architectures, yet most evaluations compare retrieval strategies under a single model. A critical gap remains: ",
    { text: "when the retrieval component is held constant, how much does model scale affect answer quality?", italics: true },
  ], { after: 60 }),
  // P3 - Contributions
  p(["Our contributions are threefold:"], { after: 20 }),
  p([
    { text: "1) ", bold: true },
    "A multi-database, multi-strategy Graph RAG architecture integrating PostgreSQL, Qdrant, and Neo4j with four parallel retrieval strategies and a dual-path query router.",
  ], { after: 20, indent: { left: 180 } }),
  p([
    { text: "2) ", bold: true },
    "Empirical evidence that Gemma 3 4B [6] (locally deployed, zero API cost) matches Claude Haiku 4.5 [7] within <1% on all 12 generation metrics under identical retrieval conditions.",
  ], { after: 20, indent: { left: 180 } }),
  p([
    { text: "3) ", bold: true },
    "A 19-metric evaluation framework spanning retrieval, reference-based, semantic, and LLM-judged dimensions [5] over 100 curated questions in 5 types.",
  ], { after: 60, indent: { left: 180 } }),
];

// II. SYSTEM ARCHITECTURE
const archContent = [
  sectionHead("II. System Architecture"),

  // Figure 1 - compact text-based architecture diagram
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 60, after: 0, line: 200 },
    children: [new TextRun({ text: "66 Books (Traditional Chinese Bible)", font: "Courier New", size: PT7 })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 0, line: 200 },
    children: [new TextRun({ text: "\u2193 Chunking \u2192 NER \u2192 Embedding", font: "Courier New", size: PT7 })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 0, line: 200 },
    children: [new TextRun({ text: "PostgreSQL(100K) | Qdrant(3K) | Neo4j(19K/58K)", font: "Courier New", size: PT7 })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 0, line: 200 },
    children: [new TextRun({ text: "\u2193 Verse | Semantic | Graph | CrossRef", font: "Courier New", size: PT7 })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 20, line: 200 },
    children: [new TextRun({ text: "Fusion \u2192 Dedup \u2192 Rerank \u2192 LLM \u2192 Answer", font: "Courier New", size: PT7 })],
  }),
  // Figure caption
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 80, line: 200 },
    children: [
      new TextRun({ text: "Fig. 1. ", font: FONT, size: PT8, bold: true }),
      new TextRun({ text: "System architecture overview.", font: FONT, size: PT8 }),
    ],
  }),

  // A. Data Processing
  subHead("A. Data Processing Pipeline"),
  p([
    "Scripture is processed through hierarchical chunking: Book (66) \u2192 Chapter (1,189) \u2192 Pericope (2,779) \u2192 Chunk (431), with token-aware splitting (512\u20131024 tokens) respecting verse boundaries. CKIP Transformers [8] perform Chinese NER with LLM validation, extracting 14,845 entities (6 types) with 80,912 mentions. BGE-M3 [4] generates 1024-dim embeddings for 3,041 vectors.",
  ]),

  // B. Triple-Database
  subHead("B. Triple-Database Architecture"),
  p([
    "PostgreSQL stores structured verse/chapter/book data (100,222 records) for exact lookup. Qdrant provides dense vector search via cosine similarity over 3,041 embedding points. Neo4j maintains a knowledge graph with 19,310 nodes and 57,877 relationships (CONTAINS, MENTIONS, CROSS_REFERENCES, NEXT).",
  ]),

  // C. Multi-Strategy Retrieval
  subHead("C. Multi-Strategy Retrieval"),
  p([
    "A dual-path router classifies queries: the ",
    { text: "fast path", italics: true },
    " handles verse lookups via PostgreSQL exact match (~20\u201350ms), while the ",
    { text: "normal path", italics: true },
    " (~810ms) executes four strategies in parallel: (1) Verse Direct \u2192 PostgreSQL, (2) Semantic \u2192 BGE-M3 query embedding \u2192 Qdrant cosine search, (3) Graph \u2192 entity name matching \u2192 Neo4j MENTIONS traversal, (4) Cross-Reference \u2192 conditional Neo4j CROSS_REFERENCES. Results undergo ID-based deduplication with highest-weight retention, followed by BGE-Reranker-v2-M3 reranking [4].",
  ]),

  // D. Pluggable LLM
  subHead("D. Pluggable LLM Generation"),
  p([
    "A factory pattern supports multiple providers (Claude, Gemini, OpenAI, Ollama). An identical evidence-first system prompt enforces strict citation. Critically, ",
    { text: "only the LLM differs between experiments", italics: true },
    "\u2014ensuring a controlled comparison of model capability.",
  ]),
];

// III. EXPERIMENTS
const expContent = [
  sectionHead("III. Experiments"),
  p([
    { text: "Setup. ", bold: true },
    "We curated 100 questions across 5 types (20 each): VERSE_LOOKUP, TOPIC, PERSON, EVENT, and GENERAL. We compare Claude Haiku 4.5 (commercial API) [7] against Gemma 3 4B (local Ollama) [6], sharing an identical retrieval pipeline (temperature=0.1, top_k=5). We employ 19 metrics in 4 categories: retrieval (7), reference-based (4), semantic (1), and LLM-judged (7, via RAGAS [5]).",
  ], { after: 40 }),

  // Table I caption
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 40, after: 40, line: 200 },
    children: [new TextRun({ text: "TABLE I", font: FONT, size: PT8, bold: true })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 0, after: 40, line: 200 },
    children: [new TextRun({ text: "Overall Performance Comparison (Selected Metrics)", font: FONT, size: PT8 })],
  }),

  // Table I (9 rows)
  new Table({
    width: { size: T1_COLS.reduce((a, b) => a + b, 0), type: WidthType.DXA },
    columnWidths: T1_COLS,
    rows: [
      t1Row("Category", "Metric", "Claude", "Gemma", "\u0394", { borders: topBottomBorders, headerBold: true }),
      t1Row("Retrieval", "Hit Rate", "0.920", "0.920", "0.000", { catItalics: true }),
      t1Row("", "Recall@5", "0.846", "0.846", "0.000"),
      t1Row("", "MRR", "0.800", "0.800", "0.000", { borders: bottomOnlyBorders }),
      t1Row("LLM Judge", "Faithfulness", "0.607", "0.607", "+0.001", { catItalics: true }),
      t1Row("", "Ans. Relevancy", "0.727", "0.733", "+0.006"),
      t1Row("", "Ctx. Recall", "0.721", "0.727", "+0.006"),
      t1Row("", "Ans. Correctness", "0.522", "0.522", "+0.001", { borders: bottomOnlyBorders }),
      t1Row("Semantic", "Similarity", "0.769", "0.768", "\u22120.001", { catItalics: true, borders: bottomOnlyBorders }),
      t1Row("Ref-based", "BERTScore", "0.653", "0.652", "\u22120.001", { catItalics: true, borders: bottomOnlyBorders }),
    ],
  }),

  // Table II caption
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 80, after: 40, line: 200 },
    children: [new TextRun({ text: "TABLE II", font: FONT, size: PT8, bold: true })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 0, after: 40, line: 200 },
    children: [new TextRun({ text: "Answer Correctness by Question Type", font: FONT, size: PT8 })],
  }),

  // Table II
  new Table({
    width: { size: T2_COLS.reduce((a, b) => a + b, 0), type: WidthType.DXA },
    columnWidths: T2_COLS,
    rows: [
      t2Row("Type", "Claude", "Gemma", "\u0394", { borders: topBottomBorders, headerBold: true }),
      t2Row("VERSE_LOOKUP", "0.614", "0.629", "+0.014", { typeItalics: false }),
      t2Row("TOPIC", "0.578", "0.547", "\u22120.031"),
      t2Row("PERSON", "0.453", "0.473", "+0.020"),
      t2Row("EVENT", "0.480", "0.467", "\u22120.013"),
      t2Row("GENERAL", "0.482", "0.495", "+0.013", { borders: bottomOnlyBorders }),
    ],
  }),
];

// IV. RESULTS AND DISCUSSION
const resultsContent = [
  sectionHead("IV. Results and Discussion"),

  subHead("Finding 1: RAG Equalizes Model Differences"),
  p([
    "Table I confirms that all retrieval metrics are identical (shared pipeline), validating experimental control. Crucially, all 12 generation metrics differ by <1%\u2014the maximum delta is 0.98% (point coverage, not shown). This implies that when high-quality context is provided, the LLM\u2019s role reduces to surface-level synthesis from evidence, making model scale far less critical than retrieval design. A free, locally-deployed 4B model is functionally indistinguishable from a commercial API.",
  ]),

  subHead("Finding 2: Per-Type Analysis"),
  p([
    "Table II reveals type-specific patterns. VERSE_LOOKUP scores highest (0.614/0.629) because fast-path retrieval supplies exact verses from PostgreSQL. EVENT scores lowest for both models (0.480/0.467), with hit_rate=0.75\u2014confirming retrieval, not model capability, is the bottleneck; event narratives span multiple chapters, challenging fixed-window chunking. PERSON questions benefit from Neo4j graph traversal (MENTIONS edges connect entities directly). Interestingly, Claude leads on TOPIC (\u22120.031) while Gemma leads on VERSE (+0.014) and PERSON (+0.020), suggesting complementary generation biases even under identical context.",
  ]),

  subHead("Finding 3: Cost-Quality Tradeoff"),
  p([
    "Gemma 3 4B runs locally via Ollama with zero API cost and full data privacy\u2014critical for sensitive corpora. Given the <1% gap, the key investment shifts from model selection to retrieval infrastructure. Low ROUGE/BLEU (<0.03) reflect paraphrased generation rather than failure; semantic similarity (0.769) and BERTScore (0.653) confirm actual quality, exposing the limitation of lexical metrics for generative QA. This architecture generalizes to any domain with structured, entity-rich corpora.",
  ]),
];

// V. CONCLUSION
const conclusionContent = [
  sectionHead("V. Conclusion"),
  p([
    "We designed, deployed, and evaluated a Graph RAG architecture for Traditional Chinese Bible QA integrating three databases and four retrieval strategies. A locally-deployed Gemma 3 4B matches Claude Haiku 4.5 within <1% on all generation metrics, confirming that retrieval quality\u2014not model scale\u2014determines domain QA performance. Future work includes hybrid dense-sparse retrieval [10], multilingual evaluation across Bible translations, and prompt optimization for small language models.",
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
