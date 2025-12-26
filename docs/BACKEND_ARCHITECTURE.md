# Bible RAG 後端架構規格文件

本文件詳細說明 Bible RAG 後端系統的檔案架構、模組功能與資料流程。

## 目錄

1. [專案結構總覽](#專案結構總覽)
2. [核心模組 (app/core)](#核心模組-appcore)
3. [資料模型 (app/models)](#資料模型-appmodels)
4. [服務層 (app/services)](#服務層-appservices)
5. [API 層 (app/api)](#api-層-appapi)
6. [腳本工具 (scripts)](#腳本工具-scripts)
7. [資料流程圖](#資料流程圖)
8. [模組依賴關係](#模組依賴關係)

---

## 專案結構總覽

```
backend/
├── app/                          # 主應用程式
│   ├── __init__.py
│   ├── main.py                   # FastAPI 應用程式入口
│   ├── core/                     # 核心配置與連線管理
│   │   ├── __init__.py
│   │   ├── config.py             # 環境變數與應用設定
│   │   ├── database.py           # PostgreSQL 資料庫連線
│   │   └── neo4j_client.py       # Neo4j 圖資料庫連線
│   ├── models/                   # 資料模型定義
│   │   ├── __init__.py
│   │   ├── orm/                  # SQLAlchemy ORM 模型
│   │   │   ├── __init__.py
│   │   │   ├── base.py           # ORM 基礎類別
│   │   │   ├── book.py           # 書卷模型
│   │   │   ├── chapter.py        # 章節模型
│   │   │   ├── verse.py          # 經文模型
│   │   │   ├── pericope.py       # 段落模型
│   │   │   ├── entity.py         # 實體模型 (人物/地點)
│   │   │   └── topic.py          # 主題模型
│   │   └── schemas/              # Pydantic 驗證模型
│   │       ├── __init__.py
│   │       ├── query.py          # 查詢請求/回應
│   │       ├── book.py           # 書卷 Schema
│   │       ├── pericope.py       # 段落 Schema
│   │       ├── verse.py          # 經文 Schema
│   │       └── graph.py          # 圖譜 Schema
│   ├── services/                 # 業務邏輯服務
│   │   ├── __init__.py
│   │   ├── rag_pipeline.py       # RAG 管線主控
│   │   ├── embedding_service.py  # 向量嵌入服務
│   │   ├── llm_client.py         # LLM 客戶端
│   │   ├── fusion.py             # RRF 融合演算法
│   │   ├── context_builder.py    # 上下文建構器
│   │   └── retrievers/           # 檢索器模組
│   │       ├── __init__.py
│   │       ├── base.py           # 檢索器基礎類別
│   │       ├── dense_retriever.py    # 向量檢索器
│   │       ├── sparse_retriever.py   # 全文檢索器
│   │       └── graph_retriever.py    # 圖譜檢索器
│   └── api/                      # API 路由與端點
│       ├── __init__.py
│       └── v1/                   # API v1 版本
│           ├── __init__.py
│           ├── router.py         # 路由配置
│           ├── deps.py           # 依賴注入
│           └── endpoints/        # API 端點
│               ├── __init__.py
│               ├── query.py      # RAG 查詢端點
│               ├── books.py      # 書卷端點
│               ├── pericopes.py  # 段落端點
│               ├── verses.py     # 經文端點
│               └── graph.py      # 圖譜端點
├── scripts/                      # 工具腳本
│   ├── pdf_parser.py             # PDF 解析器
│   ├── build_index.py            # 索引建構工具
│   ├── compute_topic_relations.py    # 主題關係計算
│   ├── summary_generator.py      # 摘要生成器
│   ├── import_cross_references.py    # 交叉引用匯入
│   ├── import_prophecy_links.py      # 預言連結匯入
│   └── import_synoptic_parallels.py  # 對觀福音平行匯入
├── alembic/                      # 資料庫遷移
│   ├── versions/                 # 遷移版本
│   └── env.py                    # 遷移環境配置
├── tests/                        # 測試檔案
├── requirements.txt              # Python 依賴
├── alembic.ini                   # Alembic 配置
└── .env                          # 環境變數
```

---

## 核心模組 (app/core)

核心模組負責應用程式的基礎設施配置，包括環境變數管理、資料庫連線池和外部服務客戶端。

### config.py - 應用程式設定

**功能**: 使用 Pydantic Settings 管理所有環境變數和應用設定。

```python
class Settings(BaseSettings):
    """應用程式設定類別"""

    # 基本設定
    APP_NAME: str = "Bible RAG API"
    VERSION: str = "1.0.0"
    DEBUG: bool = False
    API_V1_PREFIX: str = "/api/v1"

    # PostgreSQL 設定
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str
    POSTGRES_DB: str = "bible_rag"

    # Neo4j 設定
    NEO4J_URI: str = "bolt://localhost:7687"
    NEO4J_USER: str = "neo4j"
    NEO4J_PASSWORD: str

    # Ollama LLM 設定
    OLLAMA_HOST: str = "http://localhost:11434"
    OLLAMA_MODEL: str = "gemm3:4b"

    # Embedding 設定
    EMBEDDING_MODEL: str = "BAAI/bge-m3"
    EMBEDDING_DIMENSION: int = 1024

    # RAG 設定
    RRF_K: int = 60                    # RRF 演算法 k 值
    TOP_K_PERICOPES: int = 5           # 返回的段落數量
    TOP_K_DENSE: int = 10              # 向量檢索數量
    TOP_K_SPARSE: int = 10             # 全文檢索數量
    TOP_K_GRAPH: int = 5               # 圖譜檢索數量

    # CORS 設定
    ALLOWED_ORIGINS: list[str] = ["http://localhost:3000"]
```

**關鍵屬性**:

| 屬性 | 類型 | 說明 |
|------|------|------|
| `DATABASE_URL` | property | 組合完整的 PostgreSQL asyncpg 連線字串 |
| `RRF_K` | int | RRF 融合演算法的 k 參數，預設 60 |
| `EMBEDDING_DIMENSION` | int | 向量維度，bge-m3 為 1024 維 |

---

### database.py - PostgreSQL 資料庫連線

**功能**: 管理 SQLAlchemy 非同步資料庫連線和會話。

```python
# 非同步引擎配置
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_size=5,           # 連線池大小
    max_overflow=10,       # 最大溢出連線
    pool_pre_ping=True,    # 連線健康檢查
)

# 會話工廠
async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)
```

**主要函數**:

| 函數 | 說明 |
|------|------|
| `init_db()` | 初始化資料庫連線，應用啟動時呼叫 |
| `close_db()` | 關閉資料庫連線，應用關閉時呼叫 |
| `get_db_session()` | FastAPI 依賴注入，提供資料庫會話 |

**會話管理模式**:
```python
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """提供資料庫會話的依賴注入函數"""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
```

---

### neo4j_client.py - Neo4j 圖資料庫客戶端

**功能**: 提供 Neo4j 非同步操作的單例客戶端。

```python
class Neo4jClient:
    """Neo4j 非同步客戶端 (單例模式)"""

    _driver: AsyncDriver | None = None

    @classmethod
    async def initialize(cls) -> None:
        """初始化 Neo4j 驅動程式"""
        cls._driver = AsyncGraphDatabase.driver(
            settings.NEO4J_URI,
            auth=(settings.NEO4J_USER, settings.NEO4J_PASSWORD),
            max_connection_pool_size=50,
        )

    @classmethod
    async def execute_read(cls, query: str, params: dict = None) -> list[dict]:
        """執行讀取查詢"""

    @classmethod
    async def execute_write(cls, query: str, params: dict = None) -> list[dict]:
        """執行寫入查詢"""

    @classmethod
    async def execute_write_batch(cls, queries: list[tuple[str, dict]]) -> None:
        """批次執行寫入查詢"""
```

**主要方法**:

| 方法 | 說明 |
|------|------|
| `initialize()` | 初始化連線，應用啟動時呼叫 |
| `close()` | 關閉連線，應用關閉時呼叫 |
| `execute_read(query, params)` | 執行 Cypher 讀取查詢 |
| `execute_write(query, params)` | 執行 Cypher 寫入查詢 |
| `execute_write_batch(queries)` | 批次執行多個寫入查詢 |
| `health_check()` | 檢查連線健康狀態 |

---

## 資料模型 (app/models)

### ORM 模型 (app/models/orm)

#### base.py - ORM 基礎類別

```python
class Base(DeclarativeBase):
    """SQLAlchemy ORM 基礎類別"""
    pass
```

所有 ORM 模型都繼承此基礎類別。

---

#### book.py - 書卷模型

**功能**: 定義聖經 66 卷書的資料結構。

```python
class Book(Base):
    """書卷 ORM 模型"""
    __tablename__ = "books"

    id: Mapped[int] = mapped_column(primary_key=True)
    name_zh: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    abbrev_zh: Mapped[str] = mapped_column(String(10))
    testament: Mapped[str] = mapped_column(String(2))  # OT/NT
    order_index: Mapped[int] = mapped_column(unique=True)

    # 關聯
    chapters: Mapped[list["Chapter"]] = relationship(back_populates="book")
    pericopes: Mapped[list["Pericope"]] = relationship(back_populates="book")
    verses: Mapped[list["Verse"]] = relationship(back_populates="book")
```

**欄位說明**:

| 欄位 | 類型 | 說明 |
|------|------|------|
| `id` | int | 主鍵 |
| `name_zh` | str | 中文書名 (如「創世記」) |
| `abbrev_zh` | str | 中文縮寫 (如「創」) |
| `testament` | str | 舊約/新約 ("OT"/"NT") |
| `order_index` | int | 排列順序 (1-66) |

---

#### chapter.py - 章節模型

**功能**: 定義章節資料結構。

```python
class Chapter(Base):
    """章節 ORM 模型"""
    __tablename__ = "chapters"

    id: Mapped[int] = mapped_column(primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"))
    chapter_number: Mapped[int]
    verse_count: Mapped[int]

    # 關聯
    book: Mapped["Book"] = relationship(back_populates="chapters")

    # 複合唯一約束
    __table_args__ = (
        UniqueConstraint("book_id", "chapter_number"),
    )
```

---

#### verse.py - 經文模型

**功能**: 定義經文資料結構，包含全文搜尋索引。

```python
class Verse(Base):
    """經文 ORM 模型"""
    __tablename__ = "verses"

    id: Mapped[int] = mapped_column(primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"))
    chapter: Mapped[int]
    verse: Mapped[int]
    text: Mapped[str] = mapped_column(Text)
    pericope_id: Mapped[int | None] = mapped_column(ForeignKey("pericopes.id"))

    # 全文搜尋向量 (PostgreSQL TSVECTOR)
    tsv: Mapped[Any] = mapped_column(
        TSVECTOR,
        Computed("to_tsvector('simple', text)", persisted=True)
    )

    # 關聯
    book: Mapped["Book"] = relationship(back_populates="verses")
    pericope: Mapped["Pericope"] = relationship(back_populates="verses")

    # 索引
    __table_args__ = (
        Index("ix_verses_tsv", "tsv", postgresql_using="gin"),
        UniqueConstraint("book_id", "chapter", "verse"),
    )
```

**欄位說明**:

| 欄位 | 類型 | 說明 |
|------|------|------|
| `text` | str | 經文內容 |
| `tsv` | TSVECTOR | 自動計算的全文搜尋向量 |
| `pericope_id` | int | 所屬段落 ID |

**索引**:
- `ix_verses_tsv`: GIN 索引，用於加速全文搜尋

---

#### pericope.py - 段落模型

**功能**: 定義聖經段落 (Pericope) 資料結構，包含向量嵌入。

```python
class Pericope(Base):
    """段落 ORM 模型"""
    __tablename__ = "pericopes"

    id: Mapped[int] = mapped_column(primary_key=True)
    book_id: Mapped[int] = mapped_column(ForeignKey("books.id"))
    chapter_start: Mapped[int]
    verse_start: Mapped[int]
    chapter_end: Mapped[int]
    verse_end: Mapped[int]
    title: Mapped[str] = mapped_column(String(200))
    summary: Mapped[str | None] = mapped_column(Text)

    # 向量嵌入 (pgvector, 1024 維)
    embedding: Mapped[Any] = mapped_column(Vector(1024), nullable=True)

    # 關聯
    book: Mapped["Book"] = relationship(back_populates="pericopes")
    verses: Mapped[list["Verse"]] = relationship(back_populates="pericope")

    # 索引
    __table_args__ = (
        Index(
            "ix_pericopes_embedding",
            "embedding",
            postgresql_using="ivfflat",
            postgresql_with={"lists": 100},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )
```

**欄位說明**:

| 欄位 | 類型 | 說明 |
|------|------|------|
| `title` | str | 段落標題 (如「創造天地」) |
| `summary` | str | LLM 生成的段落摘要 |
| `embedding` | Vector(1024) | bge-m3 嵌入向量 |

**索引**:
- `ix_pericopes_embedding`: IVFFlat 索引 (100 lists)，用於加速向量相似度搜尋

---

#### entity.py - 實體模型

**功能**: 定義聖經中的實體 (人物、地點、群體、事件)。

```python
class EntityType(str, Enum):
    """實體類型"""
    PERSON = "PERSON"      # 人物
    PLACE = "PLACE"        # 地點
    GROUP = "GROUP"        # 群體
    EVENT = "EVENT"        # 事件


class Entity(Base):
    """實體 ORM 模型"""
    __tablename__ = "entities"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    type: Mapped[EntityType]
    description: Mapped[str | None] = mapped_column(Text)

    # 關聯
    verse_entities: Mapped[list["VerseEntity"]] = relationship(back_populates="entity")


class VerseEntity(Base):
    """經文-實體關聯表 (多對多)"""
    __tablename__ = "verse_entities"

    id: Mapped[int] = mapped_column(primary_key=True)
    verse_id: Mapped[int] = mapped_column(ForeignKey("verses.id"))
    entity_id: Mapped[int] = mapped_column(ForeignKey("entities.id"))
    role: Mapped[str | None] = mapped_column(String(50))  # 角色描述
```

---

#### topic.py - 主題模型

**功能**: 定義聖經主題標籤。

```python
class TopicType(str, Enum):
    """主題類型"""
    DOCTRINE = "DOCTRINE"      # 教義
    MORAL = "MORAL"            # 道德
    HISTORICAL = "HISTORICAL"  # 歷史
    PROPHETIC = "PROPHETIC"    # 預言
    OTHER = "OTHER"            # 其他


class Topic(Base):
    """主題 ORM 模型"""
    __tablename__ = "topics"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, index=True)
    type: Mapped[TopicType]
    description: Mapped[str | None] = mapped_column(Text)

    # 關聯
    verse_topics: Mapped[list["VerseTopic"]] = relationship(back_populates="topic")


class VerseTopic(Base):
    """經文-主題關聯表 (多對多)"""
    __tablename__ = "verse_topics"

    id: Mapped[int] = mapped_column(primary_key=True)
    verse_id: Mapped[int] = mapped_column(ForeignKey("verses.id"))
    topic_id: Mapped[int] = mapped_column(ForeignKey("topics.id"))
    weight: Mapped[float] = mapped_column(default=1.0)  # 關聯強度 (0-1)
```

---

### Pydantic Schema (app/models/schemas)

#### query.py - 查詢模型

**功能**: 定義 RAG 查詢的請求和回應結構。

```python
class QueryMode(str, Enum):
    """查詢模式"""
    AUTO = "auto"        # 自動分類
    VERSE = "verse"      # 經文查詢
    TOPIC = "topic"      # 主題查詢
    PERSON = "person"    # 人物查詢
    EVENT = "event"      # 事件查詢


class QueryType(str, Enum):
    """查詢類型 (LLM 分類結果)"""
    VERSE_LOOKUP = "VERSE_LOOKUP"              # 經文查找
    TOPIC_QUESTION = "TOPIC_QUESTION"          # 主題問題
    PERSON_QUESTION = "PERSON_QUESTION"        # 人物問題
    EVENT_QUESTION = "EVENT_QUESTION"          # 事件問題
    GENERAL_BIBLE_QUESTION = "GENERAL_BIBLE_QUESTION"  # 一般問題


class QueryRequest(BaseModel):
    """查詢請求"""
    query: str = Field(..., min_length=1, max_length=500)
    mode: QueryMode = Field(default=QueryMode.AUTO)
    options: QueryOptions = Field(default_factory=QueryOptions)


class QueryResponse(BaseModel):
    """查詢回應"""
    answer: str                                # LLM 生成的答案
    segments: list[PericopeSegment]           # 相關段落
    meta: QueryMeta                           # 元資料
    graph_context: GraphContext | None = None  # 圖譜上下文
```

---

## 服務層 (app/services)

服務層實作核心業務邏輯，包括 RAG 管線、嵌入服務、LLM 客戶端和檢索器。

### rag_pipeline.py - RAG 管線主控

**功能**: 協調整個 RAG 查詢流程。

```python
class RAGPipeline:
    """RAG 管線主控類別"""

    def __init__(
        self,
        db_session: AsyncSession,
        embedding_service: EmbeddingService,
        llm_client: LLMClient,
    ):
        self.db = db_session
        self.embedding = embedding_service
        self.llm = llm_client

        # 初始化檢索器
        self.dense_retriever = DenseRetriever(db_session, embedding_service)
        self.sparse_retriever = SparseRetriever(db_session)
        self.graph_retriever = GraphRetriever(llm_client)

    async def execute(self, request: QueryRequest) -> QueryResponse:
        """執行完整 RAG 管線"""
        start_time = time.time()

        # 1. 查詢分類
        query_type = await self.llm.classify_query(request.query)

        # 2. 並行檢索
        dense_results, sparse_results, graph_results = await asyncio.gather(
            self.dense_retriever.retrieve(request.query, top_k=settings.TOP_K_DENSE),
            self.sparse_retriever.retrieve(request.query, top_k=settings.TOP_K_SPARSE),
            self.graph_retriever.retrieve(request.query, query_type),
        )

        # 3. RRF 融合
        fused_results = rrf_fusion(
            [dense_results, sparse_results, graph_results],
            k=settings.RRF_K,
        )[:request.options.max_results]

        # 4. 建構上下文
        context = build_context(fused_results)

        # 5. LLM 生成答案
        answer = await self.llm.generate_answer(request.query, context)

        # 6. 組裝回應
        processing_time = int((time.time() - start_time) * 1000)
        return QueryResponse(
            answer=answer,
            segments=self._to_segments(fused_results),
            meta=QueryMeta(
                query_type=query_type.value,
                used_retrievers=["dense", "sparse", "graph"],
                total_processing_time_ms=processing_time,
                llm_model=settings.OLLAMA_MODEL,
            ),
            graph_context=self._extract_graph_context(graph_results),
        )
```

**執行流程**:

```
QueryRequest
     │
     ▼
┌─────────────┐
│ 1. 查詢分類  │  LLM 判斷查詢類型
└─────────────┘
     │
     ▼
┌─────────────────────────────────────┐
│         2. 並行檢索 (asyncio.gather) │
├───────────┬───────────┬─────────────┤
│   Dense   │  Sparse   │    Graph    │
│  向量檢索  │  全文檢索  │   圖譜檢索   │
└───────────┴───────────┴─────────────┘
     │
     ▼
┌─────────────┐
│ 3. RRF 融合 │  Reciprocal Rank Fusion
└─────────────┘
     │
     ▼
┌─────────────┐
│ 4. 建構上下文│  組合相關經文
└─────────────┘
     │
     ▼
┌─────────────┐
│ 5. LLM 生成 │  生成答案
└─────────────┘
     │
     ▼
QueryResponse
```

---

### embedding_service.py - 向量嵌入服務

**功能**: 使用 bge-m3 模型生成文本向量嵌入。

```python
class EmbeddingService:
    """向量嵌入服務 (單例模式)"""

    _instance: "EmbeddingService" | None = None
    _model: BGEM3FlagModel | None = None

    def __init__(self):
        if EmbeddingService._model is None:
            EmbeddingService._model = BGEM3FlagModel(
                settings.EMBEDDING_MODEL,
                use_fp16=True,  # 使用半精度加速
            )

    def encode(self, texts: str | list[str]) -> np.ndarray:
        """編碼文本為向量"""
        if isinstance(texts, str):
            texts = [texts]
        outputs = self._model.encode(
            texts,
            batch_size=32,
            max_length=512,
            return_dense=True,
            return_sparse=False,
            return_colbert_vecs=False,
        )
        return outputs["dense_vecs"]

    def encode_query(self, query: str) -> np.ndarray:
        """編碼查詢文本"""
        return self.encode(query)[0]

    def encode_documents(self, documents: list[str]) -> np.ndarray:
        """批次編碼文檔"""
        return self.encode(documents)


# 單例取得函數
def get_embedding_service() -> EmbeddingService:
    if EmbeddingService._instance is None:
        EmbeddingService._instance = EmbeddingService()
    return EmbeddingService._instance
```

**特性**:
- 使用 `BAAI/bge-m3` 多語言嵌入模型
- 輸出 1024 維向量
- 支援批次處理 (batch_size=32)
- 使用 FP16 半精度加速
- 單例模式避免重複載入模型

---

### llm_client.py - LLM 客戶端

**功能**: 封裝 Ollama LLM API 呼叫。

```python
class LLMClient:
    """Ollama LLM 客戶端"""

    def __init__(self):
        self.base_url = settings.OLLAMA_HOST
        self.model = settings.OLLAMA_MODEL

    async def generate(self, prompt: str, system: str = None) -> str:
        """生成文本"""
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "system": system,
                    "stream": False,
                },
                timeout=60.0,
            )
            return response.json()["response"]

    async def classify_query(self, query: str) -> QueryType:
        """分類查詢類型"""
        system_prompt = """你是一個查詢分類器。根據使用者的問題，判斷其類型。

        類型：
        - VERSE_LOOKUP: 查找特定經文 (如「約翰福音3:16」)
        - TOPIC_QUESTION: 關於主題的問題 (如「聖經怎麼說饒恕」)
        - PERSON_QUESTION: 關於人物的問題 (如「大衛是誰」)
        - EVENT_QUESTION: 關於事件的問題 (如「出埃及發生了什麼」)
        - GENERAL_BIBLE_QUESTION: 一般聖經問題

        只回答類型名稱，不要其他文字。"""

        result = await self.generate(query, system=system_prompt)
        return QueryType(result.strip())

    async def generate_answer(self, query: str, context: str) -> str:
        """根據上下文生成答案"""
        system_prompt = """你是一個專業的聖經解答助手。根據提供的經文上下文回答問題。

        要求：
        1. 答案要基於提供的經文內容
        2. 使用清晰的結構化格式
        3. 適當引用經文章節
        4. 如果上下文不足以回答，請誠實說明"""

        prompt = f"""問題：{query}

相關經文：
{context}

請回答上述問題。"""

        return await self.generate(prompt, system=system_prompt)
```

**主要方法**:

| 方法 | 說明 |
|------|------|
| `generate(prompt, system)` | 基礎文本生成 |
| `classify_query(query)` | 分類查詢類型 |
| `generate_answer(query, context)` | 根據上下文生成答案 |

---

### fusion.py - RRF 融合演算法

**功能**: 實作 Reciprocal Rank Fusion 演算法，融合多個檢索器的結果。

```python
@dataclass
class FusedResult:
    """融合結果"""
    id: int                  # 段落 ID
    book_name: str          # 書卷名稱
    title: str              # 段落標題
    text: str               # 經文內容
    score: float            # RRF 分數
    sources: list[str]      # 來源檢索器


def rrf_fusion(
    result_lists: list[list[RetrievalResult]],
    k: int = 60,
) -> list[FusedResult]:
    """
    Reciprocal Rank Fusion 演算法

    公式: score(d) = Σ 1/(k + rank_i(d))

    Args:
        result_lists: 多個檢索器的結果列表
        k: RRF k 參數 (預設 60)

    Returns:
        按 RRF 分數排序的融合結果
    """
    scores: dict[int, float] = defaultdict(float)
    metadata: dict[int, dict] = {}
    sources: dict[int, list[str]] = defaultdict(list)

    for retriever_idx, results in enumerate(result_lists):
        retriever_name = ["dense", "sparse", "graph"][retriever_idx]
        for rank, result in enumerate(results, start=1):
            # RRF 公式
            scores[result.id] += 1.0 / (k + rank)
            sources[result.id].append(retriever_name)
            if result.id not in metadata:
                metadata[result.id] = {
                    "book_name": result.book_name,
                    "title": result.title,
                    "text": result.text,
                }

    # 按分數排序
    sorted_ids = sorted(scores.keys(), key=lambda x: scores[x], reverse=True)

    return [
        FusedResult(
            id=doc_id,
            book_name=metadata[doc_id]["book_name"],
            title=metadata[doc_id]["title"],
            text=metadata[doc_id]["text"],
            score=scores[doc_id],
            sources=sources[doc_id],
        )
        for doc_id in sorted_ids
    ]
```

**RRF 演算法說明**:
- 公式: `score(d) = Σ 1/(k + rank_i(d))`
- `k` 參數控制排名的影響程度，預設 60
- 融合來自 Dense、Sparse、Graph 三個檢索器的結果
- 高排名文件獲得較高分數

---

### context_builder.py - 上下文建構器

**功能**: 將融合結果組裝成 LLM 可讀的上下文。

```python
def build_context(results: list[FusedResult], max_length: int = 4000) -> str:
    """
    建構 LLM 上下文

    Args:
        results: 融合後的檢索結果
        max_length: 最大上下文長度

    Returns:
        格式化的上下文字串
    """
    context_parts = []
    current_length = 0

    for i, result in enumerate(results, start=1):
        segment = f"""
【段落 {i}】{result.book_name} - {result.title}
{result.text}
---
"""
        segment_length = len(segment)
        if current_length + segment_length > max_length:
            break
        context_parts.append(segment)
        current_length += segment_length

    return "\n".join(context_parts)
```

---

### retrievers/base.py - 檢索器基礎類別

```python
@dataclass
class RetrievalResult:
    """檢索結果資料類別"""
    id: int              # 段落 ID
    book_name: str       # 書卷名稱
    title: str           # 段落標題
    text: str            # 經文內容
    score: float         # 相關性分數


class BaseRetriever(ABC):
    """檢索器抽象基礎類別"""

    @abstractmethod
    async def retrieve(self, query: str, top_k: int = 10) -> list[RetrievalResult]:
        """執行檢索"""
        pass
```

---

### retrievers/dense_retriever.py - 向量檢索器

**功能**: 使用 pgvector 執行語義相似度檢索。

```python
class DenseRetriever(BaseRetriever):
    """向量檢索器 (pgvector)"""

    def __init__(self, db: AsyncSession, embedding_service: EmbeddingService):
        self.db = db
        self.embedding = embedding_service

    async def retrieve(self, query: str, top_k: int = 10) -> list[RetrievalResult]:
        """執行向量相似度檢索"""
        # 1. 編碼查詢
        query_embedding = self.embedding.encode_query(query)

        # 2. 執行向量搜尋
        stmt = (
            select(
                Pericope.id,
                Book.name_zh.label("book_name"),
                Pericope.title,
                func.string_agg(Verse.text, " ").label("text"),
                Pericope.embedding.cosine_distance(query_embedding).label("distance"),
            )
            .join(Book, Pericope.book_id == Book.id)
            .join(Verse, Verse.pericope_id == Pericope.id)
            .where(Pericope.embedding.isnot(None))
            .group_by(Pericope.id, Book.name_zh, Pericope.title)
            .order_by("distance")
            .limit(top_k)
        )

        result = await self.db.execute(stmt)
        rows = result.all()

        return [
            RetrievalResult(
                id=row.id,
                book_name=row.book_name,
                title=row.title,
                text=row.text,
                score=1 - row.distance,  # 轉換為相似度分數
            )
            for row in rows
        ]
```

**特性**:
- 使用 pgvector 的 `cosine_distance` 函數
- IVFFlat 索引加速搜尋
- 距離轉換為相似度: `score = 1 - distance`

---

### retrievers/sparse_retriever.py - 全文檢索器

**功能**: 使用 PostgreSQL Full-Text Search 執行關鍵字檢索。

```python
class SparseRetriever(BaseRetriever):
    """全文檢索器 (PostgreSQL FTS)"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def retrieve(self, query: str, top_k: int = 10) -> list[RetrievalResult]:
        """執行全文搜尋"""
        # 建立 tsquery
        ts_query = func.plainto_tsquery("simple", query)

        stmt = (
            select(
                Pericope.id,
                Book.name_zh.label("book_name"),
                Pericope.title,
                func.string_agg(Verse.text, " ").label("text"),
                func.sum(func.ts_rank(Verse.tsv, ts_query)).label("rank"),
            )
            .join(Book, Pericope.book_id == Book.id)
            .join(Verse, Verse.pericope_id == Pericope.id)
            .where(Verse.tsv.op("@@")(ts_query))
            .group_by(Pericope.id, Book.name_zh, Pericope.title)
            .order_by(desc("rank"))
            .limit(top_k)
        )

        result = await self.db.execute(stmt)
        rows = result.all()

        return [
            RetrievalResult(
                id=row.id,
                book_name=row.book_name,
                title=row.title,
                text=row.text,
                score=float(row.rank),
            )
            for row in rows
        ]
```

**特性**:
- 使用 `plainto_tsquery` 將查詢轉換為 tsquery
- 使用 `ts_rank` 計算相關性分數
- GIN 索引加速搜尋
- 使用 "simple" 配置支援中文

---

### retrievers/graph_retriever.py - 圖譜檢索器

**功能**: 使用 Neo4j 知識圖譜進行實體關係檢索。

```python
class GraphRetriever(BaseRetriever):
    """知識圖譜檢索器 (Neo4j)"""

    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    async def retrieve(
        self, query: str, query_type: QueryType, top_k: int = 5
    ) -> list[RetrievalResult]:
        """執行圖譜檢索"""
        # 1. LLM 提取查詢中的實體
        entities = await self._extract_entities(query)

        if not entities:
            return []

        # 2. 根據查詢類型選擇 Cypher 查詢
        if query_type == QueryType.PERSON_QUESTION:
            results = await self._query_person(entities)
        elif query_type == QueryType.TOPIC_QUESTION:
            results = await self._query_topic(entities)
        elif query_type == QueryType.EVENT_QUESTION:
            results = await self._query_event(entities)
        else:
            results = await self._query_general(entities)

        return results[:top_k]

    async def _extract_entities(self, query: str) -> list[str]:
        """使用 LLM 從查詢中提取實體"""
        prompt = f"""從以下問題中提取聖經相關的實體（人物、地點、事件、主題）。
        只回答實體名稱，用逗號分隔。

        問題：{query}"""

        response = await self.llm.generate(prompt)
        return [e.strip() for e in response.split(",") if e.strip()]

    async def _query_person(self, entities: list[str]) -> list[RetrievalResult]:
        """查詢人物相關段落"""
        cypher = """
        MATCH (p:Person)-[:APPEARS_IN]->(per:Pericope)
        WHERE p.name IN $entities
        RETURN per.id AS id, per.book_name AS book_name,
               per.title AS title, per.text AS text
        LIMIT 10
        """
        records = await Neo4jClient.execute_read(cypher, {"entities": entities})
        return [self._to_result(r) for r in records]
```

**特性**:
- 使用 LLM 從查詢中提取實體
- 根據查詢類型選擇對應的 Cypher 查詢
- 支援人物、主題、事件等多種查詢模式

---

## API 層 (app/api)

### deps.py - 依賴注入

**功能**: 定義 FastAPI 依賴注入函數。

```python
from typing import Annotated
from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db_session
from app.services.embedding_service import EmbeddingService, get_embedding_service
from app.services.llm_client import LLMClient
from app.services.rag_pipeline import RAGPipeline


# 類型別名
DBSession = Annotated[AsyncSession, Depends(get_db_session)]


def get_llm_client() -> LLMClient:
    """取得 LLM 客戶端"""
    return LLMClient()


def get_rag_pipeline(
    db: DBSession,
    embedding: Annotated[EmbeddingService, Depends(get_embedding_service)],
    llm: Annotated[LLMClient, Depends(get_llm_client)],
) -> RAGPipeline:
    """取得 RAG 管線"""
    return RAGPipeline(db, embedding, llm)


# 依賴類型
RAGPipelineDep = Annotated[RAGPipeline, Depends(get_rag_pipeline)]
```

---

### v1/router.py - 路由配置

**功能**: 配置 API v1 的所有路由。

```python
from fastapi import APIRouter

from app.api.v1.endpoints import books, graph, pericopes, query, verses

api_router = APIRouter()

# 註冊端點路由
api_router.include_router(query.router, prefix="/query", tags=["Query"])
api_router.include_router(books.router, prefix="/books", tags=["Books"])
api_router.include_router(pericopes.router, prefix="/pericopes", tags=["Pericopes"])
api_router.include_router(verses.router, prefix="/verses", tags=["Verses"])
api_router.include_router(graph.router, prefix="/graph", tags=["Graph"])
```

**路由結構**:

| 前綴 | 標籤 | 說明 |
|------|------|------|
| `/query` | Query | RAG 查詢 API |
| `/books` | Books | 書卷相關 API |
| `/pericopes` | Pericopes | 段落相關 API |
| `/verses` | Verses | 經文相關 API |
| `/graph` | Graph | 知識圖譜 API |

---

### endpoints/query.py - RAG 查詢端點

```python
from fastapi import APIRouter
from app.api.v1.deps import RAGPipelineDep
from app.models.schemas.query import QueryRequest, QueryResponse

router = APIRouter()


@router.post("", response_model=QueryResponse)
async def rag_query(
    request: QueryRequest,
    pipeline: RAGPipelineDep,
) -> QueryResponse:
    """
    執行 RAG 查詢

    流程：查詢分類 → 並行檢索 → RRF 融合 → LLM 生成

    Args:
        request: 查詢請求，包含問題和選項
        pipeline: RAG 管線 (依賴注入)

    Returns:
        QueryResponse: 包含答案、相關段落和元資料
    """
    return await pipeline.execute(request)
```

---

### endpoints/books.py - 書卷端點

```python
router = APIRouter()


@router.get("", response_model=list[BookListItem])
async def list_books(db: DBSession) -> list[BookListItem]:
    """列出所有書卷"""


@router.get("/{book_id}", response_model=BookDetail)
async def get_book(book_id: int, db: DBSession) -> BookDetail:
    """取得書卷詳情"""


@router.get("/{book_id}/chapters", response_model=list[ChapterInfo])
async def list_chapters(book_id: int, db: DBSession) -> list[ChapterInfo]:
    """列出書卷的所有章節"""


@router.get("/{book_id}/chapters/{chapter}/verses", response_model=list[VerseItem])
async def list_verses(book_id: int, chapter: int, db: DBSession) -> list[VerseItem]:
    """取得章節的所有經文"""
```

---

### endpoints/pericopes.py - 段落端點

```python
router = APIRouter()


@router.get("", response_model=PaginatedPericopes)
async def list_pericopes(
    db: DBSession,
    book_id: int | None = None,
    page: int = 1,
    page_size: int = 20,
) -> PaginatedPericopes:
    """列出段落 (支援分頁和書卷篩選)"""


@router.get("/{pericope_id}", response_model=PericopeDetail)
async def get_pericope(pericope_id: int, db: DBSession) -> PericopeDetail:
    """取得段落詳情"""


@router.get("/{pericope_id}/verses", response_model=list[VerseItem])
async def get_pericope_verses(pericope_id: int, db: DBSession) -> list[VerseItem]:
    """取得段落包含的經文"""
```

---

### endpoints/verses.py - 經文端點

```python
router = APIRouter()


@router.get("/{verse_id}", response_model=VerseDetail)
async def get_verse(verse_id: int, db: DBSession) -> VerseDetail:
    """取得經文詳情"""


@router.get("/search", response_model=SearchResult)
async def search_verses(
    q: str,
    db: DBSession,
    book_id: int | None = None,
    page: int = 1,
    page_size: int = 20,
) -> SearchResult:
    """全文搜尋經文"""
```

---

### endpoints/graph.py - 知識圖譜端點

```python
router = APIRouter()


@router.get("/entities", response_model=list[EntityItem])
async def list_entities(
    type: EntityType | None = None,
    limit: int = 50,
) -> list[EntityItem]:
    """列出實體"""


@router.get("/entities/{entity_id}", response_model=EntityDetail)
async def get_entity(entity_id: str) -> EntityDetail:
    """取得實體詳情"""


@router.get("/topics", response_model=list[TopicItem])
async def list_topics(limit: int = 50) -> list[TopicItem]:
    """列出主題"""


@router.get("/topics/{topic_id}/related", response_model=RelatedEntities)
async def get_related_entities(topic_id: str) -> RelatedEntities:
    """取得主題相關實體"""
```

---

## 腳本工具 (scripts)

### pdf_parser.py - PDF 解析器

**功能**: 解析新標點和合本聖經 PDF，提取結構化資料。

```python
@dataclass
class ParsedVerse:
    """解析的經文"""
    chapter: int
    verse: int
    text: str


@dataclass
class ParsedPericope:
    """解析的段落"""
    title: str
    chapter_start: int
    verse_start: int
    chapter_end: int
    verse_end: int
    verses: list[ParsedVerse]


@dataclass
class ParsedChapter:
    """解析的章節"""
    chapter_number: int
    pericopes: list[ParsedPericope]


@dataclass
class ParsedBook:
    """解析的書卷"""
    name: str
    abbrev: str
    testament: str
    chapters: list[ParsedChapter]


# 66 卷書元資料
BIBLE_BOOKS = [
    {"name": "創世記", "abbrev": "創", "testament": "OT"},
    {"name": "出埃及記", "abbrev": "出", "testament": "OT"},
    # ... 共 66 卷
]


def parse_bible_pdf(pdf_path: str) -> list[ParsedBook]:
    """
    解析聖經 PDF

    Args:
        pdf_path: PDF 檔案路徑

    Returns:
        解析後的書卷列表
    """
    # 1. 使用 PyMuPDF 讀取 PDF
    # 2. 識別書卷標題
    # 3. 識別段落標題
    # 4. 提取經文內容
    # 5. 組裝結構化資料
```

**輸出格式** (JSON):
```json
{
  "books": [
    {
      "name": "創世記",
      "abbrev": "創",
      "testament": "OT",
      "chapters": [
        {
          "chapter_number": 1,
          "pericopes": [
            {
              "title": "創造天地",
              "chapter_start": 1,
              "verse_start": 1,
              "chapter_end": 2,
              "verse_end": 3,
              "verses": [
                {"chapter": 1, "verse": 1, "text": "起初，神創造天地。"}
              ]
            }
          ]
        }
      ]
    }
  ]
}
```

---

### build_index.py - 索引建構工具

**功能**: CLI 工具，用於初始化資料庫和匯入解析後的聖經資料。

```python
@click.group()
def cli():
    """Bible RAG 索引建構工具"""
    pass


@cli.command()
def init_database():
    """
    初始化資料庫

    1. 建立 pgvector 擴充套件
    2. 建立 pg_trgm 擴充套件
    3. 執行 Alembic 遷移
    """
    async def _init():
        async with engine.begin() as conn:
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            await conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))

    asyncio.run(_init())
    os.system("alembic upgrade head")


@cli.command()
def clear_tables():
    """清空所有資料表"""


@cli.command()
@click.argument("json_path")
def import_from_json(json_path: str):
    """
    從 JSON 匯入聖經資料

    流程：
    1. 讀取 PDF 解析產生的 JSON
    2. 匯入書卷、章節、段落、經文
    3. 生成段落嵌入向量
    """


@cli.command()
def compute_embeddings():
    """
    計算所有段落的嵌入向量

    使用 bge-m3 模型批次處理
    """


if __name__ == "__main__":
    cli()
```

**使用方式**:
```bash
# 初始化資料庫
python scripts/build_index.py init-database

# 清空資料
python scripts/build_index.py clear-tables

# 匯入資料
python scripts/build_index.py import-from-json data/bible.json

# 計算嵌入向量
python scripts/build_index.py compute-embeddings
```

---

### compute_topic_relations.py - 主題關係計算

**功能**: 計算主題之間的共現關係並寫入 Neo4j。

```python
async def compute_topic_relations():
    """
    計算主題共現關係

    算法：
    1. 取得所有段落-主題關聯
    2. 計算主題共現矩陣
    3. 建立 Neo4j 中的 RELATED_TO 關係
    """
```

---

### summary_generator.py - 摘要生成器

**功能**: 使用 LLM 為段落生成摘要。

```python
async def generate_summaries():
    """
    批次生成段落摘要

    流程：
    1. 查詢未有摘要的段落
    2. 呼叫 LLM 生成摘要
    3. 更新資料庫
    """
```

---

### import_cross_references.py - 交叉引用匯入

**功能**: 從 OpenBible.info 匯入交叉引用資料。

---

### import_prophecy_links.py - 預言連結匯入

**功能**: 匯入舊約預言與新約應驗的對應關係。

---

### import_synoptic_parallels.py - 對觀福音平行匯入

**功能**: 匯入馬太、馬可、路加福音的平行段落。

---

## 資料流程圖

### RAG 查詢流程

```
┌─────────────────────────────────────────────────────────────────┐
│                         使用者查詢                               │
│                    "聖經怎麼談饒恕？"                             │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                     1. 查詢分類 (LLM)                            │
│                                                                 │
│  輸入: "聖經怎麼談饒恕？"                                         │
│  輸出: QueryType.TOPIC_QUESTION                                 │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                    2. 並行檢索 (asyncio.gather)                  │
│                                                                 │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │  Dense 檢索器    │  │  Sparse 檢索器   │  │  Graph 檢索器   │  │
│  │                 │  │                 │  │                 │  │
│  │ • 向量嵌入查詢  │  │ • FTS 關鍵字    │  │ • LLM 實體提取  │  │
│  │ • pgvector     │  │ • PostgreSQL    │  │ • Cypher 查詢   │  │
│  │ • cosine相似度 │  │ • ts_rank       │  │ • Neo4j         │  │
│  │                 │  │                 │  │                 │  │
│  │ 返回: 10 結果   │  │ 返回: 10 結果   │  │ 返回: 5 結果    │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                      3. RRF 融合                                │
│                                                                 │
│  score(d) = Σ 1/(60 + rank_i(d))                               │
│                                                                 │
│  • 合併去重                                                      │
│  • 計算 RRF 分數                                                 │
│  • 排序取 Top-K                                                  │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                    4. 上下文建構                                 │
│                                                                 │
│  【段落 1】馬太福音 - 饒恕七十個七次                              │
│  那時，彼得進前來，對耶穌說：主啊，我弟兄得罪我...                │
│  ---                                                            │
│  【段落 2】路加福音 - 饒恕的教導                                  │
│  ...                                                            │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                    5. LLM 答案生成                               │
│                                                                 │
│  System: 你是一個專業的聖經解答助手...                            │
│  Prompt: 問題 + 上下文                                           │
│  Model: Ollama gemm3:4b                                            │
│                                                                 │
│  輸出: 結構化的答案                                               │
└─────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                       回應組裝                                   │
│                                                                 │
│  {                                                              │
│    "answer": "## 饒恕的核心教導\n\n聖經中對於饒恕...",            │
│    "segments": [...],                                           │
│    "meta": {                                                    │
│      "query_type": "TOPIC_QUESTION",                            │
│      "used_retrievers": ["dense", "sparse", "graph"],           │
│      "total_processing_time_ms": 3542,                          │
│      "llm_model": "gemm3:4b"                                       │
│    }                                                            │
│  }                                                              │
└─────────────────────────────────────────────────────────────────┘
```

---

### 資料匯入流程

```
┌──────────────┐
│  PDF 檔案    │
│ 和合本聖經    │
└──────────────┘
       │
       ▼
┌──────────────────────────────────────┐
│         pdf_parser.py                │
│                                      │
│  1. 讀取 PDF                          │
│  2. 識別書卷邊界                       │
│  3. 識別段落標題                       │
│  4. 提取經文內容                       │
│  5. 輸出結構化 JSON                    │
└──────────────────────────────────────┘
       │
       ▼
┌──────────────┐
│  JSON 檔案   │
│ bible.json   │
└──────────────┘
       │
       ▼
┌──────────────────────────────────────┐
│         build_index.py               │
│                                      │
│  1. 初始化資料庫擴充套件               │
│  2. 執行 Alembic 遷移                 │
│  3. 匯入書卷、章節、經文               │
│  4. 計算段落嵌入向量                   │
└──────────────────────────────────────┘
       │
       ├──────────────────┬────────────────────┐
       ▼                  ▼                    ▼
┌──────────────┐   ┌──────────────┐   ┌──────────────┐
│ PostgreSQL   │   │    Neo4j     │   │   Ollama     │
│              │   │              │   │              │
│ • 書卷表     │   │ • Person 節點│   │ • 嵌入計算   │
│ • 章節表     │   │ • Topic 節點 │   │ • 摘要生成   │
│ • 經文表     │   │ • Event 節點 │   │              │
│ • 段落表     │   │ • 關係邊     │   │              │
│ • 向量索引   │   │              │   │              │
│ • FTS 索引   │   │              │   │              │
└──────────────┘   └──────────────┘   └──────────────┘
```

---

## 模組依賴關係

```
┌─────────────────────────────────────────────────────────────────┐
│                          app/main.py                            │
│                       (FastAPI 應用入口)                         │
└─────────────────────────────────────────────────────────────────┘
                                │
                                │ 引用
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                          app/core/                              │
│                                                                 │
│   config.py ◄──── database.py                                   │
│       ▲               │                                         │
│       │               │                                         │
│       └───────────────┴──── neo4j_client.py                     │
└─────────────────────────────────────────────────────────────────┘
                                │
                                │ 引用
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                         app/models/                             │
│                                                                 │
│   orm/                              schemas/                    │
│   ├── base.py                       ├── query.py                │
│   ├── book.py ◄───┐                 ├── book.py                 │
│   ├── chapter.py ◄┤                 ├── pericope.py             │
│   ├── verse.py ◄──┤                 ├── verse.py                │
│   ├── pericope.py◄┤                 └── graph.py                │
│   ├── entity.py   │                                             │
│   └── topic.py    │                                             │
│                   │ (外鍵關聯)                                   │
└─────────────────────────────────────────────────────────────────┘
                                │
                                │ 引用
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                        app/services/                            │
│                                                                 │
│   rag_pipeline.py                                               │
│        │                                                        │
│        ├──► embedding_service.py                                │
│        ├──► llm_client.py                                       │
│        ├──► fusion.py                                           │
│        ├──► context_builder.py                                  │
│        │                                                        │
│        └──► retrievers/                                         │
│             ├── base.py ◄─────────────────┐                     │
│             ├── dense_retriever.py ───────┤                     │
│             ├── sparse_retriever.py ──────┤                     │
│             └── graph_retriever.py ───────┘                     │
└─────────────────────────────────────────────────────────────────┘
                                │
                                │ 引用
                                ▼
┌─────────────────────────────────────────────────────────────────┐
│                           app/api/                              │
│                                                                 │
│   v1/                                                           │
│   ├── router.py ◄─────────────────────────┐                     │
│   ├── deps.py ◄───────────────────────────┤                     │
│   │                                       │                     │
│   └── endpoints/                          │                     │
│       ├── query.py ───────────────────────┤                     │
│       ├── books.py ───────────────────────┤                     │
│       ├── pericopes.py ───────────────────┤                     │
│       ├── verses.py ──────────────────────┤                     │
│       └── graph.py ───────────────────────┘                     │
└─────────────────────────────────────────────────────────────────┘
```

---

## 附錄：技術規格摘要

| 項目 | 規格 |
|------|------|
| **Python 版本** | 3.11+ |
| **Web 框架** | FastAPI 0.100+ |
| **ORM** | SQLAlchemy 2.0 (Async) |
| **資料庫** | PostgreSQL 15+ with pgvector |
| **圖資料庫** | Neo4j 5.x |
| **LLM** | Ollama (gemm3:4b) |
| **嵌入模型** | BAAI/bge-m3 (1024 維) |
| **向量索引** | IVFFlat (100 lists) |
| **全文搜尋** | PostgreSQL TSVECTOR + GIN |
| **融合演算法** | RRF (k=60) |

---

*文件版本: 1.0.0*
*最後更新: 2024*
