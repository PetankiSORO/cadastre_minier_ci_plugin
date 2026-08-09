"""
Utilitaires de traitement des GeoPackages (admin + cadastre minier).
Logique métier : lecture, normalisation, extraction et sauvegarde des couches.
"""
import re
import unicodedata
from io import BytesIO
from pathlib import Path
import warnings

import pyogrio
import pandas as pd
import geopandas as gpd

import src.config as cfg
from src.logger import logger

warnings.filterwarnings("ignore",
    message=".*non conformant file extension.*", category=RuntimeWarning)

# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

def normalize_name(name: str) -> str:
    """
    Transforme un nom en nom PostgreSQL comparable (sans accents ni caractères spéciaux).
    Exemple : "Routes_Abidjan_Éco !" -> "routes_abidjan_eco"
    """
    name = unicodedata.normalize('NFD', name)
    name = "".join(c for c in name if unicodedata.category(c) != 'Mn')

    name = re.sub(r"[^a-zA-Z0-9_]", "_", name)
    name = re.sub(r"_+", "_", name)

    return name.lower().strip("_")


# ---------------------------------------------------------------------------
# Lecture
# ---------------------------------------------------------------------------

def read_geopackage(*files: bytes, crs: str = cfg.crs) -> dict[str, gpd.GeoDataFrame]:
    """
    Lit toutes les couches d'un ou plusieurs GeoPackages (en mémoire), les
    convertit dans le CRS demandé, et normalise les noms de couches/colonnes.

    Returns:
        dict {nom_couche_normalise: GeoDataFrame}
    """
    layers = {}
    for file in files:
        buffer = BytesIO(file)
        raw_layers = pyogrio.list_layers(buffer)
        logger.debug(f"{len(raw_layers)} couche(s) détectée(s) dans le fichier source.")

        for layer_info in raw_layers:
            buffer.seek(0)
            gdf = gpd.read_file(buffer, layer=layer_info[0], engine="pyogrio")

            if gdf.crs is None:
                logger.warning(f"'{layer_info[0]}' n'a pas de CRS défini.")
            else:
                gdf = gdf.to_crs(crs)

            gdf.columns = [normalize_name(col) for col in gdf.columns.tolist()]
            layer_key = normalize_name(layer_info[0])
            if "cadastre_minier_ci" in layer_key:
                layer_key = "cadastre_minier_ci"
            layers[layer_key] = gdf
            logger.debug(f"Couche '{layer_key}' chargée ({len(gdf)} entités).")

    return layers


# ---------------------------------------------------------------------------
# Cadastre minier : demandes / licences
# ---------------------------------------------------------------------------

def add_area(layer: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """
    Construit une colonne 'area' lisible à partir de 'areavalue' et 'areaunit'.
    """
    layer = layer.copy()
    if "areavalue" not in layer.columns:
        layer["areavalue"] = ""
    if "areaunit" not in layer.columns:
        layer["areaunit"] = ""

    value = layer["areavalue"].fillna("").astype(str).str.strip()
    unit = layer["areaunit"].fillna("").astype(str).str.strip()
    unit = (
        unit.str.replace("hectares", "hm²", case=False, regex=False)
        .str.replace("kilomètres carrés", "km²", case=False, regex=False)
    )

    layer["area"] = (value + " " + unit).str.strip()

    return layer


def extract_columns(gdf: gpd.GeoDataFrame, columns: list[str]) -> gpd.GeoDataFrame:
    """
    Retourne un sous-ensemble du GeoDataFrame limité aux colonnes présentes
    (parmi celles demandées) + la géométrie.
    """
    present_columns = [col for col in columns if col in gdf.columns]
    missing = set(columns) - set(present_columns)
    if missing:
        logger.warning(f"Colonnes absentes ignorées : {sorted(missing)}")
    return gdf[present_columns + [gdf.geometry.name]]


def split_applications_licenses(
    applications_cols: list[str],
    licenses_cols: list[str],
    layers: dict[str, gpd.GeoDataFrame],
    layer_key: str,
    crs: str = cfg.crs,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """
    Sépare une couche du cadastre minier en deux GeoDataFrames :
    demandes (statusgrp == "demande") et licences (le reste).
    """
    if layer_key not in layers:
        logger.error(f"Couche '{layer_key}' absente des couches lues.")
        raise KeyError(f"Couche '{layer_key}' absente des couches lues.")

    gdf = add_area(layers[layer_key]).copy()

    if "statusgrp" not in gdf.columns:
        logger.error("La colonne 'statusgrp' est absente.")
        raise ValueError("La colonne 'statusgrp' est absente.")

    geom_col = gdf.geometry.name
    status = gdf["statusgrp"].astype(str).str.strip().str.casefold()

    applications = gdf[status == "demande"].copy()
    licenses = gdf[status != "demande"].copy()

    logger.info(f"Séparation cadastre : {len(applications)} demande(s), {len(licenses)} licence(s).")

    applications = extract_columns(applications, applications_cols)
    licenses = extract_columns(licenses, licenses_cols)

    applications = gpd.GeoDataFrame(applications, geometry=geom_col, crs=crs)
    licenses = gpd.GeoDataFrame(licenses, geometry=geom_col, crs=crs)

    return applications, licenses


# ---------------------------------------------------------------------------
# Administration
# ---------------------------------------------------------------------------

def merge_admin_layers(
    admin_cols: list[str],
    admin_name_source: dict[str, list[str]],
    layers: dict[str, gpd.GeoDataFrame],
    crs: str = cfg.crs,
) -> gpd.GeoDataFrame:
    """
    Fusionne plusieurs couches administratives en une seule, en normalisant
    la colonne 'name' à partir d'une colonne source différente par couche.
    """
    admin_layers = []
    geom_col = None

    for layer_key, name_source_cols in admin_name_source.items():
        if layer_key not in layers:
            logger.warning(f"Couche administrative absente : '{layer_key}'")
            continue

        gdf = layers[layer_key].copy()
        geom_col = gdf.geometry.name

        temp = pd.DataFrame(index=gdf.index)
        if name_source_cols and name_source_cols[0] in gdf.columns:
            temp["name"] = gdf[name_source_cols[0]]
        else:
            if name_source_cols:
                logger.warning(
                    f"Colonne source '{name_source_cols[0]}' absente pour '{layer_key}', "
                    "'name' restera vide."
                )
            temp["name"] = ""

        for col in admin_cols[1:]:
            temp[col] = gdf[col] if col in gdf.columns else ""

        temp[geom_col] = gdf.geometry
        admin_layers.append(gpd.GeoDataFrame(temp, geometry=geom_col, crs=crs))
        logger.debug(f"Couche administrative '{layer_key}' ajoutée ({len(temp)} entités).")

    if not admin_layers:
        logger.error("Aucune couche administrative n'a pu être extraite.")
        raise ValueError("Aucune couche administrative n'a pu être extraite.")

    admin = gpd.GeoDataFrame(
        pd.concat(admin_layers, ignore_index=True), geometry=geom_col, crs=crs
    )
    admin["name"] = admin["name"].astype(str).str.title()

    logger.info(f"Fusion des couches administratives : {len(admin)} entités au total.")

    return admin[admin_cols + [geom_col]]


# ---------------------------------------------------------------------------
# Sauvegarde
# ---------------------------------------------------------------------------

def save_geopackage(
    applications: gpd.GeoDataFrame,
    licenses: gpd.GeoDataFrame,
    admin: gpd.GeoDataFrame,
    output_file: Path,
    crs: str = cfg.crs,
) -> Path:
    """
    Sauvegarde les trois couches (administration, licences, demandes)
    dans un unique GeoPackage. Écrase le fichier existant s'il y en a un.
    """
    layers = {
        "administration": admin,
        "licences": licenses,
        "demandes": applications,
    }

    output_file = Path(output_file)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    if output_file.exists():
        logger.debug(f"Suppression de l'ancien fichier '{output_file}'.")
        output_file.unlink()

    for layer_name, gdf in layers.items():
        if gdf.crs is None:
            logger.error(f"Le CRS de '{layer_name}' n'est pas défini.")
            raise ValueError(f"Le CRS de '{layer_name}' n'est pas défini.")
        gdf = gdf.to_crs(crs)
        gdf.to_file(output_file, layer=layer_name, driver="GPKG")
        logger.info(f"Couche '{layer_name}' sauvegardée ({len(gdf)} entités).")

    logger.info(f"GeoPackage créé : {output_file}")
    return output_file


# ---------------------------------------------------------------------------
# Pipeline complet
# ---------------------------------------------------------------------------

def run_pipeline(
    admin_bytes: bytes,
    cadastre_bytes: bytes,
    output_file: Path,
) -> Path:
    """
    Pipeline complet : lit les deux GeoPackages sources, extrait
    demandes/licences/administration, et sauvegarde le résultat consolidé.
    """
    logger.info("Lecture des GeoPackages sources...")
    layers = read_geopackage(admin_bytes, cadastre_bytes)

    logger.info("Séparation des demandes et licences du cadastre minier...")
    applications, licenses = split_applications_licenses(
        cfg.applications_cols, cfg.licenses_cols, layers, "cadastre_minier_ci"
    )

    logger.info("Fusion des couches administratives...")
    admin = merge_admin_layers(
        cfg.admin_cols, cfg.admin_name_source, layers
    )

    return save_geopackage(applications, licenses, admin, output_file)