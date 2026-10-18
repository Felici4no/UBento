"""Gera assets/ubento.ico a partir de assets/ubento.svg (usado no empacotamento)."""

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication, QImage, QPainter
from PySide6.QtSvg import QSvgRenderer

root = Path(__file__).resolve().parents[1]
app = QGuiApplication(sys.argv)
renderer = QSvgRenderer(str(root / "assets" / "ubento.svg"))
image = QImage(256, 256, QImage.Format.Format_ARGB32)
image.fill(Qt.GlobalColor.transparent)
painter = QPainter(image)
renderer.render(painter)
painter.end()
out = root / "assets" / "ubento.ico"
assert image.save(str(out), "ICO"), "falha ao gravar o .ico"
print(out)
