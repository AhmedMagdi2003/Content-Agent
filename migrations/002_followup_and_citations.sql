-- Migration 002: Add project series continuity, sources context, and block citations

ALTER TABLE content_ops.content_items
ADD COLUMN IF NOT EXISTS project_slug VARCHAR(100);

ALTER TABLE content_ops.content_items
ADD COLUMN IF NOT EXISTS content_type VARCHAR(50) DEFAULT 'project_update';

ALTER TABLE content_ops.content_items
ADD COLUMN IF NOT EXISTS sources_context JSON;

CREATE INDEX IF NOT EXISTS ix_content_ops_content_items_project_slug
ON content_ops.content_items (project_slug);

ALTER TABLE content_ops.content_revisions
ADD COLUMN IF NOT EXISTS citations JSON;
