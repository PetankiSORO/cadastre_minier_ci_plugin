"""
Configuration centralisée du système de journalisation (logging).
Écrit les logs à la fois dans la console et dans un fichier .log daté.
Conserve uniquement les MAX_LOG_FILES fichiers les plus récents.
"""
import logging
from datetime import datetime
from pathlib import Path

import src.config as cfg

cfg.log_dir.mkdir(exist_ok=True)
log_file = cfg.log_dir / f"cadastre_minier_ci_{datetime.now():%Y%m%d_%H%M%S}.log"

def cleanup_old_logs(log_dir: Path, max_files: int) -> None:
    """Supprime les plus anciens fichiers .log si leur nombre dépasse max_files."""
    log_files = sorted(
        log_dir.glob("*.log"),
        key=lambda f: f.stat().st_mtime,
        reverse=True,
    )
    for old_file in log_files[max_files:]:
        try:
            old_file.unlink()
        except OSError:
            pass  # fichier verrouillé ou déjà supprimé, on ignore


def get_logger(name: str = "cadastre_minier_ci") -> logging.Logger:
    """Retourne un logger configuré (console + fichier), réutilisable partout."""
    logger = logging.getLogger(name)

    if logger.handlers:  # évite les doublons si déjà initialisé (ex. reload spyder)
        return logger

    logger.setLevel(logging.DEBUG)

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # --- Handler fichier ---
    file_handler = logging.FileHandler(log_file, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    # --- Handler console ---
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    cleanup_old_logs(cfg.log_dir, cfg.max_log_file)

    return logger

logger = get_logger()