"""가입 이력, 심사, 보유 칭호 및 소속 명함. 기존 활성 모임의 개설자를 연결한다."""

from alembic import op

revision = "aa2611000002"
down_revision = "aa2611000001"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        ALTER TABLE groups ADD activity_goals text[] NOT NULL DEFAULT '{}',
            ADD badge_id uuid REFERENCES media_assets(id) ON DELETE SET NULL;
        CREATE TABLE group_memberships (
            id uuid PRIMARY KEY, group_id uuid NOT NULL REFERENCES groups(id),
            senior_id uuid NOT NULL REFERENCES seniors(id), joined_at timestamptz NOT NULL DEFAULT
                now(),
            left_at timestamptz CHECK (left_at >= joined_at), CONSTRAINT uq_group_memberships_id
                UNIQUE(id,senior_id), CONSTRAINT uq_membership_group_owner
                UNIQUE(id,group_id,senior_id));
        CREATE UNIQUE INDEX uq_membership_active ON group_memberships(group_id,senior_id) WHERE
            left_at IS NULL;
        CREATE TABLE group_join_requests (
            id uuid PRIMARY KEY, group_id uuid NOT NULL REFERENCES groups(id),
            senior_id uuid NOT NULL REFERENCES seniors(id), status text NOT NULL,
            reviewed_by uuid REFERENCES seniors(id), membership_id uuid CONSTRAINT
                uq_group_join_requests_membership_id UNIQUE,
            created_at timestamptz NOT NULL DEFAULT now(), resolved_at timestamptz,
            FOREIGN KEY(membership_id,group_id,senior_id) REFERENCES
                group_memberships(id,group_id,senior_id),
            CHECK(status IN ('pending','approved','rejected','canceled') AND
            (status='approved')=(membership_id IS NOT NULL) AND (status='pending')=(resolved_at IS
                NULL)
            AND (status IN ('approved','rejected'))=(reviewed_by IS NOT NULL) AND resolved_at >=
                created_at));
        CREATE UNIQUE INDEX uq_join_pending ON group_join_requests(group_id,senior_id) WHERE
            status='pending';
        CREATE INDEX ix_join_queue ON group_join_requests(group_id,created_at,id) WHERE
            status='pending';
        CREATE TABLE membership_titles (
            id uuid PRIMARY KEY, membership_id uuid NOT NULL REFERENCES group_memberships(id),
            label text NOT NULL, evidence_ref text NOT NULL, CONSTRAINT uq_membership_titles_id
                UNIQUE(id,membership_id), CONSTRAINT uq_membership_titles_membership_id
                UNIQUE(membership_id,label));
        ALTER TABLE cards DROP CONSTRAINT uq_cards_senior_id,
            ADD membership_id uuid CONSTRAINT uq_cards_membership_id UNIQUE, ADD role text, ADD
                group_intro text, ADD selected_title_id uuid,
            ADD FOREIGN KEY(membership_id,senior_id) REFERENCES group_memberships(id,senior_id),
            ADD FOREIGN KEY(selected_title_id,membership_id) REFERENCES
                membership_titles(id,membership_id),
            ADD CHECK(membership_id IS NOT NULL OR (role IS NULL AND group_intro IS NULL AND
                selected_title_id IS NULL));
        CREATE UNIQUE INDEX uq_personal_card ON cards(senior_id) WHERE membership_id IS NULL;
        INSERT INTO group_memberships(id,group_id,senior_id,joined_at)
            SELECT gen_random_uuid(),id,owner_id,created_at FROM groups WHERE status='active';
        INSERT INTO cards(id,senior_id,membership_id,template_key,visible_fields,version)
            SELECT gen_random_uuid(),senior_id,id,'default','{}',1 FROM group_memberships;
    """)


def downgrade():
    raise RuntimeError("가입 이력을 보존하려면 전환 전 백업을 복원하세요.")
