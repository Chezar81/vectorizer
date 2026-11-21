"""Priority C: click-zap, PNG scale linking, and basic-guide settings."""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image
from PySide6.QtWidgets import QApplication

from vectorizer.domain.settings import (
    AaArtifactRejection,
    AutomaticQuality,
    ColorMode,
    EdgeTreatment,
    TraceSettings,
    WorkflowMode,
)
from vectorizer.errors import SegmentationError
from vectorizer.export.png import linked_export_size
from vectorizer.gui.settings_panel import SettingsPanel, guide_color_choice
from vectorizer.segmentation.map import SegmentationMap
from vectorizer.segmentation.ops import zap_component, zap_fringes

A = (10, 20, 30, 255)
B = (200, 30, 40, 255)
X = (250, 250, 250, 255)


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance()
    if app is None:
        app = QApplication(["vectorizer-priority-c"])
    assert isinstance(app, QApplication)
    return app


def test_click_zap_splits_a_component_across_neighbors() -> None:
    image = Image.new("RGBA", (5, 5), A)
    for y in range(1, 4):
        for x in range(1, 4):
            image.putpixel((x, y), X)
    for x in range(1, 4):
        image.putpixel((x, 4), B)
    source = SegmentationMap(image)
    updated = zap_component(source, 2, 2)
    assert source.image.getpixel((2, 2)) == X
    assert updated.image.getpixel((2, 1)) == A
    assert updated.image.getpixel((2, 3)) == B
    assert updated.image.getpixel((2, 2)) != X
    assert updated.image.getpixel((0, 0)) == A
    assert updated.image.getpixel((2, 4)) == B
    colors = {updated.image.getpixel((x, y)) for y in range(1, 4) for x in range(1, 4)}
    assert A in colors and B in colors
    assert X not in colors


def test_click_zap_dissolves_a_component_zap_fringes_keeps() -> None:
    red = (180, 20, 20, 255)
    blue = (20, 20, 180, 255)
    image = Image.new("RGBA", (20, 5), red)
    for x in range(2, 17):
        image.putpixel((x, 2), blue)
    kept = zap_fringes(SegmentationMap(image), max_pixels=8)
    assert kept.image.getpixel((8, 2)) == blue
    zapped = zap_component(SegmentationMap(image), 8, 2)
    assert zapped.image.getpixel((8, 2))[:3] == red[:3]
    assert zapped.image.getpixel((8, 2))[3] == 255
    assert zapped.image.getpixel((0, 0)) == red


def test_click_zap_ignores_transparent_and_rejects_outside() -> None:
    image = Image.new("RGBA", (3, 3), (0, 0, 0, 0))
    image.putpixel((1, 1), (1, 2, 3, 255))
    untouched = zap_component(SegmentationMap(image), 0, 0)
    assert untouched.image.getpixel((0, 0))[3] == 0
    assert untouched.image.getpixel((1, 1)) == (1, 2, 3, 255)
    alone = zap_component(SegmentationMap(image), 1, 1)
    assert alone.image.getpixel((1, 1)) == (1, 2, 3, 255)
    with pytest.raises(SegmentationError):
        zap_component(SegmentationMap(image), -1, 0)


def test_linked_png_scale_preserves_aspect() -> None:
    assert linked_export_size(100, 50, scale=2) == (200, 100, 2.0)
    assert linked_export_size(100, 50, width=50) == (50, 25, 0.5)
    assert linked_export_size(100, 50, height=100) == (200, 100, 2.0)
    assert linked_export_size(101, 50) == (101, 50, 1.0)
    width, height, scale = linked_export_size(101, 50, width=50)
    assert width == 50
    assert height == 25
    assert scale == pytest.approx(50 / 101)


def test_png_dialog_links_scale_presets(qapp: QApplication) -> None:
    from vectorizer.gui.main_window import PngExportDialog

    dialog = PngExportDialog(
        None, default_w=100, default_h=50, source_w=100, source_h=50
    )
    assert dialog.lock_aspect.isChecked()
    dialog.width_spin.setValue(200)
    assert dialog.height_spin.value() == 100
    assert dialog.scale_spin.value() == pytest.approx(2.0)
    dialog._scale_buttons[4].click()
    assert dialog.values()[:2] == (400, 200)
    dialog.lock_aspect.setChecked(False)
    dialog.width_spin.setValue(300)
    assert dialog.height_spin.value() == 200
    assert dialog.scale_spin.value() == pytest.approx(3.0)
    dialog.close()


def test_basic_guide_color_choice_buckets() -> None:
    assert (
        guide_color_choice(colormode=ColorMode.COLOR, palette=(), target_colors=0)
        == "unlimited"
    )
    assert guide_color_choice(colormode=ColorMode.BINARY) == "two"
    assert guide_color_choice(colormode=ColorMode.COLOR, palette=("#000000", "#ffffff")) == "two"
    assert guide_color_choice(colormode=ColorMode.COLOR, target_colors=8) == "custom"
    assert guide_color_choice(colormode=ColorMode.COLOR, palette_choice=-2) == "custom"


def test_settings_panel_advanced_and_basic_guide(qapp: QApplication, tmp_path) -> None:
    from vectorizer import presets as presets_mod

    previous = presets_mod._PRESETS_DIR_OVERRIDE
    presets_mod.set_presets_dir_override(tmp_path)
    try:
        panel = SettingsPanel()
        panel.set_settings(
            TraceSettings(
                workflow=WorkflowMode.ADVANCED,
                contour_smoothness=80,
                node_budget=30,
                filter_speckle=9,
                color_precision=7,
                cluster_similar_colors=True,
                aa_artifact_rejection=AaArtifactRejection.AGGRESSIVE,
            )
        )
        panel.show()
        qapp.processEvents()
        got = panel.settings()
        assert got.workflow == WorkflowMode.ADVANCED
        assert got.contour_smoothness == 80
        assert got.node_budget == 30
        assert got.filter_speckle == 9
        assert got.color_precision == 7
        assert got.cluster_similar_colors is True
        assert got.aa_artifact_rejection == AaArtifactRejection.AGGRESSIVE
        assert panel._curves_box.isVisible()
        assert panel._segments_box.isVisible()
        assert panel._palette_box.isVisible()
        assert not panel._engine_body.isVisible()
        assert not panel._basic_guide.isVisible()
        assert panel._noise_in_engine
        assert panel._cluster_in_palette

        panel.set_settings(
            TraceSettings(workflow=WorkflowMode.BASIC, edge_treatment=EdgeTreatment.HARD)
        )
        assert panel._basic_guide.isVisible()
        assert not panel._colors_box.isVisible()
        assert not panel._output_box.isVisible()
        assert not panel._curves_box.isVisible()
        assert panel._presets_box.isVisible()
        assert not panel._noise_in_engine
        assert not panel._cluster_in_palette
        assert panel.settings().edge_treatment == EdgeTreatment.HARD
        assert panel.settings().filter_speckle == TraceSettings().filter_speckle
        assert panel.settings().contour_smoothness == 50

        panel.set_settings(TraceSettings(workflow=WorkflowMode.AUTOMATIC))
        assert not panel._basic_guide.isVisible()
        assert not panel._colors_box.isVisible()
        assert not panel._presets_box.isVisible()
        assert not panel._output_box.isVisible()
        assert panel._preprocess_box.isVisible()
        assert panel.auto_quality.isVisible()

        panel.set_settings(
            TraceSettings(workflow=WorkflowMode.BASIC, edge_treatment=EdgeTreatment.HARD)
        )
        panel.set_analysis_hints(
            TraceSettings(
                edge_treatment=EdgeTreatment.BLENDED,
                automatic_quality=AutomaticQuality.BALANCED,
                colormode=ColorMode.BINARY,
            ),
            transparency_note="Soft edges are true transparent anti-aliasing. Leave transparency on.",
            transparency_recommendation="leave",
        )
        assert panel._basic_guide.isVisible()
        assert panel._basic_edge_badge.isVisible()
        assert panel._basic_color_badge.isVisible()
        photo = panel.basic_image_type.findData(EdgeTreatment.PHOTO)
        panel.basic_image_type.setCurrentIndex(photo)
        panel.basic_image_type.activated.emit(photo)
        assert panel.settings().edge_treatment == EdgeTreatment.PHOTO
        assert panel._basic_edge_badge.isVisible()
        blended = panel.basic_image_type.findData(EdgeTreatment.BLENDED)
        panel.basic_image_type.setCurrentIndex(blended)
        panel.basic_image_type.activated.emit(blended)
        assert panel.settings().edge_treatment == EdgeTreatment.BLENDED
        assert not panel._basic_edge_badge.isVisible()

        fast = panel.basic_quality.findData(AutomaticQuality.FAST)
        panel.basic_quality.setCurrentIndex(fast)
        panel.basic_quality.activated.emit(fast)
        assert panel.settings().automatic_quality == AutomaticQuality.FAST
        assert panel._basic_quality_badge.isVisible()

        two = panel.basic_color.findData("two")
        panel.basic_color.setCurrentIndex(two)
        panel.basic_color.activated.emit(two)
        assert panel.settings().colormode == ColorMode.BINARY
        assert not panel._basic_color_badge.isVisible()

        panel.preserve_transparency.setChecked(False)
        assert panel._basic_transparency_badge.isVisible()
        panel.preserve_transparency.setChecked(True)
        assert not panel._basic_transparency_badge.isVisible()

        # Collapsed engine values still round-trip after returning to Advanced.
        panel.set_settings(
            TraceSettings(workflow=WorkflowMode.ADVANCED, color_precision=3, filter_speckle=11)
        )
        assert not panel._engine_body.isVisible()
        assert panel.settings().color_precision == 3
        assert panel.settings().filter_speckle == 11
        panel.close()
    finally:
        presets_mod.set_presets_dir_override(previous)
