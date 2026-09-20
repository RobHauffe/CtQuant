# CtQuant - qPCR Analysis & cDNA Synthesis Tool

CtQuant is a comprehensive tool for molecular biology workflows, integrating cDNA synthesis planning with qPCR data analysis using the ddCt (2^-ddCt) quantification method.

## Version 1.2.0

## Citation

Users are requested to cite **Hauffe et al. 2026 (in submission)** when using CtQuant.

## License
This software is free for academic and non-commercial research use.
Commercial use requires a separate license agreement.
See the LICENSE file for details.

## Credits

**Author:** Dr. Robert Hauffe

## Features

### cDNA Synthesis Planning
- **Automated Calculations:** Determine RNA and H2O volumes for reverse transcription based on concentration inputs.
- **Dilution Logic:** Calculate post-synthesis dilution volumes to reach a target final cDNA concentration.
- **Flexible Input:** Supports `.csv`, `.xls`, and `.xlsx` files from various spectrophotometers (e.g., NanoDrop).
- **Pipetting Support:** Export pipetting schemes as PDF and Excel files.
- **Workflow Integration:** Transfer defined sample groups directly to the Plate Mapper.

### qPCR Analysis
- **Flexible Mapping:** Visual plate mapper for 96-well and 384-well formats with "Paint" and "Erase" tools.
- **Automated Calculations:** Technical replicate averaging, dCt, ddCt, and Fold Change.
- **Statistical Analysis:** Built-in Student's t-test and Welch's t-test.
- **Interactive Refinement:** Exclude biological replicates directly from results view.
- **Comprehensive Export:** Export summary and detailed biological/technical replicate data to multi-sheet Excel files.

## Workflow

### 1. cDNA Synthesis
1.  **Load Data:** Import RNA concentration data (CSV/Excel). The tool automatically detects "Sample Name" and "Concentration" columns.
2.  **Configure Parameters:**
    *   **Rxn Vol pre-RTase (µL):** Volume available for RNA + H2O before adding the master mix.
    *   **Total Synth Vol (µL):** Total volume of the cDNA synthesis reaction (e.g., 20 µL).
    *   **Final cDNA Conc (ng/µL):** Desired concentration of cDNA after dilution.
3.  **Review & Group:** The tool automatically maximizes RNA input (up to 1000 ng). Assign group names (e.g., "WT", "KO") for downstream analysis.
4.  **Export:** Generate a pipetting scheme (PDF) or detailed Excel report.
5.  **Transfer:** Click "Define Group Names" to transfer sample names to the Plate Mapper.

### 2. qPCR Analysis
1.  **Load Data:** Import raw Ct values from your qPCR instrument (Excel).
2.  **Map Plate:**
    *   **Samples:** Use the "Paint" tool to assign samples to wells. (Right-click to erase).
    *   **Targets:** Assign Gene of Interest (GOI) and Housekeeping (HK) genes.
3.  **Analyze:** Click "Calculate" to process data.
4.  **Refine:** Review results, exclude outliers if necessary, and re-calculate.
5.  **Export:** Save comprehensive results to Excel.

## Methodology (qPCR)

CtQuant processes raw Ct values through the following pipeline:

1.  **Technical Replicate Averaging:**
    -   Ct values for technical replicates (same Sample, Gene, and Group) are averaged.
    -   Standard Deviation (SD) is calculated; samples with SD > 0.5 are flagged in the detailed view.

2.  **Delta Ct ($\Delta Ct$) Calculation:**
    -   For each biological replicate:
        $$ \Delta Ct = Ct_{GOI} - Ct_{Housekeeping} $$
    -   Housekeeping (HK) gene values are matched to Genes of Interest (GOI) by Sample Name.

3.  **Delta Delta Ct ($\Delta\Delta Ct$) Calculation:**
    -   The average $\Delta Ct$ of the **Control Group** is calculated for each gene.
    -   For each biological replicate:
        $$ \Delta\Delta Ct = \Delta Ct_{Sample} - \text{Average }\Delta Ct_{ControlGroup} $$

4.  **Fold Change:**
    -   Relative quantification is calculated as:
        $$ \text{Fold Change} = 2^{-\Delta\Delta Ct} $$

5.  **Statistical Analysis:**
    -   Statistical tests are performed comparing the **Fold Change** values of the Treatment group vs. the Control group.
    -   **Student's t-test:** Assumes equal variance between groups.
    -   **Welch's t-test:** Does not assume equal variance (recommended for biological data).
    -   **Note:** Two-way ANOVA is currently a placeholder for future implementation; selecting it defaults to Welch's t-test.

## Building from Source

To build the standalone executable yourself, follow these steps:

### 1. Prerequisites
Ensure you have Python installed. Then, install the required dependencies:
```bash
pip install pandas numpy scipy PyQt6 pyinstaller openpyxl reportlab xlrd
```

### 2. Build the Executable
Run the following command in the project root directory:
```bash
pyinstaller --clean --noconfirm --onefile --windowed --name "CtQuant_v1.2.0" --icon="CtQuant_icon.ico" --add-data="CtQuant_icon.ico;." CtQuant.py
```
The executable will be available in the `dist/` folder.

## Verification

To verify the integrity of the distributed executable (`CtQuant_v1.2.0.exe`), you can compare its SHA256 checksum with the following value:

**SHA256 Checksum:**
`BF395D33A10AA94DDD80933AEDBEA34E44A935C92FB55ED3CAE7F58D1D148623`

You can verify this in PowerShell using:
```powershell
Get-FileHash -Path "CtQuant_v1.2.0.exe" -Algorithm SHA256
```

