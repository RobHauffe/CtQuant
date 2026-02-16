import os
import sys
import pandas as pd
import numpy as np
from scipy import stats
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QLabel, QTableWidget, QTableWidgetItem, QFileDialog, 
                             QTabWidget, QComboBox, QGroupBox, QGridLayout, QScrollArea,
                             QHeaderView, QMessageBox, QMenu, QDialog, QFormLayout, QCheckBox,
                             QTreeWidget, QTreeWidgetItem, QToolButton)
from PyQt6.QtCore import Qt, pyqtSignal, QRect, QSize
from PyQt6.QtGui import QColor, QPainter, QBrush, QPen, QAction, QIcon

def resource_path(relative_path):
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

class WellButton(QWidget):
    """A custom widget representing a single well in the plate."""
    
    def __init__(self, row, col, parent=None):
        super().__init__(parent)
        self.row = row
        self.col = col
        self.selected = False
        self.sample_name = ""
        self.gene_name = ""
        self.group_type = "None" # "Control", "Treatment", "None"
        self.gene_type = "None" # "Housekeeping", "GOI", "None"
        self.ct_value = None
        self.is_excluded = False
        self.setFixedSize(30, 30)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents) # Let parent handle events
        
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Color based on group type and gene type
        # We'll use a gradient or a split color if both are defined?
        # Let's use Gene Type for the main color and Group for the border or a small dot.
        
        base_color = QColor(240, 240, 240)
        if self.gene_type == 'Housekeeping':
            base_color = QColor(144, 238, 144) # LightGreen
        elif self.gene_type == 'GOI':
            base_color = QColor(255, 255, 153) # LightYellow
            
        if self.selected:
            painter.setPen(QPen(Qt.GlobalColor.blue, 3))
        else:
            border_color = Qt.GlobalColor.gray
            if self.group_type == 'Control':
                border_color = QColor(0, 0, 255) # Blue border for control
            elif self.group_type == 'Treatment':
                border_color = QColor(255, 0, 0) # Red border for treatment
            painter.setPen(QPen(border_color, 2 if self.group_type != "None" else 1))
            
        painter.setBrush(QBrush(base_color))
        painter.drawEllipse(2, 2, 26, 26)
        
        if self.is_excluded:
            painter.setPen(QPen(Qt.GlobalColor.red, 2))
            painter.drawLine(5, 5, 25, 25)
            painter.drawLine(5, 25, 25, 5)

        painter.setPen(Qt.GlobalColor.black)
        font = painter.font()
        font.setPointSize(5)
        painter.setFont(font)
        
        text = ""
        if self.sample_name: text += self.sample_name[:3] + "\n"
        if self.gene_name: text += self.gene_name[:3]
        painter.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, text)

class HeaderButton(QLabel):
    """A clickable header for row/column selection."""
    clicked = pyqtSignal(str, int) # type ('row' or 'col'), index

    def __init__(self, text, type, index, parent=None):
        super().__init__(text, parent)
        self.type = type
        self.index = index
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("font-weight: bold; color: #555; background: #eee; border: 1px solid #ccc; border-radius: 3px;")
        self.setFixedSize(30, 30)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.type, self.index)

class PlateMapper(QWidget):
    """The grid component for mapping samples to wells."""
    selection_changed = pyqtSignal()

    def __init__(self, rows=16, cols=24, parent=None):
        super().__init__(parent)
        self.rows = rows
        self.cols = cols
        self.wells = {} # (row, col) -> WellButton
        self.is_dragging = False
        self.drag_start_well = None
        self.setMouseTracking(True)
        self.init_ui()
        
    def init_ui(self):
        # Clear existing layout
        if self.layout():
            while self.layout().count():
                child = self.layout().takeAt(0)
                if child.widget():
                    child.widget().deleteLater()
            
        self.grid_layout = QGridLayout(self)
        self.grid_layout.setSpacing(1)
        self.grid_layout.setContentsMargins(0, 0, 0, 0)
        
        for c in range(self.cols):
            btn = HeaderButton(str(c+1), 'col', c)
            btn.clicked.connect(self.select_column)
            self.grid_layout.addWidget(btn, 0, c+1)
            
        for r in range(self.rows):
            btn = HeaderButton(chr(65+r), 'row', r)
            btn.clicked.connect(self.select_row)
            self.grid_layout.addWidget(btn, r+1, 0)
            
        for r in range(self.rows):
            for c in range(self.cols):
                well = WellButton(r, c)
                self.grid_layout.addWidget(well, r+1, c+1)
                self.wells[(r, c)] = well

    def select_row(self, type, index):
        # Check if all wells in the row are already selected
        all_selected = all(self.wells[(index, c)].selected for c in range(self.cols))
        
        if not (QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier):
            self.clear_selection(update=False)
            
        target_state = not all_selected
        for c in range(self.cols):
            self.wells[(index, c)].selected = target_state
            self.wells[(index, c)].update()
        self.selection_changed.emit()

    def select_column(self, type, index):
        # Check if all wells in the column are already selected
        all_selected = all(self.wells[(r, index)].selected for r in range(self.rows))

        if not (QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier):
            self.clear_selection(update=False)
            
        target_state = not all_selected
        for r in range(self.rows):
            self.wells[(r, index)].selected = target_state
            self.wells[(r, index)].update()
        self.selection_changed.emit()

    def get_well_at(self, pos):
        # Calculate row/col based on fixed size (30x30) + spacing (1)
        # Headers are also 30x30
        x = pos.x()
        y = pos.y()
        
        # Grid starts at (0,0) but has headers
        # Col 0 is row labels, Row 0 is col labels
        c = (x // 31) - 1
        r = (y // 31) - 1
        
        if 0 <= r < self.rows and 0 <= c < self.cols:
            return self.wells.get((r, c))
        return None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            well = self.get_well_at(event.position().toPoint())
            if well:
                self.is_dragging = True
                self.drag_start_well = well
                
                modifiers = event.modifiers()
                if modifiers & Qt.KeyboardModifier.ShiftModifier:
                    # Select all to the left in this row
                    for c in range(well.col + 1):
                        self.wells[(well.row, c)].selected = True
                        self.wells[(well.row, c)].update()
                elif modifiers & Qt.KeyboardModifier.ControlModifier:
                    well.selected = not well.selected
                    well.update()
                else:
                    # If it's already selected and no other wells are selected, toggle it off
                    selected_count = len(self.get_selected_wells())
                    if well.selected and selected_count == 1:
                        well.selected = False
                    else:
                        self.clear_selection(update=False)
                        well.selected = True
                    well.update()
                
                self.selection_changed.emit()

    def mouseMoveEvent(self, event):
        if self.is_dragging:
            well = self.get_well_at(event.position().toPoint())
            if well and well != self.drag_start_well:
                self.select_range(self.drag_start_well, well)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_dragging = False
            self.selection_changed.emit()

    def select_range(self, start_well, end_well):
        r1, r2 = min(start_well.row, end_well.row), max(start_well.row, end_well.row)
        c1, c2 = min(start_well.col, end_well.col), max(start_well.col, end_well.col)
        
        # If Ctrl is NOT held, we should probably only select the current range
        # and clear others. But dragging usually implies extending selection.
        # Let's match standard spreadsheet behavior.
        
        is_ctrl = QApplication.keyboardModifiers() & Qt.KeyboardModifier.ControlModifier
        
        for r in range(self.rows):
            for c in range(self.cols):
                in_range = r1 <= r <= r2 and c1 <= c <= c2
                if in_range:
                    self.wells[(r, c)].selected = True
                elif not is_ctrl:
                    self.wells[(r, c)].selected = False
                self.wells[(r, c)].update()

    def clear_selection(self, update=True):
        for well in self.wells.values():
            well.selected = False
            if update:
                well.update()

    def reset_all_wells(self):
        """Clears all assignments and selections from all wells."""
        for well in self.wells.values():
            well.selected = False
            well.sample_name = ""
            well.gene_name = ""
            well.group_type = "None"
            well.gene_type = "None"
            # We might want to keep ct_value if it's from a loaded file, 
            # but usually "Clear Plate" means start over.
            well.ct_value = None
            well.is_excluded = False
            well.update()
        self.selection_changed.emit()
            
    def get_selected_wells(self):
        return [pos for pos, well in self.wells.items() if well.selected]

    def assign_mapping(self, sample_name, gene_name, group_type, gene_type):
        selected_positions = self.get_selected_wells()
        for pos in selected_positions:
            well = self.wells[pos]
            if sample_name is not None: well.sample_name = sample_name
            if gene_name is not None: well.gene_name = gene_name
            if group_type is not None: well.group_type = group_type
            if gene_type is not None: well.gene_type = gene_type
            well.selected = False
            well.update()
        self.selection_changed.emit()

class AboutWindow(QDialog):
    """The 'About CtQuant' window."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About CtQuant")
        self.setFixedSize(550, 450)
        
        # Define attributes used in the UI
        self.version = "v1.0.0"
        self.creation_date = "2026"
        self.author = "Dr. Robert Hauffe"
        
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        
        # Get Started Tab
        get_started = QWidget()
        gs_layout = QVBoxLayout(get_started)
        gs_text = QLabel("<b>Workflow Overview:</b><br><br>"
                         "1. <b>Load Excel:</b> Select your raw qPCR data (e.g., Bio-Rad CFX export).<br>"
                         "2. <b>Map Plate:</b> Select wells in the grid and assign them to Sample Groups and Genes.<br>"
                         "3. <b>Configure Replicates:</b> Set the number of technical replicates and their layout.<br>"
                         "4. <b>Run Analysis:</b> Processes the data using the ddCt method.<br>"
                         "5. <b>Refine:</b> Right-click any row in the Analysis tab to exclude outliers.<br>"
                         "6. <b>Export:</b> Save your results to a multi-sheet Excel file.")
        gs_text.setWordWrap(True)
        gs_layout.addWidget(gs_text)
        tabs.addTab(get_started, "Get Started")
        
        # Methodology Tab
        methodology = QWidget()
        m_layout = QVBoxLayout(methodology)
        m_text = QLabel("<b>ddCt Quantification Method:</b><br><br>"
                        "• <b>Technical Replicates:</b> Averaged per sample/gene. SD > 0.5 is flagged.<br>"
                        "• <b>dCt:</b> Ct(Gene of Interest) - Average Ct(Housekeeping Genes).<br>"
                        "• <b>ddCt:</b> dCt(Sample) - Average dCt(Control Group for that Gene).<br>"
                        "• <b>Fold Change:</b> 2<sup>-ddCt</sup>.<br>"
                        "• <b>% Change:</b> (Fold Change - 1) * 100.<br><br>"
                        "<b>Statistics:</b> Welch's t-test is used for comparison between Treatment and Control groups, "
                        "which is robust against unequal variances.")
        m_text.setWordWrap(True)
        m_layout.addWidget(m_text)
        tabs.addTab(methodology, "Methodology")
        
        # Tab 3: Credits
        credits_tab = QWidget()
        cred_layout = QVBoxLayout(credits_tab)
        
        info_layout = QFormLayout()
        info_layout.addRow("Version:", QLabel(self.version))
        info_layout.addRow("Created:", QLabel(self.creation_date))
        info_layout.addRow("Author:", QLabel(self.author))
    
        
        # License Info
        license_label = QLabel("This software is free for academic and non-commercial research use. Commercial use requires a separate license agreement. See the LICENSE file for details.")
        license_label.setWordWrap(True)
        license_label.setStyleSheet("font-weight: bold; color: #2c3e50;")
        info_layout.addRow("License:", license_label)
        
        cred_layout.addLayout(info_layout)
        
        desc_label = QLabel("Tool for the assisted quantification of qPCR data.")
        desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc_label.setStyleSheet("font-style: italic; color: #7f8c8d;")
        cred_layout.addWidget(desc_label)
        
        cred_layout.addStretch()
        tabs.addTab(credits_tab, "Credits")
        
        layout.addWidget(tabs)
        
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

class CtQuantApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("CtQuant - qPCR Analysis Tool")
        self.resize(1200, 800)
        self.version = "v1.0.0"
        
        # Set window icon
        icon_path = resource_path("CtQuant_icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        
        self.init_ui()
        
    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        
        # Top toolbar/buttons
        top_layout = QHBoxLayout()
        
        # Plate Format Combo
        self.plate_format_combo = QComboBox()
        self.plate_format_combo.addItems(["384-well", "96-well"])
        self.plate_format_combo.currentIndexChanged.connect(self.on_plate_format_changed)
        top_layout.addWidget(QLabel("Plate Format:"))
        top_layout.addWidget(self.plate_format_combo)
        
        top_layout.addStretch()
        
        # Primary "Load Excel" Button
        self.load_btn = QPushButton("Load qPCR Excel Data")
        self.load_btn.setMinimumHeight(40)
        self.load_btn.setStyleSheet("""
            QPushButton {
                background-color: #3498db;
                color: white;
                font-weight: bold;
                font-size: 14px;
                border-radius: 5px;
                padding: 5px 20px;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
        """)
        self.load_btn.clicked.connect(self.load_excel)
        top_layout.addWidget(self.load_btn)
        
        top_layout.addStretch()
        
        self.help_btn = QPushButton("?")
        self.help_btn.setFixedSize(30, 30)
        self.help_btn.clicked.connect(self.show_general_help)
        top_layout.addWidget(self.help_btn)
        
        self.about_btn = QPushButton("About CtQuant")
        self.about_btn.clicked.connect(self.show_about)
        top_layout.addWidget(self.about_btn)
        
        main_layout.addLayout(top_layout)
        
        # Main Content: Tabs for "Main View" and "Detailed Results"
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)
        
        # Tab 1: Main View (Mapper + Summary + Main Results)
        self.main_view_tab = QWidget()
        self.setup_main_view_tab()
        self.tabs.addTab(self.main_view_tab, "Main View")
        
        # Tab 2: Detailed Results
        self.detailed_tab = QWidget()
        self.setup_detailed_tab()
        self.tabs.addTab(self.detailed_tab, "Detailed Results")

    def setup_main_view_tab(self):
        layout = QVBoxLayout(self.main_view_tab)
        
        # Top Section: Mapper and Controls
        top_section = QHBoxLayout()
        
        # Left: Plate Mapper
        mapper_group = QGroupBox("Plate Mapper")
        mapper_layout = QVBoxLayout(mapper_group)
        scroll = QScrollArea()
        self.mapper = PlateMapper(16, 24)
        scroll.setWidget(self.mapper)
        scroll.setWidgetResizable(True)
        mapper_layout.addWidget(scroll)
        top_section.addWidget(mapper_group, 2)
        
        # Right: Controls
        controls_layout = QVBoxLayout()
        
        mapping_box = QGroupBox("Assign Mapping")
        mapping_layout = QFormLayout(mapping_box)
        
        self.group_type_combo = QComboBox()
        self.group_type_combo.addItems(["None", "Control", "Treatment"])
        self.group_type_combo.setCurrentText("Control")
        mapping_layout.addRow("Group:", self.group_type_combo)
        
        self.sample_name_input = QComboBox()
        self.sample_name_input.setEditable(True)
        self.sample_name_input.lineEdit().returnPressed.connect(
            lambda: self.add_to_combo(self.sample_name_input))
        mapping_layout.addRow("Sample Name:", self.sample_name_input)
        
        self.gene_type_combo = QComboBox()
        self.gene_type_combo.addItems(["None", "Housekeeping", "GOI"])
        self.gene_type_combo.setCurrentText("Housekeeping")
        mapping_layout.addRow("Gene Type:", self.gene_type_combo)
        
        self.gene_name_input = QComboBox()
        self.gene_name_input.setEditable(True)
        self.gene_name_input.lineEdit().returnPressed.connect(
            lambda: self.add_to_combo(self.gene_name_input))
        mapping_layout.addRow("Gene Name:", self.gene_name_input)
        
        self.assign_btn = QPushButton("Assign Selected")
        self.assign_btn.clicked.connect(self.assign_mapping)
        mapping_layout.addRow(self.assign_btn)
        
        self.clear_plate_btn = QPushButton("Clear Plate")
        self.clear_plate_btn.clicked.connect(self.clear_plate)
        self.clear_plate_btn.setStyleSheet("color: #c0392b; font-weight: bold;")
        mapping_layout.addRow(self.clear_plate_btn)
        
        controls_layout.addWidget(mapping_box)

        # Technical Replicates config
        rep_box = QGroupBox("Technical Replicates")
        rep_layout = QFormLayout(rep_box)
        self.num_reps = QComboBox()
        self.num_reps.addItems(["1", "2", "3", "4"])
        self.num_reps.setCurrentText("2")
        rep_layout.addRow("Number of Reps:", self.num_reps)
        
        self.rep_layout_combo = QComboBox()
        self.rep_layout_combo.addItems(["Manual (from labels)", "Horizontal (A1, A2)", "Vertical (A1, B1)"])
        self.rep_layout_combo.setCurrentText("Horizontal (A1, A2)")
        rep_layout.addRow("Layout:", self.rep_layout_combo)
        
        controls_layout.addWidget(rep_box)
        
        self.run_analysis_btn = QPushButton("Run Analysis")
        self.run_analysis_btn.clicked.connect(self.run_analysis)
        self.run_analysis_btn.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; padding: 10px;")
        controls_layout.addWidget(self.run_analysis_btn)

        # Statistics Selection
        stats_group = QGroupBox("Analysis Settings")
        stats_layout = QFormLayout(stats_group)
        
        stats_row = QHBoxLayout()
        self.stats_combo = QComboBox()
        self.stats_combo.addItems(["Student's t-test", "Welch's t-test", "Two-way ANOVA"])
        self.stats_combo.setCurrentText("Welch's t-test")
        stats_row.addWidget(self.stats_combo)
        
        self.stats_help = QToolButton()
        self.stats_help.setText("ⓘ")
        self.stats_help.setCursor(Qt.CursorShape.PointingHandCursor)
        self.stats_help.setStyleSheet("""
            QToolButton {
                color: #3498db;
                font-weight: bold;
                font-size: 14px;
                border: none;
                background: transparent;
            }
            QToolButton:hover {
                color: #2980b9;
            }
        """)
        self.stats_help.setToolTip(
            "<b>Statistics Guide:</b><br><br>"
            "<b>Student's t-test:</b> Compares two groups assuming equal variance.<br>"
            "<b>Welch's t-test:</b> Compares two groups without assuming equal variance (Safer for biological data).<br>"
            "<b>Two-way ANOVA:</b> Analyzes how two independent variables (e.g. Treatment and Time) affect the result."
        )
        self.stats_help.clicked.connect(self.show_stats_help_dialog)
        stats_row.addWidget(self.stats_help)
        
        stats_layout.addRow("Statistics:", stats_row)
        controls_layout.addWidget(stats_group)
        
        controls_layout.addStretch()
        top_section.addLayout(controls_layout, 1)
        
        layout.addLayout(top_section, 1)
        
        # Bottom Section: Results
        results_group = QGroupBox("Analysis Results (Summary)")
        results_layout = QVBoxLayout(results_group)
        
        # Summary Tables
        self.overview_table = QTableWidget()
        self.overview_table.setColumnCount(8)
        self.overview_table.setHorizontalHeaderLabels(["Gene", "Group", "dCt (Avg)", "2^-dCt (Avg)", "ddCt (Avg)", "Fold Change", "Final N", "p-value"])
        self.overview_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        results_layout.addWidget(self.overview_table)
        
        self.export_btn = QPushButton("Export Results to Excel")
        self.export_btn.clicked.connect(self.export_excel)
        self.export_btn.setMinimumHeight(35)
        self.export_btn.setStyleSheet("""
            QPushButton {
                background-color: #3498db;
                color: white;
                font-weight: bold;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
        """)
        results_layout.addWidget(self.export_btn)
        
        layout.addWidget(results_group, 1)

    def show_stats_help_dialog(self):
        QMessageBox.information(self, "Statistics Guide", 
            "<b>Student's t-test:</b> Best when you have few replicates and assume equal variance between groups.<br><br>"
            "<b>Welch's t-test:</b> Safer for biological data as it does not assume equal variance between groups.<br><br>"
            "<b>Two-way ANOVA:</b> (Simplified in this version) Used for analyzing multiple independent factors.")

    def setup_detailed_tab(self):
        layout = QVBoxLayout(self.detailed_tab)
        
        # Detailed results as a Tree: Gene > Group > Sample
        self.results_tree = QTreeWidget()
        self.results_tree.setColumnCount(8)
        self.results_tree.setHeaderLabels(["Category", "Ct Mean", "Ct SD", "dCt", "2^-dCt", "ddCt", "2^-ddCt", "Status"])
        self.results_tree.header().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.results_tree)
        
        info_label = QLabel("<i>Right-click any Sample to exclude biological replicates from analysis.</i>")
        layout.addWidget(info_label)
        
        self.export_btn_detailed = QPushButton("Export Results to Excel")
        self.export_btn_detailed.clicked.connect(self.export_excel)
        self.export_btn_detailed.setMinimumHeight(35)
        self.export_btn_detailed.setStyleSheet("""
            QPushButton {
                background-color: #3498db;
                color: white;
                font-weight: bold;
                border-radius: 4px;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
        """)
        layout.addWidget(self.export_btn_detailed)
        
        self.results_tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.results_tree.customContextMenuRequested.connect(self.show_results_context_menu)

    def on_plate_format_changed(self):
        fmt = self.plate_format_combo.currentText()
        rows, cols = (16, 24) if fmt == "384-well" else (8, 12)
        
        # Recreate mapper
        old_mapper = self.mapper
        self.mapper = PlateMapper(rows, cols)
        
        # Find scroll area and replace widget
        scroll = self.mapper_tab.findChild(QScrollArea)
        scroll.setWidget(self.mapper)
        
    def load_excel(self):
        # Check if analysis has been performed and ask to save
        if hasattr(self, 'results_df') and not self.results_df.empty:
            reply = QMessageBox.question(
                self, 'Save Results?',
                "Analysis results exist. Would you like to export them to Excel before loading a new file?\n\n"
                "Loading a new file will clear all current results.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Yes
            )
            
            if reply == QMessageBox.StandardButton.Yes:
                self.export_excel()
                # After export, continue to load (unless user cancelled export file dialog)
            elif reply == QMessageBox.StandardButton.Cancel:
                return

        path, _ = QFileDialog.getOpenFileName(self, "Open qPCR Excel", "", "Excel Files (*.xlsx *.xls)")
        if path:
            # Clear previous results and tables
            if hasattr(self, 'results_df'):
                delattr(self, 'results_df')
            if hasattr(self, 'analysis_df'):
                delattr(self, 'analysis_df')
            
            self.overview_table.setRowCount(0)
            self.results_tree.clear()
            
            # Reset plate mapping
            if hasattr(self, 'mapper'):
                self.mapper.reset_all_wells()
            
            try:
                # 1. Load data with flexible header detection
                df_header = pd.read_excel(path, nrows=50)
                skip = 0
                well_col = None
                ct_col = None
                sample_col = None
                target_col = None
                
                # Look for column headers in the first 50 rows
                for i, row in df_header.iterrows():
                    row_vals = [str(v).strip().lower() for v in row.values]
                    if 'well' in row_vals:
                        skip = i + 1
                        # Map columns
                        row_list = list(row.values)
                        for idx, val in enumerate(row_list):
                            v_low = str(val).strip().lower()
                            if v_low == 'well': well_col = val
                            if v_low in ['cq', 'ct', 'cp', 'cycle']: ct_col = val
                            if v_low == 'sample': sample_col = val
                            if v_low in ['target', 'gene']: target_col = val
                        break
                
                if skip == 0:
                    # Fallback: assume first row if 'well' not found in first 50
                    self.raw_df = pd.read_excel(path)
                else:
                    self.raw_df = pd.read_excel(path, skiprows=skip)
                
                # Normalize column names for internal use
                self.raw_df.columns = [str(c).strip() for c in self.raw_df.columns]
                
                # Final check for required columns
                if well_col is None:
                    for col in self.raw_df.columns:
                        if col.lower() == 'well':
                            well_col = col
                            break
                if ct_col is None:
                    for col in self.raw_df.columns:
                        if col.lower() in ['cq', 'ct', 'cp', 'cycle']:
                            ct_col = col
                            break
                
                if not well_col or not ct_col:
                    QMessageBox.warning(self, "Format Error", "Could not find 'Well' or 'Cq/Ct' columns.")
                    return
                
                self.well_col = well_col
                self.ct_col = ct_col
                self.raw_data_path = path
                
                # 2. Extract Descriptors for Dropdowns
                samples = []
                genes = []
                
                # Try to find sample/target columns if not found during header scan
                if sample_col is None:
                    for col in self.raw_df.columns:
                        if col.lower() == 'sample': sample_col = col; break
                if target_col is None:
                    for col in self.raw_df.columns:
                        if col.lower() in ['target', 'gene']: target_col = col; break
                
                if sample_col in self.raw_df.columns:
                    samples = sorted(self.raw_df[sample_col].dropna().unique().astype(str))
                if target_col in self.raw_df.columns:
                    genes = sorted(self.raw_df[target_col].dropna().unique().astype(str))
                
                # Update dropdowns
                self.sample_name_input.clear()
                self.sample_name_input.addItems(samples)
                self.gene_name_input.clear()
                self.gene_name_input.addItems(genes)
                
                # 3. Auto-populate Wells
                for _, row in self.raw_df.iterrows():
                    well_str = str(row[well_col]).strip()
                    if not well_str or len(well_str) < 2: continue
                    
                    # Convert A01 or A1 to (row, col)
                    r_char = well_str[0].upper()
                    r = ord(r_char) - 65
                    try:
                        c_part = "".join(filter(str.isdigit, well_str[1:]))
                        c = int(c_part) - 1
                        if (r, c) in self.mapper.wells:
                            well = self.mapper.wells[(r, c)]
                            well.ct_value = row[ct_col]
                            if sample_col and sample_col in row:
                                well.sample_name = str(row[sample_col])
                            if target_col and target_col in row:
                                well.gene_name = str(row[target_col])
                            well.update()
                    except (ValueError, IndexError):
                        continue
                
                # 4. Post-Load Configuration Dialog
                self.show_post_load_dialog(samples, genes)
                
            except Exception as e:
                import traceback
                traceback.print_exc()
                QMessageBox.critical(self, "Error", f"Failed to load Excel: {str(e)}")

    def show_post_load_dialog(self, samples, genes):
        dialog = QDialog(self)
        dialog.setWindowTitle("Configure Experiment")
        dialog.setMinimumWidth(400)
        layout = QVBoxLayout(dialog)
        
        layout.addWidget(QLabel("<b>Data loaded successfully!</b><br>Please configure your groups and replicates:"))
        
        form = QFormLayout()
        
        # Control Sample Selection
        control_combo = QComboBox()
        control_combo.addItem("None (No Control Group)")
        control_combo.addItems(samples)
        form.addRow("Select Control Sample:", control_combo)
        
        # Housekeeping Gene Selection
        hk_combo = QComboBox()
        hk_combo.addItem("None (Assign Manually)")
        hk_combo.addItems(genes)
        form.addRow("Select Housekeeping Gene:", hk_combo)
        
        layout.addLayout(form)
        
        btn_box = QHBoxLayout()
        ok_btn = QPushButton("Apply Configuration")
        ok_btn.clicked.connect(dialog.accept)
        btn_box.addWidget(ok_btn)
        layout.addLayout(btn_box)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            ctrl_sample = control_combo.currentText()
            hk_gene = hk_combo.currentText()
            
            # Apply to all wells
            for well in self.mapper.wells.values():
                if ctrl_sample != "None (No Control Group)" and well.sample_name == ctrl_sample:
                    well.group_type = "Control"
                elif well.sample_name:
                    well.group_type = "Treatment"
                
                if hk_gene != "None (Assign Manually)" and well.gene_name == hk_gene:
                    well.gene_type = "Housekeeping"
                elif well.gene_name:
                    well.gene_type = "GOI"
                well.update()
            
            QMessageBox.information(self, "Ready", "Plate mapping and group assignments completed.")

    def add_to_combo(self, combo):
        text = combo.currentText().strip()
        if text and combo.findText(text) == -1:
            combo.addItem(text)
            combo.setCurrentText(text)
            QMessageBox.information(self, "Entry Added", f"'{text}' has been added to the dropdown list.")

    def assign_mapping(self):
        g_type = self.group_type_combo.currentText()
        s_name = self.sample_name_input.currentText()
        gene_type = self.gene_type_combo.currentText()
        gene_name = self.gene_name_input.currentText()
        
        # Only update fields that are not empty/None if we want to allow partial updates
        # But let's keep it simple for now.
        self.mapper.assign_mapping(s_name, gene_name, g_type, gene_type)
        
        # Update combo box suggestions
        if s_name and self.sample_name_input.findText(s_name) == -1:
            self.sample_name_input.addItem(s_name)
        if gene_name and self.gene_name_input.findText(gene_name) == -1:
            self.gene_name_input.addItem(gene_name)

    def clear_plate(self):
        # Custom dialog with checkbox
        dialog = QDialog(self)
        dialog.setWindowTitle("Clear Plate")
        layout = QVBoxLayout(dialog)
        
        layout.addWidget(QLabel("<b>Are you sure you want to clear the plate?</b>"))
        
        retain_hk_check = QCheckBox("Retain Housekeeping (HK) data for next plate")
        layout.addWidget(retain_hk_check)
        
        btn_box = QHBoxLayout()
        yes_btn = QPushButton("Yes, Clear")
        yes_btn.clicked.connect(dialog.accept)
        no_btn = QPushButton("Cancel")
        no_btn.clicked.connect(dialog.reject)
        btn_box.addWidget(yes_btn)
        btn_box.addWidget(no_btn)
        layout.addLayout(btn_box)
        
        if dialog.exec() == QDialog.DialogCode.Accepted:
            retain_hk = retain_hk_check.isChecked()
            
            # Use mapper's reset with selective logic
            for pos, well in self.mapper.wells.items():
                is_hk = (well.gene_type == "Housekeeping")
                
                if retain_hk and is_hk:
                    # Keep mapping for HK but clear Ct if desired? 
                    # User said "retain housekeeping data", usually means the mapping.
                    # Let's clear Ct values regardless because it's a new plate.
                    well.ct_value = None
                    well.selected = False
                    well.update()
                else:
                    well.selected = False
                    well.sample_name = ""
                    well.gene_name = ""
                    well.group_type = "None"
                    well.gene_type = "None"
                    well.ct_value = None
                    well.is_excluded = False
                    well.update()
            
            self.mapper.selection_changed.emit()
            
            # Clear internal data references
            if hasattr(self, 'raw_df'): del self.raw_df
            if hasattr(self, 'analysis_df'): del self.analysis_df
            if hasattr(self, 'results_df'): del self.results_df
            self.results_tree.clear()
            self.overview_table.setRowCount(0)
            
            QMessageBox.information(self, "Success", "Plate cleared" + (" (HK retained)" if retain_hk else "") + ".")

    def run_analysis(self):
        if not hasattr(self, 'raw_df'):
            QMessageBox.warning(self, "Error", "Please load an Excel file first.")
            return
            
        # 1. Collect all mapped data
        data = []
        num_reps = int(self.num_reps.currentText())
        rep_layout = self.rep_layout_combo.currentText()
        
        # Sort wells to ensure consistent technical replicate grouping
        well_positions = sorted(self.mapper.wells.keys())
        
        # We need to track which wells have been processed to group technical reps
        processed_wells = set()
        
        for pos in well_positions:
            if pos in processed_wells:
                continue
                
            well = self.mapper.wells[pos]
            if not (well.sample_name and well.gene_name and well.ct_value is not None):
                continue

            # Identify technical replicates based on layout
            tech_rep_wells = [well]
            processed_wells.add(pos)
            
            row, col = pos
            if "Horizontal" in rep_layout:
                for r in range(1, num_reps):
                    next_pos = (row, col + r)
                    if next_pos in self.mapper.wells:
                        w = self.mapper.wells[next_pos]
                        # Must match sample and gene to be a tech rep
                        if w.sample_name == well.sample_name and w.gene_name == well.gene_name:
                            tech_rep_wells.append(w)
                            processed_wells.add(next_pos)
            elif "Vertical" in rep_layout:
                for r in range(1, num_reps):
                    next_pos = (row + r, col)
                    if next_pos in self.mapper.wells:
                        w = self.mapper.wells[next_pos]
                        if w.sample_name == well.sample_name and w.gene_name == well.gene_name:
                            tech_rep_wells.append(w)
                            processed_wells.add(next_pos)
            else: # Manual
                # In manual mode, we group by same Sample + Gene + Group across the whole plate
                # But to avoid double counting, we'll only do this once per unique combination
                pass # Manual grouping is handled by the groupby in perform_calculations if we just pass all wells

            # For Automatic layouts, we assign a "BioSampleID" to keep replicates together
            # If Manual, we'll rely on Sample name alone (which might be the issue if names are identical)
            
            for w in tech_rep_wells:
                data.append({
                    'Well': f"{chr(65+w.row)}{w.col+1:02d}",
                    'Sample': w.sample_name,
                    'Gene': w.gene_name,
                    'Group': w.group_type,
                    'GeneType': w.gene_type,
                    'Ct': w.ct_value,
                    'Excluded': w.is_excluded,
                    # Unique ID for this specific biological sample (set of technical reps)
                    'BioSampleID': f"{well.sample_name}_{well.gene_name}_{pos[0]}_{pos[1]}" 
                })
        
        if not data:
            QMessageBox.warning(self, "Error", "No wells have been assigned with both Sample and Gene names.")
            return
            
        self.analysis_df = pd.DataFrame(data)
        self.perform_calculations()

    def perform_calculations(self):
        # 1. Filter excluded
        df = self.analysis_df[~self.analysis_df['Excluded']].copy()
        
        # 2. Technical Replicates: Group by the Unique Biological Sample ID
        # This ensures A01+A02 are averaged even if they have the same name as A03+A04
        tech_reps = df.groupby(['BioSampleID', 'Sample', 'Gene', 'Group', 'GeneType'])['Ct'].agg(['mean', 'std', 'count']).reset_index()
        tech_reps.rename(columns={'mean': 'Ct_Mean', 'std': 'Ct_SD', 'count': 'Rep_Count'}, inplace=True)
        
        # 3. Separate HK and GOI
        hk_df = tech_reps[tech_reps['GeneType'] == 'Housekeeping'].copy()
        goi_df = tech_reps[tech_reps['GeneType'] == 'GOI'].copy()
        
        if hk_df.empty:
            QMessageBox.warning(self, "Error", "No Housekeeping gene data found.")
            return
        if goi_df.empty:
            QMessageBox.warning(self, "Error", "No Gene of Interest data found.")
            return

        # 4. Calculate dCt per Biological Replicate
        # Match HK to GOI by Sample Name (Biological replicates should have the same Sample Name for both HK and GOI)
        hk_avg_per_sample = hk_df.groupby('Sample')['Ct_Mean'].mean().reset_index()
        hk_avg_per_sample.rename(columns={'Ct_Mean': 'HK_Ct_Mean'}, inplace=True)
        
        results_df = goi_df.merge(hk_avg_per_sample, on='Sample', how='left')
        results_df['dCt'] = results_df['Ct_Mean'] - results_df['HK_Ct_Mean']
        
        # 5. Expression relative to HK (2^-dCt) per Biological Replicate
        results_df['Rel_Exp_HK'] = 2 ** (-results_df['dCt'])
        
        # 6. Calculate ddCt per Biological Replicate
        # Average dCt for Control group per Gene
        control_dct_avg = results_df[results_df['Group'] == 'Control'].groupby('Gene')['dCt'].mean().reset_index()
        control_dct_avg.rename(columns={'dCt': 'Control_dCt_Avg'}, inplace=True)
        
        results_df = results_df.merge(control_dct_avg, on='Gene', how='left')
        results_df['ddCt'] = results_df['dCt'] - results_df['Control_dCt_Avg']
        
        # 7. Fold Change (2^-ddCt) per Biological Replicate
        results_df['Fold_Change'] = 2 ** (-results_df['ddCt'])
        
        self.results_df = results_df
        self.display_results()
        self.update_overview()
        # Stay on main view to see summary
        QMessageBox.information(self, "Analysis Complete", "Data processed successfully. Summary is available in the Main View.")

    def display_results(self):
        # Save expansion state
        expanded_items = set()
        # If the tree is empty, we consider it a fresh run and want items expanded by default
        is_fresh_run = self.results_tree.topLevelItemCount() == 0
        
        for i in range(self.results_tree.topLevelItemCount()):
            gene_node = self.results_tree.topLevelItem(i)
            if gene_node.isExpanded():
                expanded_items.add(gene_node.text(0))
            for j in range(gene_node.childCount()):
                group_node = gene_node.child(j)
                if group_node.isExpanded():
                    # Key: "GeneName|GroupName (Avg)"
                    expanded_items.add(f"{gene_node.text(0)}|{group_node.text(0)}")

        self.results_tree.clear()
        if not hasattr(self, 'results_df'): return
        
        # Sort by Gene and then by Group (Control first)
        df = self.results_df.copy()
        # Custom sorting for Group to ensure Control is first
        df['group_sort'] = df['Group'].apply(lambda x: 0 if x == 'Control' else 1)
        df = df.sort_values(['Gene', 'group_sort', 'Sample'])
        
        genes = df['Gene'].unique()
        stats_type = self.stats_combo.currentText()
        
        for gene in genes:
            gene_node = QTreeWidgetItem([gene])
            # Restore expansion state: Expand if it was expanded before OR if this is the first time showing results
            gene_node.setExpanded(is_fresh_run or gene in expanded_items) 
            self.results_tree.addTopLevelItem(gene_node)
            
            gene_df = df[df['Gene'] == gene]
            groups = gene_df['Group'].unique()
            # Ensure Control is first in the tree
            if 'Control' in groups:
                groups = ['Control'] + [g for g in groups if g != 'Control']
            
            # Calculate p-value for the gene if possible
            p_val_text = "-"
            if len(groups) >= 2:
                ctrl_data = gene_df[gene_df['Group'] == 'Control']['Fold_Change'].dropna()
                treat_data = gene_df[gene_df['Group'] != 'Control']['Fold_Change'].dropna()
                
                if len(ctrl_data) >= 2 and len(treat_data) >= 2:
                    try:
                        if stats_type == "Student's t-test":
                            _, p_val = stats.ttest_ind(ctrl_data, treat_data, equal_var=True)
                        elif stats_type == "Welch's t-test":
                            _, p_val = stats.ttest_ind(ctrl_data, treat_data, equal_var=False)
                        else: # Two-way ANOVA (Simplified as t-test for now)
                            _, p_val = stats.ttest_ind(ctrl_data, treat_data, equal_var=False)
                        p_val_text = f"p = {p_val:.4f}"
                    except:
                        p_val_text = "Error"

            for group in groups:
                group_df = gene_df[gene_df['Group'] == group]
                
                # Group Summary stats (Average of Biological Replicates)
                avg_ct = group_df['Ct_Mean'].mean()
                avg_dct = group_df['dCt'].mean()
                avg_rel_exp = group_df['Rel_Exp_HK'].mean()
                avg_ddct = group_df['ddCt'].mean()
                avg_fc = group_df['Fold_Change'].mean()
                
                # Display p-value only in the average group row for non-control groups
                display_p = p_val_text if group != 'Control' else "-"
                
                group_name_full = f"{group} (Avg)"
                group_node = QTreeWidgetItem([
                    group_name_full, 
                    f"{avg_ct:.3f}" if not pd.isna(avg_ct) else "-",
                    "-", 
                    f"{avg_dct:.3f}" if not pd.isna(avg_dct) else "-",
                    f"{avg_rel_exp:.3f}" if not pd.isna(avg_rel_exp) else "-",
                    f"{avg_ddct:.3f}" if not pd.isna(avg_ddct) else "-",
                    f"{avg_fc:.3f}" if not pd.isna(avg_fc) else "-",
                    display_p
                ])
                # Restore expansion state: Expand if it was expanded before OR if this is the first time showing results
                group_node.setExpanded(is_fresh_run or f"{gene}|{group_name_full}" in expanded_items)
                # Color group summary rows
                for col in range(8):
                    group_node.setBackground(col, QColor(240, 240, 240))
                gene_node.addChild(group_node)
                
                # Individual Biological Replicates
                for _, row in group_df.iterrows():
                    sample_node = QTreeWidgetItem([
                        row['Sample'],
                        f"{row['Ct_Mean']:.3f}",
                        f"{row['Ct_SD']:.3f}",
                        f"{row['dCt']:.3f}",
                        f"{row['Rel_Exp_HK']:.3f}",
                        f"{row['ddCt']:.3f}",
                        f"{row['Fold_Change']:.3f}",
                        "-" # No p-value for individual replicates
                    ])
                    # High technical variation highlight
                    if row['Ct_SD'] > 0.5:
                        sample_node.setBackground(2, QColor(255, 200, 200))
                        sample_node.setToolTip(2, "Technical replicate variation > 0.5 Ct!")

                    # Store data for context menu
                    sample_node.setData(0, Qt.ItemDataRole.UserRole, {
                        'sample': row['Sample'],
                        'gene': row['Gene'],
                        'biosample_id': row['BioSampleID']
                    })
                    group_node.addChild(sample_node)

    def show_results_context_menu(self, pos):
        item = self.results_tree.itemAt(pos)
        if not item or not item.data(0, Qt.ItemDataRole.UserRole): return
        
        data = item.data(0, Qt.ItemDataRole.UserRole)
        sample = data['sample']
        gene = data['gene']
        biosample_id = data.get('biosample_id')
        
        menu = QMenu()
        exclude_action = QAction(f"Exclude Biological Replicate: {sample} ({gene})", self)
        exclude_action.triggered.connect(lambda: self.exclude_sample(sample, gene, biosample_id))
        menu.addAction(exclude_action)
        menu.exec(self.results_tree.viewport().mapToGlobal(pos))

    def exclude_sample(self, sample, gene, biosample_id=None):
        # Mark technical replicates for this specific biological replicate as excluded
        # We use biosample_id if available to be precise, otherwise fallback to sample+gene
        for well in self.mapper.wells.values():
            if biosample_id:
                # Reconstruct what the BioSampleID was during run_analysis
                # BioSampleID = f"{well.sample_name}_{well.gene_name}_{pos[0]}_{pos[1]}"
                # This is tricky because wells don't store their BioSampleID.
                # Let's use the property that we know which wells belong to a BioSampleID.
                # Actually, the most reliable way is to store BioSampleID on the well during run_analysis
                # or just use the Sample + Gene + Position logic.
                pass
            
            # Revised logic: If we have a biosample_id, it contains the start position
            # e.g. "Sample1_Gene1_0_0"
            if biosample_id:
                parts = biosample_id.split('_')
                if len(parts) >= 4:
                    orig_sample = parts[0]
                    orig_gene = parts[1]
                    start_row = int(parts[-2])
                    start_col = int(parts[-1])
                    
                    # We need to find the tech replicates that were grouped with this start position
                    num_reps = int(self.num_reps.currentText())
                    rep_layout = self.rep_layout_combo.currentText()
                    
                    target_wells = []
                    if "Horizontal" in rep_layout:
                        target_wells = [(start_row, start_col + r) for r in range(num_reps)]
                    elif "Vertical" in rep_layout:
                        target_wells = [(start_row + r, start_col) for r in range(num_reps)]
                    
                    for pos, well in self.mapper.wells.items():
                        if pos in target_wells and well.sample_name == orig_sample and well.gene_name == orig_gene:
                            well.is_excluded = True
                            well.update()
                else:
                    # Fallback to sample/gene if ID format is unexpected
                    if well.sample_name == sample and well.gene_name == gene:
                        well.is_excluded = True
                        well.update()
            else:
                # Fallback for manual layout or missing ID
                if well.sample_name == sample and well.gene_name == gene:
                    well.is_excluded = True
                    well.update()
        
        self.run_analysis() # Re-run analysis

    def update_overview(self):
        self.overview_table.setRowCount(0)
        if not hasattr(self, 'results_df'): return
        
        # Calculate summary per Gene and Group (Average of Biological Replicates)
        summary = self.results_df.groupby(['Gene', 'Group']).agg({
            'dCt': 'mean',
            'Rel_Exp_HK': 'mean',
            'ddCt': 'mean',
            'Fold_Change': 'mean',
            'Sample': 'count'
        }).reset_index()
        
        # Custom sorting for Group to ensure Control is first
        summary['group_sort'] = summary['Group'].apply(lambda x: 0 if x == 'Control' else 1)
        summary = summary.sort_values(['Gene', 'group_sort'])
        
        stats_type = self.stats_combo.currentText()
        
        self.overview_table.setRowCount(len(summary))
        for i, (_, row) in enumerate(summary.iterrows()):
            gene = row['Gene']
            group = row['Group']
            
            # Calculate p-value for the gene
            p_val_text = "-"
            if group != 'Control':
                gene_data = self.results_df[self.results_df['Gene'] == gene]
                ctrl_data = gene_data[gene_data['Group'] == 'Control']['Fold_Change'].dropna()
                treat_data = gene_data[gene_data['Group'] == group]['Fold_Change'].dropna()
                
                if len(ctrl_data) >= 2 and len(treat_data) >= 2:
                    try:
                        if stats_type == "Student's t-test":
                            _, p_val = stats.ttest_ind(ctrl_data, treat_data, equal_var=True)
                        elif stats_type == "Welch's t-test":
                            _, p_val = stats.ttest_ind(ctrl_data, treat_data, equal_var=False)
                        else: # Two-way ANOVA (Simplified as t-test for now)
                            _, p_val = stats.ttest_ind(ctrl_data, treat_data, equal_var=False)
                        p_val_text = f"{p_val:.4f}"
                    except:
                        p_val_text = "Error"

            self.overview_table.setItem(i, 0, QTableWidgetItem(gene))
            self.overview_table.setItem(i, 1, QTableWidgetItem(group))
            self.overview_table.setItem(i, 2, QTableWidgetItem(f"{row['dCt']:.3f}"))
            self.overview_table.setItem(i, 3, QTableWidgetItem(f"{row['Rel_Exp_HK']:.3f}"))
            self.overview_table.setItem(i, 4, QTableWidgetItem(f"{row['ddCt']:.3f}"))
            self.overview_table.setItem(i, 5, QTableWidgetItem(f"{row['Fold_Change']:.3f}"))
            self.overview_table.setItem(i, 6, QTableWidgetItem(str(int(row['Sample']))))
            self.overview_table.setItem(i, 7, QTableWidgetItem(p_val_text))
        
        self.overview_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)

    def export_excel(self):
        if not hasattr(self, 'results_df'):
            QMessageBox.warning(self, "Error", "No results to export.")
            return
            
        path, _ = QFileDialog.getSaveFileName(self, "Save Results", "CtQuant_Results.xlsx", "Excel Files (*.xlsx)")
        if path:
            try:
                with pd.ExcelWriter(path) as writer:
                    # 1. Summary Results Sheet
                    summary_df = self.results_df.groupby(['Gene', 'Group']).agg({
                        'dCt': 'mean',
                        'Rel_Exp_HK': 'mean',
                        'ddCt': 'mean',
                        'Fold_Change': 'mean',
                        'Sample': 'count'
                    }).reset_index()
                    summary_df.rename(columns={
                        'dCt': 'Avg dCt',
                        'Rel_Exp_HK': 'Avg 2^-dCt',
                        'ddCt': 'Avg ddCt', 
                        'Fold_Change': 'Avg Fold Change',
                        'Sample': 'Final N'
                    }, inplace=True)
                    
                    # Calculate p-values for summary
                    summary_df['p-value'] = ""
                    stats_type = self.stats_combo.currentText()
                    
                    for gene in summary_df['Gene'].unique():
                        gene_data = self.results_df[self.results_df['Gene'] == gene]
                        ctrl_data = gene_data[gene_data['Group'] == 'Control']['Fold_Change'].dropna()
                        
                        for i, row in summary_df[summary_df['Gene'] == gene].iterrows():
                            if row['Group'] != 'Control':
                                treat_data = gene_data[gene_data['Group'] == row['Group']]['Fold_Change'].dropna()
                                if len(ctrl_data) >= 2 and len(treat_data) >= 2:
                                    try:
                                        if stats_type == "Student's t-test":
                                            _, p_val = stats.ttest_ind(ctrl_data, treat_data, equal_var=True)
                                        elif stats_type == "Welch's t-test":
                                            _, p_val = stats.ttest_ind(ctrl_data, treat_data, equal_var=False)
                                        else: # Two-way ANOVA placeholder
                                            _, p_val = stats.ttest_ind(ctrl_data, treat_data, equal_var=False)
                                        summary_df.at[i, 'p-value'] = f"{p_val:.4f}"
                                    except:
                                        summary_df.at[i, 'p-value'] = "Error"
                    
                    # Sort Summary
                    summary_df['group_sort'] = summary_df['Group'].apply(lambda x: 0 if x == 'Control' else 1)
                    summary_df = summary_df.sort_values(['Gene', 'group_sort']).drop(columns=['group_sort'])
                    summary_df.to_excel(writer, sheet_name='Summary Results', index=False)
                    
                    # 2. Biological Replicates Sheet (Individual sample calculations)
                    detailed_cols = ['Sample', 'Gene', 'Group', 'Ct_Mean', 'Ct_SD', 'dCt', 'Rel_Exp_HK', 'ddCt', 'Fold_Change']
                    detailed_export = self.results_df[detailed_cols].copy()
                    detailed_export.rename(columns={'Rel_Exp_HK': '2^-dCt (Rel Exp)'}, inplace=True)
                    
                    # Sort Detailed
                    detailed_export['group_sort'] = detailed_export['Group'].apply(lambda x: 0 if x == 'Control' else 1)
                    detailed_export = detailed_export.sort_values(['Gene', 'group_sort', 'Sample']).drop(columns=['group_sort'])
                    detailed_export.to_excel(writer, sheet_name='Biological Replicates', index=False)
                    
                    # 3. Technical Replicates (The plate mapping with individual well Ct values)
                    raw_export = self.analysis_df[self.analysis_df['Sample'] != ""].copy()
                    raw_export.to_excel(writer, sheet_name='Technical Replicates', index=False)
                
                QMessageBox.information(self, "Success", f"Results exported to {path}")
                
                # Open the file
                try:
                    os.startfile(path)
                except Exception as e:
                    QMessageBox.warning(self, "Warning", f"Could not open file automatically: {str(e)}")

            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to export Excel: {str(e)}")

    def show_about(self):
        AboutWindow(self).exec()

    def show_general_help(self):
        QMessageBox.information(self, "Help", "CtQuant Help:\n\n"
                                "1. Load Excel: Select your raw qPCR data.\n"
                                "2. Mapper: Click and drag (or click) wells to select, then assign them to a group.\n"
                                "3. Run Analysis: Processes data using the ddCt method.\n"
                                "4. Outliers: Right-click rows in the results table to exclude samples.")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = CtQuantApp()
    window.show()
    sys.exit(app.exec())
