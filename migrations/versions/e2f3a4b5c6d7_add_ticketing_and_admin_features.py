from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'e2f3a4b5c6d7'
down_revision = 'd1f2a3b4c5d6'
branch_labels = None
depends_on = None


def _has_column(inspector, table_name, column_name):
    return any(column['name'] == column_name for column in inspector.get_columns(table_name))


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if _has_column(inspector, 'screenings', 'ticket_price') is False:
        op.add_column('screenings', sa.Column('ticket_price', sa.Float(), nullable=True))
        op.execute('UPDATE screenings SET ticket_price = 450 WHERE ticket_price IS NULL')
        op.alter_column('screenings', 'ticket_price', nullable=False)

    if _has_column(inspector, 'screenings', 'poster_override_path') is False:
        op.add_column('screenings', sa.Column('poster_override_path', sa.String(length=255), nullable=True))

    booking_columns = {
        'ticket_code': sa.Column('ticket_code', sa.String(length=32), nullable=True),
        'price_paid': sa.Column('price_paid', sa.Float(), nullable=True),
        'confirmed_at': sa.Column('confirmed_at', sa.DateTime(), nullable=True),
        'paid_at': sa.Column('paid_at', sa.DateTime(), nullable=True),
        'emailed_at': sa.Column('emailed_at', sa.DateTime(), nullable=True),
        'receipt_issued_at': sa.Column('receipt_issued_at', sa.DateTime(), nullable=True),
        'receipt_issued_by_id': sa.Column('receipt_issued_by_id', sa.Integer(), nullable=True),
    }

    for name, column in booking_columns.items():
        if _has_column(inspector, 'bookings', name) is False:
            op.add_column('bookings', column)

    fk_names = {fk['name'] for fk in inspector.get_foreign_keys('bookings') if fk.get('name')}
    if 'fk_bookings_receipt_issued_by_id_users' not in fk_names:
        op.create_foreign_key(
            'fk_bookings_receipt_issued_by_id_users',
            'bookings',
            'users',
            ['receipt_issued_by_id'],
            ['id'],
        )

    unique_names = {uc['name'] for uc in inspector.get_unique_constraints('bookings') if uc.get('name')}
    if 'uq_bookings_ticket_code' not in unique_names:
        op.create_unique_constraint('uq_bookings_ticket_code', 'bookings', ['ticket_code'])

    op.execute("UPDATE bookings SET status = 'reserved' WHERE status = 'active'")


def downgrade():
    op.drop_constraint('uq_bookings_ticket_code', 'bookings', type_='unique')
    op.drop_constraint('fk_bookings_receipt_issued_by_id_users', 'bookings', type_='foreignkey')

    for column in [
        'receipt_issued_by_id',
        'receipt_issued_at',
        'emailed_at',
        'paid_at',
        'confirmed_at',
        'price_paid',
        'ticket_code',
    ]:
        op.drop_column('bookings', column)

    op.drop_column('screenings', 'poster_override_path')
    op.drop_column('screenings', 'ticket_price')