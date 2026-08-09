"""
Configuration centralisée du projet.
"""
import os
from pathlib import Path

# --- Répertoires ---
base_dir = Path(__file__).parent

# --- Google Drive / OAuth ---
scopes = ["https://www.googleapis.com/auth/drive.file"]

drive_folder_id = os.environ.get("DRIVE_FOLDER_ID")
if not drive_folder_id:
    raise EnvironmentError("La variable d'environnement DRIVE_FOLDER_ID est requise.")

# --- Fichiers à récupérer : préfixe dans le nom -> nom local voulu ---
input_files = {
    "admin": "admin_ci.gpkg",
    "cadastre": "cadastre_minier_ci.gpkg",
}

# --- Système de coordonnées ---
crs = "EPSG:4326"

# --- Colonnes attendues dans le cadastre minier ---
applications_cols = [
    "code", "type", "typecode", "status", "parties", "dteapplied",
    "area", "commodities", "part", "layer", "date_update",
]

licenses_cols = [
    "code", "type", "typecode", "status", "parties",
    "dteapplied", "dteexpires", "dtegranted", "dterenewal",
    "area", "commodities", "part", "layer", "date_update",
]

# --- Colonnes attendues dans les couches administratives ---
admin_cols = ["name", "layer", "date_update"]

admin_name_source = {
    "zone_artisanale": [],
    "foret_classifiee": ["nom_forit"],
    "parc_national": ["nom"],
    "sub_prefectures": ["nom"],
    "departments": ["nom"],
    "region": ["nom_reg"],
}

# --- paramètres du logger ---
log_dir = base_dir / "logs"

max_log_file = 30
max_retries = 3
retry_delay_seconds = 5
