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
    spacing: { after: opts.after !== undefined ? opts.after : 30, before: opts.before || 0, line: opts.line || 220 },
    indent: opts.indent,
    children,
  });
}

function sectionHead(text) {
  return new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 80, after: 40, line: 228 },
    children: [new TextRun({ text, font: FONT, size: PT10, bold: true, allCaps: true })],
  });
}

function subHead(text) {
  return new Paragraph({
    spacing: { before: 50, after: 20, line: 228 },
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
    margins: { top: 15, bottom: 15, left: 30, right: 30 },
    shading: opts.shading ? { fill: opts.shading, type: ShadingType.CLEAR } : undefined,
    children: [new Paragraph({
      alignment: opts.alignment || AlignmentType.LEFT,
      spacing: { after: 0, before: 0, line: 200 },
      children: [new TextRun({
        text, font: FONT,
        size: opts.size || PT7,
        bold: opts.bold || false,
        italics: opts.italics || false,
      })],
    })],
  });
}

// Table I column widths (5 columns, wider metric name column)
const T1_COLS = [750, 1650, 750, 750, 1100]; // total 5000 DXA

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

// Table II column widths (5 columns for per-type breakdown)
const T2_COLS = [1400, 800, 800, 1000, 1000];

function t2Row(type, hitRate, ndcg, claudeAPC, gemmaAPC, opts = {}) {
  const borders = opts.borders || noAllBorders;
  return new TableRow({
    children: [
      tableCell(type, { width: T2_COLS[0], borders, bold: opts.headerBold, size: opts.size || PT7, italics: opts.typeItalics }),
      tableCell(hitRate, { width: T2_COLS[1], borders, bold: opts.headerBold, alignment: AlignmentType.CENTER, size: opts.size || PT7 }),
      tableCell(ndcg, { width: T2_COLS[2], borders, bold: opts.headerBold, alignment: AlignmentType.CENTER, size: opts.size || PT7 }),
      tableCell(claudeAPC, { width: T2_COLS[3], borders, bold: opts.headerBold, alignment: AlignmentType.CENTER, size: opts.size || PT7 }),
      tableCell(gemmaAPC, { width: T2_COLS[4], borders, bold: opts.headerBold, alignment: AlignmentType.CENTER, size: opts.size || PT7 }),
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
    spacing: { after: 120, line: 228 },
    children: [new TextRun({ text: "Department, University", font: FONT, size: PT10, italics: true })],
  }),
  // Abstract heading
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 40, before: 60, line: 228 },
    children: [new TextRun({ text: "Abstract", font: FONT, size: PT10, bold: true, italics: true })],
  }),
  // Abstract body — v4: research-question-first, ~148 words
  p([{
    text: "When high-quality retrieval context is provided, does LLM scale still matter? We investigate this question through a multi-strategy Graph RAG system for Traditional Chinese Bible question answering, integrating PostgreSQL (100K records), Qdrant (3,041 vectors), and Neo4j (19K nodes, 58K relationships) with four parallel retrieval strategies and a dual-path query router. In a controlled experiment where only the generation model varies, a locally deployed Gemma 3 4B matches the commercial Claude Haiku 4.5 within less than 1% on all 12 generation metrics (maximum absolute difference = 0.0098) across a 100-question benchmark evaluated with 19 metrics spanning retrieval, reference-based, semantic, and LLM-judged dimensions. Per-type analysis confirms that retrieval quality, not model scale, is the primary determinant of answer quality. These findings position RAG as a model equalizer, enabling zero-cost, privacy-preserving local deployment with no measurable quality loss.",
    italics: true,
  }], { after: 60, line: 200, size: PT9 }),
];

// ── Body content (double-column) ─────────────────────────────────────

// I. INTRODUCTION — v4: strengthened narrative
const introContent = [
  sectionHead("I. Introduction"),
  // P1 - Problem motivation (strengthened domain-specific challenges)
  p([
    "Large language models (LLMs) achieve impressive performance on general question answering, yet deploying them for domain-specific tasks presents two persistent challenges. First, commercial API costs scale linearly with query volume, making sustained deployment economically prohibitive for resource-constrained settings such as academic institutions and non-profit organizations. Second, non-English specialized corpora\u2014such as Traditional Chinese biblical texts spanning 66 books with archaic vocabulary and cross-referential narrative structures\u2014receive minimal coverage during pre-training, leading to factual gaps and hallucination regardless of model size. These constraints motivate a fundamental question: ",
    { text: "can a well-designed retrieval pipeline decouple answer quality from model scale?", italics: true },
  ], { after: 30 }),
  // P2 - Related work and gap (added controlled comparison emphasis)
  p([
    "Retrieval-Augmented Generation (RAG) [1] supplements LLM generation with retrieved evidence, reducing hallucination and enabling domain adaptation without fine-tuning. Knowledge graph-enhanced RAG [2] further captures entity relationships, complementing dense passage retrieval [9] and lexical methods such as BM25 [10]. Recent surveys [3] catalogue diverse RAG architectures, yet most evaluations compare retrieval strategies under a single model. A critical empirical gap remains: ",
    { text: "when the retrieval component is held constant, how much does model scale actually affect downstream answer quality?", italics: true },
    " We address this gap through a controlled comparison\u2014identical retrieval pipeline, identical prompts, only the LLM varies\u2014isolating the generation component\u2019s contribution.",
  ], { after: 30 }),
  // P3 - Contributions
  p(["This paper makes three contributions:"], { after: 10 }),
  p([
    { text: "1) ", bold: true },
    "A multi-database, multi-strategy Graph RAG architecture integrating PostgreSQL (100K records), Qdrant (3,041 vectors), and Neo4j (19K nodes, 58K relationships) with four parallel retrieval strategies and a dual-path query router.",
  ], { after: 10, indent: { left: 180 } }),
  p([
    { text: "2) ", bold: true },
    "Controlled empirical evidence that a locally deployed Gemma 3 4B [6] achieves functional equivalence with the commercial Claude Haiku 4.5 [7]\u2014differing by less than 1% on all 12 generation metrics\u2014when retrieval conditions are held constant.",
  ], { after: 10, indent: { left: 180 } }),
  p([
    { text: "3) ", bold: true },
    "A 19-metric evaluation framework across four categories [5], applied to 100 curated questions in five types, revealing retrieval quality as the primary determinant of answer quality.",
  ], { after: 30, indent: { left: 180 } }),
];

// II. SYSTEM ARCHITECTURE
const archContent = [
  sectionHead("II. System Architecture"),

  // Figure 1 - compact text-based architecture diagram
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 30, after: 0, line: 200 },
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
    spacing: { after: 10, line: 200 },
    children: [new TextRun({ text: "Fusion \u2192 Dedup \u2192 Rerank \u2192 LLM \u2192 Answer", font: "Courier New", size: PT7 })],
  }),
  // Figure caption
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 40, line: 200 },
    children: [
      new TextRun({ text: "Fig. 1. ", font: FONT, size: PT8, bold: true }),
      new TextRun({ text: "System architecture overview.", font: FONT, size: PT8 }),
    ],
  }),

  // A. Data Processing
  subHead("A. Data Processing Pipeline"),
  p([
    "The Traditional Chinese Bible (66 books) undergoes hierarchical chunking: Book (66) \u2192 Chapter (1,189) \u2192 Pericope (2,779) \u2192 Chunk (431), with token-aware splitting (512\u20131,024 tokens) respecting verse boundaries. CKIP Transformers [8] perform Chinese NER, extracting 14,845 entities across six types (Person, Place, Group, Event, Object, Theme) with 80,912 mentions. An LLM validation pass supplements NER output for abstract entity types. BGE-M3 [4] generates 1,024-dimensional embeddings for 3,041 text segments at three granularity levels.",
  ], { after: 30 }),

  // B. Triple-Database
  subHead("B. Triple-Database Architecture"),
  p([
    "Each database serves a distinct retrieval function. PostgreSQL stores structured verse, chapter, and book data (100,222 records) supporting exact-match lookup and full-text search. Qdrant indexes 3,041 dense vectors with cosine similarity for semantic retrieval. Neo4j maintains a knowledge graph of 19,310 nodes and 57,877 relationships (CONTAINS, NEXT, MENTIONS, CROSS_REFERENCES), enabling entity-centric graph traversal. All three databases share a unified ID scheme ensuring consistent cross-database linkage.",
  ], { after: 30 }),

  // C. Multi-Strategy Retrieval
  subHead("C. Multi-Strategy Retrieval"),
  p([
    "A dual-path router classifies incoming queries. The ",
    { text: "fast path", italics: true },
    " handles explicit verse references via PostgreSQL exact match (~20\u201350 ms). The ",
    { text: "normal path", italics: true },
    " (~810 ms) dispatches four strategies in parallel: (1) Verse Direct\u2014PostgreSQL lookup; (2) Semantic\u2014BGE-M3 query embedding followed by Qdrant cosine search; (3) Graph\u2014entity name matching via Neo4j MENTIONS traversal; and (4) Cross-Reference\u2014conditional Neo4j expansion. Results undergo ID-based deduplication retaining the highest-weight candidate, followed by BGE-Reranker-v2-M3 cross-encoder reranking [4].",
  ], { after: 30 }),

  // D. Pluggable LLM
  subHead("D. Pluggable LLM Generation"),
  p([
    "A factory pattern abstracts the generation layer, supporting multiple providers (Anthropic, Google, OpenAI, Ollama). An identical evidence-first system prompt enforces strict citation from retrieved passages. Crucially, ",
    { text: "only the LLM component differs between experimental conditions", italics: true },
    "\u2014all retrieval, fusion, and reranking stages remain identical, ensuring a controlled comparison.",
  ], { after: 30 }),
];

// III. EXPERIMENTS
const expContent = [
  sectionHead("III. Experiments"),
  p([
    { text: "Setup. ", bold: true },
    "We curated 100 questions across five types (20 each): VERSE_LOOKUP, TOPIC, PERSON, EVENT, and GENERAL. We compare Claude Haiku 4.5 [7] (commercial API) against Gemma 3 4B [6] (local Ollama deployment), sharing an identical retrieval pipeline (temperature = 0.1, top_k = 5). We employ 19 metrics in four categories: 7 retrieval (hit rate, MRR, NDCG@5, MAP@5, precision/recall/F1@k), 4 reference-based (BLEU [12], ROUGE-1/2/L), 2 semantic (BERTScore [11], embedding cosine similarity), and 6 LLM-judged via RAGAS [5] (faithfulness, answer relevancy, context precision/recall, answer correctness, answer point coverage).",
  ], { after: 20 }),

  // Retrieval metrics inline
  p([
    { text: "Retrieval results. ", bold: true },
    "All 7 retrieval metrics are identical between models, confirming experimental control: hit rate = 0.920, MRR = 0.800, NDCG@5 = 0.835, MAP@5 = 0.758, precision@k = 0.342, recall@k = 0.846, F1@k = 0.454.",
  ], { after: 20 }),

  // Table I caption
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 20, after: 20, line: 200 },
    children: [new TextRun({ text: "TABLE I", font: FONT, size: PT8, bold: true })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 0, after: 20, line: 200 },
    children: [new TextRun({ text: "Generation Metric Comparison (All 12 Metrics)", font: FONT, size: PT8 })],
  }),

  // Table I — all 12 generation metrics
  new Table({
    width: { size: T1_COLS.reduce((a, b) => a + b, 0), type: WidthType.DXA },
    columnWidths: T1_COLS,
    rows: [
      t1Row("Category", "Metric", "Claude", "Gemma", "\u0394", { borders: topBottomBorders, headerBold: true }),
      // Semantic (2)
      t1Row("Semantic", "BERTScore", "0.6531", "0.6520", "\u22120.0011", { catItalics: true }),
      t1Row("", "Sem. Similarity", "0.7690", "0.7684", "\u22120.0006", { borders: bottomOnlyBorders }),
      // Ref-based (4)
      t1Row("Ref-based", "BLEU", "0.0278", "0.0285", "+0.0007", { catItalics: true }),
      t1Row("", "ROUGE-1", "0.0176", "0.0153", "\u22120.0023"),
      t1Row("", "ROUGE-2", "0.0039", "0.0052", "+0.0013"),
      t1Row("", "ROUGE-L", "0.0176", "0.0153", "\u22120.0023", { borders: bottomOnlyBorders }),
      // LLM Judge (6)
      t1Row("LLM Judge", "Faithfulness", "0.6065", "0.6072", "+0.0007", { catItalics: true }),
      t1Row("", "Ans. Relevancy", "0.7273", "0.7331", "+0.0058"),
      t1Row("", "Ctx. Precision", "0.5671", "0.5687", "+0.0016"),
      t1Row("", "Ctx. Recall", "0.7210", "0.7267", "+0.0057"),
      t1Row("", "Ans. Correctness", "0.5215", "0.5220", "+0.0005"),
      t1Row("", "Ans. Pt. Coverage", "0.5065", "0.4967", "\u22120.0098", { borders: bottomOnlyBorders }),
    ],
  }),

  // Note under Table I
  p([{
    text: "Note: \u0394 = Gemma \u2212 Claude. Positive values indicate Gemma advantage.",
    italics: true, size: PT7,
  }], { after: 30, size: PT7, line: 200 }),
];

// IV. RESULTS AND DISCUSSION — v4: deepened analysis
const resultsContent = [
  sectionHead("IV. Results and Discussion"),

  subHead("A. RAG Equalizes Model Differences"),
  p([
    "Table I presents the central finding: ",
    { text: "all 12 generation metrics differ by less than 1%", bold: true },
    ". The maximum absolute delta is 0.0098 (answer point coverage). Of the 12 metrics, Gemma leads on 7 while Claude leads on 5. The bidirectional distribution of advantages confirms stochastic fluctuations rather than systematic model superiority.",
  ], { after: 20 }),
  // v4: theoretical explanation paragraph
  p([
    "This convergence has a mechanistic explanation. With retrieval NDCG@5 = 0.835, the top-ranked passages already contain the answer evidence, reducing the LLM\u2019s task from open-ended knowledge recall to ",
    { text: "evidence-grounded paraphrasing", italics: true },
    "\u2014a capability well within the reach of a 4B-parameter model. When the retrieval system supplies sufficiently precise context, additional model parameters contribute diminishing returns, as the generation bottleneck shifts from knowledge capacity to surface-level synthesis. A free, locally deployed 4B model is thus functionally indistinguishable from a commercial API.",
  ], { after: 30 }),

  subHead("B. Retrieval Quality Determines Answer Quality"),
  p([
    "Table II reveals a clear relationship between retrieval and generation quality across question types.",
  ], { after: 15 }),

  // Table II caption
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 15, after: 20, line: 200 },
    children: [new TextRun({ text: "TABLE II", font: FONT, size: PT8, bold: true })],
  }),
  new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { before: 0, after: 20, line: 200 },
    children: [new TextRun({ text: "Per-Type Retrieval and Generation Quality", font: FONT, size: PT8 })],
  }),

  // Table II
  new Table({
    width: { size: T2_COLS.reduce((a, b) => a + b, 0), type: WidthType.DXA },
    columnWidths: T2_COLS,
    rows: [
      t2Row("Type", "Hit Rate", "NDCG@5", "Cl. APC", "Ge. APC", { borders: topBottomBorders, headerBold: true }),
      t2Row("VERSE_LOOKUP", "1.000", "1.000", "0.958", "0.975"),
      t2Row("TOPIC", "1.000", "0.983", "0.629", "0.592"),
      t2Row("PERSON", "1.000", "0.927", "0.303", "0.287"),
      t2Row("EVENT", "0.750", "0.548", "0.298", "0.340"),
      t2Row("GENERAL", "0.850", "0.715", "0.343", "0.290", { borders: bottomOnlyBorders }),
    ],
  }),

  // Per-type analysis — v4: added PERSON anomaly explanation
  p([
    "VERSE_LOOKUP achieves perfect retrieval (hit rate = 1.0, NDCG@5 = 1.0) via PostgreSQL exact match, yielding the highest APC (0.958/0.975). TOPIC questions also achieve perfect hit rate with high NDCG (0.983), producing strong APC (0.629/0.592). EVENT questions exhibit the lowest retrieval quality (hit rate = 0.750, NDCG@5 = 0.548)\u2014event narratives span multiple chapters, challenging fixed-window chunking.",
  ], { before: 15, after: 15 }),
  // v4: PERSON anomaly mechanism explanation
  p([
    "PERSON questions present an instructive anomaly: despite perfect hit rate and high NDCG (0.927), APC remains low (0.303/0.287). The Neo4j MENTIONS relationship achieves broad recall (F1@k = 0.778) by retrieving all passages mentioning an entity, but this breadth introduces noise\u2014passages that mention a person incidentally rather than substantively. High NDCG reflects the presence of relevant passages in the top-k, while low APC indicates the LLM must filter through peripherally related context, diluting answer precision. This ",
    { text: "breadth-versus-precision tradeoff", italics: true },
    " confirms that retrieval infrastructure, not model capability, remains the performance bottleneck.",
  ], { after: 30 }),

  subHead("C. Metric Selection for RAG Evaluation"),
  p([
    "ROUGE-1/2/L scores are extremely low (<0.03), reflecting the paraphrased nature of Traditional Chinese answers rather than failure. Semantic similarity (0.769) and BERTScore (0.653) better capture answer quality by measuring meaning preservation over lexical overlap. Among LLM-judged metrics, answer relevancy (0.73) and context recall (0.72) best differentiate question types. We recommend prioritizing semantic and LLM-judged metrics over n-gram metrics for cross-lingual or generative RAG systems.",
  ]),
];

// V. CONCLUSION — v4: expanded with broader impact
const conclusionContent = [
  sectionHead("V. Conclusion"),
  p([
    "We designed, deployed, and evaluated a multi-strategy Graph RAG architecture for Traditional Chinese Bible question answering. A controlled experiment comparing Gemma 3 4B (local deployment) against Claude Haiku 4.5 (commercial API) demonstrates that all 12 generation metrics differ by less than 1% (max |\u0394| = 0.0098) when retrieval conditions are identical. Per-type analysis reveals that retrieval quality\u2014not model scale\u2014is the primary determinant of answer quality, and identifies a breadth-versus-precision tradeoff in graph-based entity retrieval.",
  ], { after: 15 }),
  p([
    "These results carry implications beyond biblical studies. Any domain where LLM pre-training provides insufficient coverage\u2014legal codes, medical guidelines, indigenous-language archives\u2014can benefit from the same RAG-as-equalizer paradigm: invest in retrieval infrastructure rather than larger models. Future work includes hybrid dense-sparse retrieval for improved recall on event narratives, adaptive chunking for multi-chapter passages, and multilingual evaluation across Bible translations.",
  ]),
];

// REFERENCES
function ref(num, text) {
  return p([
    { text: `[${num}] `, bold: false, size: PT7 },
    { text, size: PT7 },
  ], { after: 8, line: 192, size: PT7, indent: { left: 280, hanging: 280 } });
}

const referencesContent = [
  sectionHead("References"),
  ref(1, 'P. Lewis et al., "Retrieval-augmented generation for knowledge-intensive NLP tasks," in Proc. NeurIPS, 2020.'),
  ref(2, 'D. Edge et al., "From local to global: A graph RAG approach to query-focused summarization," arXiv:2404.16130, 2024.'),
  ref(3, 'Y. Gao et al., "Retrieval-augmented generation for large language models: A survey," arXiv:2312.10997, 2024.'),
  ref(4, 'J. Chen et al., "BGE M3-embedding: Multi-lingual, multi-functionality, multi-granularity text embeddings through self-knowledge distillation," arXiv:2402.03216, 2024.'),
  ref(5, 'S. Es et al., "RAGAS: Automated evaluation of retrieval augmented generation," arXiv:2309.15217, 2024.'),
  ref(6, 'Google DeepMind, "Gemma 3 technical report," arXiv:2503.19786, 2025.'),
  ref(7, 'Anthropic, "The Claude model family," 2024.'),
  ref(8, 'W.-Y. Ma and K.-J. Chen, "CKIP Transformers: An NLP toolkit for traditional Chinese," in Proc. ROCLING, 2021.'),
  ref(9, 'V. Karpukhin et al., "Dense passage retrieval for open-domain question answering," in Proc. EMNLP, 2020.'),
  ref(10, 'S. Robertson and H. Zaragoza, "The probabilistic relevance framework: BM25 and beyond," Found. Trends Inf. Retr., vol. 3, no. 4, pp. 333\u2013389, 2009.'),
  ref(11, 'T. Zhang et al., "BERTScore: Evaluating text generation with BERT," in Proc. ICLR, 2020.'),
  ref(12, 'K. Papineni et al., "BLEU: A method for automatic evaluation of machine translation," in Proc. ACL, 2002.'),
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
  const outPath = "paper_v4.docx";
  fs.writeFileSync(outPath, buffer);
  console.log(`Generated ${outPath} (${buffer.length} bytes)`);
});
