# Bible RAG - 聖經智慧問答系統

基於 RAG (Retrieval-Augmented Generation) 技術的聖經知識問答系統，結合向量檢索、全文搜尋與知識圖譜，提供智慧化的聖經探索體驗。

---

## 功能特色

| 功能 | 說明 |
|------|------|
| **RAG 智慧問答** | 自然語言提問，系統結合向量檢索與 LLM 生成答案，並展示相關經文出處 |
| **聖經瀏覽** | 結構化導航 66 卷書、章節與經文內容 |
| **知識圖譜視覺化** | 探索人物、地點、事件、主題之間的關係網絡 |
| **經文搜尋** | 支援全文搜尋，快速定位相關經文 |

---

## 技術棧

### 前端

| 技術 | 用途 |
|------|------|
| React 19 + TypeScript | UI 框架 |
| Vite (Rolldown) | 建構工具 |
| TanStack Query | 伺服器狀態管理 |
| Zustand | 客戶端狀態管理 |
| Tailwind CSS | 樣式框架 |
| D3.js | 知識圖譜視覺化 |
| Axios | HTTP 客戶端 |

### 後端

| 技術 | 用途 |
|------|------|
| FastAPI + Uvicorn | API 框架 |
| PostgreSQL + pgvector | 關聯式資料庫 + 向量搜尋 |
| Neo4j | 知識圖譜資料庫 (可選) |
| Ollama + gemma3:4b | 本地 LLM 推論 |
| BAAI/bge-m3 | 多語言嵌入模型 |
| SQLAlchemy + Alembic | ORM + 資料庫遷移 |

### 部署

| 技術 | 用途 |
|------|------|
| Docker + Docker Compose | 容器化部署 |
| Nginx | 反向代理 + 靜態檔案服務 |

---

## 系統架構

```
                                    +------------------+
                                    |     Browser      |
                                    +--------+---------+
                                             |
                                             | HTTP :80
                                             v
+------------------------------------------------------------------------------------+
|                                       Nginx                                         |
|                              (Reverse Proxy + Gzip)                                |
+------------------------------------------------------------------------------------+
        |                                                    |
        | /api/*                                             | /*
        v                                                    v
+-------------------+                              +-------------------+
|     Backend       |                              |     Frontend      |
|    (FastAPI)      |                              |  (React + Vite)   |
|      :8000        |                              |       :80         |
+--------+----------+                              +-------------------+
         |
         +------------------+------------------+------------------+
         |                  |                  |                  |
         v                  v                  v                  v
+----------------+  +----------------+  +----------------+  +----------------+
|   PostgreSQL   |  |     Neo4j      |  |    Ollama      |  |   Embedding    |
|   + pgvector   |  | (Knowledge     |  |   (LLM)        |  |   Service      |
|     :5432      |  |   Graph)       |  |    :11434      |  |   (bge-m3)     |
+----------------+  |  :7474/:7687   |  +----------------+  +----------------+
                    +----------------+
```

### 資料流程

```
使用者提問
    |
    v
[Query API] --> [Embedding Service] --> 向量化查詢
    |
    +---> [Dense Retriever] ---> pgvector 向量搜尋
    |
    +---> [Sparse Retriever] --> PostgreSQL 全文搜尋
    |
    +---> [Graph Retriever] ---> Neo4j 知識圖譜查詢
    |
    v
[Fusion (RRF)] --> 合併排序結果
    |
    v
[Context Builder] --> 組裝上下文
    |
    v
[LLM Client] --> Ollama 生成答案
    |
    v
返回答案 + 相關經文
```

---

## 快速開始

### 環境需求

- Docker 和 Docker Compose
- NVIDIA GPU (建議，用於 LLM 推論加速)
- 至少 16GB RAM
- 至少 20GB 磁碟空間

### Docker 部署 (一鍵部署)

```bash
# 1. 複製專案
git clone https://github.com/KenZx0521/bible_RAG.git
cd bible_RAG

# 2. 複製環境變數設定檔
cp .env.example .env

# 3. 構建並啟動服務 (不含 Neo4j)
docker compose up -d --build

# 或者，包含 Neo4j 知識圖譜
docker compose --profile full up -d --build

# 4. 首次啟動需下載 LLM 模型 (約 2.5GB)
docker compose exec ollama ollama pull gemma3:4b

# 5. 查看服務狀態
docker compose ps

# 6. 查看日誌 (可觀察初始化進度)
docker compose logs -f backend
```

### 首次啟動說明

首次啟動時，後端服務會自動執行以下初始化流程：

| 步驟 | 說明 | 預估時間 |
|------|------|----------|
| 1 | 等待 PostgreSQL 就緒 | ~10 秒 |
| 2 | 執行資料庫遷移 | ~5 秒 |
| 3 | 建立聖經索引 (解析 PDF) | ~10-15 分鐘 |
| 4 | 檢查 Neo4j 可用性 | ~5 秒 |
| 5 | 建置知識圖譜 (若啟用 Neo4j) | ~6-10 小時 |
| 6 | 啟動 API 服務 | 即時 |

> **注意**：
> - 可透過 `docker compose logs -f backend` 觀察初始化進度
> - 後續重啟會跳過已完成的步驟，幾秒內即可完成啟動
> - 知識圖譜建置需要使用 `--profile full` 啟動 Neo4j
> - 若知識圖譜建置中斷，支援斷點續傳

### 知識圖譜建置 (可選)

知識圖譜提供人物、地點、事件、主題的關係網絡探索功能。

```bash
# 使用 full profile 啟動 (包含 Neo4j)
docker compose --profile full up -d --build

# 知識圖譜建置會自動執行，包含：
# 1. LLM 實體標註 (6-10 小時)
# 2. Neo4j 圖譜建置
# 3. 主題關聯計算

# 若需手動執行或斷點續傳：
docker compose exec backend python -m scripts.entity_extractor --batch-size 10
docker compose exec backend python -m scripts.build_graph
docker compose exec backend python -m scripts.compute_topic_relations
```

### 訪問服務

| 服務 | 網址 |
|------|------|
| 主入口 (前端) | http://localhost |
| API 文檔 (Swagger) | http://localhost/api/v1/docs |
| API 文檔 (ReDoc) | http://localhost/api/v1/redoc |
| Neo4j Browser | http://localhost:7474 (需啟用 full profile) |

### 停止服務

```bash
# 停止所有服務
docker compose down

# 停止並清除資料卷 (警告：會刪除所有資料)
docker compose down -v
```

---

## 本地開發設置

### 後端開發

```bash
# 進入後端目錄
cd backend

# 建立 Python 虛擬環境 (Python 3.11+)
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或 venv\Scripts\activate  # Windows

# 安裝依賴
pip install -e ".[dev]"

# 複製環境變數
cp .env.example .env

# 執行資料庫遷移
alembic upgrade head

# 啟動開發伺服器
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### 前端開發

```bash
# 進入前端目錄
cd frontend

# 安裝依賴
npm install

# 啟動開發伺服器
npm run dev

# 建構生產版本
npm run build

# 程式碼檢查
npm run lint
```

### 開發環境服務依賴

本地開發時，仍需透過 Docker 啟動資料庫服務：

```bash
# 僅啟動資料庫和 Ollama
docker compose up -d postgres ollama

# 包含 Neo4j
docker compose --profile full up -d postgres neo4j ollama
```

---

## 環境變數說明

複製 `.env.example` 為 `.env` 並依需求調整：

### PostgreSQL 設定

| 變數 | 預設值 | 說明 |
|------|--------|------|
| `POSTGRES_USER` | `bible_user` | 資料庫使用者名稱 |
| `POSTGRES_PASSWORD` | `bible_password` | 資料庫密碼 |
| `POSTGRES_DB` | `bible_rag` | 資料庫名稱 |
| `POSTGRES_HOST` | `postgres` | 資料庫主機 |
| `POSTGRES_PORT` | `5432` | 資料庫端口 |

### Neo4j 設定 (可選)

| 變數 | 預設值 | 說明 |
|------|--------|------|
| `NEO4J_USER` | `neo4j` | Neo4j 使用者名稱 |
| `NEO4J_PASSWORD` | `neo4j_password` | Neo4j 密碼 |
| `NEO4J_URI` | `bolt://neo4j:7687` | Neo4j 連線 URI |

### Ollama LLM 設定

| 變數 | 預設值 | 說明 |
|------|--------|------|
| `OLLAMA_BASE_URL` | `http://ollama:11434` | Ollama 服務位址 |
| `LLM_MODEL_NAME` | `gemma3:4b` | 使用的 LLM 模型 |
| `LLM_TEMPERATURE` | `0.7` | 生成溫度 (0-1) |
| `LLM_MAX_TOKENS` | `2048` | 最大生成 token 數 |

### 嵌入模型設定

| 變數 | 預設值 | 說明 |
|------|--------|------|
| `EMBED_MODEL_NAME` | `BAAI/bge-m3` | 嵌入模型名稱 |
| `EMBED_BATCH_SIZE` | `32` | 批次處理大小 |
| `EMBED_USE_FP16` | `true` | 使用 FP16 精度 |
| `EMBED_DEVICE` | `cuda` | 運算裝置 (cuda/cpu) |

### RAG 參數

| 變數 | 預設值 | 說明 |
|------|--------|------|
| `RRF_K` | `60` | RRF 融合參數 |
| `MAX_RETRIEVE_RESULTS` | `20` | 最大檢索結果數 |
| `MAX_CONTEXT_TOKENS` | `4000` | 上下文最大 token 數 |
| `TOP_K_PERICOPES` | `5` | 返回的段落數量 |

### 應用程式設定

| 變數 | 預設值 | 說明 |
|------|--------|------|
| `APP_NAME` | `Bible RAG API` | 應用程式名稱 |
| `VERSION` | `0.1.0` | 版本號 |
| `DEBUG` | `false` | 除錯模式 |
| `API_V1_PREFIX` | `/api/v1` | API 路徑前綴 |
| `ALLOWED_ORIGINS` | `http://localhost:5173,...` | CORS 允許來源 |
| `LOG_LEVEL` | `INFO` | 日誌等級 |

---

## API 端點概覽

### 健康檢查

| 方法 | 端點 | 說明 |
|------|------|------|
| GET | `/health` | 應用程式健康狀態 |

### RAG 查詢

| 方法 | 端點 | 說明 |
|------|------|------|
| POST | `/api/v1/query` | 執行 RAG 查詢，返回 LLM 生成答案與相關經文 |

### 書卷 (Books)

| 方法 | 端點 | 說明 |
|------|------|------|
| GET | `/api/v1/books` | 取得所有書卷列表 |
| GET | `/api/v1/books/{book_id}` | 取得單一書卷詳情 |
| GET | `/api/v1/books/{book_id}/chapters` | 取得書卷的章節列表 |
| GET | `/api/v1/books/{book_id}/pericopes` | 取得書卷的段落列表 |
| GET | `/api/v1/books/{book_id}/verses` | 取得書卷的經文列表 |

### 段落 (Pericopes)

| 方法 | 端點 | 說明 |
|------|------|------|
| GET | `/api/v1/pericopes` | 取得段落列表 (分頁) |
| GET | `/api/v1/pericopes/{pericope_id}` | 取得單一段落詳情 |

### 經文 (Verses)

| 方法 | 端點 | 說明 |
|------|------|------|
| GET | `/api/v1/verses` | 取得經文列表 (分頁) |
| GET | `/api/v1/verses/search` | 經文全文搜尋 |
| GET | `/api/v1/verses/{verse_id}` | 取得單一經文詳情 |

### 知識圖譜 (Graph)

| 方法 | 端點 | 說明 |
|------|------|------|
| GET | `/api/v1/graph/health` | 知識圖譜服務健康狀態 |
| GET | `/api/v1/graph/stats` | 圖譜統計資訊 |
| GET | `/api/v1/graph/entity/search` | 搜尋實體 (人物、地點等) |
| GET | `/api/v1/graph/entity/{entity_id}` | 取得實體詳情 |
| GET | `/api/v1/graph/topic/search` | 搜尋主題 |
| GET | `/api/v1/graph/topic/{topic_id}` | 取得主題詳情 |
| GET | `/api/v1/graph/topic/{topic_id}/related` | 取得相關主題 |
| GET | `/api/v1/graph/relationships` | 取得關係圖資料 |
| GET | `/api/v1/graph/verse/{verse_id}/entities` | 取得經文相關實體 |
| GET | `/api/v1/graph/verse/{verse_id}/cross-references` | 取得交叉引用 |
| GET | `/api/v1/graph/verse/{verse_id}/prophecies` | 取得預言關聯 |
| GET | `/api/v1/graph/pericope/{pericope_id}/parallels` | 取得平行經文 |

完整 API 文檔請參閱：http://localhost/api/v1/docs

---

## 專案結構

```
bible_RAG/
├── backend/                    # 後端應用程式
│   ├── app/
│   │   ├── api/
│   │   │   └── v1/
│   │   │       ├── endpoints/  # API 端點
│   │   │       │   ├── books.py
│   │   │       │   ├── graph.py
│   │   │       │   ├── pericopes.py
│   │   │       │   ├── query.py
│   │   │       │   └── verses.py
│   │   │       └── router.py
│   │   ├── core/               # 核心設定
│   │   │   ├── config.py       # 應用程式設定
│   │   │   ├── database.py     # 資料庫連線
│   │   │   └── neo4j_client.py # Neo4j 客戶端
│   │   ├── models/
│   │   │   ├── orm/            # SQLAlchemy ORM 模型
│   │   │   └── schemas/        # Pydantic 資料模型
│   │   ├── services/           # 業務邏輯
│   │   │   ├── retrievers/     # 檢索器
│   │   │   │   ├── dense_retriever.py
│   │   │   │   ├── sparse_retriever.py
│   │   │   │   └── graph_retriever.py
│   │   │   ├── context_builder.py
│   │   │   ├── embedding_service.py
│   │   │   ├── fusion.py       # RRF 融合
│   │   │   ├── llm_client.py   # Ollama 客戶端
│   │   │   └── rag_pipeline.py # RAG 管線
│   │   └── main.py             # 應用程式入口
│   ├── scripts/                # 工具腳本
│   ├── tests/                  # 測試檔案
│   ├── Dockerfile
│   ├── pyproject.toml          # Python 專案設定
│   └── requirements.txt
│
├── frontend/                   # 前端應用程式
│   ├── src/
│   │   ├── api/                # API 客戶端
│   │   │   └── endpoints/
│   │   ├── components/
│   │   │   ├── bible/          # 聖經瀏覽元件
│   │   │   ├── common/         # 共用元件
│   │   │   ├── graph/          # 知識圖譜元件
│   │   │   ├── layout/         # 版面元件
│   │   │   └── search/         # 搜尋元件
│   │   ├── hooks/
│   │   │   └── api/            # API Hooks (TanStack Query)
│   │   ├── pages/              # 頁面元件
│   │   ├── stores/             # Zustand 狀態管理
│   │   ├── types/              # TypeScript 型別定義
│   │   ├── utils/              # 工具函式
│   │   ├── App.tsx
│   │   ├── router.tsx
│   │   └── index.css
│   ├── Dockerfile
│   ├── nginx.conf
│   ├── package.json
│   └── vite.config.ts
│
├── nginx/                      # Nginx 反向代理
│   ├── Dockerfile
│   └── nginx.conf
│
├── docker-compose.yml          # Docker Compose 設定
├── .env.example                # 環境變數範本
└── README.md
```

---

## 服務端口

| 服務 | 端口 | 說明 |
|------|------|------|
| Nginx | 80 | 主入口 (反向代理) |
| Backend API | 8000 | FastAPI 後端服務 |
| PostgreSQL | 5432 | 資料庫 |
| Neo4j HTTP | 7474 | Neo4j 瀏覽器介面 |
| Neo4j Bolt | 7687 | Neo4j 連線協定 |
| Ollama | 11434 | LLM 推論服務 |

---

## 貢獻指南

歡迎提交 Issue 和 Pull Request！

### 開發流程

1. Fork 此專案
2. 建立功能分支 (`git checkout -b feature/amazing-feature`)
3. 提交變更 (`git commit -m 'Add amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 開啟 Pull Request

### 程式碼規範

- **後端**: 使用 Ruff 進行程式碼格式化與檢查
- **前端**: 使用 ESLint 進行程式碼檢查

```bash
# 後端程式碼檢查
cd backend
ruff check .
ruff format .

# 前端程式碼檢查
cd frontend
npm run lint
```

### 提交訊息格式

請使用語意化提交訊息：

- `feat:` 新功能
- `fix:` 錯誤修復
- `docs:` 文檔更新
- `style:` 程式碼格式調整
- `refactor:` 程式碼重構
- `test:` 測試相關
- `chore:` 建構/工具相關

---

## 常見問題

### Ollama 模型下載失敗

```bash
# 檢查 Ollama 服務狀態
docker compose logs ollama

# 手動進入容器下載
docker compose exec ollama bash
ollama pull gemma3:4b
```

### GPU 加速未生效

確認 NVIDIA Container Toolkit 已安裝：

```bash
# 檢查 GPU 是否可用
docker run --rm --gpus all nvidia/cuda:12.0-base nvidia-smi
```

### 資料庫連線失敗

```bash
# 檢查資料庫容器狀態
docker compose ps postgres

# 查看資料庫日誌
docker compose logs postgres
```

---

## 授權

本專案採用 [MIT 授權](https://opensource.org/licenses/MIT)。

---

## 致謝

- 聖經經文來源：新標點和合本
- [FastAPI](https://fastapi.tiangolo.com/) - 現代 Python Web 框架
- [Ollama](https://ollama.ai/) - 本地 LLM 推論
- [pgvector](https://github.com/pgvector/pgvector) - PostgreSQL 向量擴充
- [bge-m3](https://huggingface.co/BAAI/bge-m3) - 多語言嵌入模型
