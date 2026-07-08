# Comprehensive Guide to RAG Evaluation Methodology

> **性質**：設計期研究筆記（2026-02）— 通用 RAG 評估方法論參考，非本專案現況文檔。本專案實際採用的 13 項指標與用法見 [../../evaluation/README.md](../../evaluation/README.md)，現行評估框架見 [../ARCHITECTURE.md](../ARCHITECTURE.md) §8；文中 BLEU／ROUGE／METEOR／Perplexity 等章節未被本專案採用。

## Table of Contents
1. [RAG Evaluation Overview](#overview)
2. [Retrieval Metrics](#retrieval-metrics)
3. [Generation Metrics](#generation-metrics)
4. [Context Metrics](#context-metrics)
5. [End-to-End Metrics](#end-to-end-metrics)
6. [LLM-as-Judge Methodology](#llm-as-judge)
7. [Practical Implementation](#implementation)

---

## 1. RAG Evaluation Overview {#overview}

RAG (Retrieval-Augmented Generation) systems consist of two critical components:

```
Query → [RETRIEVER] → Retrieved Context → [GENERATOR] → Final Response
          ↓                                      ↓
    Retrieval Metrics               Generation Metrics
```

**Key Principle**: The quality of RAG output is a **product, not a sum**. If either retriever or generator fails, overall quality drops to zero regardless of how well the other performs.

### Evaluation Categories

RAG evaluation metrics fall into distinct categories:

| Category | What It Evaluates | When Available | Example Metrics |
|----------|-------------------|----------------|-----------------|
| **Retrieval** | Quality of documents retrieved | Always | Precision@k, Recall@k, NDCG |
| **Generation** | Quality of LLM output | Always | Faithfulness, Answer Relevancy |
| **Context** | Quality of context used | Always | Context Precision, Context Recall |
| **End-to-End** | Complete pipeline performance | With ground truth | Correctness, Semantic Similarity |

### Ground Truth Requirements

- **With ground truth**: Can use reference-based metrics (BLEU, ROUGE, exact match)
- **Without ground truth**: Must use reference-free metrics (faithfulness, relevancy, hallucination detection)

---

## 2. Retrieval Metrics {#retrieval-metrics}

Retrieval metrics evaluate how well your retriever identifies and ranks relevant documents.

### 2.1 Order-Unaware Metrics

These metrics only care about **whether** relevant documents are retrieved, not their ranking position.

#### Precision@k

**What it measures**: Among the top k retrieved documents, what fraction are relevant?

**Formula**:
```
Precision@k = (# of relevant documents in top k) / k
```

**Example**:
```python
# Retrieved 5 documents, relevance labels: [True, False, True, False, False]
Precision@5 = 2/5 = 0.4
```

**When to use**: 
- When you have limited context window and must ensure high-quality retrieved documents
- When cost of irrelevant documents is high
- Good for systems where every retrieved document is shown to users

**Interpretation**: Precision@5 = 0.8 means 80% of retrieved documents are relevant.

---

#### Recall@k

**What it measures**: Among all relevant documents that exist, what fraction did we retrieve in top k?

**Formula**:
```
Recall@k = (# of relevant documents in top k) / (total # of relevant documents)
```

**Example**:
```python
# Top 5 retrieved: 2 relevant documents
# Total relevant documents in dataset: 4
Recall@5 = 2/4 = 0.5
```

**When to use**:
- When missing relevant information is costly
- For comprehensive retrieval where you want high coverage
- Medical/legal domains where completeness matters

**Interpretation**: Recall@5 = 0.5 means we found 50% of all relevant documents.

---

#### F1@k Score

**What it measures**: Harmonic mean of Precision@k and Recall@k, balancing both metrics.

**Formula**:
```
F1@k = 2 × (Precision@k × Recall@k) / (Precision@k + Recall@k)
```

**When to use**: When you need balance between precision and recall.

**Important**: Harmonic mean heavily penalizes if either precision or recall is low.

---

### 2.2 Order-Aware Metrics

These metrics reward systems that rank more relevant documents higher in the result list.

#### Mean Reciprocal Rank (MRR)

**What it measures**: Average position of the **first** relevant document across queries.

**Formula**:
```
RR (single query) = 1 / (rank of first relevant document)
MRR = average of RR across all queries
```

**Example**:
```python
Query 1: First relevant at rank 2 → RR = 1/2 = 0.5
Query 2: First relevant at rank 1 → RR = 1/1 = 1.0
Query 3: First relevant at rank 3 → RR = 1/3 = 0.333

MRR = (0.5 + 1.0 + 0.333) / 3 = 0.611
```

**When to use**:
- Question-answering where typically one correct answer exists
- Search engines where first result quality matters most
- "I'm Feeling Lucky" type scenarios

**Interpretation**: 
- MRR = 1.0: First result is always relevant
- MRR = 0.5: On average, first relevant result appears at rank 2
- **Very interpretable**: Tells you expected rank of first hit

**Limitation**: Ignores all documents after the first relevant one.

---

#### Mean Average Precision (MAP@k)

**What it measures**: Average of precision values at each relevant document position.

**Formula**:
```
AP@k for single query = (Σ Precision@i × rel(i)) / (# of relevant docs)

where:
- i = rank position (1 to k)
- rel(i) = 1 if document at position i is relevant, 0 otherwise
- Precision@i = precision computed at position i

MAP@k = mean of AP@k across all queries
```

**Step-by-step calculation example**:

```python
Retrieved documents: [R, NR, R, R, NR]  # R=Relevant, NR=Not Relevant
k = 5
Total relevant = 3

Position 1: R  → Precision@1 = 1/1 = 1.0
Position 2: NR → skip (not relevant)
Position 3: R  → Precision@3 = 2/3 = 0.667
Position 4: R  → Precision@4 = 3/4 = 0.75
Position 5: NR → skip

AP@5 = (1.0 + 0.667 + 0.75) / 3 = 0.806
```

**When to use**:
- Recommendation systems
- When you care about ranking quality across all relevant items
- Binary relevance (document is either relevant or not)

**Interpretation**: 
- MAP@k = 0.2 means on average, correct answers appear within top 5 positions
- Considers both presence and position of all relevant documents

**Key advantage over MRR**: Accounts for all relevant documents, not just the first one.

---

#### Normalized Discounted Cumulative Gain (NDCG@k)

**What it measures**: Ranking quality accounting for **graded relevance** (not just binary).

**Why "Normalized Discounted Cumulative Gain"?**
1. **Gain**: Relevance score of each document
2. **Cumulative**: Sum across multiple documents  
3. **Discounted**: Relevance value decreases based on position (logarithmic decay)
4. **Normalized**: Divided by ideal ranking to get 0-1 scale

**Formula**:

```
DCG@k = Σ(i=1 to k) (rel_i / log₂(i + 1))

where:
- rel_i = relevance score at position i
- log₂(i + 1) = discount factor

IDCG@k = DCG@k for the ideal ranking (best possible order)

NDCG@k = DCG@k / IDCG@k
```

**Detailed example with graded relevance**:

```python
# Relevance scale: 0 (not relevant) to 3 (highly relevant)
Retrieved docs: [3, 2, 3, 0, 1, 2]
k = 5

# Calculate DCG@5
Position 1: 3 / log₂(2) = 3 / 1.0 = 3.0
Position 2: 2 / log₂(3) = 2 / 1.585 = 1.262
Position 3: 3 / log₂(4) = 3 / 2.0 = 1.5
Position 4: 0 / log₂(5) = 0 / 2.322 = 0.0
Position 5: 1 / log₂(6) = 1 / 2.585 = 0.387

DCG@5 = 3.0 + 1.262 + 1.5 + 0.0 + 0.387 = 6.149

# Calculate IDCG@5 (ideal ranking: [3, 3, 2, 2, 1])
Position 1: 3 / log₂(2) = 3.0
Position 2: 3 / log₂(3) = 1.893
Position 3: 2 / log₂(4) = 1.0
Position 4: 2 / log₂(5) = 0.861
Position 5: 1 / log₂(6) = 0.387

IDCG@5 = 3.0 + 1.893 + 1.0 + 0.861 + 0.387 = 7.141

NDCG@5 = 6.149 / 7.141 = 0.861
```

**When to use**:
- **Multi-level relevance**: Documents have varying degrees of relevance (not just yes/no)
- Search engines, recommendation systems
- **RAG systems**: Where you need multiple documents with different importance levels
- When position in ranking is critical

**Key advantages**:
- Handles graded relevance (unlike MAP which is binary)
- Normalized to [0, 1] for easy comparison
- Heavily used in information retrieval research
- Default metric in MTEB Leaderboard for retrieval

**Interpretation**: 
- NDCG@5 = 1.0: Perfect ranking
- NDCG@5 = 0.861: Ranking is 86.1% as good as ideal ordering

---

### 2.3 Hit Rate

**What it measures**: Percentage of queries that have at least one relevant document in top k.

**Formula**:
```
Hit Rate@k = (# of queries with ≥1 relevant doc in top k) / (total # of queries)
```

**Example**:
```python
10 queries total
7 queries have at least 1 relevant doc in top 5
Hit Rate@5 = 7/10 = 0.7
```

**When to use**: Simple binary success metric - did we find anything relevant?

---

### Retrieval Metrics Comparison Table

| Metric | Order-Aware? | Graded Relevance? | Focus | Best For |
|--------|--------------|-------------------|-------|----------|
| Precision@k | No | No | Accuracy | Limited context windows |
| Recall@k | No | No | Coverage | Comprehensive retrieval |
| F1@k | No | No | Balance | Balanced precision/recall |
| MRR | Yes | No | First hit | Single answer QA |
| MAP@k | Yes | No | All relevant positions | Binary relevance ranking |
| NDCG@k | Yes | Yes | Weighted ranking | Multi-level relevance |
| Hit Rate | No | No | Any success | Basic success rate |

---

## 3. Generation Metrics {#generation-metrics}

Generation metrics evaluate the quality of text produced by the LLM based on retrieved context.

### 3.1 Reference-Based Metrics

These metrics **require ground truth answers** for comparison.

#### BLEU (Bilingual Evaluation Understudy)

**What it measures**: N-gram overlap between generated and reference text, focusing on **precision**.

**Formula**:
```
BLEU = BP × exp(Σ(n=1 to N) wₙ log pₙ)

where:
- pₙ = modified n-gram precision
- wₙ = weight for n-gram (usually 1/N for uniform weighting)
- BP = brevity penalty (penalizes short outputs)
```

**When to use**: 
- Machine translation tasks
- When exact word matching is important
- Less suitable for RAG (too focused on exact matches)

**Limitation**: Doesn't capture semantic similarity, only lexical overlap.

---

#### ROUGE (Recall-Oriented Understudy for Gisting Evaluation)

**What it measures**: N-gram overlap focusing on **recall** (coverage of reference text).

**Variants**:
- **ROUGE-N**: N-gram overlap (ROUGE-1, ROUGE-2)
- **ROUGE-L**: Longest common subsequence
- **ROUGE-W**: Weighted longest common subsequence

**Formula for ROUGE-N**:
```
ROUGE-N = Σ(n-grams in reference) Count_match(n-gram) / Σ(n-grams in reference) Count(n-gram)
```

**When to use**:
- Summarization tasks
- When coverage of reference content matters
- Evaluating whether key information is captured

---

#### METEOR (Metric for Evaluation of Translation with Explicit ORdering)

**What it measures**: N-gram overlap considering synonyms, stemming, and word order.

**Advantages over BLEU/ROUGE**:
- Considers synonyms and paraphrases
- Better correlation with human judgment
- Accounts for word order

**When to use**: When semantic equivalence matters more than exact word match.

---

#### BERTScore

**What it measures**: Semantic similarity using contextual embeddings from BERT.

**How it works**:
1. Generate BERT embeddings for each token in generated and reference text
2. Compute cosine similarity between token embeddings
3. Use greedy matching to align tokens
4. Aggregate to get precision, recall, F1

**Formula**:
```
BERTScore = F1 of matched token embeddings using cosine similarity
```

**When to use**:
- **Modern alternative to BLEU/ROUGE**
- Captures semantic similarity even with different wording
- **Highly recommended for RAG evaluation** when ground truth exists

**Example**:
```
Generated: "The dog is sleeping"
Reference: "The canine is resting"

BLEU: Low score (different words)
BERTScore: High score (semantically similar)
```

---

### 3.2 Reference-Free Metrics (RAG-Specific)

These metrics **don't require ground truth** - essential for production RAG systems.

#### Faithfulness (No Hallucination)

**What it measures**: Whether the generated answer is factually grounded in the retrieved context.

**Core concept**: Every claim in the answer should be supported by the context.

**Calculation methodology**:

**Method 1: Claim-based approach (used by RAGAS)**

```python
1. Extract individual claims from generated answer using LLM
   Answer: "Python was created in 1991 by Guido van Rossum"
   Claims: ["Python was created in 1991", "Python was created by Guido van Rossum"]

2. For each claim, verify if it's supported by context using LLM
   
3. Faithfulness = (# of supported claims) / (total # of claims)
```

**Method 2: NLI-based approach**

```python
1. Break answer into statements
2. For each statement, use NLI (Natural Language Inference) model
3. Check if context entails, contradicts, or is neutral to statement
4. Faithfulness = (# of entailed statements) / (total statements)
```

**Implementation example**:
```python
from ragas.metrics import faithfulness
from ragas import evaluate

# LLM extracts claims and verifies against context
faithfulness_score = faithfulness.score(
    contexts=[retrieved_context],
    answer=generated_answer
)
```

**When to use**: **Always** in RAG systems - core metric to prevent hallucinations.

**Interpretation**:
- Faithfulness = 1.0: All claims supported by context
- Faithfulness = 0.7: 30% of claims are hallucinated
- **Recommended threshold**: ≥ 0.85 for production systems (≥ 0.90 for critical domains)

---

#### Answer Relevancy

**What it measures**: How well the answer addresses the original question.

**Core concept**: An answer can be factually correct but still irrelevant to the question.

**Calculation methodology**:

```python
1. Generate questions that the answer would appropriately address (using LLM)
   Original Question: "What is the capital of France?"
   Generated questions from answer: 
   - "What is the capital of France?"
   - "Which city is France's capital?"
   
2. Compute semantic similarity between:
   - Original question
   - Each generated question
   
3. Answer Relevancy = mean similarity score
```

**Alternative approach**:
```python
# Direct LLM evaluation
relevancy = LLM evaluates: 
  "On a scale 0-1, how well does this answer address the question?"
```

**When to use**:
- Prevent verbose, off-topic, or tangential answers
- Ensure conciseness and directness
- Complement to faithfulness (can be faithful but irrelevant)

**Example of low relevancy**:
```
Question: "What is the capital of France?"
Answer: "France is a country in Europe with a rich history. Paris is one of its major cities and serves as the capital. The country is known for wine and cheese."

Faithfulness: High (all true)
Relevancy: Low (verbose, includes unnecessary information)
```

---

#### Answer Correctness

**What it measures**: Combined factual and semantic correctness when ground truth is available.

**Formula**:
```
Answer Correctness = w₁ × Factual Similarity + w₂ × Semantic Similarity

where:
- Factual Similarity: F1 score of fact overlap (LLM-extracted facts)
- Semantic Similarity: Cosine similarity of embeddings
- w₁, w₂: Weights (typically 0.5 each)
```

**When to use**: When you have ground truth and want comprehensive evaluation.

---

#### Answer Semantic Similarity

**What it measures**: Semantic closeness between generated and reference answer using embeddings.

**Calculation**:
```python
1. Embed generated answer: E_gen
2. Embed reference answer: E_ref
3. Similarity = cosine_similarity(E_gen, E_ref)
```

**When to use**: 
- When semantic equivalence matters more than exact wording
- Faster alternative to BERTScore
- Good for approximate correctness checking

---

#### Hallucination Rate

**What it measures**: Proportion of generated content that contradicts or is unsupported by context.

**Formula**:
```
Hallucination Rate = 1 - Faithfulness
```

**Advanced calculation**:
```python
# Using LLM to detect contradictions
1. Extract claims from answer
2. For each claim, classify as:
   - Supported by context
   - Contradicted by context  
   - Not mentioned in context (unsupported)
   
3. Hallucination Rate = (contradicted + unsupported) / total claims
```

**When to use**: 
- Critical safety applications
- Healthcare, legal, financial domains
- When cost of misinformation is high

**Specialized tools**:
- **Vectara HHEM**: Hughes Hallucination Evaluation Model
- **FaithJudge**: LLM-as-judge with few-shot examples
- **TLM (Trustworthy Language Model)**: Real-time evaluation model
- **Patronus Lynx**: Specialized hallucination detector

---

### 3.3 Traditional NLG Metrics

#### Perplexity

**What it measures**: How "surprised" the model is by the generated text (lower = more confident).

**Formula**:
```
Perplexity = exp(-1/N × Σ log P(word_i))
```

**When to use**: 
- Model confidence assessment
- Comparing different generation approaches
- Less useful for RAG evaluation (doesn't measure correctness)

---

#### Coherence

**What it measures**: Logical flow and consistency of generated text.

**Calculation**: Typically LLM-as-judge evaluation.

**When to use**: Long-form content generation, narrative tasks.

---

## 4. Context Metrics {#context-metrics}

Context metrics evaluate the quality of the **retrieval context** before it reaches the generator.

### 4.1 Context Precision

**What it measures**: Are relevant nodes ranked higher than irrelevant ones in the retrieved context?

**Purpose**: Evaluates the **reranker** effectiveness.

**Calculation methodology**:

```python
1. For each context chunk, determine if it's relevant to ground truth answer (using LLM)

2. Calculate precision at each position where relevant chunk appears

3. Average the precision values

Context Precision = Σ(Precision@k for each relevant position) / # relevant chunks
```

**Example**:
```python
Retrieved context: [Relevant, Irrelevant, Relevant, Relevant, Irrelevant]
Ground truth exists in positions 1, 3, 4

Precision@1: 1/1 = 1.0
Precision@3: 2/3 = 0.667
Precision@4: 3/4 = 0.75

Context Precision = (1.0 + 0.667 + 0.75) / 3 = 0.806
```

**When to use**:
- Evaluating reranking algorithms
- When LLM has limited context window
- Optimizing token efficiency

**What it tells you**: Higher precision means less noise in context, reducing hallucination risk.

---

### 4.2 Context Recall

**What it measures**: Does the retrieved context contain all information needed to answer the question?

**Purpose**: Evaluates the **embedding model** and retrieval coverage.

**Calculation methodology**:

```python
1. Extract key facts from ground truth answer (using LLM)

2. For each fact, check if it can be attributed to retrieved context (using LLM)

3. Context Recall = (# facts found in context) / (total # facts in ground truth)
```

**Example**:
```python
Ground truth: "Paris is the capital of France and was founded in 3rd century BC"
Facts: ["Paris is capital of France", "Paris founded in 3rd century BC"]

Retrieved context mentions: "Paris is France's capital" 
But doesn't mention founding date

Context Recall = 1/2 = 0.5
```

**When to use**:
- Ensuring comprehensive information retrieval
- Medical/legal domains where completeness is critical
- Optimizing chunk size and retrieval parameters

**What it tells you**: Low recall means missing information, even if what you retrieved is accurate.

---

### 4.3 Context Relevancy

**What it measures**: Overall relevance of retrieved context to the user query.

**Calculation methodology**:

```python
1. For each sentence in retrieved context, classify as:
   - Relevant to question
   - Irrelevant to question
   
2. Context Relevancy = (# relevant sentences) / (total # sentences)
```

**Alternative approach**:
```python
# LLM-as-judge evaluation
relevancy_score = LLM rates: "How relevant is this context to answering the question?"
```

**When to use**:
- Evaluating retrieval quality before generation
- Optimizing embedding models and retrieval strategies
- Reducing noise in context

---

### 4.4 Context Utilization

**What it measures**: How much of the retrieved context was actually used in the answer.

**When to use**: Detecting over-retrieval or redundant context.

---

## 5. End-to-End Metrics {#end-to-end-metrics}

End-to-end metrics evaluate the complete RAG pipeline as a black box.

### 5.1 Component Interaction

```
Input Query
    ↓
[Retriever] ← Context Precision/Recall/Relevancy
    ↓
Retrieved Context
    ↓
[Generator] ← Faithfulness, Answer Relevancy
    ↓
Final Answer
    ↓
[Evaluation] ← Answer Correctness, Semantic Similarity
```

### 5.2 Key Principles

1. **Use both component-level AND end-to-end metrics**
   - Component metrics: Debug specific failures
   - End-to-end metrics: Measure overall performance

2. **Balance multiple metrics**
   - No single metric tells complete story
   - Combine retrieval + generation + end-to-end

3. **Adapt to your use case**
   - QA systems: Emphasize correctness, faithfulness
   - Summarization: Emphasize coherence, coverage
   - Chatbots: Emphasize relevancy, engagement

---

## 6. LLM-as-Judge Methodology {#llm-as-judge}

**LLM-as-Judge** uses one LLM to evaluate another LLM's outputs - the current state-of-the-art for RAG evaluation.

### 6.1 Why LLM-as-Judge?

**Traditional metrics limitations**:
- BLEU/ROUGE: Only measure lexical overlap, miss semantic similarity
- Can't evaluate nuanced qualities like relevance, faithfulness
- Don't capture human judgment well

**LLM-as-judge advantages**:
- Evaluates semantic meaning, not just words
- Can assess complex criteria (coherence, relevance, factuality)
- Scales better than human evaluation
- Higher correlation with human judgment than traditional metrics

### 6.2 Core Approaches

#### Approach 1: Pointwise Scoring (G-Eval)

**How it works**: LLM assigns numerical score based on detailed rubric.

```python
prompt = f"""
Given the following:
- Question: {question}
- Context: {context}
- Answer: {answer}

Evaluate the answer's faithfulness to the context on a scale of 1-5:

1: Highly unfaithful (major contradictions or hallucinations)
2: Somewhat unfaithful (several unsupported claims)
3: Moderately faithful (some unsupported claims)
4: Mostly faithful (minor issues)
5: Completely faithful (all claims supported)

Provide reasoning and score.
"""

response = llm.generate(prompt)
# Parse score from response
```

**Key techniques for G-Eval**:

1. **Chain-of-Thought (CoT)**: Ask LLM to explain reasoning before scoring
2. **Detailed rubrics**: Provide clear criteria for each score level
3. **Few-shot examples**: Include 2-5 annotated examples in prompt
4. **Multiple evaluations**: Run multiple times, aggregate scores (reduces variance)

---

#### Approach 2: Pairwise Comparison

**How it works**: LLM compares two answers and picks the better one.

```python
prompt = f"""
Which answer is better for the question "{question}"?

Answer A: {answer_a}
Answer B: {answer_b}

Consider: factual accuracy, relevance, completeness.
Choose: A, B, or Tie
"""
```

**When to use**: A/B testing different RAG configurations.

---

#### Approach 3: Reference-Free Verification

**How it works**: LLM verifies claims without needing ground truth.

```python
# Step 1: Extract claims
claims = llm.generate(f"Extract factual claims from: {answer}")

# Step 2: Verify each claim
for claim in claims:
    verification = llm.generate(f"""
    Claim: {claim}
    Context: {context}
    
    Is this claim supported by the context?
    Answer: Yes/No with explanation
    """)
```

---

### 6.3 Advanced Techniques

#### FaithJudge Approach (State-of-the-Art for Hallucination Detection)

**Key innovation**: Few-shot prompting with diverse human-annotated hallucination examples.

```python
# Build example pool from annotated data
few_shot_examples = [
    {
        "context": "...",
        "answer": "...",
        "hallucinations": ["specific claim X is unsupported", ...],
        "verdict": "Unfaithful"
    },
    # 5-10 diverse examples
]

# Evaluation prompt
prompt = f"""
Here are examples of hallucination detection:

{few_shot_examples}

Now evaluate this:
Context: {context}
Answer: {answer}

Identify any hallucinations and provide verdict.
"""
```

**Results**: FaithJudge achieves much higher agreement with human judgments than zero-shot or fine-tuned models.

---

#### Structured Output

**Technique**: Force LLM to respond in structured JSON format.

```python
from pydantic import BaseModel

class FaithfulnessEvaluation(BaseModel):
    claims_extracted: List[str]
    claims_supported: List[bool]
    hallucinations: List[str]
    score: float
    reasoning: str

# Use with function calling or JSON mode
evaluation = llm.generate(
    prompt,
    response_format=FaithfulnessEvaluation
)
```

**Benefits**:
- Easier parsing
- Consistent output format
- Forces structured thinking

---

### 6.4 Best Practices for LLM-as-Judge

1. **Choice of judge LLM**:
   - GPT-4, Claude 3.5 Sonnet, Gemini 1.5 Pro: High quality, expensive
   - GPT-4o-mini, Claude 3 Haiku: Good balance of cost/quality
   - Specialized models: Patronus Lynx (hallucination), FaithLens (faithfulness)

2. **Prompt engineering**:
   ```python
   # BAD: Vague prompt
   "Is this answer good?"
   
   # GOOD: Specific criteria
   """
   Evaluate faithfulness by:
   1. Extracting factual claims
   2. Verifying each against context
   3. Counting unsupported claims
   4. Scoring as (supported claims)/(total claims)
   """
   ```

3. **Temperature settings**:
   - Use **temperature = 0** for consistency
   - For multiple evaluations, run 3-5 times and aggregate

4. **Calibration**:
   - Validate against human judgments on small sample
   - Adjust prompts if systematic biases detected
   - Monitor agreement rates

5. **Cost optimization**:
   - Use cheaper models for initial filtering
   - Use expensive models for final evaluation
   - Batch requests when possible

---

### 6.5 LLM-as-Judge Limitations

**1. Positional bias**: Tends to prefer first option in pairwise comparison
   - **Mitigation**: Randomize order, run both permutations

**2. Verbosity bias**: May prefer longer answers
   - **Mitigation**: Explicitly instruct to focus on quality over length

**3. Self-preference**: Model may favor its own outputs
   - **Mitigation**: Use different model as judge

**4. Limited detection of subtle hallucinations**:
   - Even best models achieve ~50-80% accuracy on hard cases
   - **Mitigation**: Combine with specialized hallucination detectors

**5. Cost**: Can be expensive at scale
   - **Mitigation**: Cache evaluations, use tiered approach

---

## 7. Practical Implementation {#implementation}

### 7.1 Complete Evaluation Pipeline

```python
from ragas import evaluate
from ragas.metrics import (
    faithfulness,
    answer_relevancy,
    context_precision,
    context_recall,
    answer_correctness
)
from deepeval.metrics import FaithfulnessMetric, AnswerRelevancyMetric
from llama_index.core.evaluation import RetrieverEvaluator

# Step 1: Retrieval evaluation
retrieval_metrics = RetrieverEvaluator.from_metric_names(
    ["hit_rate", "mrr", "ndcg"],
    retriever=your_retriever
)

# Step 2: Context evaluation
context_eval_results = evaluate(
    dataset=eval_dataset,
    metrics=[context_precision, context_recall],
    llm=evaluator_llm
)

# Step 3: Generation evaluation (without ground truth)
generation_eval = evaluate(
    dataset=eval_dataset,
    metrics=[faithfulness, answer_relevancy],
    llm=evaluator_llm
)

# Step 4: End-to-end (with ground truth)
e2e_eval = evaluate(
    dataset=eval_dataset_with_ground_truth,
    metrics=[answer_correctness],
    llm=evaluator_llm
)
```

---

### 7.2 Evaluation Dataset Construction

**Option 1: Manual curation**
```python
eval_dataset = [
    {
        "question": "What is the capital of France?",
        "contexts": ["Paris is the capital and largest city of France..."],
        "answer": "The capital of France is Paris.",
        "ground_truth": "Paris"
    },
    # 50-200 examples minimum
]
```

**Option 2: Synthetic generation**
```python
from ragas.testset.generator import TestsetGenerator
from ragas.testset.evolutions import simple, reasoning, multi_context

# Generate test cases from your documents
generator = TestsetGenerator.from_langchain(
    generator_llm,
    critic_llm,
    embeddings
)

testset = generator.generate_with_langchain_docs(
    documents,
    test_size=100,
    distributions={
        simple: 0.5,
        reasoning: 0.25,
        multi_context: 0.25
    }
)
```

---

### 7.3 Evaluation Frequency

**Development phase**:
- Run full eval suite on every major change
- Track metrics over time
- A/B test different configurations

**Production monitoring**:
- Sample 1-5% of traffic for evaluation
- Run faithfulness check on all responses (if budget allows)
- Alert on metric degradation

**Continuous evaluation pipeline**:
```python
# Example monitoring setup
@monitor_every_nth_request(n=20)
def evaluate_rag_response(question, context, answer):
    metrics = {
        "faithfulness": faithfulness_metric.score(context, answer),
        "relevancy": relevancy_metric.score(question, answer)
    }
    
    # Log to monitoring system
    log_metrics(metrics)
    
    # Alert if below threshold
    if metrics["faithfulness"] < 0.85:
        send_alert("Low faithfulness detected")
```

---

### 7.4 Metric Selection Guide

**For Bible RAG specifically**:

```python
# Must-have metrics
required_metrics = [
    faithfulness,           # Prevent biblical misquotes
    context_precision,      # Ensure correct verses retrieved
    context_recall,         # Don't miss relevant verses
]

# Highly recommended
recommended_metrics = [
    answer_relevancy,       # Stay on topic
    ndcg,                  # Rank most relevant verses first
]

# Optional (if ground truth available)
optional_metrics = [
    answer_correctness,     # Validate against expert answers
    theological_accuracy,   # Custom metric for doctrinal alignment
]
```

---

### 7.5 Optimization Workflow

```python
# Iterative improvement process

# 1. Baseline evaluation
baseline_scores = evaluate_current_system()

# 2. Identify bottleneck
if baseline_scores["context_recall"] < 0.7:
    # Problem: Missing relevant verses
    # Solution: Adjust chunk size, improve embeddings
    pass

elif baseline_scores["faithfulness"] < 0.85:
    # Problem: Hallucinations
    # Solution: Better prompting, stronger LLM, add citations
    pass

elif baseline_scores["answer_relevancy"] < 0.8:
    # Problem: Verbose or off-topic answers
    # Solution: Improve prompt instructions
    pass

# 3. Implement improvements

# 4. Re-evaluate
new_scores = evaluate_improved_system()

# 5. Compare
improvement = calculate_delta(new_scores, baseline_scores)
```

---

### 7.6 Cost Optimization Strategies

**1. Tiered evaluation**:
```python
# Cheap first pass
if fast_check(answer) == "potentially_problematic":
    # Expensive detailed check
    detailed_evaluation(answer)
```

**2. Caching**:
```python
# Cache evaluation results
@cache_result(ttl=3600)
def evaluate_answer(question, answer, context):
    return expensive_llm_evaluation()
```

**3. Sampling**:
```python
# Only evaluate subset in production
if random.random() < 0.05:  # 5% sampling
    evaluate_response()
```

**4. Batch processing**:
```python
# Batch multiple evaluations
evaluations = batch_evaluate(
    questions=questions,
    answers=answers,
    batch_size=50
)
```

---

## Summary: Metric Selection Cheat Sheet

### Quick Reference Table

| Scenario | Primary Metrics | Secondary Metrics |
|----------|----------------|-------------------|
| **Development** | Faithfulness, Context Recall, NDCG | Answer Relevancy, Context Precision |
| **Production** | Faithfulness (sampled), Hit Rate | Answer Relevancy |
| **A/B Testing** | Answer Correctness, F1 | BERTScore, Semantic Similarity |
| **Retrieval Optimization** | NDCG, MRR, Recall@k | Precision@k, Context Recall |
| **Generation Optimization** | Faithfulness, Answer Relevancy | Hallucination Rate |
| **Cost-Sensitive** | Simple metrics (Hit Rate, Precision) | LLM-as-judge (sampled) |

---

### Recommended Minimal Set

For most RAG systems, start with these **5 core metrics**:

1. **NDCG@k** (retrieval quality)
2. **Context Recall** (retrieval completeness)
3. **Faithfulness** (no hallucinations)
4. **Answer Relevancy** (stays on topic)
5. **Answer Correctness** (if ground truth available)

Then expand based on your specific needs and failure patterns.

---

## Tools and Frameworks

**Popular evaluation frameworks**:

| Framework | Focus | Strengths |
|-----------|-------|-----------|
| **RAGAS** | RAG-specific | Reference-free metrics, easy integration |
| **DeepEval** | LLM evaluation | Comprehensive metrics, customizable |
| **TruLens** | RAG observability | Production monitoring, tracing |
| **LangSmith** | LangChain integration | Development workflow |
| **Evidently AI** | ML monitoring | Dashboard, drift detection |
| **Arize** | Production monitoring | Enterprise features |

**Specialized hallucination detectors**:
- **Vectara HHEM**: Fine-tuned hallucination model
- **FaithJudge**: Few-shot LLM-as-judge
- **Patronus Lynx**: Specialized evaluation model
- **Cleanlab TLM**: Trustworthy Language Model

---

This comprehensive guide covers all major aspects of RAG evaluation methodology. The key is to:

1. Understand what each metric measures
2. Choose metrics appropriate for your use case  
3. Combine multiple metrics for comprehensive evaluation
4. Iterate based on metric insights
5. Balance quality with cost constraints
