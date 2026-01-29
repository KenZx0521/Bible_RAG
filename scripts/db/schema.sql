-- Bible RAG PostgreSQL Schema
-- Requires pgvector extension (automatically available in pgvector/pgvector image)

CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================
-- Books Table
-- ============================================
CREATE TABLE books (
    id VARCHAR(10) PRIMARY KEY,
    type VARCHAR(20) NOT NULL DEFAULT 'book',
    name VARCHAR(100) NOT NULL,
    name_en VARCHAR(100) NOT NULL,
    testament VARCHAR(10) NOT NULL CHECK (testament IN ('old', 'new')),
    category VARCHAR(50) NOT NULL,
    "order" INTEGER NOT NULL,
    total_chapters INTEGER NOT NULL,
    total_pericopes INTEGER NOT NULL,
    total_verses INTEGER NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_books_testament ON books(testament);
CREATE INDEX idx_books_category ON books(category);
CREATE INDEX idx_books_order ON books("order");

-- ============================================
-- Chapters Table
-- ============================================
CREATE TABLE chapters (
    id VARCHAR(20) PRIMARY KEY,
    type VARCHAR(20) NOT NULL DEFAULT 'chapter',
    parent_id VARCHAR(10) NOT NULL REFERENCES books(id) ON DELETE CASCADE,
    chapter_num INTEGER NOT NULL,
    total_verses INTEGER NOT NULL,
    total_pericopes INTEGER NOT NULL,
    metadata JSONB DEFAULT '{}',
    footnotes JSONB DEFAULT '[]',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_chapters_parent ON chapters(parent_id);
CREATE INDEX idx_chapters_num ON chapters(chapter_num);

-- ============================================
-- Pericopes Table
-- ============================================
CREATE TABLE pericopes (
    id VARCHAR(30) PRIMARY KEY,
    type VARCHAR(20) NOT NULL DEFAULT 'pericope',
    parent_id VARCHAR(20) NOT NULL REFERENCES chapters(id) ON DELETE CASCADE,
    title VARCHAR(200) NOT NULL,
    content TEXT NOT NULL,
    content_for_embedding TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    cross_references JSONB DEFAULT '[]',
    verses JSONB DEFAULT '[]',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_pericopes_parent ON pericopes(parent_id);
CREATE INDEX idx_pericopes_title ON pericopes(title);

-- ============================================
-- Chunks Table
-- ============================================
CREATE TABLE chunks (
    id VARCHAR(40) PRIMARY KEY,
    type VARCHAR(20) NOT NULL DEFAULT 'chunk',
    parent_id VARCHAR(30) NOT NULL REFERENCES pericopes(id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    content_for_embedding TEXT NOT NULL,
    metadata JSONB DEFAULT '{}',
    verses JSONB DEFAULT '[]',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_chunks_parent ON chunks(parent_id);

-- ============================================
-- Entities Table
-- ============================================
CREATE TABLE entities (
    entity_id VARCHAR(100) PRIMARY KEY,
    type VARCHAR(50) NOT NULL,
    canonical_name VARCHAR(200) NOT NULL,
    aliases JSONB DEFAULT '[]',
    description TEXT,
    extraction_method VARCHAR(20) NOT NULL,
    mention_count INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_entities_type ON entities(type);
CREATE INDEX idx_entities_name ON entities(canonical_name);
CREATE INDEX idx_entities_mention_count ON entities(mention_count DESC);

-- ============================================
-- Entity Mentions Table
-- ============================================
CREATE TABLE entity_mentions (
    mention_id VARCHAR(100) PRIMARY KEY,
    entity_id VARCHAR(100) NOT NULL REFERENCES entities(entity_id) ON DELETE CASCADE,
    source_id VARCHAR(50) NOT NULL,
    source_type VARCHAR(20) NOT NULL,
    text_span VARCHAR(200) NOT NULL,
    context TEXT,
    start_pos INTEGER,
    end_pos INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_mentions_entity ON entity_mentions(entity_id);
CREATE INDEX idx_mentions_source ON entity_mentions(source_id);
CREATE INDEX idx_mentions_source_type ON entity_mentions(source_type);

-- ============================================
-- Embedding Queue View (for reference)
-- ============================================
CREATE VIEW embedding_sources AS
SELECT 
    id,
    'pericope' as source_type,
    content_for_embedding,
    metadata
FROM pericopes
WHERE (metadata->>'requires_chunking')::boolean = false OR metadata->>'requires_chunking' IS NULL
UNION ALL
SELECT 
    id,
    'chunk' as source_type,
    content_for_embedding,
    metadata
FROM chunks;

-- Grant permissions
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO bible;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO bible;
