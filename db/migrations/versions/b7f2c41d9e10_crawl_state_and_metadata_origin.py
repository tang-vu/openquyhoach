"""crawl state + metadata provenance

Adds the operational crawl layer:

* source_resources — deduplicated candidate-resource inventory per source
* source_observations — append-only per-resource check log
* source_crawl_state — per-source health/freshness/lock state
* source_change_events — upstream change records

Plus metadata_origin on documents + planning_versions (derived metadata
must never silently read as official), and priority/admin_unit_id on
sources for scheduling and jurisdiction linkage.

Revision ID: b7f2c41d9e10
Revises: 33604bdea89d
Create Date: 2026-09-19 12:00:00
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = 'b7f2c41d9e10'
down_revision = '33604bdea89d'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table('source_crawl_state',
        sa.Column('source_id', sa.Uuid(), nullable=False),
        sa.Column('last_check_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_success_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_change_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_run_id', sa.Uuid(), nullable=True),
        sa.Column('last_http_status', sa.Integer(), nullable=True),
        sa.Column('consecutive_failures', sa.Integer(), nullable=False),
        sa.Column('next_check_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('health', sa.String(length=32), nullable=False),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('resources_seen', sa.Integer(), nullable=False),
        sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('lock_token', sa.String(length=64), nullable=True),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['last_run_id'], ['ingestion_runs.id'], name=op.f('fk_source_crawl_state_last_run_id_ingestion_runs')),
        sa.ForeignKeyConstraint(['source_id'], ['sources.id'], name=op.f('fk_source_crawl_state_source_id_sources')),
        sa.PrimaryKeyConstraint('source_id', name=op.f('pk_source_crawl_state'))
    )
    op.create_index(op.f('ix_source_crawl_state_health'), 'source_crawl_state', ['health'], unique=False)
    op.create_index(op.f('ix_source_crawl_state_locked_until'), 'source_crawl_state', ['locked_until'], unique=False)
    op.create_index(op.f('ix_source_crawl_state_next_check_at'), 'source_crawl_state', ['next_check_at'], unique=False)

    op.create_table('source_resources',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('source_id', sa.Uuid(), nullable=False),
        sa.Column('resource_key', sa.String(length=128), nullable=False),
        sa.Column('url', sa.Text(), nullable=False),
        sa.Column('canonical_url', sa.Text(), nullable=True),
        sa.Column('title', sa.Text(), nullable=True),
        sa.Column('discovered_metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('first_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('last_changed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('status', sa.String(length=32), nullable=False),
        sa.Column('http_status', sa.Integer(), nullable=True),
        sa.Column('etag', sa.String(length=512), nullable=True),
        sa.Column('last_modified', sa.String(length=255), nullable=True),
        sa.Column('content_sha256', sa.String(length=64), nullable=True),
        sa.Column('file_size', sa.BigInteger(), nullable=True),
        sa.Column('artifact_id', sa.Uuid(), nullable=True),
        sa.Column('consecutive_failures', sa.Integer(), nullable=False),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('metadata', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['artifact_id'], ['source_artifacts.id'], name=op.f('fk_source_resources_artifact_id_source_artifacts')),
        sa.ForeignKeyConstraint(['source_id'], ['sources.id'], name=op.f('fk_source_resources_source_id_sources')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_source_resources'))
    )
    op.create_index('uq_source_resources_key', 'source_resources', ['source_id', 'resource_key'], unique=True)
    op.create_index(op.f('ix_source_resources_canonical_url'), 'source_resources', ['canonical_url'], unique=False)
    op.create_index(op.f('ix_source_resources_source_id'), 'source_resources', ['source_id'], unique=False)
    op.create_index(op.f('ix_source_resources_status'), 'source_resources', ['status'], unique=False)

    op.create_table('source_observations',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('source_id', sa.Uuid(), nullable=False),
        sa.Column('resource_id', sa.Uuid(), nullable=True),
        sa.Column('run_id', sa.Uuid(), nullable=True),
        sa.Column('observed_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('outcome', sa.String(length=32), nullable=False),
        sa.Column('http_status', sa.Integer(), nullable=True),
        sa.Column('etag', sa.String(length=512), nullable=True),
        sa.Column('last_modified', sa.String(length=255), nullable=True),
        sa.Column('content_sha256', sa.String(length=64), nullable=True),
        sa.Column('artifact_id', sa.Uuid(), nullable=True),
        sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(['artifact_id'], ['source_artifacts.id'], name=op.f('fk_source_observations_artifact_id_source_artifacts')),
        sa.ForeignKeyConstraint(['resource_id'], ['source_resources.id'], name=op.f('fk_source_observations_resource_id_source_resources')),
        sa.ForeignKeyConstraint(['run_id'], ['ingestion_runs.id'], name=op.f('fk_source_observations_run_id_ingestion_runs')),
        sa.ForeignKeyConstraint(['source_id'], ['sources.id'], name=op.f('fk_source_observations_source_id_sources')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_source_observations'))
    )
    op.create_index(op.f('ix_source_observations_outcome'), 'source_observations', ['outcome'], unique=False)
    op.create_index(op.f('ix_source_observations_source_id'), 'source_observations', ['source_id'], unique=False)
    op.create_index('ix_source_obs_source_time', 'source_observations', ['source_id', 'observed_at'], unique=False)
    op.create_index('ix_source_obs_resource', 'source_observations', ['resource_id'], unique=False)

    op.create_table('source_change_events',
        sa.Column('id', sa.Uuid(), nullable=False),
        sa.Column('source_id', sa.Uuid(), nullable=False),
        sa.Column('run_id', sa.Uuid(), nullable=True),
        sa.Column('resource_id', sa.Uuid(), nullable=True),
        sa.Column('change_type', sa.String(length=32), nullable=False),
        sa.Column('detected_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('from_artifact_id', sa.Uuid(), nullable=True),
        sa.Column('to_artifact_id', sa.Uuid(), nullable=True),
        sa.Column('detail', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.ForeignKeyConstraint(['from_artifact_id'], ['source_artifacts.id'], name=op.f('fk_source_change_events_from_artifact_id_source_artifacts')),
        sa.ForeignKeyConstraint(['resource_id'], ['source_resources.id'], name=op.f('fk_source_change_events_resource_id_source_resources')),
        sa.ForeignKeyConstraint(['run_id'], ['ingestion_runs.id'], name=op.f('fk_source_change_events_run_id_ingestion_runs')),
        sa.ForeignKeyConstraint(['source_id'], ['sources.id'], name=op.f('fk_source_change_events_source_id_sources')),
        sa.ForeignKeyConstraint(['to_artifact_id'], ['source_artifacts.id'], name=op.f('fk_source_change_events_to_artifact_id_source_artifacts')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_source_change_events'))
    )
    op.create_index(op.f('ix_source_change_events_detected_at'), 'source_change_events', ['detected_at'], unique=False)
    op.create_index(op.f('ix_source_change_events_source_id'), 'source_change_events', ['source_id'], unique=False)
    op.create_index('ix_change_events_source_time', 'source_change_events', ['source_id', 'detected_at'], unique=False)
    op.create_index('ix_change_events_type', 'source_change_events', ['change_type'], unique=False)

    with op.batch_alter_table('sources', schema=None) as batch_op:
        batch_op.add_column(sa.Column('priority', sa.Integer(), nullable=False, server_default='100'))
        batch_op.add_column(sa.Column('admin_unit_id', sa.Uuid(), nullable=True))
        batch_op.create_foreign_key(batch_op.f('fk_sources_admin_unit_id_administrative_units'), 'administrative_units', ['admin_unit_id'], ['id'])

    with op.batch_alter_table('documents', schema=None) as batch_op:
        batch_op.add_column(sa.Column('metadata_origin', sa.String(length=32), nullable=False, server_default='unknown'))

    with op.batch_alter_table('planning_versions', schema=None) as batch_op:
        batch_op.add_column(sa.Column('metadata_origin', sa.String(length=32), nullable=False, server_default='unknown'))


def downgrade() -> None:
    with op.batch_alter_table('planning_versions', schema=None) as batch_op:
        batch_op.drop_column('metadata_origin')
    with op.batch_alter_table('documents', schema=None) as batch_op:
        batch_op.drop_column('metadata_origin')
    with op.batch_alter_table('sources', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('fk_sources_admin_unit_id_administrative_units'), type_='foreignkey')
        batch_op.drop_column('admin_unit_id')
        batch_op.drop_column('priority')
    op.drop_table('source_change_events')
    op.drop_table('source_observations')
    op.drop_table('source_resources')
    op.drop_table('source_crawl_state')
