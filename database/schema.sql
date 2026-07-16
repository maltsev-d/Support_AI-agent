CREATE EXTENSION IF NOT EXISTS vector;

-- Пользователи (Telegram)
CREATE TABLE users (
    id BIGSERIAL PRIMARY KEY,
    telegram_id BIGINT UNIQUE NOT NULL,
    username TEXT,
    first_seen_at TIMESTAMPTZ DEFAULT now(),
    is_blocked BOOLEAN DEFAULT false
);

-- Диалоги (сессия = один "заход" юзера, не вся история жизни)
CREATE TABLE conversations (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(id),
    status TEXT NOT NULL DEFAULT 'active',
        -- active | escalated | resolved | abandoned
    created_at TIMESTAMPTZ DEFAULT now(),
    last_message_at TIMESTAMPTZ DEFAULT now()
);

-- Сообщения внутри диалога
CREATE TABLE messages (
    id BIGSERIAL PRIMARY KEY,
    conversation_id BIGINT REFERENCES conversations(id),
    role TEXT NOT NULL,        -- user | assistant | system
    content TEXT NOT NULL,
    intent TEXT,               -- результат классификатора, nullable
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Эскалации (отдельно от conversations — это уже "инцидент")
CREATE TABLE escalations (
    id BIGSERIAL PRIMARY KEY,
    conversation_id BIGINT REFERENCES conversations(id),
    reason TEXT NOT NULL,        -- low_confidence | user_angry | manual
    summary TEXT,                -- то, что уйдёт в Telegram-группу оператору
    status TEXT DEFAULT 'pending', -- pending | active | handled
    created_at TIMESTAMPTZ DEFAULT now(),
    handled_at TIMESTAMPTZ
);

-- Follow-up задачи (для n8n Schedule Trigger)
CREATE TABLE followups (
    id BIGSERIAL PRIMARY KEY,
    conversation_id BIGINT REFERENCES conversations(id),
    due_at TIMESTAMPTZ NOT NULL,
    status TEXT DEFAULT 'scheduled', -- scheduled | sent | cancelled
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE INDEX idx_messages_conversation_id
ON messages(conversation_id);

CREATE INDEX idx_conversations_user_id
ON conversations(user_id);

CREATE INDEX idx_messages_created_at
ON messages(created_at);

-- База знаний + векторный поиск (RAG)
-- Откуда приходят документы
CREATE TABLE kb_sources (
    id BIGSERIAL PRIMARY KEY,
    source_type TEXT NOT NULL,				-- Тип источника данных. Например:google_drive, website, manual_upload
    source_id TEXT NOT NULL,				-- Внешний ID источника. Для Google Drive: folder_idб; Для сайта: URL
    category TEXT NOT NULL,					-- Категория знаний. Используется для маршрутизации RAG. Например: company, cars, equipment
    created_at TIMESTAMPTZ DEFAULT now(),	-- Когда подключили источник
    updated_at TIMESTAMPTZ DEFAULT now(),	-- Обновление настроек источника
    UNIQUE(source_type, source_id)			-- Запрещаем два одинаковых источника
);

-- Какой файл породил эти embeddings
CREATE TABLE documents (
    id BIGSERIAL PRIMARY KEY,
    document_id TEXT UNIQUE NOT NULL,	-- ID документа во внешней системе. Например: Google Drive file_id
    source_id BIGINT
        REFERENCES kb_sources(id)
        ON DELETE CASCADE,				-- Связь с источником
	filename TEXT NOT NULL,				-- Имя файла
	external_url TEXT,					-- URL документа
    category TEXT NOT NULL,				-- Категория
    mime_type TEXT,						-- Тип файла
    hash TEXT,							-- Хеш содержимого файла. Нужен для проверки изменений
    file_size BIGINT,					-- Размер файла
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Здесь лежит RAG индекс
CREATE TABLE kb_chunks (
    id BIGSERIAL PRIMARY KEY,
    document_id BIGINT NOT NULL
        REFERENCES documents(id)
        ON DELETE CASCADE,			-- Родительский документ
    chunk_index INT NOT NULL
    	CHECK(chunk_index >= 0),	-- Номер чанка внутри документа
    content TEXT NOT NULL,			-- Текст чанка
    token_count INT,				-- Размер чанка
    metadata JSONB,
    language TEXT DEFAULT 'ru',		-- Язык текста
    embedding VECTOR(1024),			-- Вектор embeddings
    created_at TIMESTAMPTZ DEFAULT now()
    UNIQUE(document_id, chunk_index)
);

-- Индекс документов
CREATE INDEX idx_documents_document_id
ON documents(document_id);

-- Индекс категории
CREATE INDEX idx_documents_category
ON documents(category);

-- Индекс chunk document_id (для удаления)
CREATE INDEX idx_chunks_document_id
ON kb_chunks(document_id);

--Главный индекс pgvector
CREATE INDEX idx_kb_chunks_embedding
ON kb_chunks USING hnsw (embedding vector_cosine_ops);
---------------------------------------------------------

CREATE TYPE intent_type AS ENUM (
    'жалоба',
    'оплата',
    'вопрос_по_продукту',
    'вопрос_по_компании',
    'техподдержка',
    'доставка',
    'спам',
    'другое'
);

ALTER TABLE messages ALTER COLUMN intent TYPE intent_type USING intent::intent_type;
