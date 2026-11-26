"""소속 기간별 활동 횟수와 칭호 기준, 기존 활동 소급 반영."""

from alembic import op

revision = "aa2611000005"
down_revision = "aa2611000004"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE activity_title_rules (
            label text PRIMARY KEY, tier text NOT NULL, activity text NOT NULL,
            threshold integer NOT NULL,
            CONSTRAINT uq_activity_title_rules_activity UNIQUE(activity, threshold),
            CHECK (tier IN ('silver','gold','diamond')),
            CHECK (activity IN ('join','registration','post','exchange')),
            CHECK (threshold > 0)
        );
        INSERT INTO activity_title_rules (label, tier, activity, threshold) VALUES
            ('신규 회원', 'silver', 'join', 1),
            ('새로운 얼굴', 'silver', 'registration', 1),
            ('새로운 이웃', 'silver', 'exchange', 1),
            ('이야기꾼', 'gold', 'post', 10),
            ('친숙한 얼굴', 'gold', 'registration', 10),
            ('두루 아는 이웃', 'gold', 'exchange', 10),
            ('대문호', 'diamond', 'post', 100),
            ('터줏대감', 'diamond', 'registration', 100),
            ('마당발', 'diamond', 'exchange', 100);

        ALTER TABLE group_memberships
            ADD post_count integer NOT NULL DEFAULT 0,
            ADD exchange_count integer NOT NULL DEFAULT 0;

        WITH posts_by_period AS (
            SELECT m.id, count(*) AS n FROM group_memberships m JOIN posts p
                ON p.group_id = m.group_id AND p.author_id = m.senior_id
                AND p.created_at >= m.joined_at AND (m.left_at IS NULL OR p.created_at < m.left_at)
            GROUP BY m.id
        )
        UPDATE group_memberships m SET post_count = p.n FROM posts_by_period p WHERE m.id = p.id;

        WITH exchanged_cards AS (
            SELECT card_low_id AS id FROM card_exchanges
            UNION ALL SELECT card_high_id FROM card_exchanges
        ), counts AS (
            SELECT c.membership_id, count(*) AS n FROM exchanged_cards e JOIN cards c ON c.id = e.id
            WHERE c.membership_id IS NOT NULL GROUP BY c.membership_id
        )
        UPDATE group_memberships m SET exchange_count = c.n FROM counts c
        WHERE m.id = c.membership_id;

        WITH registrations_by_period AS (
            SELECT m.id, count(DISTINCT r.id) AS n
            FROM group_memberships m
            JOIN meetings e ON e.group_id = m.group_id
            JOIN meeting_registrations r ON r.meeting_id = e.id AND r.senior_id = m.senior_id
            JOIN registration_actions a ON a.registration_id = r.id AND a.action = 'register'
                AND a.created_at >= m.joined_at AND (m.left_at IS NULL OR a.created_at < m.left_at)
            GROUP BY m.id
        )
        INSERT INTO membership_titles (id, membership_id, label, evidence_ref)
        SELECT gen_random_uuid(), m.id, r.label, 'backfill:' || m.id || ':' || r.activity
        FROM group_memberships m LEFT JOIN registrations_by_period p ON p.id = m.id
        JOIN activity_title_rules r ON r.threshold <= CASE r.activity
            WHEN 'join' THEN 1 WHEN 'post' THEN m.post_count
            WHEN 'exchange' THEN m.exchange_count WHEN 'registration' THEN coalesce(p.n,0) END
        ON CONFLICT (membership_id, label) DO NOTHING;
    """)


def downgrade():
    raise RuntimeError("활동 횟수와 기존 대표 칭호를 보존하려면 전환 전 백업을 복원하세요.")
