"""
Utilitaires pour récupérer des fichiers depuis Google Drive via l'API officielle.
"""
import io
import os
from datetime import datetime

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

import src.config as cfg
from src.logger import logger


# ---------------------------------------------------------------------------
# Authentification
# ---------------------------------------------------------------------------

def get_drive_service():
    """
    Authentifie via un refresh token OAuth stocké en variables d'environnement
    (GDRIVE_CLIENT_ID, GDRIVE_CLIENT_SECRET, GDRIVE_REFRESH_TOKEN).
    Aucune interaction utilisateur requise : adapté à un environnement CI/CD.
    """

    client_id = os.getenv('GDRIVE_CLIENT_ID')
    client_secret = os.getenv('GDRIVE_CLIENT_SECRET')
    refresh_token = os.getenv('GDRIVE_REFRESH_TOKEN')
    
    if not all([client_id, client_secret, refresh_token]):
        logger.error("❌ Secrets OAuth manquants")
        raise ValueError(
            "GDRIVE_CLIENT_ID, GDRIVE_CLIENT_SECRET, GDRIVE_REFRESH_TOKEN "
            "doivent être définis"
        )
    
    logger.info("Drive auth : OAuth 2.0 (refresh token).")
    
    try:
        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes= cfg.scopes,  # ✅ Doit correspondre au token généré
        )
        
        # Rafraîchir immédiatement pour vérifier
        request = Request()
        creds.refresh(request)
        
        return build("drive", "v3", credentials=creds, cache_discovery=False)
        
    except Exception as e:
        logger.error(f"❌ Erreur OAuth : {e}")
        raise

# ---------------------------------------------------------------------------
# Listing / filtrage
# ---------------------------------------------------------------------------

def _list_raw_files(service, folder_id: str) -> list[dict]:
    """
    Récupère la liste brute (paginée) de tous les fichiers non supprimés
    d'un dossier Google Drive.
    """
    raw_files = []
    page_token = None

    while True:
        response = service.files().list(
            q=f"'{folder_id}' in parents and trashed = false",
            orderBy="modifiedTime desc",
            fields="nextPageToken, files(id, name, mimeType, modifiedTime, size)",
            pageToken=page_token,
        ).execute()

        raw_files.extend(response.get("files", []))
        page_token = response.get("nextPageToken")

        if not page_token:
            break

    logger.debug(f"{len(raw_files)} fichier(s) trouvé(s) dans le dossier '{folder_id}'.")
    return raw_files


def _format_file_meta(file_meta: dict) -> dict:
    """Normalise les métadonnées d'un fichier Drive dans un format exploitable."""
    date = datetime.fromisoformat(file_meta["modifiedTime"].replace("Z", "+00:00"))
    return {
        "name": file_meta["name"],
        "id": file_meta["id"],
        "size": int(file_meta["size"]) if "size" in file_meta else None,
        "modifiedTime": date,
    }


def list_gpkg_files(service, folder_id: str) -> dict[str, dict]:
    """
    Liste tous les fichiers .gpkg d'un dossier Google Drive (non supprimés).
    Retourne un dict {nom_fichier: {name, id, size, modifiedTime}}.
    """
    raw_files = _list_raw_files(service, folder_id)

    gpkg_files = {
        file_meta["name"]: _format_file_meta(file_meta)
        for file_meta in raw_files
        if file_meta["name"].lower().endswith(".gpkg")
    }

    logger.debug(f"{len(gpkg_files)} fichier(s) .gpkg retenu(s).")
    return gpkg_files


def filter_by_prefix(files_dict: dict, prefix: str) -> dict:
    """
    Filtre un dict de fichiers Drive selon un préfixe présent dans le nom
    (avant le premier underscore, insensible à la casse).
    """
    return {
        name: meta
        for name, meta in files_dict.items()
        if prefix.lower() in name.split("_")[0].lower()
    }


def most_recent(files_dict: dict) -> dict:
    """
    Retourne les métadonnées du fichier le plus récemment modifié.
    """
    if not files_dict:
        raise ValueError("Aucun fichier disponible pour déterminer le plus récent.")

    return max(files_dict.values(), key=lambda f: f["modifiedTime"])


# ---------------------------------------------------------------------------
# Téléchargement
# ---------------------------------------------------------------------------

def download_to_memory(service, file_id: str) -> bytes:
    """
    Télécharge un fichier depuis Google Drive et retourne son contenu binaire.
    """
    request = service.files().get_media(fileId=file_id)
    buffer = io.BytesIO()
    downloader = MediaIoBaseDownload(buffer, request)
    done = False

    while not done:
        status, done = downloader.next_chunk()
        if status:
            logger.info(f"Téléchargement : {int(status.progress() * 100)}%")

    return buffer.getvalue()


def fetch_latest_by_prefix(service, folder_id: str, prefix: str) -> bytes:
    """
    Récupère, parmi les fichiers d'un dossier Drive dont le nom commence par
    `prefix`, le plus récent, et le télécharge en mémoire.
    """
    files = list_gpkg_files(service, folder_id)
    matches = filter_by_prefix(files, prefix)

    if not matches:
        logger.error(f"Aucun fichier correspondant à '{prefix}' dans le dossier Drive (id={folder_id}).")
        raise FileNotFoundError(
            f"Aucun fichier correspondant à '{prefix}' dans le dossier Drive (id={folder_id})."
        )

    latest_file = most_recent(matches)
    logger.info(
        f"[{prefix}] Fichier le plus récent : {latest_file['name']} "
        f"(modifié le {latest_file['modifiedTime']})"
    )

    return download_to_memory(service, latest_file["id"])


def fetch_all(
    folder_id: str,
    files_to_fetch: dict[str, str],
    service=None,
) -> dict[str, bytes]:
    """
    Récupère, pour chaque préfixe du dict `files_to_fetch`, le fichier
    Drive le plus récent correspondant, et le télécharge en mémoire.

    Args:
        folder_id: ID du dossier Google Drive source.
        files_to_fetch: dict {prefixe: nom_fichier_local}.
        service: instance du service Drive (créée automatiquement si None).

    Returns:
        dict {nom_fichier_local: contenu_binaire}.
    """
    if service is None:
        service = get_drive_service()

    result = {}

    for prefix, local_name in files_to_fetch.items():
        logger.info(f"Récupération du fichier pour le préfixe '{prefix}'...")
        result[local_name] = fetch_latest_by_prefix(
            service=service, folder_id=folder_id, prefix=prefix
        )

    return result