"""add per-page scale provenance and trust metadata

Revision ID: l0f1a2b3c4d5
Revises: k9e0f1a2b3c4
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "l0f1a2b3c4d5"
down_revision: Union[str, Sequence[str], None] = "k9e0f1a2b3c4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("drawings", sa.Column("scale_detection_method", sa.String(50), nullable=True))
    op.add_column("drawings", sa.Column("scale_confidence", sa.Float(), nullable=True))
    op.add_column("drawings", sa.Column(
        "scale_requires_confirmation", sa.Boolean(), nullable=False, server_default=sa.true()
    ))
    op.add_column("drawings", sa.Column("scale_dpi", sa.Float(), nullable=True))
    op.add_column("drawings", sa.Column("ocr_scale_method", sa.String(50), nullable=True))
    op.add_column("drawings", sa.Column(
        "ocr_scale_conflict", sa.Boolean(), nullable=False, server_default=sa.false()
    ))
    op.add_column("drawings", sa.Column("ocr_scale_candidates", sa.Text(), nullable=True))

    # Historical manual calibration used the explicit virtual 300-DPI raster
    # coordinate convention and is safe to preserve. Accepted OCR is safe for
    # PDFs (native points); raster OCR without recorded DPI must be reconfirmed.
    op.execute("""
        UPDATE drawings
        SET scale_detection_method = 'manual_two_point',
            scale_confidence = 1.0,
            scale_requires_confirmation = false,
            scale_dpi = CASE WHEN upper(coalesce(file_type, '')) = 'PDF' THEN 72.0 ELSE 300.0 END
        WHERE scale_source = 'manual' AND scale_ratio > 0
    """)
    op.execute("""
        UPDATE drawings
        SET scale_detection_method = 'legacy_ocr_confirmed',
            scale_confidence = ocr_scale_confidence,
            scale_requires_confirmation = CASE WHEN upper(coalesce(file_type, '')) = 'PDF' THEN false ELSE true END,
            scale_dpi = CASE WHEN upper(coalesce(file_type, '')) = 'PDF' THEN 72.0 ELSE NULL END
        WHERE scale_source = 'ocr' AND scale_ratio > 0
    """)


def downgrade() -> None:
    op.drop_column("drawings", "ocr_scale_candidates")
    op.drop_column("drawings", "ocr_scale_conflict")
    op.drop_column("drawings", "ocr_scale_method")
    op.drop_column("drawings", "scale_dpi")
    op.drop_column("drawings", "scale_requires_confirmation")
    op.drop_column("drawings", "scale_confidence")
    op.drop_column("drawings", "scale_detection_method")
