-- 001: research projects, request workflow, stock reservations.
-- Idempotent: new tables are created by SQLAlchemy create_all (scripts/db_init.py) BEFORE this runs; this file alters
-- tables that may already exist from an earlier release, adds indexes create_all cannot add to existing tables,
-- and installs the append-only triggers.

-- ---------------------------------------------------------------- reagent_lots: reservations, availability, row version
ALTER TABLE reagent_lots ADD COLUMN IF NOT EXISTS reserved_quantity numeric NOT NULL DEFAULT 0;
ALTER TABLE reagent_lots ADD COLUMN IF NOT EXISTS availability varchar(16) NOT NULL DEFAULT 'active';
ALTER TABLE reagent_lots ADD COLUMN IF NOT EXISTS row_version integer NOT NULL DEFAULT 1;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_lot_reserved') THEN
    ALTER TABLE reagent_lots ADD CONSTRAINT ck_lot_reserved CHECK (reserved_quantity >= 0 AND reserved_quantity <= quantity_available);
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_lot_availability') THEN
    ALTER TABLE reagent_lots ADD CONSTRAINT ck_lot_availability CHECK (availability IN ('active', 'quarantined', 'unavailable'));
  END IF;
END $$;

-- ---------------------------------------------------------------- reagent_requests: new lifecycle
ALTER TABLE reagent_requests ADD COLUMN IF NOT EXISTS reagent_name_text varchar(200);
ALTER TABLE reagent_requests ADD COLUMN IF NOT EXISTS unit varchar(16);
ALTER TABLE reagent_requests ADD COLUMN IF NOT EXISTS details text;
ALTER TABLE reagent_requests ADD COLUMN IF NOT EXISTS urgency varchar(10) NOT NULL DEFAULT 'normal';
ALTER TABLE reagent_requests ADD COLUMN IF NOT EXISTS project_id uuid REFERENCES projects(id) ON DELETE SET NULL;
ALTER TABLE reagent_requests ADD COLUMN IF NOT EXISTS reserved_lot_id uuid REFERENCES reagent_lots(id);
ALTER TABLE reagent_requests ADD COLUMN IF NOT EXISTS reserved_quantity numeric NOT NULL DEFAULT 0;
ALTER TABLE reagent_requests ADD COLUMN IF NOT EXISTS fulfilment_note text;
ALTER TABLE reagent_requests ADD COLUMN IF NOT EXISTS fulfilled_at timestamptz;
ALTER TABLE reagent_requests ALTER COLUMN reagent_id DROP NOT NULL;
ALTER TABLE reagent_requests ALTER COLUMN status TYPE varchar(20);
ALTER TABLE reagent_requests DROP CONSTRAINT IF EXISTS ck_req_status;
UPDATE reagent_requests SET status = 'submitted' WHERE status = 'pending';
UPDATE reagent_requests SET status = 'fulfilled', fulfilled_at = COALESCE(fulfilled_at, handled_at) WHERE status = 'issued';
ALTER TABLE reagent_requests ALTER COLUMN status SET DEFAULT 'submitted';
ALTER TABLE reagent_requests ADD CONSTRAINT ck_req_status CHECK
  (status IN ('submitted', 'under_review', 'needs_clarification', 'approved', 'rejected', 'fulfilled'));
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_req_urgency') THEN
    ALTER TABLE reagent_requests ADD CONSTRAINT ck_req_urgency CHECK (urgency IN ('low', 'normal', 'high', 'urgent'));
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'ck_req_reagent') THEN
    ALTER TABLE reagent_requests ADD CONSTRAINT ck_req_reagent CHECK (reagent_id IS NOT NULL OR reagent_name_text IS NOT NULL);
  END IF;
END $$;
CREATE INDEX IF NOT EXISTS ix_reagent_requests_status ON reagent_requests (status);
-- legacy rows get a timeline entry so history is never empty
INSERT INTO request_events (request_id, kind, from_status, to_status, actor_id, comment, created_at)
SELECT q.id, 'status', NULL, 'submitted', q.requested_by, 'migrated from the previous request model', q.created_at
FROM reagent_requests q WHERE NOT EXISTS (SELECT 1 FROM request_events e WHERE e.request_id = q.id);

-- ---------------------------------------------------------------- chat / notifications
ALTER TABLE chat_history ADD COLUMN IF NOT EXISTS project_id uuid REFERENCES projects(id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS ix_chat_history_project_id ON chat_history (project_id);
ALTER TABLE notifications ADD COLUMN IF NOT EXISTS kind varchar(40);

-- conversations created before the conversations table existed: one row each, titled by the first question
INSERT INTO conversations (id, user_id, project_id, title, created_at, updated_at)
SELECT conversation_id, (array_agg(user_id ORDER BY created_at))[1], NULL,
       left((array_agg(question ORDER BY created_at))[1], 120), min(created_at), max(created_at)
FROM chat_history WHERE conversation_id IS NOT NULL
GROUP BY conversation_id
ON CONFLICT (id) DO NOTHING;

-- ---------------------------------------------------------------- append-only history
DROP TRIGGER IF EXISTS request_events_append_only ON request_events;
CREATE TRIGGER request_events_append_only BEFORE UPDATE OR DELETE ON request_events
  FOR EACH ROW EXECUTE FUNCTION forbid_mutation();

-- experiment history may only disappear when its whole project is deleted (FK cascade), never by UPDATE/direct DELETE
CREATE OR REPLACE FUNCTION forbid_version_mutation() RETURNS trigger AS $$
BEGIN
  IF TG_OP = 'UPDATE' THEN RAISE EXCEPTION 'experiment_versions is append-only'; END IF;
  IF TG_OP = 'DELETE' AND EXISTS (SELECT 1 FROM projects WHERE id = OLD.project_id) THEN
    RAISE EXCEPTION 'experiment_versions is append-only';
  END IF;
  RETURN OLD;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS experiment_versions_append_only ON experiment_versions;
CREATE TRIGGER experiment_versions_append_only BEFORE UPDATE OR DELETE ON experiment_versions
  FOR EACH ROW EXECUTE FUNCTION forbid_version_mutation();
