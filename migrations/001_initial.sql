-- Independent content application; apply only to a dedicated content schema.

CREATE SCHEMA IF NOT EXISTS content_ops;


CREATE TABLE content_ops.content_items (
	id VARCHAR(36) NOT NULL,
	source TEXT NOT NULL,
	revision INTEGER NOT NULL,
	created_at TIMESTAMP WITH TIME ZONE NOT NULL,
	PRIMARY KEY (id)
)

;

ALTER TABLE content_ops."content_items" ENABLE ROW LEVEL SECURITY;


CREATE TABLE content_ops.events (
	id VARCHAR(36) NOT NULL,
	timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
	run_id VARCHAR(36),
	request_id VARCHAR(36),
	resource_id VARCHAR(36),
	stage VARCHAR(80) NOT NULL,
	operation VARCHAR(80) NOT NULL,
	status VARCHAR(40) NOT NULL,
	duration_ms INTEGER,
	safe_metadata JSON NOT NULL,
	error_code VARCHAR(80),
	PRIMARY KEY (id)
)

;

CREATE INDEX ix_content_ops_events_request_id ON content_ops.events (request_id);

CREATE INDEX ix_content_ops_events_resource_id ON content_ops.events (resource_id);

CREATE INDEX ix_content_ops_events_run_id ON content_ops.events (run_id);

ALTER TABLE content_ops."events" ENABLE ROW LEVEL SECURITY;


CREATE TABLE content_ops.llm_usage (
	id VARCHAR(36) NOT NULL,
	run_id VARCHAR(36) NOT NULL,
	provider VARCHAR(40) NOT NULL,
	model VARCHAR(100) NOT NULL,
	operation VARCHAR(50) NOT NULL,
	input_tokens INTEGER,
	output_tokens INTEGER,
	cached_tokens INTEGER,
	estimated_usd NUMERIC(16, 8),
	details JSON NOT NULL,
	PRIMARY KEY (id)
)

;

CREATE INDEX ix_content_ops_llm_usage_run_id ON content_ops.llm_usage (run_id);

ALTER TABLE content_ops."llm_usage" ENABLE ROW LEVEL SECURITY;


CREATE TABLE content_ops.content_revisions (
	id VARCHAR(80) NOT NULL,
	content_id VARCHAR(36) NOT NULL,
	number INTEGER NOT NULL,
	drafts JSON NOT NULL,
	digest VARCHAR(64) NOT NULL,
	channels JSON NOT NULL,
	decision VARCHAR(20) DEFAULT 'draft' NOT NULL,
	decision_reason TEXT,
	approved_by VARCHAR(100),
	approved_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	FOREIGN KEY(content_id) REFERENCES content_ops.content_items (id)
)

;

CREATE INDEX ix_content_ops_content_revisions_content_id ON content_ops.content_revisions (content_id);

ALTER TABLE content_ops."content_revisions" ENABLE ROW LEVEL SECURITY;


CREATE TABLE content_ops.publications (
	id VARCHAR(150) NOT NULL,
	revision_id VARCHAR(80) NOT NULL,
	channel VARCHAR(40) NOT NULL,
	status VARCHAR(30) NOT NULL,
	attempts INTEGER NOT NULL,
	url TEXT,
	published_at TIMESTAMP WITH TIME ZONE,
	error VARCHAR(120),
	PRIMARY KEY (id),
	FOREIGN KEY(revision_id) REFERENCES content_ops.content_revisions (id)
)

;

CREATE INDEX ix_content_ops_publications_revision_id ON content_ops.publications (revision_id);

ALTER TABLE content_ops."publications" ENABLE ROW LEVEL SECURITY;
