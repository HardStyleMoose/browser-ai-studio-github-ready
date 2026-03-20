from __future__ import annotations

import copy
import time

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QSplitter,
    QFileDialog,
    QFrame,
    QGraphicsScene,
    QGraphicsView,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QComboBox,
)

from ui.features.keyboard_shortcuts import KeyboardShortcutsManager
from ui.features.minimap import MiniMap
from ui.node_graph.connection_item import ConnectionItem
from ui.node_graph.graph_serializer import GraphSerializer
from ui.node_graph.node_item import NodeItem
from ui.node_graph.node_registry import NodeRegistry
from ui.region_selector_overlay import RegionSelectorOverlay
from ui.theme_presets import get_editor_theme


class GraphScene(QGraphicsScene):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSceneRect(-2000, -2000, 4000, 4000)
        self.background_image = None
        self.background_scale = 1.0
        self._background_color = QColor("#0f172a")
        self._minor_grid_color = QColor("#182235")
        self._major_grid_color = QColor("#22304a")

    def set_background_image(self, image: QImage, scale=1.0):
        self.background_image = image
        self.background_scale = scale
        self.update()

    def clear_background_image(self):
        self.background_image = None
        self.background_scale = 1.0
        self.update()

    def apply_theme(self, colors: dict):
        self._background_color = QColor(colors["scene_bg"])
        self._minor_grid_color = QColor(colors["grid_minor"])
        self._major_grid_color = QColor(colors["grid_major"])
        self.update()

    def drawBackground(self, painter: QPainter, rect: QRectF):
        super().drawBackground(painter, rect)
        if self.background_image is not None:
            width = self.background_image.width() * self.background_scale
            height = self.background_image.height() * self.background_scale
            painter.drawImage(QRectF(0, 0, width, height), self.background_image)
        else:
            painter.fillRect(rect, self._background_color)

        minor_pen = QPen(self._minor_grid_color, 1)
        major_pen = QPen(self._major_grid_color, 1)
        grid_size = 24
        left = int(rect.left()) - (int(rect.left()) % grid_size)
        top = int(rect.top()) - (int(rect.top()) % grid_size)

        for x_pos in range(left, int(rect.right()), grid_size):
            painter.setPen(major_pen if x_pos % (grid_size * 4) == 0 else minor_pen)
            painter.drawLine(x_pos, int(rect.top()), x_pos, int(rect.bottom()))

        for y_pos in range(top, int(rect.bottom()), grid_size):
            painter.setPen(major_pen if y_pos % (grid_size * 4) == 0 else minor_pen)
            painter.drawLine(int(rect.left()), y_pos, int(rect.right()), y_pos)


class NodeEditor(QWidget):
    def __init__(self, click_overlay=None):
        super().__init__()
        self.registry = NodeRegistry()
        self.node_counter = 0
        self.nodes = {}
        self.connections = []
        self.clipboard_graph = None
        self.simulate_mode = False
        self.click_overlay = click_overlay
        self.action_handlers = {}
        self._panning = False
        self._pan_start = None
        self._current_theme_colors = None

        self.scene = GraphScene(self)
        self.view = QGraphicsView(self.scene)
        self.view.setRenderHint(QPainter.Antialiasing)
        self.view.setDragMode(QGraphicsView.RubberBandDrag)
        self.view.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)
        self.view.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.view.viewport().installEventFilter(self)
        self.view.horizontalScrollBar().valueChanged.connect(self._schedule_minimap_refresh)
        self.view.verticalScrollBar().valueChanged.connect(self._schedule_minimap_refresh)
        self.scene.changed.connect(self._schedule_minimap_refresh)

        self._minimap_refresh_timer = QTimer(self)
        self._minimap_refresh_timer.setSingleShot(True)
        self._minimap_refresh_timer.setInterval(60)
        self._minimap_refresh_timer.timeout.connect(self._update_minimap_preview)

        self.keyboard_shortcuts = KeyboardShortcutsManager(self)

        self._build_ui()
        self._wire_shortcuts()
        self._refresh_left_nav_toggle()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.toolbar_widget = QFrame()
        self.toolbar_widget.setObjectName("graphToolbar")
        self.toolbar_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.toolbar_layout = QGridLayout(self.toolbar_widget)
        self.toolbar_layout.setContentsMargins(12, 12, 12, 10)
        self.toolbar_layout.setHorizontalSpacing(10)
        self.toolbar_layout.setVerticalSpacing(10)

        add_group, add_layout = self._make_toolbar_section("Add Node")
        self.node_combo = QComboBox()
        self.node_combo.setMinimumWidth(118)
        self.node_combo.addItems([self.registry.get(node_type)["title"] for node_type in self.registry.all().keys()])
        add_button = QPushButton("Add")
        add_button.clicked.connect(self._add_selected_node)
        add_layout.addWidget(self.node_combo)
        add_layout.addWidget(add_button)

        edit_group, edit_layout = self._make_toolbar_section("Edit")
        connect_button = QPushButton("Connect")
        connect_button.clicked.connect(self.connect_selected)
        delete_button = QPushButton("Delete")
        delete_button.clicked.connect(self.delete_selected)
        copy_button = QPushButton("Copy")
        copy_button.clicked.connect(self.copy_selected)
        paste_button = QPushButton("Paste")
        paste_button.clicked.connect(self.paste_copied)
        for button in [connect_button, delete_button, copy_button, paste_button]:
            edit_layout.addWidget(button)

        bg_group, bg_layout = self._make_toolbar_section("Background")
        screenshot_button = QPushButton("Screenshot BG")
        screenshot_button.clicked.connect(self.take_screenshot_background)
        clear_button = QPushButton("Clear BG")
        clear_button.clicked.connect(self.clear_background_image)
        zoom_out_button = QPushButton("- Zoom BG")
        zoom_out_button.clicked.connect(lambda: self.scale_background(0.9))
        zoom_in_button = QPushButton("+ Zoom BG")
        zoom_in_button.clicked.connect(lambda: self.scale_background(1.1))
        for button in [screenshot_button, clear_button, zoom_out_button, zoom_in_button]:
            bg_layout.addWidget(button)

        view_group, view_layout = self._make_toolbar_section("View")
        self.left_nav_toggle_btn = QPushButton("Hide Left Nav")
        self.left_nav_toggle_btn.clicked.connect(self.toggle_left_navigation)
        view_layout.addWidget(self.left_nav_toggle_btn)
        self.toolbar_sections = [add_group, edit_group, bg_group, view_group]
        for section in self.toolbar_sections:
            section.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self._relayout_toolbar_sections()
        layout.addWidget(self.toolbar_widget)

        self.view.setMinimumHeight(240)
        self.view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.center_splitter = QSplitter(Qt.Horizontal)
        self.center_splitter.setChildrenCollapsible(False)
        self.center_splitter.addWidget(self.view)

        self.side_panel = QFrame()
        self.side_panel.setObjectName("editorSidePanel")
        side_layout = QVBoxLayout(self.side_panel)
        side_layout.setContentsMargins(12, 12, 12, 12)
        side_layout.setSpacing(10)
        self.side_header_label = QLabel("Inspector")
        side_layout.addWidget(self.side_header_label)

        toggle_row = QHBoxLayout()
        toggle_row.setSpacing(8)
        self.log_view_btn = QPushButton("Logs")
        self.log_view_btn.setCheckable(True)
        self.log_view_btn.setChecked(True)
        self.minimap_view_btn = QPushButton("Minimap")
        self.minimap_view_btn.setCheckable(True)
        view_button_group = QButtonGroup(self)
        view_button_group.setExclusive(True)
        view_button_group.addButton(self.log_view_btn)
        view_button_group.addButton(self.minimap_view_btn)
        self.log_view_btn.clicked.connect(lambda: self._set_side_mode("logs"))
        self.minimap_view_btn.clicked.connect(lambda: self._set_side_mode("minimap"))
        toggle_row.addWidget(self.log_view_btn)
        toggle_row.addWidget(self.minimap_view_btn)
        side_layout.addLayout(toggle_row)

        self.side_stack = QStackedWidget()
        side_layout.addWidget(self.side_stack, stretch=1)

        log_page = QWidget()
        log_layout = QVBoxLayout(log_page)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.setSpacing(8)
        self.log_status_label = QLabel("Simulation activity appears here.")
        log_layout.addWidget(self.log_status_label)

        self.log_panel = QTextEdit()
        self.log_panel.setReadOnly(True)
        self.log_panel.setLineWrapMode(QTextEdit.WidgetWidth)
        self.log_panel.setPlaceholderText("Simulation activity appears here.")
        log_layout.addWidget(self.log_panel, stretch=1)
        self.side_stack.addWidget(log_page)

        minimap_page = QWidget()
        minimap_layout = QVBoxLayout(minimap_page)
        minimap_layout.setContentsMargins(0, 0, 0, 0)
        minimap_layout.setSpacing(8)
        self.minimap_status_label = QLabel("Shows the full graph and your current viewport.")
        minimap_layout.addWidget(self.minimap_status_label)
        self.minimap = MiniMap()
        minimap_layout.addWidget(self.minimap, stretch=1)
        self.minimap_refresh_btn = QPushButton("Refresh Minimap")
        self.minimap_refresh_btn.clicked.connect(self._update_minimap_preview)
        minimap_layout.addWidget(self.minimap_refresh_btn)
        self.side_stack.addWidget(minimap_page)

        self.side_panel.setMinimumWidth(220)
        self.side_panel.setMaximumWidth(340)
        self.side_panel.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Expanding)
        self.center_splitter.addWidget(self.side_panel)
        self.center_splitter.setStretchFactor(0, 5)
        self.center_splitter.setStretchFactor(1, 2)
        self.center_splitter.setSizes([980, 280])
        layout.addWidget(self.center_splitter, stretch=1)

        self.controls_frame = QFrame()
        self.controls_frame.setObjectName("editorControls")
        self.controls_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        self.controls_layout = QGridLayout(self.controls_frame)
        self.controls_layout.setContentsMargins(12, 10, 12, 10)
        self.controls_layout.setHorizontalSpacing(10)
        self.controls_layout.setVerticalSpacing(10)
        self.bottom_buttons = {}
        self.bottom_button_order = []
        for label, handler in [
            ("Step", self.step_action),
            ("Pause", self.pause_action),
            ("Resume", self.resume_action),
            ("Apply Behavior", self.apply_behavior_action),
            ("Save", self.save_graph_action),
            ("Load", self.load_graph_action),
            ("History", self.history_action),
            ("Simulate", self.simulate_action),
        ]:
            button = QPushButton(label)
            button.clicked.connect(handler)
            self.bottom_buttons[label] = button
            self.bottom_button_order.append(button)
        self._relayout_bottom_buttons()
        layout.addWidget(self.controls_frame)
        self.apply_theme("terminal")

    def _make_toolbar_section(self, title: str):
        section = QFrame()
        section.setObjectName("toolbarSection")
        section_layout = QVBoxLayout(section)
        section_layout.setContentsMargins(10, 8, 10, 8)
        section_layout.setSpacing(6)
        title_label = QLabel(title)
        title_label.setObjectName("toolbarSectionTitle")
        section_layout.addWidget(title_label)
        controls_row = QHBoxLayout()
        controls_row.setContentsMargins(0, 0, 0, 0)
        controls_row.setSpacing(8)
        section_layout.addLayout(controls_row)
        return section, controls_row

    def _responsive_column_count(self, available_width: int, item_count: int) -> int:
        if item_count <= 1:
            return 1
        if available_width >= 1280:
            return min(item_count, 4)
        if available_width >= 980:
            return min(item_count, 3)
        if available_width >= 700:
            return min(item_count, 2)
        return 1

    def _clear_grid_layout(self, grid_layout: QGridLayout):
        while grid_layout.count():
            item = grid_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(grid_layout.parentWidget())

    def _relayout_toolbar_sections(self):
        if not hasattr(self, "toolbar_layout") or not hasattr(self, "toolbar_sections"):
            return
        self._clear_grid_layout(self.toolbar_layout)
        available_width = max(self.width(), self.toolbar_widget.width(), 600)
        columns = self._responsive_column_count(available_width, len(self.toolbar_sections))
        for index, section in enumerate(self.toolbar_sections):
            row = index // columns
            column = index % columns
            self.toolbar_layout.addWidget(section, row, column)
        for column in range(columns):
            self.toolbar_layout.setColumnStretch(column, 1)
        height = max(1, self.toolbar_widget.sizeHint().height())
        self.toolbar_widget.setMinimumHeight(height)
        self.toolbar_widget.setMaximumHeight(height)

    def _relayout_bottom_buttons(self):
        if not hasattr(self, "controls_layout") or not hasattr(self, "bottom_button_order"):
            return
        self._clear_grid_layout(self.controls_layout)
        available_width = max(self.width(), self.controls_frame.width(), 600)
        if available_width >= 1040:
            columns = min(len(self.bottom_button_order), 4)
        elif available_width >= 820:
            columns = min(len(self.bottom_button_order), 3)
        elif available_width >= 580:
            columns = min(len(self.bottom_button_order), 2)
        else:
            columns = 1
        for index, button in enumerate(self.bottom_button_order):
            row = index // columns
            column = index % columns
            self.controls_layout.addWidget(button, row, column)
        for column in range(columns):
            self.controls_layout.setColumnStretch(column, 1)
        height = max(1, self.controls_frame.sizeHint().height())
        self.controls_frame.setMinimumHeight(height)
        self.controls_frame.setMaximumHeight(height)

    def _sync_splitter_sizes(self):
        if not hasattr(self, "center_splitter"):
            return
        total_width = max(1, self.center_splitter.width())
        if total_width <= 0:
            return
        panel_width = 250
        if total_width < 920:
            panel_width = 220
        elif total_width > 1500:
            panel_width = 300
        graph_width = max(320, total_width - panel_width - 8)
        self.center_splitter.setSizes([graph_width, panel_width])

    def _wire_shortcuts(self):
        self.keyboard_shortcuts.add_shortcut("Ctrl+C", self.copy_selected)
        self.keyboard_shortcuts.add_shortcut("Ctrl+V", self.paste_copied)
        self.keyboard_shortcuts.add_shortcut("Delete", self.delete_selected)
        self.keyboard_shortcuts.add_shortcut("Ctrl+S", self.save_graph_action)
        self.keyboard_shortcuts.add_shortcut("Ctrl+O", self.load_graph_action)
        self.keyboard_shortcuts.add_shortcut("Ctrl+B", self.toggle_left_navigation)

    def apply_theme(self, theme_name: str):
        colors = get_editor_theme(theme_name)
        self.toolbar_widget.setStyleSheet(
            "QFrame#graphToolbar { background: %(toolbar)s; border: 1px solid %(toolbar_border)s; border-radius: 12px; }"
            "QFrame#toolbarSection { background: %(section)s; border: 1px solid %(section_border)s; border-radius: 10px; }"
            "QLabel#toolbarSectionTitle { color: %(accent)s; font-weight: 700; padding-left: 2px; }"
            "QPushButton { background: %(button_bg)s; color: %(button_fg)s; border: 1px solid %(field_border)s; border-radius: 8px; padding: 6px 10px; min-height: 18px; }"
            "QPushButton:hover { background: %(button_hover)s; }"
            "QComboBox { background: %(field)s; color: %(button_fg)s; border: 1px solid %(field_border)s; border-radius: 8px; padding: 4px 8px; min-height: 18px; }"
            "QComboBox QAbstractItemView { background: %(field)s; color: %(button_fg)s; border: 1px solid %(field_border)s; selection-background-color: %(button_hover)s; }"
            % colors
        )
        self.side_panel.setStyleSheet(
            "QFrame#editorSidePanel { background: %(panel)s; border: 1px solid %(panel_border)s; border-radius: 14px; }"
            "QLabel { color: %(accent)s; font-weight: 600; }"
            % colors
        )
        self.log_panel.setStyleSheet(
            "QTextEdit { background: %(field)s; color: %(button_fg)s; border: 1px solid %(field_border)s; border-radius: 10px; padding: 8px; }"
            % colors
        )
        self.minimap.setStyleSheet(
            "background: %(field)s; color: %(button_fg)s; border: 1px solid %(field_border)s; border-radius: 10px;" % colors
        )
        self.controls_frame.setStyleSheet(
            "QFrame#editorControls { background: %(toolbar)s; border: 1px solid %(toolbar_border)s; border-radius: 12px; }"
            % colors
        )
        self.side_header_label.setStyleSheet("color: %s; font-weight: 700;" % colors["accent"])
        self.log_status_label.setStyleSheet("color: %s;" % colors["accent"])
        self.minimap_status_label.setStyleSheet("color: %s;" % colors["accent"])
        toggle_button_style = (
            "QPushButton { background: %(button_bg)s; color: %(button_fg)s; border: 1px solid %(field_border)s; border-radius: 8px; padding: 6px 10px; min-height: 18px; }"
            "QPushButton:hover { background: %(button_hover)s; }"
            "QPushButton:checked { background: %(accent)s; color: %(toolbar)s; font-weight: 700; }"
            % colors
        )
        self.log_view_btn.setStyleSheet(toggle_button_style)
        self.minimap_view_btn.setStyleSheet(toggle_button_style)
        self.minimap_refresh_btn.setStyleSheet(toggle_button_style)
        self._current_theme_colors = colors
        self.scene.apply_theme(colors)
        self.minimap.apply_theme(colors)
        self._schedule_minimap_refresh()

    def set_action_handler(self, name: str, handler):
        self.action_handlers[name] = handler

    def _run_action_handler(self, name: str):
        handler = self.action_handlers.get(name)
        if handler is None:
            return False
        handler()
        return True

    def append_log(self, message: str):
        self.log_panel.append(message)

    def clear_log(self):
        self.log_panel.clear()

    def _main_window_host(self):
        window = self.window()
        if window is not None and hasattr(window, "toggle_sidebar_visibility") and hasattr(window, "is_sidebar_visible"):
            return window
        return None

    def _refresh_left_nav_toggle(self):
        if not hasattr(self, "left_nav_toggle_btn"):
            return
        host = self._main_window_host()
        is_visible = True if host is None else host.is_sidebar_visible()
        self.left_nav_toggle_btn.setText("Hide Left Nav" if is_visible else "Show Left Nav")

    def toggle_left_navigation(self):
        host = self._main_window_host()
        if host is None:
            self.append_log("Left navigation toggle is unavailable in this window.")
            self._refresh_left_nav_toggle()
            return
        visible = host.toggle_sidebar_visibility()
        message = "Left navigation shown." if visible else "Left navigation hidden for graph focus."
        self.append_log(message)
        if hasattr(host, "set_status"):
            host.set_status(message)
        self._refresh_left_nav_toggle()

    def _set_side_mode(self, mode: str):
        if mode == "minimap":
            self.side_stack.setCurrentIndex(1)
            self._update_minimap_preview()
        else:
            self.side_stack.setCurrentIndex(0)

    def _schedule_minimap_refresh(self, *args):
        self._minimap_refresh_timer.start()

    def _update_minimap_preview(self):
        scene_rect = self._build_minimap_scene_rect()
        if scene_rect.width() <= 0 or scene_rect.height() <= 0:
            self.minimap.clear_snapshot()
            return

        target_size = self.minimap.size()
        width = max(320, target_size.width() * 2)
        height = max(200, target_size.height() * 2)
        pixmap = QPixmap(width, height)
        background = QColor(self._current_theme_colors["field"] if self._current_theme_colors else "#07101f")
        pixmap.fill(background)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        self.scene.render(painter, QRectF(0, 0, width, height), scene_rect)
        painter.end()

        viewport_rect = self.view.mapToScene(self.view.viewport().rect()).boundingRect()
        self.minimap.set_snapshot(pixmap, scene_rect, viewport_rect)

    def _build_minimap_scene_rect(self):
        scene_rect = QRectF()
        if self.scene.background_image is not None:
            scene_rect = QRectF(
                0,
                0,
                self.scene.background_image.width() * self.scene.background_scale,
                self.scene.background_image.height() * self.scene.background_scale,
            )

        items_rect = self.scene.itemsBoundingRect()
        if scene_rect.isNull():
            scene_rect = items_rect
        else:
            scene_rect = scene_rect.united(items_rect)

        viewport_rect = self.view.mapToScene(self.view.viewport().rect()).boundingRect()
        if scene_rect.isNull():
            scene_rect = viewport_rect
        else:
            scene_rect = scene_rect.united(viewport_rect)

        if scene_rect.width() <= 0 or scene_rect.height() <= 0:
            return QRectF()
        return scene_rect.adjusted(-40, -40, 40, 40)

    def _add_selected_node(self):
        selected_title = self.node_combo.currentText()
        for node_type, definition in self.registry.all().items():
            if definition["title"] == selected_title:
                self.add_node(node_type)
                return

    def set_simulate_mode(self, mode: bool):
        self.simulate_mode = mode
        self._schedule_minimap_refresh()

    def eventFilter(self, obj, event):
        event_type = event.type()
        if event_type == QEvent.Type.Wheel:
            delta = event.angleDelta().y()
            if delta:
                self.view.scale(1.1 if delta > 0 else 0.9, 1.1 if delta > 0 else 0.9)
                self._schedule_minimap_refresh()
                return True

        if event_type == QEvent.Type.MouseButtonPress and event.button() == Qt.RightButton:
            self._panning = True
            self._pan_start = event.pos()
            return True

        if event_type == QEvent.Type.MouseMove and self._panning:
            dx = event.pos().x() - self._pan_start.x()
            dy = event.pos().y() - self._pan_start.y()
            self.view.horizontalScrollBar().setValue(self.view.horizontalScrollBar().value() - dx)
            self.view.verticalScrollBar().setValue(self.view.verticalScrollBar().value() - dy)
            self._pan_start = event.pos()
            self._schedule_minimap_refresh()
            return True

        if event_type == QEvent.Type.MouseButtonRelease and event.button() == Qt.RightButton:
            self._panning = False
            return True

        if event_type == QEvent.Type.MouseButtonPress and self.simulate_mode:
            item = self.scene.itemAt(self.view.mapToScene(event.pos()), self.view.transform())
            if hasattr(item, "node_id"):
                self.show_click_preview(item.node_id)

        return super().eventFilter(obj, event)

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_left_nav_toggle()
        self._relayout_toolbar_sections()
        self._relayout_bottom_buttons()
        self._sync_splitter_sizes()

    def show_click_preview(self, block_id):
        node = self.nodes.get(block_id)
        target = node.config.get("target") if node is not None else None
        if self.click_overlay is not None and isinstance(target, (tuple, list)) and len(target) == 2:
            self.click_overlay.show_circle(target[0], target[1], duration=700)

    def _select_region(self):
        overlay = RegionSelectorOverlay()
        overlay.show()
        while overlay.isVisible():
            QApplication.processEvents()
            time.sleep(0.01)
        return overlay.get_selected_region()

    def take_screenshot_background(self):
        try:
            from vision.screen_capture import capture_screen
        except Exception as exc:
            QMessageBox.warning(self, "Screenshot Error", f"Screen capture is unavailable: {exc}")
            return

        region = self._select_region()
        if not region:
            return
        x, y, w, h = region
        if w <= 0 or h <= 0:
            QMessageBox.warning(self, "Screenshot Error", "Selected region is invalid.")
            return

        frame = capture_screen({"left": x, "top": y, "width": w, "height": h})
        rgb_frame = frame[:, :, ::-1].copy()
        image = QImage(rgb_frame.data, w, h, 3 * w, QImage.Format.Format_RGB888)
        self.scene.set_background_image(image.copy(), scale=1.0)
        self._schedule_minimap_refresh()

    def clear_background_image(self):
        self.scene.clear_background_image()
        self._schedule_minimap_refresh()

    def scale_background(self, factor: float):
        if self.scene.background_image is None:
            return
        self.scene.background_scale *= factor
        self.scene.update()
        self._schedule_minimap_refresh()

    def _next_node_id(self, node_type: str):
        self.node_counter += 1
        return f"{node_type}_{self.node_counter}"

    def add_node(self, node_type: str, pos: QPointF | None = None, title: str | None = None, config=None, node_id: str | None = None):
        definition = self.registry.get(node_type)
        resolved_id = node_id or self._next_node_id(node_type)
        node = NodeItem(
            node_id=resolved_id,
            node_type=node_type,
            title=title or definition["title"],
            color=definition["color"],
            config=copy.deepcopy(config) if config is not None else copy.deepcopy(definition.get("config", {})),
            inputs=definition.get("inputs", 1),
            outputs=definition.get("outputs", 1),
        )
        self.nodes[resolved_id] = node
        self.scene.addItem(node)
        if pos is None:
            center_point = self.view.mapToScene(self.view.viewport().rect().center())
            pos = QPointF(center_point.x(), center_point.y())
        elif isinstance(pos, (tuple, list)):
            pos = QPointF(pos[0], pos[1])
        node.setPos(pos)
        self._schedule_minimap_refresh()
        return node

    def connect_nodes(self, from_node_id: str, to_node_id: str, from_socket_index: int = 0, to_socket_index: int = 0):
        start_node = self.nodes.get(from_node_id)
        end_node = self.nodes.get(to_node_id)
        if start_node is None or end_node is None:
            return None
        if not start_node.output_sockets or not end_node.input_sockets:
            return None

        start_socket = start_node.output_sockets[min(from_socket_index, len(start_node.output_sockets) - 1)]
        end_socket = end_node.input_sockets[min(to_socket_index, len(end_node.input_sockets) - 1)]
        for connection in self.connections:
            if connection.start_socket == start_socket and connection.end_socket == end_socket:
                return connection

        connection = ConnectionItem(start_socket, end_socket)
        self.connections.append(connection)
        self.scene.addItem(connection)
        connection.update_path()
        self._schedule_minimap_refresh()
        return connection

    def connect_selected(self):
        selected_nodes = [item for item in self.scene.selectedItems() if isinstance(item, NodeItem)]
        if len(selected_nodes) != 2:
            self.append_log("Select exactly two nodes to connect them.")
            return
        self.connect_nodes(selected_nodes[0].node_id, selected_nodes[1].node_id)

    def delete_selected(self):
        for node in [item for item in self.scene.selectedItems() if isinstance(item, NodeItem)]:
            self._remove_node(node.node_id)
        self._schedule_minimap_refresh()

    def _remove_node(self, node_id: str):
        node = self.nodes.pop(node_id, None)
        if node is None:
            return
        related_connections = []
        for socket in node.input_sockets + node.output_sockets:
            related_connections.extend(socket.connections)
        for connection in list(set(related_connections)):
            self._remove_connection(connection)
        self.scene.removeItem(node)

    def _remove_connection(self, connection):
        if connection in self.connections:
            self.connections.remove(connection)
        connection.disconnect()
        self.scene.removeItem(connection)

    def clear_graph(self):
        for connection in list(self.connections):
            self._remove_connection(connection)
        for node_id in list(self.nodes.keys()):
            self._remove_node(node_id)
        self.node_counter = 0
        self._schedule_minimap_refresh()

    def get_graph(self):
        return GraphSerializer.serialize(self)

    def set_graph(self, payload):
        if isinstance(payload, dict) and "nodes" in payload and "connections" in payload:
            self._load_modern_graph(payload)
        elif isinstance(payload, dict):
            self._load_legacy_graph(payload)
        self._schedule_minimap_refresh()

    def _load_modern_graph(self, payload):
        self.clear_graph()
        highest_counter = 0
        for node_payload in payload.get("nodes", []):
            node_id = node_payload["id"]
            self.add_node(
                node_type=node_payload["type"],
                pos=node_payload.get("position", [0, 0]),
                title=node_payload.get("title"),
                config=node_payload.get("config", {}),
                node_id=node_id,
            )
            try:
                highest_counter = max(highest_counter, int(str(node_id).rsplit("_", 1)[1]))
            except (IndexError, ValueError):
                pass
        self.node_counter = max(self.node_counter, highest_counter)
        for connection_payload in payload.get("connections", []):
            self.connect_nodes(
                connection_payload["from"],
                connection_payload["to"],
                connection_payload.get("from_socket", 0),
                connection_payload.get("to_socket", 0),
            )

    def _load_legacy_graph(self, payload):
        nodes = []
        connections = []
        for node_id, node_payload in payload.items():
            node_type = "condition" if node_payload.get("type") == "state" else node_payload.get("type", "action")
            nodes.append(
                {
                    "id": node_id,
                    "type": node_type,
                    "title": node_payload.get("label") or node_payload.get("title") or node_type.title(),
                    "config": self._legacy_config_to_modern(node_payload),
                    "position": list(node_payload.get("pos", [0, 0])),
                }
            )
            for connection_id in node_payload.get("connections", []):
                connections.append({"from": node_id, "from_socket": 0, "to": connection_id, "to_socket": 0})
        self._load_modern_graph({"nodes": nodes, "connections": connections})

    def _legacy_config_to_modern(self, payload):
        config = {}
        if payload.get("type") == "action":
            config["action"] = payload.get("action", "click")
            config["target"] = list(payload.get("target", [500, 300]))
        elif payload.get("type") == "state":
            config["condition"] = payload.get("condition", "True")
        else:
            for key, value in payload.items():
                if key not in {"type", "label", "connections", "pos"}:
                    config[key] = value
        return config

    def save_to_file(self, file_path: str):
        GraphSerializer.save(self, file_path)

    def load_from_file(self, file_path: str):
        self.set_graph(GraphSerializer.load(file_path))

    def to_legacy_graph(self):
        graph = {}
        connection_map = {}
        for connection in self.connections:
            source = connection.start_socket.parentItem().node_id
            target = connection.end_socket.parentItem().node_id
            connection_map.setdefault(source, []).append(target)

        for node_id, node in self.nodes.items():
            payload = {
                "type": "state" if node.node_type == "condition" else node.node_type,
                "label": node.title,
                "connections": connection_map.get(node_id, []),
                "pos": [node.pos().x(), node.pos().y()],
            }
            if node.node_type == "action":
                payload["action"] = node.config.get("action", "click")
                payload["target"] = node.config.get("target", [500, 300])
            elif node.node_type == "condition":
                payload["condition"] = node.config.get("condition", "True")
            else:
                payload.update(node.config)
            graph[node_id] = payload
        return graph

    def highlight_node(self, node_id: str, active: bool = True):
        node = self.nodes.get(node_id)
        if node is not None:
            node.set_active(active)

    def copy_selected(self):
        selected_ids = [item.node_id for item in self.scene.selectedItems() if isinstance(item, NodeItem)]
        if not selected_ids:
            self.append_log("No nodes selected.")
            return
        graph = self.get_graph()
        self.clipboard_graph = {
            "nodes": [node for node in graph["nodes"] if node["id"] in selected_ids],
            "connections": [
                connection for connection in graph["connections"]
                if connection["from"] in selected_ids and connection["to"] in selected_ids
            ],
        }
        self.append_log("Copied selected nodes.")

    def paste_copied(self):
        if not self.clipboard_graph:
            self.append_log("Clipboard is empty.")
            return
        id_map = {}
        pasted_nodes = []
        for node_payload in self.clipboard_graph.get("nodes", []):
            new_id = self._next_node_id(node_payload["type"])
            id_map[node_payload["id"]] = new_id
            position = node_payload.get("position", [0, 0])
            pasted_nodes.append({**node_payload, "id": new_id, "position": [position[0] + 40, position[1] + 40]})
        pasted_connections = []
        for connection in self.clipboard_graph.get("connections", []):
            pasted_connections.append({**connection, "from": id_map[connection["from"]], "to": id_map[connection["to"]]})
        current_graph = self.get_graph()
        current_graph["nodes"].extend(pasted_nodes)
        current_graph["connections"].extend(pasted_connections)
        self.set_graph(current_graph)
        self.append_log("Pasted copied nodes.")

    def step_action(self):
        if not self._run_action_handler("step"):
            self.append_log("Step action triggered.")

    def pause_action(self):
        if not self._run_action_handler("pause"):
            self.append_log("Pause action triggered.")

    def resume_action(self):
        if not self._run_action_handler("resume"):
            self.append_log("Resume action triggered.")

    def apply_behavior_action(self):
        if not self._run_action_handler("apply"):
            self.append_log("Apply behavior action triggered.")

    def save_graph_action(self):
        if self._run_action_handler("save"):
            return
        filename, _ = QFileDialog.getSaveFileName(self, "Save Behavior", "", "JSON Files (*.json)")
        if filename:
            self.save_to_file(filename)
            self.append_log(f"Saved graph to {filename}")

    def load_graph_action(self):
        if self._run_action_handler("load"):
            return
        filename, _ = QFileDialog.getOpenFileName(self, "Load Behavior", "", "JSON Files (*.json)")
        if filename:
            self.load_from_file(filename)
            self.append_log(f"Loaded graph from {filename}")

    def history_action(self):
        if not self._run_action_handler("history"):
            self.append_log("History action triggered.")

    def simulate_action(self):
        if not self._run_action_handler("simulate"):
            self.simulate_mode = not self.simulate_mode
            self.append_log(f"Simulate mode {'enabled' if self.simulate_mode else 'disabled'}.")

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._relayout_toolbar_sections()
        self._relayout_bottom_buttons()
        self._sync_splitter_sizes()
        self._schedule_minimap_refresh()

    def minimumSizeHint(self):
        return QSize(540, 420)

    def sizeHint(self):
        return QSize(1120, 720)
