
# MajidGPKG – QGIS Plugin

!QGIS
!License: GPL v3

## 📌 Overview
MajidGPKG is a QGIS plugin that packages all project layers into a single GeoPackage (.gpkg) file and optionally saves the QGIS project inside the GeoPackage.

## ✨ Features
- Package all vector and raster layers into a single GeoPackage.
- Preserve non-packageable layers (e.g., WMS) in the project file.
- Optionally store the QGIS project inside the GeoPackage.
- Automatically update layer sources to point to the new GeoPackage.

## 📂 Installation
### From QGIS Plugin Manager
1. Open QGIS.
2. Go to **Plugins → Manage and Install Plugins**.
3. Search for **MajidGPKG**.
4. Click **Install Plugin**.

### Manual Installation
1. Download the latest release from GitHub Releases.
2. Extract the ZIP file.
3. Copy the folder into your QGIS plugins directory:
   - Windows: `C:\Users\<YourUser>\AppData\Roaming\QGIS\QGIS3\profiles\default\python\plugins`
   - Linux: `~/.local/share/QGIS/QGIS3/profiles/default/python/plugins`
4. Restart QGIS and enable the plugin.

## 🛠 Usage
1. Load your QGIS project with layers.
2. Go to **Plugins → MajidGPKG → Package Project to GeoPackage**.
3. Select output GeoPackage file path and project name.
4. Click **Package Project**.

## 📷 Screenshots
*(Add screenshots here)*

## ⚙ Requirements
- QGIS 3.10 or later
- Python 3.x

## 📜 License
Licensed under GNU GPL v3. See LICENSE.

## 🐛 Issues & Support
Report issues here: GitHub Issues
