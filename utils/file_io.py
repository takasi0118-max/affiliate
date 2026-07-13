"""File input and output utilities."""

from pathlib import Path
from typing import Any
import json


def ensure_directory(path: Path) -> Path:
    """Create a directory when it does not exist and return the path."""
    # parents=Trueで途中のフォルダもまとめて作り、exist_ok=Trueで既存でもエラーにしない。
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_json_file(path: Path) -> Any:
    """Load a JSON file with a clear error message."""
    try:
        # categories.jsonやhistory.jsonなど、設定用JSONをUTF-8として読む。
        with path.open("r", encoding="utf-8") as file:
            return json.load(file)
    except FileNotFoundError as error:
        # どのJSONが見つからないのか分かるように、ファイルパス付きで例外を出す。
        raise FileNotFoundError(f"JSON file not found: {path}") from error
    except json.JSONDecodeError as error:
        # JSONのカンマ抜けなど、書式エラーもファイルパス付きで知らせる。
        raise ValueError(f"Invalid JSON file: {path}") from error


def save_json_file(path: Path, data: Any) -> None:
    """Save data as UTF-8 JSON."""
    # 保存先フォルダが未作成でも、その場で作ってからJSONを書き込む。
    ensure_directory(path.parent)
    with path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
        file.write("\n")


def read_text_lines(path: Path, ignore_comments: bool = False) -> list[str]:
    """Read non-empty text lines from a UTF-8 file."""
    if not path.exists():
        raise FileNotFoundError(f"Text file not found: {path}")

    # themes.txtなどを扱いやすいよう、空行と必要に応じてコメント行を除外する。
    lines = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped_line = line.strip()
        if not stripped_line:
            continue
        if ignore_comments and stripped_line.startswith("#"):
            continue
        lines.append(stripped_line)

    return lines


def write_text_file(path: Path, content: str) -> None:
    """Write UTF-8 text to a file."""
    # Markdown記事などのテキスト保存でも、保存先フォルダを先に作っておく。
    ensure_directory(path.parent)
    path.write_text(content, encoding="utf-8")
