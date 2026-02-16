# CtQuant - qPCR Analysis Tool

CtQuant is a powerful and intuitive tool for analyzing qPCR data using the ddCt (2^-ddCt) quantification method. It simplifies technical replicate averaging, dCt/ddCt calculations, and statistical comparisons.

## Version 1.0.0

## Citation

Users are requested to cite **Hauffe et al. 2026 (in submission)** when using CtQuant.

## License
This software is free for academic and non-commercial research use.
Commercial use requires a separate license agreement.
See the LICENSE file for details.

## Credits

**Author:** Dr. Robert Hauffe

## Features
- **Flexible Mapping:** Visual plate mapper for 96-well and 384-well formats.
- **Automated Calculations:** Technical replicate averaging, dCt, ddCt, and Fold Change.
- **Statistical Analysis:** Built-in Student's t-test and Welch's t-test.
- **Interactive Refinement:** Exclude biological replicates directly from results view.
- **Comprehensive Export:** Export summary and detailed biological/technical replicate data to multi-sheet Excel files.

## Methodology

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
pip install pandas numpy scipy PyQt6 pyinstaller
```

### 2. Build the Executable
Run the following command in the project root directory:
```bash
pyinstaller --noconfirm --onefile --windowed --icon="CtQuant_icon.ico" --add-data "CtQuant_icon.ico;." --name "CtQuant" "CtQuant.py"
```
The executable will be available in the `dist/` folder.

## Executable Verification (v1.0.0)
You can verify the integrity of the provided `CtQuant.exe` using the SHA-256 checksum:

**SHA-256 Checksum:**
`0D61E37A1171E9DD032FD39B87384C4ADCC8B9BB901DA9287A406C67CCB1AE42`

To check this on Windows:
```powershell
Get-FileHash dist/CtQuant.exe -Algorithm SHA256
```
