from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '6f4e8a9b2c1d'
down_revision = '7179226c1b9a'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('movies', sa.Column('genre', sa.String(length=120), nullable=True))
    op.add_column('movies', sa.Column('director', sa.String(length=150), nullable=True))
    op.add_column('movies', sa.Column('actors', sa.Text(), nullable=True))
    op.add_column('movies', sa.Column('country', sa.String(length=120), nullable=True))
    op.add_column('movies', sa.Column('production_year', sa.Integer(), nullable=True))
    op.add_column('movies', sa.Column('age_rating', sa.String(length=20), nullable=True))


def downgrade():
    op.drop_column('movies', 'age_rating')
    op.drop_column('movies', 'production_year')
    op.drop_column('movies', 'countryВ')
    op.drop_column('movies', 'actors')
    op.drop_column('movies', 'director')
    op.drop_column('movies', 'genre')