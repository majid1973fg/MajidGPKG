
# SPDX-License-Identifier: GPL-3.0-or-later
# Mask Filter Plugin — deletes features outside a selected polygon (mask polygon)
# and removes features that do not contain 'MR' in the 'TYP' field.
# Copyright (C) 2026  Majid Hamed Hobi
# https://github.com/majid1973fg/mask-filter-plugin
# [file name]: majidgpkg.py
# -*- coding: utf-8 -*-
"""
/***************************************************************************
 MajidGPKG
                                 A QGIS plugin
 Package project layers into a single GeoPackage
                             -------------------
        begin                : 2025-09-18
        based on             : Project Packager by Tarot Osuji
        author               : Majid
 ***************************************************************************/

/***************************************************************************
 * *
 * This program is free software; you can redistribute it and/or modify  *
 * it under the terms of the GNU General Public License as published by  *
 * the Free Software Foundation; either version 2 of the License, or     *
 * (at your option) any later version.                                   *
 * *
 ***************************************************************************/
"""

import os
import uuid
import sqlite3
import re
import tempfile
import shutil
from contextlib import closing
from datetime import datetime

from osgeo import gdal
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QFileDialog, QCheckBox, QMessageBox, QAction, QProgressBar,
    QGroupBox, QTextEdit, QSplitter, QInputDialog, QApplication
)
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtCore import Qt, QThread, pyqtSignal
from qgis.core import (
    Qgis, QgsProject, QgsMapLayerType, QgsDataProvider, QgsProviderRegistry,
    QgsVectorFileWriter, QgsFields, QgsMessageLog, QgsApplication,
    QgsRasterFileWriter, QgsRasterPipe, QgsRasterProjector, QgsRasterBlockFeedback,
    QgsRenderContext, QgsVectorLayer, QgsRasterLayer, QgsMapLayer,
    QgsLayerTree, QgsReadWriteContext, QgsMapLayerStyle, QgsLayerTreeLayer,
    QgsMapSettings, QgsSymbol, QgsSingleSymbolRenderer, QgsCategorizedSymbolRenderer,
    QgsGraduatedSymbolRenderer, QgsLayerTreeGroup
)
from qgis.PyQt.QtXml import QDomDocument


class PackagingThread(QThread):
    """Thread for packaging operations to prevent UI freezing"""
    progress = pyqtSignal(int)
    message = pyqtSignal(str)
    finished_signal = pyqtSignal(bool, str)
    layer_updates_signal = pyqtSignal(list)
    
    def __init__(self, gpkg_path, store_project, project_name=None, parent=None):
        super().__init__(parent)
        self.gpkg_path = gpkg_path
        self.store_project = store_project
        self.project_name = project_name
        self.canceled = False
    
    def run(self):
        try:
            original_project = QgsProject.instance()
            tc = original_project.transformContext()
            reg = QgsProviderRegistry.instance()
            
            # Check if GeoPackage file exists and is writable
            if os.path.exists(self.gpkg_path) and not os.access(self.gpkg_path, os.W_OK):
                 self.finished_signal.emit(False, f"GeoPackage file is not writable: {self.gpkg_path}")
                 return
            
            layers = list(original_project.mapLayers().values())
            
            # Separate layers into packageable and non-packageable (WMS, etc.)
            packageable_layers = []
            non_packageable_layers = []
            
            for lyr in layers:
                if self.is_layer_packageable(lyr):
                    packageable_layers.append(lyr)
                else:
                    non_packageable_layers.append(lyr)
            
            total_packageable = len(packageable_layers)
            total_non_packageable = len(non_packageable_layers)
            
            if total_packageable == 0 and total_non_packageable == 0:
                self.finished_signal.emit(False, "No layers found in the project to package.")
                return
            
            # Log layer counts
            if total_non_packageable > 0:
                non_packageable_names = [lyr.name() for lyr in non_packageable_layers]
                self.message.emit(f"📋 Found {total_packageable} packageable layers and {total_non_packageable} non-packageable layers (WMS, etc.)")
                self.message.emit(f"⚠️ Non-packageable layers will be preserved in project: {', '.join(non_packageable_names[:3])}{'...' if len(non_packageable_names) > 3 else ''}")
            else:
                self.message.emit(f"Packaging {total_packageable} supported layers...")
            
            processed_layers = []
            failed_layers = []
            
            # First package only the packageable layers
            for i, lyr in enumerate(packageable_layers):
                if self.canceled:
                    self.message.emit("Packaging canceled")
                    self.finished_signal.emit(False, "Packaging canceled by user")
                    return

                layername = lyr.name()
                
                # Use a cleaned name for the GeoPackage table name
                gpkg_layer_name = self.clean_layer_name(layername) 

                if not is_layer_in_gpkg(self.gpkg_path, gpkg_layer_name):
                    self.message.emit(f"Processing layer {i+1}/{total_packageable}: {layername} (as table '{gpkg_layer_name}')")
                    
                    # Store layer using the cleaned name
                    err = write_layer(lyr, self.gpkg_path, tc, gpkg_layer_name)
                    
                    if err[0]:
                        error_msg = f"Error processing {layername}: {err[1]}"
                        self.message.emit(f"❌ {error_msg}")
                        failed_layers.append(layername)
                        continue
                    else:
                        self.message.emit(f"✅ Successfully packaged {layername}")
                        processed_layers.append({
                            'original_layer': lyr,
                            'gpkg_name': gpkg_layer_name,
                            'original_name': layername,
                            'is_packageable': True
                        })
                else:
                    self.message.emit(f"⚠️ Layer {layername} (table '{gpkg_layer_name}') already exists in GeoPackage")
                    processed_layers.append({
                        'original_layer': lyr,
                        'gpkg_name': gpkg_layer_name,
                        'original_name': layername,
                        'is_packageable': True
                    })
                
                progress = int((i + 1) / total_packageable * 80)  # 80% for packageable layers
                self.progress.emit(progress)

            # Add non-packageable layers to the processed list (they won't be stored in GPKG but will be in project)
            for lyr in non_packageable_layers:
                processed_layers.append({
                    'original_layer': lyr,
                    'gpkg_name': None,  # No GPKG table name
                    'original_name': lyr.name(),
                    'is_packageable': False
                })
                self.message.emit(f"📌 Preserving non-packageable layer in project: {lyr.name()}")

            # Save project inside GeoPackage (optional)
            project_name_used = None
            if self.store_project:
                self.progress.emit(85)
                self.message.emit("Saving project to GeoPackage...")
                
                project_saved, project_name_used = self.save_project_to_gpkg(
                    original_project, self.gpkg_path, processed_layers
                )
                
                if project_saved:
                    self.message.emit(f"✅ Project saved inside GeoPackage as: {project_name_used}")
                else:
                    self.message.emit("❌ Could not save project inside GeoPackage")
                self.progress.emit(95)
            
            # Prepare layer data source updates (only for packageable layers)
            self.message.emit("Preparing layer data source updates...")
            layer_updates = []
            
            for processed_info in processed_layers:
                # Only update data sources for packageable layers
                if not processed_info['is_packageable']:
                    continue
                    
                lyr = processed_info['original_layer']
                layer_name = processed_info['original_name']
                gpkg_layer_name = processed_info['gpkg_name']
                
                if lyr.isValid():
                    try:
                        # Correct provider URI based on layer type
                        if lyr.type() == QgsMapLayerType.VectorLayer:
                            data_source = f"{self.gpkg_path}|layername={gpkg_layer_name}"
                            provider = "ogr"
                        elif lyr.type() == QgsMapLayerType.RasterLayer:
                            data_source = f"GPKG:{self.gpkg_path}:{gpkg_layer_name}"
                            provider = "gdal"
                        else:
                            continue 
                        
                        # Collect update info
                        layer_updates.append({
                            'layer_id': lyr.id(),
                            'data_source': data_source,
                            'layer_name': layer_name,
                            'provider': provider,
                            'gpkg_layer_name': gpkg_layer_name,
                            'is_packageable': True
                        })
                    except Exception as e:
                        self.message.emit(f"⚠️ Could not prepare data source update for {layer_name}: {str(e)}")
            
            # Emit signal with layer updates (will be handled in main thread)
            self.layer_updates_signal.emit(layer_updates)
            
            # Build result message
            packageable_names = [p['original_name'] for p in processed_layers if p['is_packageable']]
            non_packageable_names = [p['original_name'] for p in processed_layers if not p['is_packageable']]
            
            result_message = self._build_result_message(
                packageable_names, 
                failed_layers, 
                non_packageable_names, 
                len(layer_updates), 
                project_name_used, 
                self.gpkg_path
            )

            self.progress.emit(100)
            self.finished_signal.emit(True, result_message)
            
        except Exception as e:
            self.finished_signal.emit(False, f"Unexpected error: {str(e)}")
    
    def is_layer_packageable(self, layer):
        """
        Check if a layer can be packaged into GeoPackage.
        WMS layers (like OpenStreetMap) return False - they can't be stored in GPKG
        but will be preserved in the project file.
        """
        try:
            if not layer or not layer.isValid():
                return False
            
            # Check for unsupported providers (WMS, WFS, etc.)
            provider = layer.dataProvider().name().lower() if layer.dataProvider() else ''
            unsupported_providers = [
                'wms', 'wfs', 'wcs', 'wmts', 'arcgismapserver', 
                'arcgisfeatureserver', 'vectortile', 'mesh', 'pointcloud'
            ]
            
            if any(unsupported in provider for unsupported in unsupported_providers):
                return False  # These layers can't be stored in GPKG but will be in project
            
            if layer.type() == QgsMapLayerType.VectorLayer:
                return True  # Vector layers can be packaged
            
            if layer.type() == QgsMapLayerType.RasterLayer:
                dp = layer.dataProvider()
                # Check if it's a file-based raster that can be packaged
                if provider in ['gdal', 'ogr']:
                    return dp and dp.xSize() > 0 and dp.ySize() > 0
                return False
            
            return False
        except Exception:
            return False
    
    def save_project_to_gpkg(self, original_project, gpkg_path, processed_layers_info):
        """
        Save project inside GeoPackage using QGIS native GPKG project storage
        This includes ALL layers (both packageable and non-packageable)
        """
        try:
            # 1. Determine project name
            project_name = self.project_name or original_project.baseName() or "qgis_project"
            project_name_cleaned = self.clean_project_name(project_name)
            
            self.message.emit(f"Saving project as: {project_name_cleaned}")
            
            # 2. Create a completely new temporary project
            temp_project = QgsProject()
            
            # 3. Copy essential project settings
            temp_project.setCrs(original_project.crs())
            temp_project.setTitle(original_project.title())
            temp_project.setMetadata(original_project.metadata())
            
            # 4. Add ALL layers to temporary project (both packageable and non-packageable)
            layer_id_map = {}
            
            for processed_info in processed_layers_info:
                original_lyr = processed_info['original_layer']
                original_name = processed_info['original_name']
                gpkg_layer_name = processed_info['gpkg_name']
                is_packageable = processed_info['is_packageable']
                
                if is_packageable:
                    # For packageable layers: create new layer with GPKG source
                    if original_lyr.type() == QgsMapLayerType.VectorLayer:
                        data_source = f"{gpkg_path}|layername={gpkg_layer_name}"
                        new_lyr = QgsVectorLayer(data_source, original_name, "ogr")
                    elif original_lyr.type() == QgsMapLayerType.RasterLayer:
                        data_source = f"GPKG:{gpkg_path}:{gpkg_layer_name}"
                        new_lyr = QgsRasterLayer(data_source, original_name, "gdal")
                    else:
                        continue
                    
                    if new_lyr and new_lyr.isValid():
                        # Copy layer style using QgsMapLayerStyle
                        style = QgsMapLayerStyle()
                        style.readFromLayer(original_lyr)
                        style.writeToLayer(new_lyr)
                        
                        # Add to temporary project
                        temp_project.addMapLayer(new_lyr, False)
                        layer_id_map[original_lyr.id()] = new_lyr.id()
                        self.message.emit(f"✅ Added GPKG layer: {original_name}")
                    else:
                        self.message.emit(f"⚠️ Failed to create GPKG layer: {original_name}")
                else:
                    # For non-packageable layers (WMS, etc.): clone the original layer
                    try:
                        # Clone the layer to preserve its original source and properties
                        if original_lyr.type() == QgsMapLayerType.VectorLayer:
                            new_lyr = QgsVectorLayer(original_lyr.source(), original_name, original_lyr.providerType())
                        elif original_lyr.type() == QgsMapLayerType.RasterLayer:
                            new_lyr = QgsRasterLayer(original_lyr.source(), original_name, original_lyr.providerType())
                        else:
                            continue
                        
                        if new_lyr and new_lyr.isValid():
                            # Copy layer style
                            style = QgsMapLayerStyle()
                            style.readFromLayer(original_lyr)
                            style.writeToLayer(new_lyr)
                            
                            # Add to temporary project
                            temp_project.addMapLayer(new_lyr, False)
                            layer_id_map[original_lyr.id()] = new_lyr.id()
                            self.message.emit(f"📌 Preserved non-packageable layer: {original_name}")
                        else:
                            self.message.emit(f"⚠️ Failed to preserve non-packageable layer: {original_name}")
                    except Exception as e:
                        self.message.emit(f"⚠️ Error preserving non-packageable layer {original_name}: {str(e)}")
            
            # 5. Copy layer tree structure for ALL layers
            self._copy_layer_tree(original_project, temp_project, layer_id_map)
            
            # 6. Use the native QgsProject storage mechanism for GPKG
            self.message.emit("Writing project to GeoPackage using native storage...")
            
            # Create the project storage URI for GeoPackage
            storage_uri = f"geopackage:{gpkg_path}?projectName={project_name_cleaned}"
            
            # Save using the storage mechanism
            save_success = temp_project.write(storage_uri)
            
            if save_success:
                self.message.emit(f"✅ Project successfully saved to GeoPackage")
                # Also manually register in qgis_projects table for compatibility
                self._register_project_in_gpkg(temp_project, gpkg_path, project_name_cleaned)
                return True, project_name_cleaned
            else:
                self.message.emit("❌ Native GeoPackage storage failed, trying alternative method...")
                # Fallback: Use direct SQLite approach
                return self._save_project_direct_sqlite(temp_project, gpkg_path, project_name_cleaned)
            
        except Exception as e:
            self.message.emit(f"❌ Project saving error: {str(e)}")
            return False, None

    def _save_project_direct_sqlite(self, project, gpkg_path, project_name):
        """Alternative method: Save project directly to SQLite database"""
        try:
            self.message.emit("Using direct SQLite method to save project...")
            
            # Create project XML
            doc = QDomDocument("qgis")
            context = QgsReadWriteContext()
            project.write(doc, context)
            project_xml = doc.toString()
            
            # Connect to GPKG and save project
            with closing(sqlite3.connect(gpkg_path)) as conn:
                cursor = conn.cursor()
                
                # Create qgis_projects table if it doesn't exist
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS qgis_projects (
                        name TEXT PRIMARY KEY,
                        metadata TEXT,
                        content BLOB
                    )
                """)
                
                # Check if project already exists
                cursor.execute("SELECT name FROM qgis_projects WHERE name = ?", (project_name,))
                existing = cursor.fetchone()
                
                if existing:
                    # Update existing project
                    cursor.execute("""
                        UPDATE qgis_projects 
                        SET metadata = ?, content = ? 
                        WHERE name = ?
                    """, (f"QGIS Project: {project_name}", project_xml, project_name))
                else:
                    # Insert new project
                    cursor.execute("""
                        INSERT INTO qgis_projects (name, metadata, content)
                        VALUES (?, ?, ?)
                    """, (project_name, f"QGIS Project: {project_name}", project_xml))
                
                conn.commit()
                
                # Verify the project was saved
                cursor.execute("SELECT name FROM qgis_projects WHERE name = ?", (project_name,))
                saved = cursor.fetchone()
                
                if saved:
                    self.message.emit(f"✅ Project successfully saved via direct SQLite method: {project_name}")
                    return True, project_name
                else:
                    self.message.emit("❌ Project verification failed")
                    return False, None
                
        except Exception as e:
            self.message.emit(f"❌ Direct SQLite method failed: {str(e)}")
            return False, None

    def _copy_layer_tree(self, source_project, dest_project, layer_id_map):
        """Copy layer tree structure with proper layer ID mapping for ALL layers"""
        try:
            source_root = source_project.layerTreeRoot()
            dest_root = dest_project.layerTreeRoot()
            
            # Clear destination tree
            dest_root.removeAllChildren()
            
            # Function to recursively copy tree structure
            def copy_tree_node(source_node, dest_parent):
                for child in source_node.children():
                    if QgsLayerTree.isLayer(child):
                        # Layer node
                        original_layer_id = child.layerId()
                        if original_layer_id in layer_id_map:
                            new_layer_id = layer_id_map[original_layer_id]
                            new_layer = dest_project.mapLayer(new_layer_id)
                            if new_layer:
                                new_layer_node = QgsLayerTreeLayer(new_layer)
                                new_layer_node.setName(child.name())
                                new_layer_node.setItemVisibilityChecked(child.isVisible())
                                new_layer_node.setExpanded(child.isExpanded())
                                dest_parent.addChildNode(new_layer_node)
                    else:
                        # Group node
                        new_group = QgsLayerTreeGroup(child.name())
                        new_group.setExpanded(child.isExpanded())
                        new_group.setItemVisibilityChecked(child.isVisible())
                        dest_parent.addChildNode(new_group)
                        copy_tree_node(child, new_group)
            
            copy_tree_node(source_root, dest_root)
            
        except Exception as e:
            self.message.emit(f"⚠️ Error copying layer tree: {str(e)}")

    def _register_project_in_gpkg(self, project, gpkg_path, project_name):
        """Ensure project is properly registered in GeoPackage qgis_projects table"""
        try:
            # Create project XML
            doc = QDomDocument("qgis")
            context = QgsReadWriteContext()
            project.write(doc, context)
            project_xml = doc.toString()
            
            # Connect to GPKG and register project
            with closing(sqlite3.connect(gpkg_path)) as conn:
                cursor = conn.cursor()
                
                # Create qgis_projects table if it doesn't exist
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS qgis_projects (
                        name TEXT PRIMARY KEY,
                        metadata TEXT,
                        content BLOB
                    )
                """)
                
                # Add project to table
                cursor.execute("""
                    INSERT OR REPLACE INTO qgis_projects (name, metadata, content)
                    VALUES (?, ?, ?)
                """, (project_name, f"QGIS Project: {project_name}", project_xml))
                
                conn.commit()
                self.message.emit(f"✅ Project registered in qgis_projects table: {project_name}")
                return True
                
        except Exception as e:
            self.message.emit(f"⚠️ Could not register project in qgis_projects table: {str(e)}")
            return False
    
    def clean_project_name(self, name):
        """Clean project name for GPKG compatibility"""
        cleaned = re.sub(r'[^\w\s-]', '', name)
        cleaned = cleaned.strip()
        cleaned = cleaned.replace(' ', '_')
        cleaned = re.sub(r'_+', '_', cleaned)
        if not cleaned:
            cleaned = "qgis_project"
        if len(cleaned) > 100:
            cleaned = cleaned[:100]
        return cleaned

    def clean_layer_name(self, name):
        """Clean layer name for GPKG compatibility"""
        # More robust cleaning for SQL table names
        cleaned = re.sub(r'[^a-zA-Z0-9_]', '_', name)
        cleaned = re.sub(r'_+', '_', cleaned)
        cleaned = cleaned.strip('_')
        
        # Ensure name starts with letter or underscore
        if cleaned and not cleaned[0].isalpha() and cleaned[0] != '_':
            cleaned = '_' + cleaned
            
        # Ensure reasonable length
        if len(cleaned) > 50:
            cleaned = cleaned[:50]
            
        # Ensure name is not empty
        if not cleaned:
            cleaned = 'layer_' + uuid.uuid4().hex[:8]
            
        return cleaned

    def _build_result_message(self, processed, failed, non_packageable, updates_prepared, project_name, gpkg_path):
        """Construct the final result message."""
        result_message = f"Packaging completed!\n"
        result_message += f"📊 Summary:\n"
        result_message += f"✅ Successfully packaged: {len(processed)} layers\n"
        result_message += f"✅ Layer updates prepared: {updates_prepared} layers\n"
        
        if failed:
            result_message += f"❌ Failed: {len(failed)} layers\n"
            result_message += f"Failed layers: {', '.join(failed[:3])}{'...' if len(failed) > 3 else ''}\n"
        
        if non_packageable:
            result_message += f"📌 Preserved in project (not in GPKG): {len(non_packageable)} layers\n"
            result_message += f"Preserved: {', '.join(non_packageable[:3])}{'...' if len(non_packageable) > 3 else ''}\n"

        if project_name:
            result_message += f"\n📁 Project saved successfully!\n"
            result_message += f"To load this project later:\n"
            result_message += f"1. Go to 'Project' → 'Open From' → 'GeoPackage'\n"
            result_message += f"2. Select: {os.path.basename(gpkg_path)}\n"
            result_message += f"3. Choose project: {project_name}"
        else:
            result_message += f"\n📁 Project saved to: {gpkg_path}"
        
        result_message += f"\n\n💡 Packageable layers now reference the GeoPackage file"
        if non_packageable:
            result_message += f"\n📌 Non-packageable layers (WMS, etc.) preserved with original sources"
        
        return result_message
    
    def cancel(self):
        self.canceled = True


class PackDialog(QDialog):
    """Improved Dialog for MajidGPKG"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Package Project to GeoPackage - MajidGPKG")
        self.setMinimumWidth(600)
        self.setMinimumHeight(500)
        
        # Set window icon
        icon_path = os.path.join(os.path.dirname(__file__), 'resources', 'icon.png')
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        
        # Thread for packaging
        self.thread = None
        
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()
        
        # Main splitter for better layout
        splitter = QSplitter(Qt.Vertical)
        
        # Top section - Configuration
        config_group = QGroupBox("Package Configuration")
        config_layout = QVBoxLayout()
        
        # Output file selection
        file_layout = QHBoxLayout()
        file_layout.addWidget(QLabel("Output GeoPackage:"))
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("Select output GeoPackage file...")
        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self.browse_file)
        file_layout.addWidget(self.path_edit, 1)
        file_layout.addWidget(browse_btn)
        config_layout.addLayout(file_layout)
        
        # Project name for GPKG storage
        project_name_layout = QHBoxLayout()
        project_name_layout.addWidget(QLabel("Project Name (for GPKG storage):"))
        self.project_name_edit = QLineEdit()
        self.project_name_edit.setPlaceholderText("Enter project name for GPKG storage...")
        project_name_layout.addWidget(self.project_name_edit, 1)
        config_layout.addLayout(project_name_layout)
        
        # Options
        self.chk_store_proj = QCheckBox("Store project inside GeoPackage")
        self.chk_store_proj.setChecked(True)
        self.chk_store_proj.setToolTip("Save the QGIS project file inside the GeoPackage")
        self.chk_store_proj.toggled.connect(self.on_store_project_toggled)
        config_layout.addWidget(self.chk_store_proj)
        
        # Important note
        note_label = QLabel("💡 The project will be saved inside the GeoPackage and can be loaded via 'Project → Open From → GeoPackage'")
        note_label.setWordWrap(True)
        note_label.setStyleSheet("color: green; font-style: italic; background-color: #f0f8ff; padding: 5px;")
        config_layout.addWidget(note_label)
        
        # Warning label
        warning_label = QLabel("Note: Web services (WMS, WFS, etc.) cannot be packaged into GeoPackage but will be preserved in the project file.")
        warning_label.setWordWrap(True)
        warning_label.setStyleSheet("color: orange; font-style: italic;")
        config_layout.addWidget(warning_label)
        
        config_group.setLayout(config_layout)
        splitter.addWidget(config_group)
        
        # Bottom section - Progress and logs
        progress_group = QGroupBox("Progress")
        progress_layout = QVBoxLayout()
        
        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        progress_layout.addWidget(self.progress_bar)
        
        # Status messages
        self.status_label = QLabel("Ready to package project...")
        progress_layout.addWidget(self.status_label)
        
        # Log area
        self.log_area = QTextEdit()
        self.log_area.setMaximumHeight(150)
        self.log_area.setReadOnly(True)
        progress_layout.addWidget(QLabel("Log:"))
        progress_layout.addWidget(self.log_area)
        
        progress_group.setLayout(progress_layout)
        splitter.addWidget(progress_group)
        
        # Set splitter sizes (2/3 for config, 1/3 for progress)
        splitter.setSizes([300, 200])
        
        layout.addWidget(splitter)
        
        # Buttons
        btn_layout = QHBoxLayout()
        self.package_btn = QPushButton("Package Project")
        self.package_btn.clicked.connect(self.start_packaging)
        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.clicked.connect(self.reject)
        self.cancel_btn.setEnabled(False)
        self.close_btn = QPushButton("Close")
        self.close_btn.clicked.connect(self.accept)
        
        btn_layout.addWidget(self.package_btn)
        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addWidget(self.close_btn)
        layout.addLayout(btn_layout)

        self.setLayout(layout)
        
        # Set default filename and project name
        self.set_default_names()
        
        # Update UI based on initial state
        self.on_store_project_toggled(self.chk_store_proj.isChecked())

    def generate_gpkg_filename(self, base_name):
        """Generate GPKG filename in format 'GPKG-ORIGINALNAME'"""
        if base_name.upper().startswith('GPKG-'):
            base_name = base_name[5:]
        if base_name.upper().startswith('QGIS_'):
            base_name = base_name[5:]
            
        cleaned_name = re.sub(r'[^\w\-_.]', '_', base_name)
        cleaned_name = re.sub(r'_+', '_', cleaned_name)
        cleaned_name = cleaned_name.strip('_')
        
        gpkg_name = f"GPKG-{cleaned_name}"
        return gpkg_name

    def generate_project_name(self, base_name):
        """Generate project name for GPKG storage"""
        if base_name.upper().startswith('GPKG-'):
            base_name = base_name[5:]
        if base_name.upper().startswith('QGIS_'):
            base_name = base_name[5:]
            
        cleaned_name = re.sub(r'[^\w]', '_', base_name)
        cleaned_name = re.sub(r'_+', '_', cleaned_name)
        cleaned_name = cleaned_name.strip('_')
        
        return cleaned_name

    def set_default_names(self):
        """Set default filename and project name based on project"""
        project = QgsProject.instance()
        project_file = project.fileName()
        
        if project_file:
            original_name = os.path.splitext(os.path.basename(project_file))[0]
            gpkg_filename = self.generate_gpkg_filename(original_name)
            default_path = os.path.join(os.path.dirname(project_file), f"{gpkg_filename}.gpkg")
            project_name = self.generate_project_name(original_name)
            self.project_name_edit.setText(project_name)
        else:
            original_name = "project"
            gpkg_filename = self.generate_gpkg_filename(original_name)
            default_path = os.path.join(os.path.expanduser("~"), f"{gpkg_filename}.gpkg")
            self.project_name_edit.setText(self.generate_project_name(original_name))
        
        self.path_edit.setText(default_path)

    def on_store_project_toggled(self, checked):
        """Enable/disable project name field based on checkbox"""
        self.project_name_edit.setEnabled(checked)

    def browse_file(self):
        current_path = self.path_edit.text()
        if current_path:
            directory = os.path.dirname(current_path)
            suggested_filename = os.path.basename(current_path)
        else:
            directory = os.path.expanduser("~")
            suggested_filename = "GPKG-project.gpkg"
        
        fn, _ = QFileDialog.getSaveFileName(
            self, "Save as GeoPackage",
            os.path.join(directory, suggested_filename),
            "GeoPackage (*.gpkg)"
        )
        if fn:
            if not fn.lower().endswith(".gpkg"):
                fn += ".gpkg"
            self.path_edit.setText(fn)
            
            if not self.project_name_edit.isModified():
                base_name = os.path.splitext(os.path.basename(fn))[0]
                if base_name.upper().startswith("GPKG-"):
                    original_name = base_name[5:]
                else:
                    original_name = base_name
                
                project_name = self.generate_project_name(original_name)
                self.project_name_edit.setText(project_name)

    def log_message(self, message):
        """Add message to log area"""
        self.log_area.append(f"• {message}")
        cursor = self.log_area.textCursor()
        cursor.movePosition(cursor.End)
        self.log_area.setTextCursor(cursor)
        QgsApplication.processEvents()

    def start_packaging(self):
        """Start the packaging process"""
        gpkg_path = self.path_edit.text().strip()
        if not gpkg_path:
            QMessageBox.warning(self, "Missing File", "Please select an output GeoPackage file.")
            return
        
        project_name = None
        if self.chk_store_proj.isChecked():
            project_name = self.project_name_edit.text().strip()
            if not project_name:
                QMessageBox.warning(self, "Missing Project Name", 
                                  "Please enter a project name for GPKG storage.")
                return
            
        output_dir = os.path.dirname(gpkg_path)
        if not os.path.exists(output_dir):
            try:
                os.makedirs(output_dir)
            except OSError as e:
                QMessageBox.critical(self, "Error", f"Cannot create directory: {str(e)}")
                return

        # Disable UI during packaging
        self.package_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)
        self.close_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        
        # Clear log
        self.log_area.clear()
        self.log_message("Starting packaging process...")
        
        # Count layers
        project = QgsProject.instance()
        layers = list(project.mapLayers().values())
        
        supported_count = 0
        unsupported_count = 0
        
        for lyr in layers:
            provider = lyr.dataProvider().name().lower() if lyr.dataProvider() else 'unknown'
            if any(unsupported in provider for unsupported in ['wms', 'wfs', 'wcs', 'wmts', 'arcgismapserver']):
                unsupported_count += 1
            else:
                supported_count += 1
        
        self.log_message(f"Found {len(layers)} total layers")
        self.log_message(f"✅ Packageable layers: {supported_count}")
        self.log_message(f"📌 Non-packageable layers (WMS, etc.): {unsupported_count}")
        
        if supported_count == 0 and unsupported_count == 0:
            QMessageBox.warning(self, "No Layers", 
                              "No layers found in the current project.")
            self.package_btn.setEnabled(True)
            self.cancel_btn.setEnabled(False)
            self.close_btn.setEnabled(True)
            self.progress_bar.setVisible(False)
            return
        
        # Start packaging thread
        self.thread = PackagingThread(gpkg_path, self.chk_store_proj.isChecked(), project_name)
        self.thread.progress.connect(self.progress_bar.setValue)
        self.thread.message.connect(self.log_message)
        self.thread.finished_signal.connect(self.packaging_finished)
        self.thread.layer_updates_signal.connect(self.update_layer_sources)
        self.thread.start()

    def update_layer_sources(self, layer_updates):
        """Update layer data sources in main thread (thread-safe)"""
        self.log_message("Updating layer data sources...")
        updated_count = 0
        failed_count = 0
        
        # First, test all data sources to ensure they're valid
        valid_updates = []
        for update_info in layer_updates:
            layer_id = update_info['layer_id']
            data_source = update_info['data_source']
            layer_name = update_info['layer_name']
            provider = update_info['provider']
            
            try:
                # Test the data source first
                test_layer = None
                if provider == "ogr":
                    test_layer = QgsVectorLayer(data_source, "test_layer", provider)
                elif provider == "gdal":
                    test_layer = QgsRasterLayer(data_source, "test_layer", provider)
                
                if test_layer and test_layer.isValid():
                    valid_updates.append(update_info)
                    self.log_message(f"✅ Data source valid: {layer_name}")
                else:
                    self.log_message(f"⚠️ Invalid data source for: {layer_name}")
                    failed_count += 1
                    
                if test_layer:
                    del test_layer
                    
            except Exception as e:
                self.log_message(f"❌ Error testing data source for {layer_name}: {str(e)}")
                failed_count += 1
        
        # Now update the actual layers
        for update_info in valid_updates:
            layer_id = update_info['layer_id']
            data_source = update_info['data_source']
            layer_name = update_info['layer_name']
            provider = update_info['provider']
            
            try:
                # Get layer from project
                layer = QgsProject.instance().mapLayer(layer_id)
                if not layer:
                    self.log_message(f"⚠️ Layer not found: {layer_name}")
                    failed_count += 1
                    continue
                
                # Update the layer's data source
                layer.setDataSource(data_source, layer_name, provider, QgsDataProvider.ProviderOptions())
                
                if layer.isValid():
                    self.log_message(f"✅ Updated: {layer_name}")
                    updated_count += 1
                else:
                    self.log_message(f"⚠️ Layer became invalid after update: {layer_name}")
                    failed_count += 1
                        
            except Exception as e:
                self.log_message(f"❌ Error updating {layer_name}: {str(e)}")
                failed_count += 1
        
        self.log_message(f"✅ Successfully updated {updated_count} layers")
        if failed_count > 0:
            self.log_message(f"⚠️ Failed to update {failed_count} layers")

    def packaging_finished(self, success, message):
        """Handle packaging completion"""
        self.progress_bar.setValue(100 if success else 0)
        
        # Re-enable UI
        self.package_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.close_btn.setEnabled(True)
        
        if success:
            self.log_message("✅ Packaging completed successfully!")
            QMessageBox.information(self, "Success", message)
        else:
            self.log_message(f"❌ Packaging failed: {message}")
            QMessageBox.critical(self, "Error", message)

    def reject(self):
        """Handle cancel button"""
        if self.thread and self.thread.isRunning():
            self.thread.cancel()
            self.thread.wait(2000)
        super().reject()


class MajidGpkg:
    def __init__(self, iface):
        self.iface = iface
        self.plugin_menu = "&MajidGPKG"
        self.actions = []

    def initGui(self):
        # Get the icon path
        icon_path = os.path.join(os.path.dirname(__file__), 'resources', 'icon.png')
        
        # Main action - Package project to GeoPackage
        action_package = QAction(QIcon(icon_path), "Package project to GeoPackage", self.iface.mainWindow())
        action_package.triggered.connect(self.run_package)
        action_package.setToolTip("Package all project layers into a single GeoPackage file")
        self.iface.addPluginToMenu(self.plugin_menu, action_package)
        self.iface.addToolBarIcon(action_package)
        self.actions.append(action_package)

    def unload(self):
        for action in self.actions:
            self.iface.removePluginMenu(self.plugin_menu, action)
            self.iface.removeToolBarIcon(action)

    def run_package(self):
        """Main function to run the plugin - package layers and project"""
        project = QgsProject.instance()
        layers = project.mapLayers()
        if not layers:
            QMessageBox.information(self.iface.mainWindow(), "No Layers", 
                                  "There are no layers in the current project to package.")
            return
        
        dlg = PackDialog(self.iface.mainWindow())
        dlg.exec_()


# Helper functions
def is_layer_in_gpkg(filename, layerName):
    """Check if layer already exists in GeoPackage"""
    try:
        ds = gdal.OpenEx(filename)
        if ds is None:
            return False
        res = bool(ds.GetLayerByName(layerName) or ds.GetLayerByName(layerName.upper()))
    except (AttributeError, RuntimeError):
        res = False
    finally:
        if 'ds' in locals() and ds:
            del ds
    return res


def write_layer(layer, filename, tc, layerName):
    """Write layer to GeoPackage"""
    err = (False, '') 
    
    if layer.type() == QgsMapLayerType.VectorLayer:
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.layerName = layerName
        options.attributes = [idx for idx in layer.attributeList()
                              if layer.fields().fieldOrigin(idx) == QgsFields.OriginProvider]
        if os.path.exists(filename):
            options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer
        
        if Qgis.QGIS_VERSION_INT >= 32000:
            write = QgsVectorFileWriter.writeAsVectorFormatV3
        else:
            write = QgsVectorFileWriter.writeAsVectorFormatV2
            
        err = write(layer, filename, tc, options)

    elif layer.type() == QgsMapLayerType.RasterLayer:
        tmp_name = uuid.uuid4().hex
        dp = layer.dataProvider()
        
        if dp.extent().isEmpty():
            return (True, "Raster layer has an empty extent/no data.")
            
        projector = QgsRasterProjector()
        projector.setCrs(dp.crs(), dp.crs(), tc)
        pipe = QgsRasterPipe()
        pipe.set(dp.clone())
        pipe.insert(2, projector)
        writer = QgsRasterFileWriter(filename)
        writer.setOutputFormat('GPKG')
        writer.setCreateOptions([
            f'RASTER_TABLE={tmp_name}', 'APPEND_SUBDATASET=YES'])
        feedback = QgsRasterBlockFeedback()
        err_code = writer.writeRaster(
            pipe,
            dp.xSize(),
            dp.ySize(),
            dp.extent(),
            dp.crs(),
            tc,
            feedback)
        
        if not err_code:
            rename_raster_layer(filename, tmp_name, layerName)
        
        err = (bool(err_code), feedback.errors())

    return err


def rename_raster_layer(filename, old_name, new_name):
    """Rename raster layer in GeoPackage SQLite database"""
    with closing(sqlite3.connect(filename, isolation_level=None)) as conn:
        cursor = conn.cursor()
        
        sql_rename_table = f'ALTER TABLE "{old_name}" RENAME TO "{new_name}"'
        cursor.execute(sql_rename_table)
        
        sql_update_contents = f'''
            UPDATE gpkg_contents SET 
                table_name = "{new_name}",
                identifier = "{new_name}"
            WHERE table_name = "{old_name}"
        '''
        cursor.execute(sql_update_contents)
        
        sql_update_tile_matrix_set = f'''
            UPDATE gpkg_tile_matrix_set SET table_name = "{new_name}"
            WHERE table_name = "{old_name}"
        '''
        cursor.execute(sql_update_tile_matrix_set)
        
        sql_update_tile_matrix = f'''
            UPDATE gpkg_tile_matrix SET table_name = "{new_name}"
            WHERE table_name = "{old_name}"
        '''
        cursor.execute(sql_update_tile_matrix)
        
        sql_update_extensions = f'''
            UPDATE gpkg_extensions SET table_name = "{new_name}"
            WHERE table_name = "{old_name}"
        '''
        cursor.execute(sql_update_extensions)
        
        conn.commit()