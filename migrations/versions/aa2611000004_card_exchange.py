"""일회성 제안, 양방향 연결, 수신자별 즐겨찾기."""

from alembic import op

revision = "aa2611000004"
down_revision = "aa2611000003"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
        CREATE TABLE exchange_offers(id uuid PRIMARY KEY,card_id uuid NOT NULL REFERENCES cards(id)
            ON DELETE CASCADE,
            token_hash text NOT NULL CONSTRAINT uq_exchange_offers_token_hash UNIQUE, expires_at
                timestamptz NOT NULL, consumed_at timestamptz);
        CREATE INDEX ix_exchange_offers_card_id ON exchange_offers(card_id);
        CREATE TABLE card_exchanges(id uuid PRIMARY KEY,
            card_low_id uuid NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
            card_high_id uuid NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
            exchanged_at timestamptz NOT NULL DEFAULT now(), exchange_method text
                CHECK(exchange_method='qr'),
            CHECK(card_low_id < card_high_id), CONSTRAINT uq_card_exchanges_card_low_id
                UNIQUE(card_low_id,card_high_id));
        CREATE INDEX ix_card_exchanges_card_high_id ON card_exchanges(card_high_id);
        CREATE TABLE card_book_favorites(owner_senior_id uuid NOT NULL REFERENCES seniors(id),
            received_card_id uuid NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
            PRIMARY KEY(owner_senior_id,received_card_id));
    """)


def downgrade():
    op.drop_table("card_book_favorites")
    op.drop_table("card_exchanges")
    op.drop_table("exchange_offers")
