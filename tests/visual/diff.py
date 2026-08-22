"""Visual diff and image comparison utility for Metaglyph UI testing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from PySide6.QtCore import QPoint, QRect, QSize
from PySide6.QtGui import QColor, QFont, QImage, QPainter


@dataclass
class DiffResult:
    """Result of comparing two visual snapshots."""

    is_match: bool
    mismatch_percentage: float
    total_pixels: int
    diff_pixels: int
    baseline_path: Path | None = None
    actual_path: Path | None = None
    diff_image_path: Path | None = None
    error_message: str | None = None


class VisualDiff:
    """Pixel-by-pixel image comparator and diff overlay generator."""

    def __init__(
        self,
        pixel_tolerance: int = 16,
        max_mismatch_percentage: float = 0.05,
    ) -> None:
        """Initialize visual diff engine.

        Args:
            pixel_tolerance: Max allowable RGB channel difference per pixel (0-255)
                             to tolerate slight font anti-aliasing / subpixel variations.
            max_mismatch_percentage: Max allowable percentage of mismatched pixels
                                     (0.0 to 100.0) before failing comparison.
        """
        self.pixel_tolerance = pixel_tolerance
        self.max_mismatch_percentage = max_mismatch_percentage

    def compare_images(
        self,
        baseline_path: str | Path,
        actual_path: str | Path,
        diff_output_path: str | Path | None = None,
    ) -> DiffResult:
        """Compare two saved image files on disk and optionally generate a visual diff image."""
        baseline_p = Path(baseline_path)
        actual_p = Path(actual_path)

        if not baseline_p.exists():
            return DiffResult(
                is_match=False,
                mismatch_percentage=100.0,
                total_pixels=0,
                diff_pixels=0,
                baseline_path=baseline_p,
                actual_path=actual_p,
                error_message=f"Baseline image not found: {baseline_p}",
            )

        if not actual_p.exists():
            return DiffResult(
                is_match=False,
                mismatch_percentage=100.0,
                total_pixels=0,
                diff_pixels=0,
                baseline_path=baseline_p,
                actual_path=actual_p,
                error_message=f"Actual image not found: {actual_p}",
            )

        baseline_img = QImage(str(baseline_p))
        actual_img = QImage(str(actual_p))

        if baseline_img.isNull():
            return DiffResult(
                is_match=False,
                mismatch_percentage=100.0,
                total_pixels=0,
                diff_pixels=0,
                baseline_path=baseline_p,
                actual_path=actual_p,
                error_message=f"Failed to decode baseline image: {baseline_p}",
            )

        if actual_img.isNull():
            return DiffResult(
                is_match=False,
                mismatch_percentage=100.0,
                total_pixels=0,
                diff_pixels=0,
                baseline_path=baseline_p,
                actual_path=actual_p,
                error_message=f"Failed to decode actual image: {actual_p}",
            )

        diff_out_p = Path(diff_output_path) if diff_output_path else None
        res = self.compare_qimages(baseline_img, actual_img, diff_output_path=diff_out_p)
        res.baseline_path = baseline_p
        res.actual_path = actual_p
        return res

    def compare_qimages(
        self,
        baseline: QImage,
        actual: QImage,
        diff_output_path: Path | None = None,
    ) -> DiffResult:
        """Compare two QImage instances."""
        b_width, b_height = baseline.width(), baseline.height()
        a_width, a_height = actual.width(), actual.height()

        if b_width != a_width or b_height != a_height:
            # Dimension mismatch
            total = max(b_width * b_height, a_width * a_height)
            return DiffResult(
                is_match=False,
                mismatch_percentage=100.0,
                total_pixels=total,
                diff_pixels=total,
                error_message=f"Dimension mismatch: baseline is {b_width}x{b_height}, actual is {a_width}x{a_height}",
            )

        # Standardize format to ARGB32
        base_conv = baseline.convertToFormat(QImage.Format.Format_ARGB32)
        act_conv = actual.convertToFormat(QImage.Format.Format_ARGB32)

        width, height = b_width, b_height
        total_pixels = width * height
        diff_pixels = 0

        # Create diff overlay image (mask)
        diff_mask = QImage(width, height, QImage.Format.Format_ARGB32)
        diff_mask.fill(QColor(0, 0, 0, 0))

        tol = self.pixel_tolerance

        for y in range(height):
            for x in range(width):
                c1 = base_conv.pixelColor(x, y)
                c2 = act_conv.pixelColor(x, y)

                r_diff = abs(c1.red() - c2.red())
                g_diff = abs(c1.green() - c2.green())
                b_diff = abs(c1.blue() - c2.blue())
                a_diff = abs(c1.alpha() - c2.alpha())

                if r_diff > tol or g_diff > tol or b_diff > tol or a_diff > tol:
                    diff_pixels += 1
                    # Highlight mismatched pixel with vivid magenta
                    diff_mask.setPixelColor(x, y, QColor(255, 0, 128, 255))

        mismatch_pct = (diff_pixels / total_pixels) * 100.0 if total_pixels > 0 else 0.0
        is_match = mismatch_pct <= self.max_mismatch_percentage

        diff_saved_path: Path | None = None
        if diff_output_path and (not is_match or diff_pixels > 0):
            diff_output_path.parent.mkdir(parents=True, exist_ok=True)
            # Create composite image: [Baseline | Actual | Diff Overlay]
            composite = self._create_side_by_side_composite(base_conv, act_conv, diff_mask, mismatch_pct)
            composite.save(str(diff_output_path))
            diff_saved_path = diff_output_path

        return DiffResult(
            is_match=is_match,
            mismatch_percentage=round(mismatch_pct, 4),
            total_pixels=total_pixels,
            diff_pixels=diff_pixels,
            diff_image_path=diff_saved_path,
        )

    def _create_side_by_side_composite(
        self,
        baseline: QImage,
        actual: QImage,
        diff_mask: QImage,
        mismatch_pct: float,
    ) -> QImage:
        """Create a 3-panel side-by-side composite: Baseline | Actual | Diff Overlay."""
        w, h = baseline.width(), baseline.height()
        header_height = 40
        panel_spacing = 10
        total_w = (w * 3) + (panel_spacing * 2) + 20
        total_h = h + header_height + 20

        composite = QImage(total_w, total_h, QImage.Format.Format_ARGB32)
        composite.fill(QColor(18, 18, 24))  # Dark background

        painter = QPainter(composite)
        try:
            # Header font
            header_font = QFont("sans-serif", 10)
            header_font.setBold(True)
            painter.setFont(header_font)

            # Panel 1: Baseline
            x1 = 10
            y1 = header_height + 10
            painter.setPen(QColor(148, 163, 184))
            painter.drawText(QRect(x1, 10, w, 24), 0, "BASELINE (Expected)")
            painter.drawImage(x1, y1, baseline)

            # Panel 2: Actual
            x2 = x1 + w + panel_spacing
            painter.drawText(QRect(x2, 10, w, 24), 0, "ACTUAL (Current)")
            painter.drawImage(x2, y1, actual)

            # Panel 3: Diff Overlay (Actual with magenta diff mask over top)
            x3 = x2 + w + panel_spacing
            painter.setPen(QColor(244, 63, 94))
            painter.drawText(
                QRect(x3, 10, w, 24),
                0,
                f"DIFF OVERLAY ({mismatch_pct:.2f}% mismatch)",
            )
            dimmed_actual = actual.copy()
            painter.drawImage(x3, y1, dimmed_actual)
            painter.drawImage(x3, y1, diff_mask)

        finally:
            painter.end()

        return composite
