import os
import sys
import pandas as pd
import numpy as np
import math
import csv
from scipy import stats
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
                             QPushButton, QLabel, QTableWidget, QTableWidgetItem, QFileDialog, 
                             QTabWidget, QComboBox, QGroupBox, QGridLayout, QScrollArea,
                             QHeaderView, QMessageBox, QMenu, QDialog, QFormLayout, QCheckBox,
                             QTreeWidget, QTreeWidgetItem, QToolButton, QInputDialog, QSplitter,
                             QRadioButton, QButtonGroup, QDoubleSpinBox)
from PyQt6.QtCore import Qt, pyqtSignal, QRect, QSize, QPoint
from PyQt6.QtGui import QColor, QPainter, QBrush, QPen, QAction, QIcon

# ReportLab imports for PDF generation
try:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas
    from reportlab.lib.colors import HexColor, black
    from reportlab.lib.units import mm
except ImportError:
    pass # Handle gracefully if missing, though we installed it

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
        self.custom_color = None  # For specific GOI colors
        self.setFixedSize(30, 30)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents) # Let parent handle events
        
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        # Color based on group type and gene type
        base_color = QColor(240, 240, 240)
        
        if self.gene_type == 'Housekeeping':
            base_color = QColor(144, 238, 144) # LightGreen
        elif self.gene_type == 'GOI':
            if self.custom_color:
                base_color = self.custom_color
            else:
                base_color = QColor(255, 255, 153) # Default LightYellow
            
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
    clicked = pyqtSignal(str, int, Qt.MouseButton) # type ('row' or 'col'), index, button

    def __init__(self, text, type, index, parent=None):
        super().__init__(text, parent)
        self.type = type
        self.index = index
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("font-weight: bold; color: #555; background: #eee; border: 1px solid #ccc; border-radius: 3px;")
        self.setFixedSize(30, 30)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton or event.button() == Qt.MouseButton.RightButton:
            self.clicked.emit(self.type, self.index, event.button())

class PlateMapper(QWidget):
    """The grid component for mapping samples to wells."""
    data_changed = pyqtSignal()

    def __init__(self, rows=16, cols=24, parent=None):
        super().__init__(parent)
        self.rows = rows
        self.cols = cols
        self.wells = {} # (row, col) -> WellButton
        self.is_drawing = False
        self.current_tool = "select" # 'paint', 'erase'
        self.brush_data = {} 
        self.gene_colors = {} 
        self.color_palette = [
            QColor(173, 216, 230), QColor(255, 182, 193), QColor(152, 251, 152), 
            QColor(238, 232, 170), QColor(221, 160, 221), QColor(176, 224, 230),
            QColor(255, 160, 122), QColor(240, 128, 128), QColor(255, 218, 185)
        ]
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
            btn.clicked.connect(self.handle_header_click)
            self.grid_layout.addWidget(btn, 0, c+1)
            
        for r in range(self.rows):
            btn = HeaderButton(chr(65+r), 'row', r)
            btn.clicked.connect(self.handle_header_click)
            self.grid_layout.addWidget(btn, r+1, 0)
            
        for r in range(self.rows):
            for c in range(self.cols):
                well = WellButton(r, c)
                self.grid_layout.addWidget(well, r+1, c+1)
                self.wells[(r, c)] = well

    def get_well_at(self, pos):
        # Iterate over wells to find which one contains the point
        # This avoids issues with childAt and WA_TransparentForMouseEvents
        for well in self.wells.values():
            if well.geometry().contains(pos):
                return well
        return None

    def set_brush_data(self, data):
        if data:
            self.brush_data = data
            # Assign color if GOI
            if data.get('gene_type') == 'GOI' and data.get('gene_name'):
                gene = data['gene_name']
                if gene not in self.gene_colors:
                    idx = len(self.gene_colors) % len(self.color_palette)
                    self.gene_colors[gene] = self.color_palette[idx]
                self.brush_data['color'] = self.gene_colors[gene]
            else:
                self.brush_data['color'] = None

    def apply_brush(self, well, mode='paint'):
        if mode == 'paint':
            # Apply only if data is present
            if 'sample_name' in self.brush_data: well.sample_name = self.brush_data['sample_name']
            if 'gene_name' in self.brush_data: well.gene_name = self.brush_data['gene_name']
            if 'group_type' in self.brush_data: well.group_type = self.brush_data['group_type']
            if 'gene_type' in self.brush_data: well.gene_type = self.brush_data['gene_type']
            if 'color' in self.brush_data: well.custom_color = self.brush_data['color']
            well.update()
            self.data_changed.emit()
        elif mode == 'erase':
            well.sample_name = ""
            well.gene_name = ""
            well.group_type = "None"
            well.gene_type = "None"
            well.custom_color = None
            well.update()
            self.data_changed.emit()

    def handle_header_click(self, type, index, button):
        mode = 'paint' if button == Qt.MouseButton.LeftButton else 'erase'
        
        if type == 'row':
            for c in range(self.cols):
                well = self.wells.get((index, c))
                if well: self.apply_brush(well, mode)
        elif type == 'col':
            for r in range(self.rows):
                well = self.wells.get((r, index))
                if well: self.apply_brush(well, mode)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.current_tool = 'paint'
        elif event.button() == Qt.MouseButton.RightButton:
            self.current_tool = 'erase'
        else:
            return

        well = self.get_well_at(event.position().toPoint())
        # Start drawing if clicking on a well
        if well:
            self.is_drawing = True
            self.apply_brush(well, self.current_tool)
        else:
            # If not clicking a well, assume box selection start
            # But wait, what if the user clicks slightly outside?
            # Let's enable box selection if not directly on a well.
            self.is_drawing = True
            self.selection_start = event.position().toPoint()
            self.selection_end = self.selection_start
            self.update() # trigger paintEvent for rubber band

    def mouseMoveEvent(self, event):
        if self.is_drawing:
            if hasattr(self, 'selection_start'):
                # Box selection mode
                self.selection_end = event.position().toPoint()
                self.update()
            else:
                # Continuous paint mode (drag over wells)
                well = self.get_well_at(event.position().toPoint())
                if well:
                    self.apply_brush(well, self.current_tool)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton or event.button() == Qt.MouseButton.RightButton:
            if hasattr(self, 'selection_start'):
                # Apply to selection
                rect = QRect(self.selection_start, self.selection_end).normalized()
                for (r, c), well in self.wells.items():
                    # Map well to parent coordinates
                    well_pos = well.pos()
                    # Include a small tolerance or use center point
                    well_center = QPoint(well_pos.x() + well.width()//2, well_pos.y() + well.height()//2)
                    
                    if rect.contains(well_center):
                        self.apply_brush(well, self.current_tool)
                
                delattr(self, 'selection_start')
                delattr(self, 'selection_end')
                self.update() # clear rubber band
            
            self.is_drawing = False

    def paintEvent(self, event):
        # Draw rubber band if selecting
        if hasattr(self, 'selection_start') and hasattr(self, 'selection_end'):
            painter = QPainter(self)
            painter.setPen(QPen(Qt.GlobalColor.blue, 2, Qt.PenStyle.DashLine))
            painter.setBrush(QBrush(QColor(0, 0, 255, 50)))
            rect = QRect(self.selection_start, self.selection_end).normalized()
            painter.drawRect(rect)

    def reset_all_wells(self):
        for well in self.wells.values():
            well.sample_name = ""
            well.gene_name = ""
            well.group_type = "None"
            well.gene_type = "None"
            well.ct_value = None
            well.is_excluded = False
            well.custom_color = None
            well.update()
        self.data_changed.emit()

    def export_pipetting_scheme(self):
        """Export the plate layout to Excel or PDF."""
        choice, _ = QInputDialog.getItem(self, "Export Pipetting Scheme", "Select Format:", ["Excel", "PDF"], 0, False)
        if not choice: return

        # Gather data
        data = []
        for (r, c), well in self.wells.items():
            if well.sample_name or well.gene_name:
                well_id = f"{chr(65+r)}{c+1}"
                data.append({
                    "Well": well_id,
                    "Row": r,
                    "Col": c,
                    "Sample": well.sample_name,
                    "Gene": well.gene_name,
                    "Group": well.group_type,
                    "Type": well.gene_type
                })
        
        if not data:
            QMessageBox.warning(self, "No Data", "Plate is empty.")
            return

        df = pd.DataFrame(data)
        
        if choice == "Excel":
            path, _ = QFileDialog.getSaveFileName(self, "Save Pipetting Scheme", "Plate_Scheme.xlsx", "Excel Files (*.xlsx)")
            if not path: return
            try:
                import openpyxl
                from openpyxl.styles import PatternFill
                
                # Create workbook from scratch with openpyxl
                wb = openpyxl.Workbook()
                wb.remove(wb.active)  # Remove default sheet
                
                # Sheet 1: List view
                ws_list = wb.create_sheet("List")
                headers = list(df.columns)
                for col_idx, header in enumerate(headers, start=1):
                    ws_list.cell(row=1, column=col_idx, value=header)
                
                for row_idx, (_, row_data) in enumerate(df.iterrows(), start=2):
                    for col_idx, header in enumerate(headers, start=1):
                        ws_list.cell(row=row_idx, column=col_idx, value=row_data[header])
                
                # Sheet 2: Sample Grid
                ws_sample = wb.create_sheet("Sample_Grid")
                grid_sample = df.pivot(index='Row', columns='Col', values='Sample')
                
                # Write headers (columns)
                for col_idx, col_name in enumerate(grid_sample.columns, start=2):
                    ws_sample.cell(row=1, column=col_idx, value=col_name)
                
                # Write row indices and data
                for row_idx, row_name in enumerate(grid_sample.index, start=2):
                    ws_sample.cell(row=row_idx, column=1, value=row_name)
                    for col_idx, col_name in enumerate(grid_sample.columns, start=2):
                        value = grid_sample.loc[row_name, col_name]
                        if pd.notna(value):
                            ws_sample.cell(row=row_idx, column=col_idx, value=value)
                
                # Sheet 3: Gene Grid
                ws_gene = wb.create_sheet("Gene_Grid")
                grid_gene = df.pivot(index='Row', columns='Col', values='Gene')
                
                # Write headers (columns)
                for col_idx, col_name in enumerate(grid_gene.columns, start=2):
                    ws_gene.cell(row=1, column=col_idx, value=col_name)
                
                # Write row indices and data
                for row_idx, row_name in enumerate(grid_gene.index, start=2):
                    ws_gene.cell(row=row_idx, column=1, value=row_name)
                    for col_idx, col_name in enumerate(grid_gene.columns, start=2):
                        value = grid_gene.loc[row_name, col_name]
                        if pd.notna(value):
                            ws_gene.cell(row=row_idx, column=col_idx, value=value)
                
                # Apply colors to Gene Grid based on GOI colors
                for r in range(self.rows):
                    for c in range(self.cols):
                        well = self.wells.get((r, c))
                        if well and well.custom_color:
                            color_hex = well.custom_color.name().lstrip('#')
                            fill = PatternFill(start_color=color_hex, end_color=color_hex, fill_type='solid')
                            # +2 because 1-based index and header row/col
                            ws_gene.cell(row=r+2, column=c+2).fill = fill
                
                wb.save(path)
                os.startfile(path)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to export Excel: {e}")

        elif choice == "PDF":
            path, _ = QFileDialog.getSaveFileName(self, "Save Pipetting Scheme", "Plate_Scheme.pdf", "PDF Files (*.pdf)")
            if not path: return
            try:
                c = canvas.Canvas(path, pagesize=A4)
                width, height = A4
                c.setFont("Helvetica-Bold", 14)
                c.drawString(20*mm, height-20*mm, "Pipetting Scheme")
                
                # Draw Grid
                x_start = 20*mm
                y_start = height - 40*mm
                cell_w = 180*mm / self.cols if self.cols <= 12 else 280*mm / self.cols # Adjust for plate size
                if self.cols > 12: 
                    c.setPageSize((297*mm, 210*mm)) # Landscape for 384 well
                    width, height = (297*mm, 210*mm)
                    cell_w = 260*mm / self.cols
                    x_start = 10*mm
                    y_start = height - 30*mm
                
                cell_h = cell_w * 0.8
                
                c.setFont("Helvetica", 6 if self.cols > 12 else 8)
                
                for r in range(self.rows):
                    for c_idx in range(self.cols):
                        well = self.wells.get((r, c_idx))
                        x = x_start + c_idx * cell_w
                        y = y_start - r * cell_h
                        
                        # Fill
                        if well and well.custom_color:
                            c.setFillColor(HexColor(well.custom_color.name()))
                            c.rect(x, y - cell_h, cell_w, cell_h, fill=1, stroke=1)
                            c.setFillColor(black)
                        else:
                            c.rect(x, y - cell_h, cell_w, cell_h, fill=0, stroke=1)
                            
                        # Text
                        if well:
                            txt = ""
                            if well.sample_name: txt += well.sample_name[:4] + "\n"
                            if well.gene_name: txt += well.gene_name[:4]
                            
                            lines = txt.split('\n')
                            ty = y - cell_h/2 + (len(lines)*2)
                            for line in lines:
                                c.drawCentredString(x + cell_w/2, ty, line)
                                ty -= 8 if self.cols <= 12 else 6

                # Legend
                y = y_start - self.rows * cell_h - 20*mm
                c.setFont("Helvetica-Bold", 10)
                c.drawString(x_start, y, "Gene Legend:")
                y -= 10*mm
                c.setFont("Helvetica", 10)
                
                for gene, color in self.gene_colors.items():
                    c.setFillColor(HexColor(color.name()))
                    c.rect(x_start, y, 5*mm, 5*mm, fill=1, stroke=1)
                    c.setFillColor(black)
                    c.drawString(x_start + 8*mm, y, gene)
                    y -= 8*mm
                    if y < 20*mm:
                        c.showPage()
                        y = height - 20*mm

                c.save()
                os.startfile(path)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to export PDF: {e}")

class cDNA_Tab(QWidget):
    """Tab for cDNA calculation and planning."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.amount_colors = {
            1000: "#a5d6a7", 900: "#c8e6c9", 800: "#dcedc8", 700: "#e8f5e9",
            600: "#fff59d", 500: "#fff9c4", 400: "#fffde7",
            300: "#ffcc80", 200: "#ffe0b2", 100: "#fff3e0",
            "low": "#ffcdd2"
        }
        self.df_data = pd.DataFrame()
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)

        # Top: Load Button
        top_layout = QHBoxLayout()
        self.load_btn = QPushButton("Load RNA Concentrations (Excel/CSV)")
        self.load_btn.clicked.connect(self.load_data)
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
        top_layout.addWidget(self.load_btn)
        top_layout.addStretch()
        layout.addLayout(top_layout)
        
        # Main Content: Table (Left) + Controls (Right)
        main_content = QHBoxLayout()
        
        # Table Area (Left)
        table_area = QVBoxLayout()
        
        self.table = QTableWidget()
        self.table.setColumnCount(6)
        self.table.setHorizontalHeaderLabels(["Sample Name", "RNA Conc. (ng/µL)", "µL RNA", "ng RNA", "µL H2O", "Dilution Vol (µL)"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table_area.addWidget(self.table)
        
        # Legend
        legend_layout = QHBoxLayout()
        legend_layout.setSpacing(0)
        
        legend_items = [
            ("1000 ng", "#2E7D32"), ("900 ng", "#43A047"), ("800 ng", "#66BB6A"), ("700 ng", "#A5D6A7"),
            ("600 ng", "#FFF176"), ("500 ng", "#FFD54F"), ("400 ng", "#FFB74D"), ("300 ng", "#FF9800"),
            ("200 ng", "#F57C00"), ("100 ng", "#FF7043"), ("<100 ng (N/A)", "#B71C1C")
        ]
        
        for label_text, color_hex in legend_items:
            lbl = QLabel(label_text)
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(f"background-color: {color_hex}; border: 1px solid #ddd; padding: 2px;")
            if color_hex in ["#2E7D32", "#43A047", "#F57C00", "#FF9800", "#B71C1C", "#FF7043"]: # Darker backgrounds
                 lbl.setStyleSheet(f"background-color: {color_hex}; color: white; border: 1px solid #ddd; padding: 2px;")
            legend_layout.addWidget(lbl)
            
        table_area.addLayout(legend_layout)
        
        main_content.addLayout(table_area, 3) # Stretch factor 3
        
        # Right Side Controls
        controls_panel = QVBoxLayout()
        controls_panel.setAlignment(Qt.AlignmentFlag.AlignTop)
        
        # Target RNA Amount - REMOVED
        
        # Rxn volume pre-RTase Mix
        self.pre_rt_vol_input = QDoubleSpinBox()
        self.pre_rt_vol_input.setPrefix("Rxn Vol pre-RTase: ")
        self.pre_rt_vol_input.setSuffix(" µL")
        self.pre_rt_vol_input.setRange(1, 100)
        self.pre_rt_vol_input.setValue(15)
        self.pre_rt_vol_input.setDecimals(1)
        self.pre_rt_vol_input.valueChanged.connect(self.calculate_volumes_if_loaded)
        controls_panel.addWidget(self.pre_rt_vol_input)
        
        # Total Synthesis Volume (Hidden/Standard input for calc)
        self.synth_vol_input = QDoubleSpinBox()
        self.synth_vol_input.setPrefix("Total Synth Vol: ")
        self.synth_vol_input.setSuffix(" µL")
        self.synth_vol_input.setRange(1, 100)
        self.synth_vol_input.setValue(20)
        self.synth_vol_input.setDecimals(1)
        self.synth_vol_input.valueChanged.connect(self.calculate_volumes_if_loaded)
        controls_panel.addWidget(self.synth_vol_input)
        
        # Final cDNA Conc
        self.final_conc_input = QDoubleSpinBox()
        self.final_conc_input.setPrefix("Final cDNA Conc: ")
        self.final_conc_input.setSuffix(" ng/µL")
        self.final_conc_input.setRange(0.1, 1000)
        self.final_conc_input.setValue(5)
        self.final_conc_input.setDecimals(1)
        self.final_conc_input.valueChanged.connect(self.calculate_volumes_if_loaded)
        controls_panel.addWidget(self.final_conc_input)
        
        controls_panel.addSpacing(20)
        
        # Group Assignment
        self.assign_group_btn = QPushButton("Define Group Names")
        self.assign_group_btn.clicked.connect(self.define_groups)
        self.assign_group_btn.setEnabled(False)
        self.assign_group_btn.setStyleSheet("background-color: #dcedc8; color: black; font-weight: bold;")
        controls_panel.addWidget(self.assign_group_btn)
        
        controls_panel.addSpacing(10)
        
        self.export_excel_btn = QPushButton("Export Excel")
        self.export_excel_btn.clicked.connect(self.export_excel)
        self.export_excel_btn.setEnabled(False)
        controls_panel.addWidget(self.export_excel_btn)
        
        self.export_pdf_btn = QPushButton("Export Pipetting PDF")
        self.export_pdf_btn.clicked.connect(self.export_pdf)
        self.export_pdf_btn.setEnabled(False)
        controls_panel.addWidget(self.export_pdf_btn)
        
        controls_panel.addStretch()
        
        main_content.addLayout(controls_panel, 1) # Stretch factor 1
        layout.addLayout(main_content)

        # Footer Note
        footer_label = QLabel("To each reaction add amount of RTase, buffer, primer, and dNTPs as per the manufacturer's instructions.")
        footer_label.setStyleSheet("font-style: italic; color: #555;")
        footer_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(footer_label)

    def calculate_volumes_if_loaded(self):
        if not self.df_data.empty:
            self.calculate_volumes()
            self.update_table()

    def load_data(self):
        file_path, _ = QFileDialog.getOpenFileName(self, "Open Concentration File", "", "Data Files (*.xlsx *.xls *.csv);;All Files (*)")
        if not file_path:
            return

        # Update status message in main window
        parent = self.parent()
        while parent and not hasattr(parent, 'set_status_message'):
            parent = parent.parent()
        if parent:
            parent.set_status_message(f"Loaded: {os.path.basename(file_path)}")

        try:
            if file_path.lower().endswith('.csv'):
                # Try UTF-8 first
                try:
                    df_raw = pd.read_csv(file_path, encoding='utf-8', sep=None, engine='python', header=None)
                except UnicodeDecodeError:
                    # Try UTF-16 next
                    try:
                        df_raw = pd.read_csv(file_path, encoding='utf-16', sep=None, engine='python', header=None)
                    except UnicodeDecodeError:
                        # Finally try latin1
                        df_raw = pd.read_csv(file_path, encoding='latin1', sep=None, engine='python', header=None)
            else:
                df_raw = pd.read_excel(file_path, header=None)
            
            # Robust Header Detection
            header_row_idx = 0
            found_header = False
            
            # Search for header in first 50 rows
            for i in range(min(50, len(df_raw))):
                row_vals = [str(x).lower() for x in df_raw.iloc[i]]
                
                # Check for key columns
                has_name = any("sample" in x or "name" in x or "content" in x for x in row_vals)
                has_conc = any("conc" in x or "ng/ul" in x or "ng/µl" in x or "nucleic acid" in x for x in row_vals)
                
                if has_name and has_conc:
                    header_row_idx = i
                    found_header = True
                    break
            
            # Apply header
            if found_header:
                df = df_raw.iloc[header_row_idx+1:].copy()
                df.columns = df_raw.iloc[header_row_idx]
            else:
                # Fallback: assume first row is header if not found
                if len(df_raw) > 0:
                    df = df_raw.iloc[1:].copy()
                    df.columns = df_raw.iloc[0]
                else:
                    df = df_raw # Empty

            # Smart column detection
            name_col = None
            conc_col = None
            
            # normalize cols to lower
            cols_lower = [str(c).lower() for c in df.columns]
            
            # Find Name column
            for i, c in enumerate(cols_lower):
                if "sample" in c or "name" in c or "content" in c:
                    name_col = df.columns[i]
                    break
            
            # Find Concentration column
            for i, c in enumerate(cols_lower):
                if "conc" in c or "ng/ul" in c or "ng/µl" in c or "nucleic acid" in c:
                    conc_col = df.columns[i]
                    break
            
            # Fallback logic if smart detection fails
            if name_col is None:
                # If we have at least 1 col, take the first one
                if df.shape[1] > 0:
                    name_col = df.columns[0]
                    # But wait, if column 0 is "Date", maybe we should skip it?
                    if "date" in str(name_col).lower() and df.shape[1] > 1:
                         name_col = df.columns[1]

            if conc_col is None:
                # If name_col was 0, take 1. If name_col was 1, take 2?
                # Let's just try to find the next available column
                if name_col == df.columns[0] and df.shape[1] > 1:
                    conc_col = df.columns[1]
                elif name_col == df.columns[1] and df.shape[1] > 2:
                    conc_col = df.columns[2]
                elif df.shape[1] > 1:
                    conc_col = df.columns[1]

            if name_col is None or conc_col is None:
                QMessageBox.warning(self, "Error", f"Could not identify Name and Concentration columns.\nColumns found: {list(df.columns)}")
                return

            # Normalize data
            try:
                self.df_data = pd.DataFrame({
                    'Sample Name': df[name_col].astype(str),
                    'Concentration': pd.to_numeric(df[conc_col], errors='coerce'),
                    'Group': [''] * len(df)
                })
            except Exception as e:
                # print(f"Error normalizing data: {e}")
                QMessageBox.critical(self, "Error", f"Failed to parse columns: {e}")
                return
            
            # Drop NaN concentrations
            before_drop = len(self.df_data)
            self.df_data.dropna(subset=['Concentration'], inplace=True)
            # print(f"Rows before dropna: {before_drop}, after: {len(self.df_data)}")
            
            # Reset index
            self.df_data.reset_index(drop=True, inplace=True)
            
            self.calculate_volumes()
            self.update_table()
            self.export_excel_btn.setEnabled(True)
            self.export_pdf_btn.setEnabled(True)
            self.assign_group_btn.setEnabled(True)

        except Exception as e:
            # print(f"Exception in load_data: {e}")
            # import traceback
            # traceback.print_exc()
            QMessageBox.critical(self, "Error", f"Failed to load file: {e}")

    def calculate_volumes(self):
        # print("Calculating volumes...")
        # Calculation Logic
        pre_rt_vol = self.pre_rt_vol_input.value()
        synth_vol = self.synth_vol_input.value()
        final_conc = self.final_conc_input.value()
        
        # print(f"Inputs: Target={target_rna_ng}, PreRT={pre_rt_vol}, Synth={synth_vol}, Final={final_conc}")
        
        results = []
        for idx, row in self.df_data.iterrows():
            conc = row['Concentration']
            if conc <= 0:
                # print(f"Skipping row {idx}: Conc <= 0 ({conc})")
                continue
            
            # 1. Determine optimal RNA amount (start 1000 ng, step down 100 ng)
            optimal_rna_ng = 0
            vol_rna = 0
            
            # Try from 1000 down to 100
            for amount in range(1000, 99, -100):
                v = amount / conc
                if v <= pre_rt_vol:
                    optimal_rna_ng = amount
                    vol_rna = v
                    break
            
            # If still 0, it means even 100 ng requires > pre_rt_vol
            # Mark as "Too Low" (<100)
            if optimal_rna_ng == 0:
                # Use max possible volume to get max possible amount
                vol_rna = pre_rt_vol
                optimal_rna_ng = pre_rt_vol * conc
                # Flag this? For now, we store the actual amount, but we'll color code it red
            
            # 2. Calc H2O Volume
            if optimal_rna_ng < 100:
                vol_h2o = "N/A"
            elif vol_rna > pre_rt_vol:
                # Should only happen if "Too Low" logic kicked in or conc very low
                vol_rna = pre_rt_vol
                vol_h2o = 0
            else:
                vol_h2o = round(pre_rt_vol - vol_rna, 2)
            
            # 3. Calc Dilution
            # Total Volume Needed = Amount RNA Used / Final Conc
            # Use optimal_rna_ng for this calculation
            if optimal_rna_ng < 100:
                dilution_vol = "N/A"
            else:
                total_final_vol = optimal_rna_ng / final_conc
                
                dilution_vol = total_final_vol - synth_vol
                if dilution_vol < 0: dilution_vol = 0
                dilution_vol = round(dilution_vol, 1)
            
            results.append({
                'vol_rna': round(vol_rna, 2),
                'ng_rna': round(optimal_rna_ng, 1),
                'vol_h2o': vol_h2o,
                'dilution_vol': dilution_vol,
                'color': self.get_color_for_amount(optimal_rna_ng).name()
            })
            
        # print(f"Calculated {len(results)} results")
        
        if len(results) > 0:
            self.df_data['vol_rna'] = [r['vol_rna'] for r in results]
            self.df_data['ng_rna'] = [r['ng_rna'] for r in results]
            self.df_data['vol_h2o'] = [r['vol_h2o'] for r in results]
            self.df_data['dilution_vol'] = [r['dilution_vol'] for r in results]
            self.df_data['color'] = [r['color'] for r in results]
        else:
             # Handle empty results if needed, but columns should exist
             self.df_data['vol_rna'] = []
             self.df_data['ng_rna'] = []
             self.df_data['vol_h2o'] = []
             self.df_data['dilution_vol'] = []
             self.df_data['color'] = []

    def get_color_for_amount(self, amount):
        if amount >= 1000: return QColor("#2E7D32") # Dark Green
        if amount >= 900: return QColor("#43A047")
        if amount >= 800: return QColor("#66BB6A")
        if amount >= 700: return QColor("#A5D6A7") # Light Green
        if amount >= 600: return QColor("#FFF176") # Yellow
        if amount >= 500: return QColor("#FFD54F")
        if amount >= 400: return QColor("#FFB74D")
        if amount >= 300: return QColor("#FF9800")
        if amount >= 200: return QColor("#F57C00")
        if amount >= 100: return QColor("#FF7043") # Deep Orange (Lighter Red-ish)
        return QColor("#B71C1C") # Dark Red (<100)

    def update_table(self):
        # print(f"Updating table with {len(self.df_data)} rows")
        self.table.setRowCount(len(self.df_data))
        for r, row in self.df_data.iterrows():
            name = str(row['Sample Name'])
            if row['Group']:
                 name = str(row['Group']) # Use Group name if assigned
                 
            self.table.setItem(r, 0, QTableWidgetItem(name))
            self.table.setItem(r, 1, QTableWidgetItem(str(row['Concentration'])))
            self.table.setItem(r, 2, QTableWidgetItem(str(row['vol_rna'])))
            
            # ng RNA item with color
            ng_item = QTableWidgetItem(str(row['ng_rna']))
            color = self.get_color_for_amount(row['ng_rna'])
            ng_item.setBackground(QBrush(color))
            # Set text color to black or white for contrast? Default black usually works for pastels, 
            # but for dark green/orange maybe white? Let's stick to black for now or simple check.
            if row['ng_rna'] >= 900 or row['ng_rna'] <= 300:
                 ng_item.setForeground(QBrush(Qt.GlobalColor.white))
            else:
                 ng_item.setForeground(QBrush(Qt.GlobalColor.black))
                 
            self.table.setItem(r, 3, ng_item)
            
            self.table.setItem(r, 4, QTableWidgetItem(str(row['vol_h2o'])))
            self.table.setItem(r, 5, QTableWidgetItem(str(row['dilution_vol'])))
            
    def define_groups(self):
        rows = sorted(set(index.row() for index in self.table.selectedIndexes()))
        if not rows:
            QMessageBox.warning(self, "Warning", "Please select rows to assign a group.")
            return
            
        name, ok = QInputDialog.getText(self, "Group Name", "Enter Group Name (e.g. 'WT'):")
        if ok and name:
            # Assign names with increment
            count = 1
            for r in rows:
                group_name = f"{name} {count}"
                self.df_data.at[r, 'Group'] = group_name
                # Update Sample Name in table
                self.table.setItem(r, 0, QTableWidgetItem(group_name))
                count += 1

    def export_excel(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save Excel", "cDNA_Scheme.xlsx", "Excel Files (*.xlsx)")
        if not path: return
        
        try:
            import openpyxl
            from openpyxl.styles import PatternFill, Font, Alignment
            
            # Create a new workbook from scratch using openpyxl
            wb = openpyxl.Workbook()
            ws = wb.active
            
            # Add Summary Information
            summary_font = Font(bold=True)
            
            ws.cell(row=1, column=1, value="User Input Parameters").font = summary_font
            
            ws.cell(row=2, column=1, value="Rxn Vol (µL):")
            ws.cell(row=2, column=2, value=self.pre_rt_vol_input.value())
            
            ws.cell(row=3, column=1, value="Total Synth Vol (µL):")
            ws.cell(row=3, column=2, value=self.synth_vol_input.value())
            
            ws.cell(row=4, column=1, value="Final cDNA Conc (ng/µL):")
            ws.cell(row=4, column=2, value=self.final_conc_input.value())
            
            # Column headers for the data table (Row 5)
            headers = ["Sample Name", "RNA Conc. (ng/µL)", "µL RNA", "ng RNA", "µL H2O", "Dilution Vol (µL)"]
            header_fill = PatternFill(start_color="D3D3D3", end_color="D3D3D3", fill_type="solid")
            header_font = Font(bold=True)
            center_align = Alignment(horizontal='center', vertical='center')
            
            for col_idx, header_text in enumerate(headers, start=1):
                cell = ws.cell(row=5, column=col_idx, value=header_text)
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = center_align
            
            # Add data rows starting at row 6
            for r_idx, (_, row) in enumerate(self.df_data.iterrows(), start=6):
                name = str(row['Sample Name'])
                if row['Group']:
                    name = str(row['Group'])
                
                # Get the color for this row
                color_hex = str(row['color']).lstrip('#')
                fill = PatternFill(start_color=color_hex, end_color=color_hex, fill_type='solid') if len(color_hex) == 6 else None
                
                # Write data and apply color
                ws.cell(row=r_idx, column=1, value=name)
                ws.cell(row=r_idx, column=2, value=row['Concentration'])
                ws.cell(row=r_idx, column=3, value=row['vol_rna'])
                ws.cell(row=r_idx, column=4, value=row['ng_rna'])
                ws.cell(row=r_idx, column=5, value=row['vol_h2o'])
                ws.cell(row=r_idx, column=6, value=row['dilution_vol'])
                
                # Apply color fill to all columns in this row
                if fill:
                    for c in range(1, len(headers) + 1):
                        ws.cell(row=r_idx, column=c).fill = fill
            
            # Auto-adjust column widths
            for column_cells in ws.columns:
                max_length = 0
                column = column_cells[0].column_letter
                for cell in column_cells:
                    try:
                        val = cell.value
                        if val:
                            val_len = len(str(val))
                            if val_len > max_length:
                                max_length = val_len
                    except:
                        pass
                
                # Add extra padding for bold text and readability
                adjusted_width = (max_length + 4)
                ws.column_dimensions[column].width = adjusted_width

            # Footer Note
            last_row = len(self.df_data) + 6
            ws.cell(row=last_row+2, column=1, value="To each reaction add amount of RTase, buffer, primer, and dNTPs as per the manufacturer's instructions.")
            ws.cell(row=last_row+2, column=1).font = Font(italic=True, color="555555")

            wb.save(path)
            
            # Prompt for transfer
            reply = QMessageBox.question(self, "Transfer Samples", 
                                         "Do you want to transfer these Group names to the Plate Mapper?",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            
            if reply == QMessageBox.StandardButton.Yes:
                groups = [g for g in self.df_data['Group'] if g]
                if groups:
                    # Clean group names (remove trailing numbers)
                    import re
                    clean_groups = []
                    for g in groups:
                        # Remove trailing space and digits (e.g., "WT 1" -> "WT")
                        base_name = re.sub(r'\s+\d+$', '', str(g))
                        if base_name and base_name not in clean_groups:
                            clean_groups.append(base_name)
                    
                    # Find main window
                    parent = self.parent()
                    while parent and not isinstance(parent, QMainWindow):
                        parent = parent.parent()
                    
                    if parent and hasattr(parent, 'transfer_samples_from_cdna'):
                        parent.transfer_samples_from_cdna(clean_groups)
            
            os.startfile(path)
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to export: {e}")

    def export_pdf(self):
        path, _ = QFileDialog.getSaveFileName(self, "Save PDF", "Pipetting_Scheme.pdf", "PDF Files (*.pdf)")
        if not path: return
        
        try:
            c = canvas.Canvas(path, pagesize=A4)
            width, height = A4
            
            # Title
            c.setFont("Helvetica-Bold", 16)
            c.drawString(20 * mm, height - 20 * mm, "cDNA Synthesis Pipetting Scheme")
            
            # Summary Information
            c.setFont("Helvetica", 10)
            y_summary = height - 35 * mm
            c.drawString(20 * mm, y_summary, f"Rxn Vol: {self.pre_rt_vol_input.value()} µL")
            c.drawString(70 * mm, y_summary, f"Total Synth Vol: {self.synth_vol_input.value()} µL")
            c.drawString(120 * mm, y_summary, f"Final cDNA: {self.final_conc_input.value()} ng/µL")
            
            y = height - 50 * mm
            
            # Headers
            # App Headers: ["Sample Name", "RNA Conc. (ng/µL)", "µL RNA", "ng RNA", "µL H2O", "Dilution Vol (µL)"]
            headers = ["Sample Name", "RNA Conc.", "µL RNA", "ng RNA", "µL H2O", "Dil. Vol (µL)"]
            # Shortened slightly for PDF fit, but kept key info. 
            # "RNA Conc. (ng/µL)" -> "RNA Conc." (units implied or fit issue)
            # "Dilution Vol (µL)" -> "Dil. Vol (µL)"
            
            # Adjust x positions for 6 columns
            # Available width ~170mm (20 to 190)
            # Sample: 20, Conc: 60, VolRNA: 85, ngRNA: 110, H2O: 135, Dil: 160
            x_positions = [20, 60, 85, 110, 135, 160] 
            
            c.setFont("Helvetica-Bold", 9) # Reduced font size for headers to fit
            for i, h in enumerate(headers):
                c.drawString(x_positions[i] * mm, y, h)
                
            y -= 8 * mm
            c.setFont("Helvetica", 10)
            
            for _, row in self.df_data.iterrows():
                if y < 20 * mm:
                    c.showPage()
                    y = height - 20 * mm
                    # Redraw headers on new page? Optional, but good practice.
                    # For simplicity, we just continue data.
                
                # Determine Sample Name (Group or Original)
                name = str(row['Sample Name'])
                if row['Group']:
                    name = str(row['Group'])

                # Draw color rect
                color_val = str(row['color'])
                if color_val.startswith('#'):
                    bg_color = HexColor(color_val)
                else:
                    bg_color = HexColor('#ffffff')
                    
                c.setFillColor(bg_color)
                # Draw rect spanning all columns
                c.rect(15 * mm, y - 2 * mm, 180 * mm, 6 * mm, fill=1, stroke=0)
                
                # Determine text color for contrast
                text_color = black
                dark_colors = ["#2E7D32", "#43A047", "#F57C00", "#FF9800", "#B71C1C", "#FF7043"]
                if str(row['color']).upper() in dark_colors:
                     text_color = HexColor('#FFFFFF')
                
                c.setFillColor(text_color)
                
                # Draw row data
                c.drawString(x_positions[0] * mm, y, name[:20])
                c.drawString(x_positions[1] * mm, y, str(row['Concentration']))
                c.drawString(x_positions[2] * mm, y, str(row['vol_rna']))
                c.drawString(x_positions[3] * mm, y, str(row['ng_rna']))
                c.drawString(x_positions[4] * mm, y, str(row['vol_h2o']))
                c.drawString(x_positions[5] * mm, y, str(row['dilution_vol']))
                
                y -= 8 * mm
            
            # Footer Note
            y -= 5 * mm
            if y < 20 * mm:
                c.showPage()
                y = height - 20 * mm
            
            c.setFont("Helvetica-Oblique", 9)
            c.setFillColor(HexColor('#555555'))
            c.drawString(20 * mm, y, "To each reaction add amount of RTase, buffer, primer, and dNTPs as per the manufacturer's instructions.")
                
            c.save()
            
            # Prompt for transfer
            reply = QMessageBox.question(self, "Transfer Samples", 
                                         "Do you want to transfer these Group names to the Plate Mapper?",
                                         QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            
            if reply == QMessageBox.StandardButton.Yes:
                groups = [g for g in self.df_data['Group'] if g]
                if groups:
                    # Clean group names (remove trailing numbers)
                    import re
                    clean_groups = []
                    for g in groups:
                        # Remove trailing space and digits (e.g., "WT 1" -> "WT")
                        base_name = re.sub(r'\s+\d+$', '', str(g))
                        if base_name and base_name not in clean_groups:
                            clean_groups.append(base_name)
                    
                    # Find main window
                    parent = self.parent()
                    while parent and not isinstance(parent, QMainWindow):
                        parent = parent.parent()
                    
                    if parent and hasattr(parent, 'transfer_samples_from_cdna'):
                        parent.transfer_samples_from_cdna(clean_groups)

            os.startfile(path)
            
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to export PDF: {e}")

class AboutWindow(QDialog):
    """The 'About CtQuant' window."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("About CtQuant")
        self.setFixedSize(600, 500)
        
        # Define attributes used in the UI
        self.version = "v1.2.0"
        self.creation_date = "2026"
        self.author = "Dr. Robert Hauffe"
        
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        
        # cDNA Workflow Tab
        cdna_tab = QWidget()
        cdna_layout = QVBoxLayout(cdna_tab)
        cdna_text = QLabel("<b>cDNA Synthesis Workflow:</b><br><br>"
                           "1. <b>Load Data:</b> Import RNA concentration data (CSV/Excel). The tool detects 'Sample Name' and 'Concentration' columns.<br>"
                           "2. <b>Configure:</b> Set Rxn Vol pre-RTase (µL), Total Synth Vol (µL), and Final cDNA Conc (ng/µL).<br>"
                           "3. <b>Review:</b> The table updates automatically, maximizing RNA input (up to 1000 ng).<br>"
                           "4. <b>Define Groups:</b> Assign group names (e.g., 'WT', 'KO') to samples.<br>"
                           "5. <b>Export:</b> Generate a pipetting scheme (PDF) or Excel report.<br>"
                           "6. <b>Transfer:</b> Click 'Define Group Names' to transfer samples to the Plate Mapper.")
        cdna_text.setWordWrap(True)
        cdna_layout.addWidget(cdna_text)
        cdna_layout.addStretch()
        tabs.addTab(cdna_tab, "cDNA Workflow")

        # qPCR Workflow Tab
        qpcr_tab = QWidget()
        qpcr_layout = QVBoxLayout(qpcr_tab)
        qpcr_text = QLabel("<b>qPCR Analysis Workflow:</b><br><br>"
                         "1. <b>Load qPCR Data:</b> Import raw Ct values from your instrument (Excel).<br>"
                         "2. <b>Map Plate:</b> Use the 'Paint' tool to assign samples (transferred from cDNA or manual) and targets (GOI/HK) to wells.<br>"
                         "3. <b>Analyze:</b> Click 'Calculate' to process data using the ddCt method.<br>"
                         "4. <b>Refine:</b> Review results in the Analysis tab. Right-click to exclude outliers.<br>"
                         "5. <b>Export:</b> Save comprehensive results to Excel.")
        qpcr_text.setWordWrap(True)
        qpcr_layout.addWidget(qpcr_text)
        qpcr_layout.addStretch()
        tabs.addTab(qpcr_tab, "qPCR Workflow")
        
        # Methodology Tab
        methodology = QWidget()
        m_layout = QVBoxLayout(methodology)
        m_text = QLabel("<b>ddCt Quantification Method:</b><br><br>"
                        "• <b>Technical Replicates:</b> Averaged per sample/gene. SD > 0.5 is flagged.<br>"
                        "• <b>dCt:</b> Ct(Gene of Interest) - Average Ct(Housekeeping Genes).<br>"
                        "• <b>ddCt:</b> dCt(Sample) - Average dCt(Control Group for that Gene).<br>"
                        "• <b>Fold Change:</b> 2<sup>-ddCt</sup>.<br>"
                        "• <b>% Change:</b> (Fold Change - 1) * 100.<br><br>"
                        "<b>Statistics:</b> Welch's t-test is used for comparison between Treatment and Control groups.")
        m_text.setWordWrap(True)
        m_layout.addWidget(m_text)
        m_layout.addStretch()
        tabs.addTab(methodology, "Methodology")
        
        # Tab 4: Credits
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
        
        desc_label = QLabel("Tool for the assisted quantification of qPCR data and calculating cDNA synthesis volumes.")
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

    def set_status_message(self, message):
        """Update the status label at the bottom of the window."""
        self.status_label.setText(message)
        
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
        
        self.about_btn = QPushButton("About CtQuant")
        self.about_btn.clicked.connect(self.show_about)
        top_layout.addWidget(self.about_btn)
        
        main_layout.addLayout(top_layout)
        
        # Main Content: Tabs for "Main View" and "Detailed Results"
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)
        
        # Status Label
        self.status_label = QLabel("Ready")
        self.status_label.setStyleSheet("color: #666; font-style: italic;")
        main_layout.addWidget(self.status_label)
        
        # Tab 1: Plate Mapper/qPCR Analysis (Main View) - Default
        self.main_view_tab = QWidget()
        self.setup_main_view_tab()
        self.tabs.addTab(self.main_view_tab, "Plate Mapper/qPCR Analysis")
        
        # Tab 2: cDNA Calculation
        self.cdna_tab = cDNA_Tab()
        self.tabs.addTab(self.cdna_tab, "cDNA Calculation")
        
        # Tab 3: Detailed Results
        self.detailed_tab = QWidget()
        self.setup_detailed_tab()
        self.tabs.addTab(self.detailed_tab, "Detailed Results")

    def setup_main_view_tab(self):
        layout = QVBoxLayout(self.main_view_tab)
        
        # Load Button Section
        btn_layout = QHBoxLayout()
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
        btn_layout.addWidget(self.load_btn)
        btn_layout.addStretch()
        layout.addLayout(btn_layout)
        
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
        
        mapping_box = QGroupBox("Plate Tools")
        mapping_layout = QVBoxLayout(mapping_box)
        
        # Tools: Paint / Erase
        tools_layout = QHBoxLayout()
        instruction_label = QLabel("Left-click to Paint, Right-click to Erase")
        instruction_label.setStyleSheet("font-style: italic; color: #666;")
        instruction_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        tools_layout.addWidget(instruction_label)
        mapping_layout.addLayout(tools_layout)
        
        # Form for Paint Data
        form_layout = QFormLayout()
        
        self.group_type_combo = QComboBox()
        self.group_type_combo.addItems(["None", "Control", "Treatment"])
        self.group_type_combo.setCurrentText("Control")
        self.group_type_combo.currentTextChanged.connect(self.update_brush)
        form_layout.addRow("Group:", self.group_type_combo)
        
        self.sample_name_input = QComboBox()
        self.sample_name_input.setEditable(True)
        self.sample_name_input.lineEdit().returnPressed.connect(
            lambda: self.add_to_combo(self.sample_name_input))
        self.sample_name_input.currentTextChanged.connect(self.update_brush)
        form_layout.addRow("Sample Name:", self.sample_name_input)
        
        self.gene_type_combo = QComboBox()
        self.gene_type_combo.addItems(["None", "Housekeeping", "GOI"])
        self.gene_type_combo.setCurrentText("Housekeeping")
        self.gene_type_combo.currentTextChanged.connect(self.update_brush)
        form_layout.addRow("Gene Type:", self.gene_type_combo)
        
        self.gene_name_input = QComboBox()
        self.gene_name_input.setEditable(True)
        self.gene_name_input.lineEdit().returnPressed.connect(
            lambda: self.add_to_combo(self.gene_name_input))
        self.gene_name_input.currentTextChanged.connect(self.update_brush)
        form_layout.addRow("Gene Name:", self.gene_name_input)
        
        # Clear Plate Button
        self.clear_plate_btn = QPushButton("Clear Plate")
        self.clear_plate_btn.clicked.connect(self.clear_plate)
        self.clear_plate_btn.setStyleSheet("color: #c0392b; font-weight: bold;")
        form_layout.addRow("", self.clear_plate_btn)

        mapping_layout.addLayout(form_layout)
        
        # Action Buttons
        actions_layout = QHBoxLayout()
        self.export_pipetting_btn = QPushButton("Export Scheme")
        self.export_pipetting_btn.clicked.connect(self.mapper.export_pipetting_scheme)
        actions_layout.addWidget(self.export_pipetting_btn)
        
        # Removed redundant clear button from actions_layout
        # actions_layout.addWidget(self.clear_plate_btn)
        
        controls_layout.addWidget(mapping_box)
        
        # Initialize brush
        self.update_brush()

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

    def update_brush(self):
        data = {
            'sample_name': self.sample_name_input.currentText(),
            'gene_name': self.gene_name_input.currentText(),
            'group_type': self.group_type_combo.currentText(),
            'gene_type': self.gene_type_combo.currentText()
        }
        self.mapper.set_brush_data(data)

    def transfer_samples_from_cdna(self, groups):
        """Transfer group names from cDNA tab to Plate Mapper sample list."""
        count = 0
        for group in groups:
            if self.sample_name_input.findText(group) == -1:
                self.sample_name_input.addItem(group)
                count += 1
        
        if count > 0:
            QMessageBox.information(self, "Transfer Complete", f"Transferred {count} group names to Plate Mapper sample list.")
            # Switch to Main View tab
            self.tabs.setCurrentIndex(0)
        else:
            QMessageBox.information(self, "Transfer Complete", "All group names were already present in the list.")
            self.tabs.setCurrentIndex(0)

    def on_plate_format_changed(self):
        fmt = self.plate_format_combo.currentText()
        rows, cols = (16, 24) if fmt == "384-well" else (8, 12)
        
        # Recreate mapper
        old_mapper = self.mapper
        self.mapper = PlateMapper(rows, cols)
        
        # Find scroll area and replace widget
        scroll = self.main_view_tab.findChild(QScrollArea)
        scroll.setWidget(self.mapper)
        self.update_brush()
        
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
            self.set_status_message(f"Loaded: {os.path.basename(path)}")
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
                # Validate Excel file integrity before attempting to read
                try:
                    import zipfile
                    # XLSX files are ZIP files, so check if it's a valid ZIP
                    if not zipfile.is_zipfile(path):
                        QMessageBox.critical(self, "Invalid File", 
                            f"The selected file does not appear to be a valid Excel file.\n\n"
                            f"Please ensure the file is a proper .xlsx or .xls file and is not corrupted.")
                        return
                    
                    # If it's a ZIP, check if it has the required XLSX structure
                    with zipfile.ZipFile(path, 'r') as zf:
                        namelist = zf.namelist()
                        if '[Content_Types].xml' not in namelist:
                            QMessageBox.critical(self, "Corrupted File", 
                                f"The Excel file appears to be corrupted or incomplete.\n\n"
                                f"It is missing required internal structure ([Content_Types].xml).\n\n"
                                f"Please try:\n"
                                f"1. Re-saving the file in Excel\n"
                                f"2. Creating a fresh export from your qPCR instrument")
                            return
                except zipfile.BadZipFile:
                    QMessageBox.critical(self, "Invalid File", 
                        f"The selected file is not a valid Excel file or is corrupted.\n\n"
                        f"Please ensure you selected a proper .xlsx or .xls file.")
                    return
                
                xls = pd.ExcelFile(path)
                
                if not xls.sheet_names:
                    QMessageBox.warning(self, "Error", "No sheets found in Excel file.")
                    return

                # If multiple sheets exist, let user choose (or default to single/best)
                target_sheet_name = None
                
                if len(xls.sheet_names) > 1:
                    # Ask user to select sheet
                    item, ok = QInputDialog.getItem(self, "Select Data Sheet", 
                                                  "Multiple sheets found. Please select the sheet containing the Ct/Cq data:", 
                                                  xls.sheet_names, 0, False)
                    if ok and item:
                        target_sheet_name = item
                    else:
                        return # User cancelled
                else:
                    target_sheet_name = xls.sheet_names[0]

                found_data = False
                col_map = {} # standard_name -> actual_name
                
                # Scan the selected sheet (or all if we were to loop, but we decided to ask user)
                # If user selected a sheet, we only scan that one.
                
                sheets_to_scan = [target_sheet_name] if target_sheet_name else xls.sheet_names
                
                for sheet_name in sheets_to_scan:
                    # Read first 50 rows of the sheet
                    try:
                        df_header = pd.read_excel(path, sheet_name=sheet_name, nrows=50, header=None)
                    except:
                        continue # Skip empty sheets or read errors
                        
                    # Scoring system for header row detection
                    best_score = 0
                    best_row_idx = -1
                    best_map = {}
                    
                    for i, row in df_header.iterrows():
                        row_vals = [str(v).strip() for v in row.values]
                        row_vals_lower = [v.lower() for v in row_vals]
                        
                        current_map = {}
                        score = 0
                        
                        # Check columns
                        for idx, val in enumerate(row_vals):
                            v_low = row_vals_lower[idx]
                            
                            # Well - Prioritize "Well Position" over "Well" if both exist
                            if v_low in ['well position', 'well pos', 'pos', 'position']:
                                current_map['Well'] = val
                                score += 2
                            elif v_low == 'well':
                                if 'Well' not in current_map: # Only take 'well' if we haven't found 'well position' yet
                                    current_map['Well'] = val
                                    score += 2
                                    
                            # Ct
                            elif v_low in ['ct', 'cq', 'cp', 'cycle', 'c t']:
                                current_map['Ct'] = val
                                score += 2
                                
                            # Sample
                            elif v_low in ['sample', 'sample name', 'sample_name', 'name', 'sample names', 'sample id', 'sampleid']:
                                current_map['Sample'] = val
                                score += 1
                                
                            # Target
                            elif v_low in ['target', 'target name', 'target_name', 'gene', 'gene name', 'target names', 'detector']:
                                current_map['Target'] = val
                                score += 1
                                
                            # Other common qPCR columns (boost confidence)
                            elif v_low in ['task', 'reporter', 'quencher', 'omit', 'quantity', 'mean', 'sd', 'rq', 'rq min', 'rq max']:
                                score += 0.5

                        # We need at least Well and Ct to consider it a valid header
                        if 'Well' in current_map and 'Ct' in current_map:
                            if score > best_score:
                                best_score = score
                                best_row_idx = i
                                best_map = current_map
                    
                    if best_row_idx != -1:
                        # Found a candidate in this sheet. 
                        # Is it good enough? 
                        # If we have Sample and Target too, it's excellent.
                        # For now, just take the best one found across sheets? 
                        # Or stop at first "good" one?
                        # Let's stop at first one that has high confidence (score >= 5?)
                        # Or just take this one and break.
                        header_row_idx = best_row_idx
                        col_map = best_map
                        self.raw_df = pd.read_excel(path, sheet_name=sheet_name, skiprows=header_row_idx)
                        
                        # IMPORTANT: Strip whitespace from column names to match scanner logic
                        self.raw_df.columns = self.raw_df.columns.astype(str).str.strip()
                        
                        found_data = True
                        break
                
                if not found_data:
                    QMessageBox.warning(self, "Format Error", "Could not find 'Well' and 'Ct/Cq' columns in any sheet.")
                    return
                
                # Normalize columns
                # Before renaming, we need to handle potential conflicts.
                # Specifically, if we are mapping "Well Position" -> "Well", but "Well" already exists.
                # We want to drop the original "Well" column to avoid duplicates.
                
                actual_well_col = col_map.get('Well')
                if actual_well_col and actual_well_col != 'Well':
                    # We are mapping something else (e.g. "Well Position") to "Well".
                    # If "Well" exists in the dataframe, drop it to avoid duplicate "Well" columns after rename.
                    if 'Well' in self.raw_df.columns:
                        self.raw_df.drop(columns=['Well'], inplace=True, errors='ignore')

                rename_dict = {v: k for k, v in col_map.items()}
                self.raw_df.rename(columns=rename_dict, inplace=True)


                # Fallback: If 'Sample' or 'Target' not found in header scan, check remaining columns
                if 'Sample' not in self.raw_df.columns:
                    for c in self.raw_df.columns:
                        c_str = str(c).lower().strip()
                        if 'sample' in c_str or 'name' in c_str:
                            # Avoid renaming 'Target', 'Well', 'Ct' or other critical columns
                            if c in ['Target', 'Well', 'Ct']: continue
                            # Also check if it's likely a Target column
                            if 'target' in c_str or 'gene' in c_str: continue
                            
                            self.raw_df.rename(columns={c: 'Sample'}, inplace=True)
                            break
                
                if 'Target' not in self.raw_df.columns:
                    for c in self.raw_df.columns:
                        c_str = str(c).lower().strip()
                        if 'target' in c_str or 'gene' in c_str:
                             if c in ['Sample', 'Well', 'Ct']: continue
                             self.raw_df.rename(columns={c: 'Target'}, inplace=True)
                             break
                
                # Clean Data
                # 1. Handle non-numeric Ct
                # Coerce to numeric, turning errors (strings like "Undetermined", "N/A") to NaN
                self.raw_df['Ct'] = pd.to_numeric(self.raw_df['Ct'], errors='coerce')
                
                # 2. Drop rows with empty Well
                self.raw_df.dropna(subset=['Well'], inplace=True)
                
                self.raw_data_path = path
                
                # 2. Extract Descriptors for Dropdowns
                samples = []
                genes = []
                
                if 'Sample' in self.raw_df.columns:
                    samples = sorted(self.raw_df['Sample'].dropna().astype(str).unique())
                if 'Target' in self.raw_df.columns:
                    genes = sorted(self.raw_df['Target'].dropna().astype(str).unique())
                
                # Update dropdowns
                self.sample_name_input.clear()
                self.sample_name_input.addItems(samples)
                self.gene_name_input.clear()
                self.gene_name_input.addItems(genes)
                
                # 3. Auto-populate Wells
                count_mapped = 0
                
                # Check if we have duplicate wells? 
                # If the file has replicates as separate rows (e.g. A1, A1, A1), we might overwrite.
                # But qPCR export usually has one row per well per target?
                # Or one row per well?
                # If one row per well per target, we might have multiple rows for A1 (Target 1, Target 2).
                # PlateMapper logic: One well has one Sample and one Gene?
                # CtQuant seems designed for singleplex or handling replicates by well assignment.
                # If a well has multiple targets, the current data model (Well object) only holds one 'gene_name'.
                # So we can't support multiplexing in the same well with this app structure easily.
                # We will just overwrite, which is consistent with legacy behavior.
                
                for idx, row in self.raw_df.iterrows():
                    well_str = str(row['Well']).strip()
                    if not well_str or len(well_str) < 1: continue
                    
                    # Convert A01 or A1 to (row, col)
                    # Handle both formats.
                    # Also handle if well is just a number (though we try to avoid mapping that column).
                    
                    r = -1
                    c = -1
                    
                    # Try A1/A01 format
                    if well_str[0].isalpha():
                        r_char = well_str[0].upper()
                        r = ord(r_char) - 65
                        try:
                            c_part = "".join(filter(str.isdigit, well_str[1:]))
                            if not c_part: continue
                            c = int(c_part) - 1
                        except:
                            continue
                    else:
                        # Maybe it's a number 1..96 (or 1..384)?
                        # If we failed to get 'Well Position' and fell back to 'Well' (numeric).
                        # We can convert 1..96 to A1..H12 layout based on current plate dimensions
                        try:
                            w_idx = int(float(well_str)) - 1
                            cols_cnt = self.mapper.cols # 12 or 24
                            r = w_idx // cols_cnt
                            c = w_idx % cols_cnt
                        except:
                            continue
                    
                    if (r, c) in self.mapper.wells:
                        well = self.mapper.wells[(r, c)]
                        well.ct_value = row['Ct']
                        
                        # Only update sample/gene if they are present and not empty
                        if 'Sample' in row and pd.notna(row['Sample']):
                            s_val = str(row['Sample']).strip()
                            if s_val and s_val.lower() not in ['nan', 'none', '']:
                                well.sample_name = s_val
                        
                        if 'Target' in row and pd.notna(row['Target']):
                            t_val = str(row['Target']).strip()
                            if t_val and t_val.lower() not in ['nan', 'none', '']:
                                well.gene_name = t_val
                                
                        well.update()
                        count_mapped += 1
                
                status_msg = f"Loaded: {os.path.basename(path)} (Mapped {count_mapped} wells)"
                if 'Sample' not in self.raw_df.columns:
                    status_msg += " [Warning: No Sample Name column found]"
                self.set_status_message(status_msg)
                
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
                    well.custom_color = None
                    well.update()
            
            self.mapper.data_changed.emit()
            
            # Clear internal data references
            if hasattr(self, 'raw_df'): del self.raw_df
            if hasattr(self, 'analysis_df'): del self.analysis_df
            if hasattr(self, 'results_df'): del self.results_df
            self.results_tree.clear()
            self.overview_table.setRowCount(0)
            
            # Clear input fields in Plate Tools
            self.sample_name_input.clear()
            self.gene_name_input.clear()
            self.update_brush()
            
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
            # Must have Sample, Gene, and a valid (non-NaN) Ct value
            if not (well.sample_name and well.gene_name and well.ct_value is not None and not pd.isna(well.ct_value)):
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
    window.showMaximized()
    sys.exit(app.exec())
