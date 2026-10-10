from pathlib import Path
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage, QPainter, QColor, QPen, QPolygonF
from PySide6.QtCore import Qt, QRectF, QPointF
from PIL import Image

app = QApplication([])
im = QImage(256, 256, QImage.Format.Format_ARGB32)
im.fill(Qt.GlobalColor.transparent)
p = QPainter(im)
p.setRenderHint(QPainter.RenderHint.Antialiasing)
p.setPen(Qt.PenStyle.NoPen)
p.setBrush(QColor('#326ed5'))
p.drawRoundedRect(QRectF(12, 12, 232, 232), 48, 48)
p.setBrush(QColor('#ffffff'))
p.drawRoundedRect(QRectF(66, 47, 124, 162), 12, 12)
p.setPen(QPen(QColor('#326ed5'), 12, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
p.drawLine(91, 89, 164, 89)
p.drawLine(91, 116, 164, 116)
p.drawLine(91, 143, 131, 143)
p.setPen(QPen(QColor('#326ed5'), 11, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
p.drawLine(126, 173, 169, 173)
p.drawLine(155, 159, 169, 173)
p.drawLine(169, 173, 155, 187)
p.end()
dest = Path(__file__).parent / 'src'
im.save(str(dest / 'app.png'))
image = Image.open(dest / 'app.png')
image.save(dest / 'app.ico', sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
