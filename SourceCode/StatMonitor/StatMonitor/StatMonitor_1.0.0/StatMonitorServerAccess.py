from __future__ import annotations

import hmac
import json
import os
import secrets
import tempfile
import threading
from pathlib import Path


SCHEMA_VERSION = 1


class StatMonitorServerAccess:
	def __init__(self, root: str | os.PathLike[str]):
		self.root = Path(root).resolve()
		self.path = self.root / "Appdata" / "ServerAccess" / "StatMonitorServerAccess.json"
		self.legacy_path = self.root / "Appdata" / "Settings" / "StatMonitorServerAccess.json"
		self._lock = threading.RLock()
		self._token = ""
		self._load_or_create()

	def get_token(self) -> str:
		with self._lock:
			return self._token

	def verify(self, candidate) -> bool:
		if not isinstance(candidate, str) or not candidate:
			return False
		with self._lock:
			return hmac.compare_digest(candidate, self._token)

	def _load_or_create(self) -> None:
		with self._lock:
			token = self._read_token(self.path)
			if isinstance(token, str) and len(token) >= 32:
				self._token = token
				return
			token = self._read_token(self.legacy_path)
			if isinstance(token, str) and len(token) >= 32:
				self._token = token
				self._save_locked()
				try:
					self.legacy_path.unlink()
				except OSError:
					pass
				return
			self._token = secrets.token_urlsafe(32)
			self._save_locked()

	def _read_token(self, path: Path) -> str | None:
		try:
			with path.open("r", encoding="utf-8") as file:
				data = json.load(file)
		except (OSError, json.JSONDecodeError):
			return None
		token = data.get("token") if isinstance(data, dict) else None
		return token if isinstance(token, str) else None

	def _save_locked(self) -> None:
		self.path.parent.mkdir(parents=True, exist_ok=True)
		descriptor, temporary_name = tempfile.mkstemp(prefix=f"{self.path.name}.", suffix=".tmp", dir=self.path.parent)
		try:
			with os.fdopen(descriptor, "w", encoding="utf-8") as file:
				json.dump({"schemaVersion": SCHEMA_VERSION, "token": self._token}, file, indent=2)
				file.write("\n")
				file.flush()
				os.fsync(file.fileno())
			os.replace(temporary_name, self.path)
			if os.name != "nt":
				try:
					os.chmod(self.path, 0o600)
				except OSError:
					pass
		finally:
			if os.path.exists(temporary_name):
				os.unlink(temporary_name)
