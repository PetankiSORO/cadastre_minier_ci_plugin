"""
Script principal : récupère les fichiers sources depuis Google Drive,
charge les couches, et sauvegarde le résultat consolidé.
"""
import sys
import time
from pathlib import Path

import src.config as cfg
import src.gdrive as gdrive
import src.processing as prs
from src.logger import logger

base_dir = Path(__file__).parent
data_dir = base_dir / "data"
output_file = data_dir / "cadastre_minier_ci.gpkg"

def fetch_source_files(folder_id: str, files: dict[str, str]) -> dict[str, bytes]:
    """Télécharge les derniers fichiers .gpkg depuis Google Drive."""
    logger.info("--- Récupération des fichiers depuis Google Drive ---")
    return gdrive.fetch_all(folder_id, files)


def process_and_save(
    admin_bytes: bytes,
    cadastre_bytes: bytes,
    output_file,
) -> None:
    """Traite les données et sauvegarde le GeoPackage consolidé."""
    logger.info("--- Traitement et sauvegarde des données ---")
    prs.run_pipeline(admin_bytes, cadastre_bytes, output_file)


def with_retry(func, *args,
               max_retries: int = cfg.max_retries,
               delay: int = cfg.retry_delay_seconds, **kwargs):
    """
    Exécute `func` avec réessais automatiques en cas d'échec.
    Ne réessaie pas pour les erreurs non transitoires (FileNotFoundError, KeyError, ValueError).
    """
    non_retryable = (FileNotFoundError, KeyError, ValueError)
    last_exception = None
    
    for attempt in range(1, max_retries + 1):
        try:
            return func(*args, **kwargs)
        except non_retryable as exc:
            logger.error(f"Erreur non récupérable dans '{func.__name__}' : {exc}")
            raise
        except Exception as exc:
            last_exception = exc
            logger.warning(
                f"Échec de '{func.__name__}' (tentative {attempt}/{max_retries}) : {exc}"
            )
            if attempt < max_retries:
                logger.info(f"Nouvelle tentative dans {delay}s...")
                time.sleep(delay)
                
    logger.error(f"Échec définitif de '{func.__name__}' après {max_retries} tentatives.")
    raise last_exception
    
    
def main() -> None:
    logger.info("=== Démarrage du pipeline cadastre minier CI ===")
    
    try:
        source_files = with_retry(
            fetch_source_files, cfg.drive_folder_id, cfg.input_files
        )
        
        with_retry(
            process_and_save,
            source_files[cfg.input_files["admin"]],
            source_files[cfg.input_files["cadastre"]],
            output_file,
        )
        
    except Exception:
        logger.exception("Le pipeline a échoué de manière irrécupérable.")
        sys.exit(1)
        
    logger.info("=== Pipeline terminé avec succès ===")


if __name__ == "__main__":
    main()
