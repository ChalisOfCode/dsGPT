"""Forward-only, transactional schema changes. No migration may execute user content."""

VERSION_2 = """
CREATE TABLE memories (
 id TEXT PRIMARY KEY, task_id TEXT REFERENCES work_tasks(id),
 title TEXT NOT NULL, content TEXT NOT NULL, source TEXT NOT NULL,
 revision INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX memories_scope ON memories(task_id,updated_at);
CREATE VIRTUAL TABLE memories_fts USING fts5(
 title,content,content='memories',content_rowid='rowid'
);
CREATE TRIGGER memories_insert AFTER INSERT ON memories BEGIN
 INSERT INTO memories_fts(rowid,title,content) VALUES(new.rowid,new.title,new.content);
END;
CREATE TRIGGER memories_delete AFTER DELETE ON memories BEGIN
 INSERT INTO memories_fts(memories_fts,rowid,title,content)
 VALUES('delete',old.rowid,old.title,old.content);
END;
CREATE TRIGGER memories_update AFTER UPDATE ON memories BEGIN
 INSERT INTO memories_fts(memories_fts,rowid,title,content)
 VALUES('delete',old.rowid,old.title,old.content);
 INSERT INTO memories_fts(rowid,title,content) VALUES(new.rowid,new.title,new.content);
END;
CREATE TABLE work_sessions (
 task_id TEXT PRIMARY KEY REFERENCES work_tasks(id), model_id TEXT NOT NULL,
 step INTEGER NOT NULL DEFAULT 0, summary TEXT NOT NULL DEFAULT '',
 error_code TEXT, last_action_hash TEXT, repeated_actions INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE work_steps (
 task_id TEXT NOT NULL REFERENCES work_tasks(id), step INTEGER NOT NULL,
 action TEXT NOT NULL, result TEXT NOT NULL, created_at TEXT NOT NULL,
 PRIMARY KEY(task_id,step)
);
CREATE TABLE work_files (
 task_id TEXT NOT NULL REFERENCES work_tasks(id), path TEXT NOT NULL,
 content TEXT NOT NULL, sha256 TEXT NOT NULL, revision INTEGER NOT NULL,
 updated_at TEXT NOT NULL, PRIMARY KEY(task_id,path)
);
CREATE TABLE scheduler_state (
 id INTEGER PRIMARY KEY CHECK(id=1), chat_streak INTEGER NOT NULL DEFAULT 0,
 chat_grants INTEGER NOT NULL DEFAULT 0, work_grants INTEGER NOT NULL DEFAULT 0
);
INSERT INTO scheduler_state(id) VALUES(1);
CREATE TABLE model_records (
 id TEXT PRIMARY KEY, definition TEXT NOT NULL, verified_at TEXT NOT NULL
);
CREATE TABLE work_creation_requests (
 task_id TEXT PRIMARY KEY REFERENCES work_tasks(id), request_hash TEXT NOT NULL
);
"""

VERSION_3 = """
CREATE TABLE downloads (
 id TEXT PRIMARY KEY, asset_id TEXT NOT NULL UNIQUE, definition TEXT NOT NULL,
 status TEXT NOT NULL, downloaded INTEGER NOT NULL DEFAULT 0,
 error_code TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
"""

VERSION_4 = """
CREATE TABLE runtime_installations (
 id TEXT PRIMARY KEY, definition TEXT NOT NULL, manifest TEXT NOT NULL,
 installed_at TEXT NOT NULL
);
CREATE TABLE runtime_sources (
 runtime_id TEXT NOT NULL REFERENCES runtime_installations(id) ON DELETE CASCADE,
 asset_id TEXT NOT NULL REFERENCES downloads(asset_id),
 PRIMARY KEY(runtime_id,asset_id)
);
CREATE TABLE managed_models (
 model_id TEXT PRIMARY KEY REFERENCES model_records(id) ON DELETE CASCADE,
 asset_id TEXT NOT NULL REFERENCES downloads(asset_id),
 runtime_id TEXT NOT NULL REFERENCES runtime_installations(id),
 gpu_layers INTEGER NOT NULL CHECK(gpu_layers BETWEEN 0 AND 999)
);
"""

VERSION_5 = """
CREATE TABLE run_research (
 run_id TEXT PRIMARY KEY REFERENCES runs(id), definition TEXT NOT NULL,
 plan TEXT, retrieval_complete INTEGER NOT NULL DEFAULT 0, warnings TEXT NOT NULL DEFAULT '[]'
);
CREATE TABLE web_sources (
 id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES runs(id), url TEXT NOT NULL,
 status TEXT NOT NULL, document TEXT, error_code TEXT,
 UNIQUE(run_id,url)
);
CREATE INDEX web_sources_run ON web_sources(run_id);
"""

VERSION_6 = """
CREATE TABLE memory_creation_requests (
 memory_id TEXT PRIMARY KEY, request_hash TEXT NOT NULL
);
"""

VERSION_7 = """
CREATE TABLE work_sources (
 task_id TEXT NOT NULL REFERENCES work_tasks(id), source_id TEXT NOT NULL, url TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('pending','retrieved','failed')),
 document TEXT, error_code TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 PRIMARY KEY(task_id,source_id), UNIQUE(task_id,url)
);
CREATE INDEX work_sources_pending ON work_sources(task_id,status);
"""

VERSION_8 = """
CREATE TABLE search_settings (
 id INTEGER PRIMARY KEY CHECK(id=1), origin TEXT,
 revision INTEGER NOT NULL, updated_at TEXT NOT NULL, probe TEXT
);
INSERT INTO search_settings VALUES(1,NULL,0,'',NULL);
"""

VERSION_9 = """
CREATE TABLE message_attachments (
 id TEXT PRIMARY KEY, message_id TEXT NOT NULL REFERENCES messages(id),
 name TEXT NOT NULL, text TEXT, bytes INTEGER NOT NULL, sha256 TEXT NOT NULL,
 created_at TEXT NOT NULL, removed INTEGER NOT NULL DEFAULT 0,
 CHECK((removed=0 AND text IS NOT NULL) OR (removed=1 AND text IS NULL))
);
CREATE INDEX message_attachments_message ON message_attachments(message_id);
"""

VERSION_10 = """
CREATE TABLE history_batches (
 id TEXT PRIMARY KEY, request_hash TEXT NOT NULL, archive_sha256 TEXT NOT NULL,
 created_at TEXT NOT NULL, result TEXT NOT NULL
);
CREATE TABLE history_sources (
 conversation_id TEXT PRIMARY KEY REFERENCES conversations(id),
 source_id TEXT NOT NULL, source_sha256 TEXT NOT NULL, source_title TEXT,
 source_created_at TEXT, source_updated_at TEXT, current_node TEXT NOT NULL,
 member TEXT NOT NULL, omissions TEXT NOT NULL, parser TEXT NOT NULL,
 batch_id TEXT NOT NULL REFERENCES history_batches(id), imported_at TEXT NOT NULL,
 removed INTEGER NOT NULL DEFAULT 0,
 UNIQUE(source_id,source_sha256)
);
CREATE TABLE history_messages (
 message_id TEXT PRIMARY KEY REFERENCES messages(id), source_node_id TEXT NOT NULL,
 source_created_at TEXT, content_sha256 TEXT NOT NULL
);
CREATE TABLE history_tombstones (
 source_id TEXT PRIMARY KEY, removed_at TEXT NOT NULL
);
CREATE VIRTUAL TABLE messages_fts USING fts5(
 content,content='messages',content_rowid='rowid'
);
CREATE TRIGGER messages_fts_insert AFTER INSERT ON messages BEGIN
 INSERT INTO messages_fts(rowid,content) VALUES(new.rowid,new.content);
END;
CREATE TRIGGER messages_fts_delete AFTER DELETE ON messages BEGIN
 INSERT INTO messages_fts(messages_fts,rowid,content) VALUES('delete',old.rowid,old.content);
END;
CREATE TRIGGER messages_fts_update AFTER UPDATE OF content ON messages
WHEN new.content != old.content BEGIN
 INSERT INTO messages_fts(messages_fts,rowid,content) VALUES('delete',old.rowid,old.content);
 INSERT INTO messages_fts(rowid,content) VALUES(new.rowid,new.content);
END;
INSERT INTO messages_fts(messages_fts) VALUES('rebuild');
"""

VERSION_11 = """
CREATE TABLE semantic_settings (
 id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL DEFAULT 0,
 history_enabled INTEGER NOT NULL DEFAULT 0, revision INTEGER NOT NULL DEFAULT 0
);
INSERT INTO semantic_settings(id) VALUES(1);
CREATE TABLE semantic_jobs (
 kind TEXT NOT NULL CHECK(kind IN ('memory','history')), source_id TEXT NOT NULL,
 generation INTEGER NOT NULL DEFAULT 1, status TEXT NOT NULL DEFAULT 'pending',
 omitted_chars INTEGER NOT NULL DEFAULT 0, error_code TEXT,
 PRIMARY KEY(kind,source_id)
);
CREATE TABLE semantic_chunks (
 kind TEXT NOT NULL, source_id TEXT NOT NULL, ordinal INTEGER NOT NULL,
 generation INTEGER NOT NULL, start INTEGER NOT NULL, end INTEGER NOT NULL,
 vector BLOB NOT NULL CHECK(length(vector)=1536),
 PRIMARY KEY(kind,source_id,ordinal),
 FOREIGN KEY(kind,source_id) REFERENCES semantic_jobs(kind,source_id) ON DELETE CASCADE
);
CREATE INDEX semantic_pending ON semantic_jobs(status,kind);
CREATE TRIGGER semantic_memory_insert AFTER INSERT ON memories BEGIN
 INSERT INTO semantic_jobs(kind,source_id) VALUES('memory',new.id);
END;
CREATE TRIGGER semantic_memory_update AFTER UPDATE ON memories BEGIN
 DELETE FROM semantic_chunks WHERE kind='memory' AND source_id=old.id;
 UPDATE semantic_jobs SET generation=generation+1,status='pending',
 omitted_chars=0,error_code=NULL WHERE kind='memory' AND source_id=new.id;
END;
CREATE TRIGGER semantic_memory_delete AFTER DELETE ON memories BEGIN
 DELETE FROM semantic_jobs WHERE kind='memory' AND source_id=old.id;
END;
CREATE TRIGGER semantic_message_insert AFTER INSERT ON messages
WHEN new.status='completed' AND new.content!='' AND new.role IN ('user','assistant') BEGIN
 INSERT INTO semantic_jobs(kind,source_id) VALUES('history',new.id);
END;
CREATE TRIGGER semantic_message_update AFTER UPDATE OF content,status ON messages
WHEN new.content!=old.content OR new.status!=old.status BEGIN
 DELETE FROM semantic_chunks WHERE kind='history' AND source_id=old.id;
 UPDATE semantic_jobs SET generation=generation+1,status='pending',
 omitted_chars=0,error_code=NULL WHERE kind='history' AND source_id=new.id;
 INSERT OR IGNORE INTO semantic_jobs(kind,source_id)
 SELECT 'history',new.id WHERE new.status='completed' AND new.content!=''
 AND new.role IN ('user','assistant');
 DELETE FROM semantic_jobs WHERE kind='history' AND source_id=new.id
 AND (new.status!='completed' OR new.content='' OR new.role NOT IN ('user','assistant'));
END;
CREATE TRIGGER semantic_message_delete AFTER DELETE ON messages BEGIN
 DELETE FROM semantic_jobs WHERE kind='history' AND source_id=old.id;
END;
INSERT INTO semantic_jobs(kind,source_id) SELECT 'memory',id FROM memories;
INSERT INTO semantic_jobs(kind,source_id) SELECT 'history',id FROM messages
 WHERE status='completed' AND content!='' AND role IN ('user','assistant');
"""

VERSION_12 = """
CREATE TABLE sandbox_identity (id INTEGER PRIMARY KEY CHECK(id=1), owner_id TEXT NOT NULL);
INSERT INTO sandbox_identity VALUES(1,lower(hex(randomblob(16))));
CREATE TABLE work_build_profiles (
 task_id TEXT PRIMARY KEY REFERENCES work_tasks(id), target TEXT NOT NULL
 CHECK(target IN ('files','apk','exe'))
);
CREATE TABLE work_executions (
 id TEXT PRIMARY KEY, task_id TEXT REFERENCES work_tasks(id), step INTEGER,
 action TEXT NOT NULL, snapshot_sha256 TEXT NOT NULL, image_id TEXT,
 status TEXT NOT NULL, result TEXT, cleanup_pending INTEGER NOT NULL DEFAULT 1,
 recorded INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 UNIQUE(task_id,step)
);
CREATE TABLE work_artifacts (
 id TEXT PRIMARY KEY, execution_id TEXT NOT NULL REFERENCES work_executions(id),
 task_id TEXT NOT NULL REFERENCES work_tasks(id), path TEXT NOT NULL,
 sha256 TEXT NOT NULL, bytes INTEGER NOT NULL, content BLOB NOT NULL,
 UNIQUE(execution_id,path)
);
CREATE INDEX work_artifacts_task ON work_artifacts(task_id);
"""

VERSION_13 = """
CREATE TABLE attachment_documents (
 id TEXT PRIMARY KEY REFERENCES message_attachments(id), original BLOB,
 extraction TEXT NOT NULL
);
"""

VERSION_14 = """
ALTER TABLE work_sources RENAME TO work_sources_v13;
DROP INDEX work_sources_pending;
CREATE TABLE work_sources (
 task_id TEXT NOT NULL REFERENCES work_tasks(id), source_id TEXT NOT NULL, url TEXT NOT NULL,
 status TEXT NOT NULL CHECK(status IN ('pending','retrieved','failed','removed')),
 document TEXT, error_code TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
 generation INTEGER NOT NULL DEFAULT 1 CHECK(generation>=1),
 PRIMARY KEY(task_id,source_id), UNIQUE(task_id,url)
);
INSERT INTO work_sources SELECT *,1 FROM work_sources_v13;
DROP TABLE work_sources_v13;
CREATE INDEX work_sources_pending ON work_sources(task_id,status);
CREATE TABLE work_source_requests (
 task_id TEXT NOT NULL REFERENCES work_tasks(id), request_id TEXT NOT NULL,
 definition TEXT NOT NULL, PRIMARY KEY(task_id,request_id)
);
"""

VERSION_15 = """
CREATE VIRTUAL TABLE attachments_fts USING fts5(
 name,text,content='message_attachments',content_rowid='rowid'
);
CREATE TRIGGER attachments_ai AFTER INSERT ON message_attachments BEGIN
 INSERT INTO attachments_fts(rowid,name,text) VALUES(new.rowid,new.name,new.text);
END;
CREATE TRIGGER attachments_ad AFTER DELETE ON message_attachments BEGIN
 INSERT INTO attachments_fts(attachments_fts,rowid,name,text)
 VALUES('delete',old.rowid,old.name,old.text);
END;
CREATE TRIGGER attachments_au AFTER UPDATE ON message_attachments BEGIN
 INSERT INTO attachments_fts(attachments_fts,rowid,name,text)
 VALUES('delete',old.rowid,old.name,old.text);
 INSERT INTO attachments_fts(rowid,name,text) VALUES(new.rowid,new.name,new.text);
END;
INSERT INTO attachments_fts(attachments_fts) VALUES('rebuild');
"""

# Preserve existing vectors and generations while extending the source-kind constraint.
VERSION_16 = (
    """
ALTER TABLE semantic_settings ADD COLUMN attachments_enabled INTEGER NOT NULL DEFAULT 0;
CREATE TEMP TABLE saved_semantic_jobs AS SELECT * FROM semantic_jobs;
CREATE TEMP TABLE saved_semantic_chunks AS SELECT * FROM semantic_chunks;
DROP TRIGGER semantic_memory_insert;
DROP TRIGGER semantic_memory_update;
DROP TRIGGER semantic_memory_delete;
DROP TRIGGER semantic_message_insert;
DROP TRIGGER semantic_message_update;
DROP TRIGGER semantic_message_delete;
DROP TABLE semantic_chunks;
DROP TABLE semantic_jobs;
"""
    + VERSION_11[
        VERSION_11.index("CREATE TABLE semantic_jobs") : VERSION_11.index(
            "INSERT INTO semantic_jobs(kind,source_id) SELECT 'memory'"
        )
    ].replace("('memory','history')", "('memory','history','attachment')")
    + """
INSERT INTO semantic_jobs SELECT * FROM saved_semantic_jobs;
INSERT INTO semantic_chunks SELECT * FROM saved_semantic_chunks;
DROP TABLE saved_semantic_jobs;
DROP TABLE saved_semantic_chunks;
CREATE TRIGGER semantic_attachment_insert AFTER INSERT ON message_attachments
WHEN new.removed=0 AND new.text!='' BEGIN
 INSERT INTO semantic_jobs(kind,source_id) VALUES('attachment',new.id);
END;
CREATE TRIGGER semantic_attachment_update AFTER UPDATE ON message_attachments BEGIN
 DELETE FROM semantic_chunks WHERE kind='attachment' AND source_id=old.id;
 UPDATE semantic_jobs SET generation=generation+1,status='pending',omitted_chars=0,
 error_code=NULL WHERE kind='attachment' AND source_id=new.id;
 INSERT OR IGNORE INTO semantic_jobs(kind,source_id)
 SELECT 'attachment',new.id WHERE new.removed=0 AND new.text!='';
 DELETE FROM semantic_jobs WHERE kind='attachment' AND source_id=new.id
 AND (new.removed!=0 OR new.text IS NULL OR new.text='');
END;
CREATE TRIGGER semantic_attachment_delete AFTER DELETE ON message_attachments BEGIN
 DELETE FROM semantic_jobs WHERE kind='attachment' AND source_id=old.id;
END;
INSERT INTO semantic_jobs(kind,source_id) SELECT 'attachment',id FROM message_attachments
 WHERE removed=0 AND text!='';
"""
)

VERSION_17 = """
CREATE TABLE search_service_jobs (
 id TEXT PRIMARY KEY, action TEXT NOT NULL, status TEXT NOT NULL,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, error_code TEXT
);
CREATE TABLE tool_settings(id INTEGER PRIMARY KEY CHECK(id=1), image_id TEXT);
INSERT INTO tool_settings(id) VALUES(1);
CREATE TABLE tool_setup_jobs (
 id TEXT PRIMARY KEY, status TEXT NOT NULL, created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL, image_id TEXT, error_code TEXT, log TEXT NOT NULL DEFAULT ''
);
"""

VERSION_18 = """
CREATE TABLE work_research (
 task_id TEXT PRIMARY KEY REFERENCES work_tasks(id) ON DELETE CASCADE,
 public_query TEXT,
 follow_links INTEGER NOT NULL DEFAULT 0,
 status TEXT NOT NULL,
 error_code TEXT
);
"""

VERSION_19 = """
CREATE TABLE work_inputs (
 task_id TEXT NOT NULL REFERENCES work_tasks(id) ON DELETE CASCADE,
 name TEXT NOT NULL,
 original BLOB NOT NULL,
 sha256 TEXT NOT NULL,
 extraction TEXT NOT NULL,
 PRIMARY KEY(task_id,name)
);
"""

VERSION_20 = """
CREATE TABLE chat_submission_receipts (
 request_id TEXT PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
 request_hash TEXT NOT NULL
);
CREATE TABLE work_submission_receipts (
 request_id TEXT PRIMARY KEY REFERENCES work_tasks(id) ON DELETE CASCADE,
 request_hash TEXT NOT NULL
);
"""

MIGRATIONS = {
    20: VERSION_20,
    19: VERSION_19,
    18: VERSION_18,
    17: VERSION_17,
    16: VERSION_16,
    15: VERSION_15,
    2: VERSION_2,
    3: VERSION_3,
    4: VERSION_4,
    5: VERSION_5,
    6: VERSION_6,
    7: VERSION_7,
    8: VERSION_8,
    9: VERSION_9,
    10: VERSION_10,
    11: VERSION_11,
    12: VERSION_12,
    13: VERSION_13,
    14: VERSION_14,
}

REQUIRED_TABLES = {
    21: {"diagnostic_snapshots"},
    20: {"chat_submission_receipts", "work_submission_receipts"},
    19: {"work_inputs"},
    18: {"work_research"},
    17: {"tool_settings", "tool_setup_jobs", "search_service_jobs"},
    16: {"semantic_settings", "semantic_jobs", "semantic_chunks"},
    15: {"attachments_fts"},
    14: {"work_source_requests"},
    13: {"attachment_documents"},
    1: {
        "devices",
        "pairings",
        "conversations",
        "messages",
        "runs",
        "events",
        "work_tasks",
        "checkpoints",
        "diagnostic_events",
        "snapshots",
        "collections",
        "exports",
    },
    2: {
        "memories",
        "memories_fts",
        "work_sessions",
        "work_steps",
        "work_files",
        "scheduler_state",
        "model_records",
        "work_creation_requests",
    },
    3: {"downloads"},
    4: {"runtime_installations", "runtime_sources", "managed_models"},
    5: {"run_research", "web_sources"},
    6: {"memory_creation_requests"},
    7: {"work_sources"},
    8: {"search_settings"},
    9: {"message_attachments"},
    10: {
        "history_batches",
        "history_sources",
        "history_messages",
        "history_tombstones",
        "messages_fts",
    },
    11: {"semantic_settings", "semantic_jobs", "semantic_chunks"},
    12: {"sandbox_identity", "work_build_profiles", "work_executions", "work_artifacts"},
}

MIGRATIONS[21] = """
CREATE TABLE diagnostic_snapshots (
 id TEXT PRIMARY KEY, reason TEXT NOT NULL, correlation_id TEXT,
 captured_at TEXT NOT NULL, sha256 TEXT NOT NULL, payload TEXT NOT NULL
);
"""

MIGRATIONS[22] = """
CREATE TABLE generation_options (
 kind TEXT NOT NULL CHECK(kind IN ('chat','work')), id TEXT NOT NULL,
 effort TEXT, web_mode TEXT NOT NULL DEFAULT 'off', web_planned INTEGER NOT NULL DEFAULT 0,
 PRIMARY KEY(kind,id)
);
"""
REQUIRED_TABLES[22] = {"generation_options"}

MIGRATIONS[23] = """
ALTER TABLE work_build_profiles RENAME TO work_build_profiles_v22;
CREATE TABLE work_build_profiles (
 task_id TEXT PRIMARY KEY REFERENCES work_tasks(id), target TEXT NOT NULL
 CHECK(target IN ('files','apk','exe','apps'))
);
INSERT INTO work_build_profiles SELECT * FROM work_build_profiles_v22;
DROP TABLE work_build_profiles_v22;
CREATE TABLE work_specs (
 task_id TEXT PRIMARY KEY REFERENCES work_tasks(id), requirements_sha256 TEXT NOT NULL,
 brief TEXT NOT NULL DEFAULT ''
);
CREATE TABLE work_spec_sections (
 task_id TEXT NOT NULL REFERENCES work_tasks(id), ordinal INTEGER NOT NULL,
 start INTEGER NOT NULL, end INTEGER NOT NULL, notes TEXT,
 status TEXT NOT NULL DEFAULT 'pending', evidence TEXT, evidence_paths TEXT,
 snapshot_sha256 TEXT, PRIMARY KEY(task_id,ordinal)
);
CREATE TABLE work_signing_keys (
 task_id TEXT PRIMARY KEY REFERENCES work_tasks(id), key_bytes BLOB NOT NULL,
 sha256 TEXT NOT NULL, created_at TEXT NOT NULL
);
"""
REQUIRED_TABLES[23] = {"work_specs", "work_spec_sections", "work_signing_keys"}

MIGRATIONS[24] = """
CREATE TABLE work_web_calls (
 task_id TEXT NOT NULL REFERENCES work_tasks(id), step INTEGER NOT NULL,
 action TEXT NOT NULL, task_revision INTEGER NOT NULL, status TEXT NOT NULL,
 result TEXT, recorded INTEGER NOT NULL DEFAULT 0,
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL, PRIMARY KEY(task_id,step)
);
"""
REQUIRED_TABLES[24] = {"work_web_calls"}

MIGRATIONS[25] = """
CREATE TABLE work_uploads (
 id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES devices(id), name TEXT NOT NULL,
 size INTEGER NOT NULL, received INTEGER NOT NULL DEFAULT 0, sha256 TEXT,
 content BLOB NOT NULL, updated_at TEXT NOT NULL
);
"""
MIGRATIONS[25] += """
CREATE TABLE device_presence (
 device_id TEXT PRIMARY KEY REFERENCES devices(id) ON DELETE CASCADE,
 last_seen REAL NOT NULL, app_version TEXT NOT NULL
);
"""
REQUIRED_TABLES[25] = {"work_uploads", "device_presence"}

MIGRATIONS[26] = """
CREATE TABLE account_sessions (
 id TEXT PRIMARY KEY, owner TEXT NOT NULL REFERENCES devices(id),
 label TEXT NOT NULL, origin TEXT NOT NULL, read_path TEXT NOT NULL,
 created_at TEXT NOT NULL, sealed_cookie BLOB NOT NULL
);
"""
REQUIRED_TABLES[26] = {"account_sessions"}

MIGRATIONS[27] = """
CREATE TABLE account_grants (
 id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES account_sessions(id) ON DELETE CASCADE,
 task_id TEXT NOT NULL REFERENCES work_tasks(id) ON DELETE CASCADE,
 task_revision INTEGER NOT NULL, device_id TEXT NOT NULL REFERENCES devices(id),
 created_at TEXT NOT NULL, expires_at REAL NOT NULL
);
CREATE INDEX account_grants_session ON account_grants(session_id);
"""
REQUIRED_TABLES[27] = {"account_grants"}

MIGRATIONS[28] = """
CREATE TABLE account_browser_writes (
 id TEXT PRIMARY KEY,
 session_id TEXT NOT NULL REFERENCES account_sessions(id) ON DELETE CASCADE,
 status TEXT NOT NULL CHECK(status IN
 ('uncertain','response_received','verified_applied','verified_not_applied')),
 created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX account_browser_writes_session ON account_browser_writes(session_id,status);
"""
REQUIRED_TABLES[28] = {"account_browser_writes"}

MIGRATIONS[29] = """
CREATE TABLE account_browser_profiles (
 session_id TEXT PRIMARY KEY REFERENCES account_sessions(id) ON DELETE CASCADE,
 revision INTEGER NOT NULL CHECK(revision > 0), sealed_profile BLOB NOT NULL
);
"""
REQUIRED_TABLES[29] = {"account_browser_profiles"}
