
# MajidGPKG – QGIS Plugin

![QGIS](https://img.shields.io://img.shields.io/badge/License-GPLv3-blue.svg)
!Status

## 📌 Overview
**MajidGPKG** is a QGIS plugin that packages all project layers into a single **GeoPackage (.gpkg)** file and optionally saves the QGIS project inside the GeoPackage.  
This is useful for:
- Sharing projects with all data in one file.
-tegrity and easy backup.

---

## ✨ Features
- Package **all vector and raster layers** into a single GeoPackage.
- Preserve non-packageable layers (e.g., WMS) in the project file.
- Optionally **store the QGIS project inside the GeoPackage**.
- Automatically update layer sources to point to the new GeoPackage.
- User-friendly interface with progress tracking.

---

## 📂 Installation

### **From QGIS Plugin Manager**
1. Open QGIS.
2. Go to **Plugins → Manage and Install Plugins**.
3. Search for **MajidGPKG**.
4. Click **Install Plugin**.

### **Manual Installation**
1. Download the latest release from GitHub Releases.
2. Extract the ZIP file.
3. Copy the folder into your QGIS plugins directory:
   - **Windows:** `C:\Users\<YourUser>\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins`
   - **Linux:** `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins`
4. Restart QGIS and enable the plugin in **Plugins → Manage and Install Plugins**.

---

## 🛠 Usage
1. Load your QGIS project with layers.
2. Go to **Plugins → MajidGPKG → Package Project to GeoPackage**.
3. Select:
   - Output GeoPackage file path.
   - Project name for storage inside GeoPackage.
4. Click **Package Project**.
5. Wait for the process to complete.  
   ✅ All layers will be packaged, and the project will be saved inside the GeoPackage (if selected).

---

## 📷 Screenshots
*(Add screenshots of the plugin UI here)*

---

## ⚙ Requirements
- QGIS **3.10 or later**
- Python **3.x**
- GDAL and SQLite support (included in QGIS)

---

## 📜 License
This plugin is licensed under the **GNU GPL v3**.  
See the [LICENSE](LICENSE) file for details.

---

## 🐛 Issues & Support
- Report issues or request features here:  
  GitHub Issues

---

## ✅ Changelog
**v0.2**
- Initial release.
- Added support for packaging vector and raster layers.
- Option to store QGIS project inside GeoPackage.

---

### ⭐ If you find this plugin useful, please star the repository!
