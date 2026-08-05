from __future__ import annotations

import argparse
import math
from pathlib import Path

from PIL import Image, ImageDraw


def _hex_points(size: int, radius: float) -> list[tuple[float, float]]:
    center = size / 2.0
    return [
        (
            center + radius * math.cos(math.radians(60 * index - 30)),
            center + radius * math.sin(math.radians(60 * index - 30)),
        )
        for index in range(6)
    ]


def build_icon(path: Path) -> None:
    canvas_size = 256
    image = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.polygon(_hex_points(canvas_size, 114), fill="#FFA814")
    draw.polygon(_hex_points(canvas_size, 82), fill="#0DA9E5")
    draw.polygon(_hex_points(canvas_size, 48), fill="#FFFFFF")
    image.save(
        path,
        format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )


def build_version_file(path: Path, version: str, artifact_name: str) -> None:
    parts = tuple(int(part) for part in version.split("."))
    if len(parts) != 3:
        raise ValueError(f"VERSION 必须是三段版本号：{version!r}")
    numeric = (*parts, 0)
    text = f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers={numeric},
    prodvers={numeric},
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable(
        '080404b0',
        [
          StringStruct('CompanyName', 'HexInfinite Solver'),
          StringStruct('FileDescription', 'HexInfinite Seed and Step Solver'),
          StringStruct('FileVersion', '{version}'),
          StringStruct('InternalName', 'HexInfiniteSolver'),
          StringStruct('LegalCopyright', 'Open-source project; Hexcells Infinite assets are not distributed.'),
          StringStruct('OriginalFilename', '{artifact_name}.exe'),
          StringStruct('ProductName', 'HexInfinite Solver'),
          StringStruct('ProductVersion', '{version}')
        ]
      )
    ]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
"""
    path.write_text(text, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--artifact-name", required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    build_icon(args.output_dir / "HexInfiniteSolver.ico")
    build_version_file(
        args.output_dir / "version_info.txt",
        args.version,
        args.artifact_name,
    )


if __name__ == "__main__":
    main()
