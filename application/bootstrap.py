from __future__ import annotations

from dataclasses import dataclass

from config import load_config
from application.pipeline_service import ViralForgePipeline
from utils.fs import ensure_project_dirs
from utils.logging import setup_logging


@dataclass
class RuntimeContext:
    config: object
    logger: object
    pipeline: ViralForgePipeline


def build_runtime(config_path: str | None = None, auto_host: bool | None = None) -> RuntimeContext:
    config = load_config(config_path=config_path)
    ensure_project_dirs(config)
    logger = setup_logging(config)
    config.auto_host = auto_host
    pipeline = ViralForgePipeline(config, logger=logger)
    return RuntimeContext(config=config, logger=logger, pipeline=pipeline)
