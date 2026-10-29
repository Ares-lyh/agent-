"""Atomic Checkpoint Engine for state persistence and zero-loss resume."""
import os
import json
from typing import List, Dict, Any, Optional
from datetime import datetime
from pydantic import BaseModel, Field
from src.core.state_machine import ProjectState
from src.core.exceptions import CheckpointCorruptError, ProjectNotFoundError


from src.models.workflow import ProjectCheckpoint
from src.utils.persistence import atomic_write


class CheckpointManager:
    """Manages project workspaces and atomic checkpoint files."""

    def __init__(self, base_storage_dir: str = "storage/projects"):
        self.base_storage_dir = os.path.abspath(base_storage_dir)
        os.makedirs(self.base_storage_dir, exist_ok=True)

    def get_project_dir(self, project_id: str) -> str:
        """Get absolute path to project directory."""
        import re
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", project_id):
            raise ValueError("项目 ID 格式不合法")
        project_dir = os.path.join(self.base_storage_dir, project_id)
        os.makedirs(project_dir, exist_ok=True)
        return project_dir

    def get_checkpoint_path(self, project_id: str) -> str:
        return os.path.join(self.get_project_dir(project_id), "checkpoint.json")

    def project_exists(self, project_id: str) -> bool:
        ckpt_path = self.get_checkpoint_path(project_id)
        return os.path.exists(ckpt_path)

    def save_checkpoint(self, checkpoint: ProjectCheckpoint):
        """Atomically persist checkpoint to disk using rename."""
        checkpoint.updated_at = datetime.utcnow().isoformat() + "Z"
        project_dir = self.get_project_dir(checkpoint.project_id)
        ckpt_path = os.path.join(project_dir, "checkpoint.json")
        atomic_write(ckpt_path, checkpoint.model_dump_json(indent=2))

    def load_checkpoint(self, project_id: str) -> ProjectCheckpoint:
        """Load and validate checkpoint for a given project ID."""
        if not self.project_exists(project_id):
            raise ProjectNotFoundError(f"未找到项目 '{project_id}' 的存储数据或 checkpoint")

        ckpt_path = self.get_checkpoint_path(project_id)
        try:
            with open(ckpt_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return ProjectCheckpoint.model_validate(data)
        except Exception as e:
            raise CheckpointCorruptError(f"解析 checkpoint 文件损坏: {ckpt_path}, 详情: {str(e)}")
