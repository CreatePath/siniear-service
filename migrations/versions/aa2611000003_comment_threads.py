"""게시글·일정 원댓글과 한 단계 답글."""

from alembic import op

revision = "aa2611000003"
down_revision = "aa2611000002"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE comments ALTER COLUMN post_id DROP NOT NULL,
          ADD meeting_id uuid REFERENCES meetings(id),
          ADD parent_comment_id uuid REFERENCES comments(id) ON DELETE CASCADE,
          ADD CHECK(num_nonnulls(post_id, meeting_id)=1);
        CREATE INDEX ix_comments_meeting_created ON comments(meeting_id,created_at,id);
        CREATE INDEX ix_comments_parent_created ON comments(parent_comment_id,created_at,id);
        CREATE FUNCTION validate_comment_parent() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF TG_OP='UPDATE' AND (NEW.post_id,NEW.meeting_id,NEW.parent_comment_id) IS DISTINCT FROM
               (OLD.post_id,OLD.meeting_id,OLD.parent_comment_id) THEN
            RAISE EXCEPTION 'immutable comment target' USING ERRCODE='23514';
          END IF;
          IF NEW.parent_comment_id IS NOT NULL AND NOT EXISTS (
              SELECT 1 FROM comments p WHERE p.id=NEW.parent_comment_id AND p.parent_comment_id IS
                  NULL
              AND p.post_id IS NOT DISTINCT FROM NEW.post_id AND p.meeting_id IS NOT DISTINCT FROM
                  NEW.meeting_id FOR KEY SHARE
          ) THEN RAISE EXCEPTION 'invalid reply parent' USING ERRCODE='23514'; END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER comment_parent BEFORE INSERT OR UPDATE OF
            post_id,meeting_id,parent_comment_id
          ON comments FOR EACH ROW EXECUTE FUNCTION validate_comment_parent();
    """)


def downgrade():
    raise RuntimeError("일정 댓글과 답글 보존을 위해 전환 전 백업을 복원하세요.")
