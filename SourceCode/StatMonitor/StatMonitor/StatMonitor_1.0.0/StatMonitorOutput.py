from __future__ import annotations


_RAW_OUTPUT_ENABLED = False


def set_raw_output(enabled: bool) -> None:
	global _RAW_OUTPUT_ENABLED
	_RAW_OUTPUT_ENABLED = bool(enabled)


def raw_output_enabled() -> bool:
	return _RAW_OUTPUT_ENABLED


def print_raw(text: str) -> None:
	if _RAW_OUTPUT_ENABLED:
		print(text, flush=True)
