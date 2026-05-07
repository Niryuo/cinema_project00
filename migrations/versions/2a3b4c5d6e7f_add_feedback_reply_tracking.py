from alembic import op
import sqlalchemy as sa

revision = '2a3b4c5d6e7f'
down_revision = '6f4e8a9b2c1d'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('feedback_requests', sa.Column('responded_at', sa.DateTime(), nullable=True))
    op.add_column('feedback_requests', sa.Column('response_emailed_at', sa.DateTime(), nullable=True))
    op.execute("UPDATE feedback_requests SET status = 'sent' WHERE status = 'new'")


def downgrade():
    op.execute("UPDATE feedback_requests SET status = 'new' WHERE status = 'sent'")
    op.drop_column('feedback_requests', 'response_emailed_at')
    op.drop_column('feedback_requests', 'responded_at')