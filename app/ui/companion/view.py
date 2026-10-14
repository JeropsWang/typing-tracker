"""One painted, alpha-masked character surface for both display hosts."""
import time
from PySide6.QtCore import QBuffer, QIODevice, QPoint, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QImage, QMovie, QPainter, QPixmap, QRegion, QTransform
from PySide6.QtWidgets import QApplication, QWidget
from .motion import CharacterMotion


class CompanionView(QWidget):
    """Qt 主线程的桌宠绘制与输入视图；仅显示素材/气泡，互动通过信号交控制器。"""
    clicked = Signal()
    double_clicked = Signal()
    dragged = Signal(QPoint)
    drag_finished = Signal()
    menu_requested = Signal(QPoint)

    def __init__(self, parent=None):
        """建立透明视图、姿态动效、图片/GIF 状态及单击/拖动计时器。"""
        super().__init__(parent)
        self.setObjectName('sarianaCompanion')
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setFocusPolicy(Qt.NoFocus)
        self.setStyleSheet('QWidget#sarianaCompanion {background:transparent;border:none;}')
        self.setMouseTracking(True)
        self.setAccessibleName('Sariana 小伙伴：拖出窗口到桌面，单击摸头，双击互动，右键打开菜单')
        self._image = QPixmap()
        self._previous_image = None
        self._blend = 1
        self._blend_started = 0
        self._movie = None
        self._movie_buffer = None
        self._sprite = None
        self._text = ''
        self._motion = False
        self._press = None
        self._dragging = False
        self.draggable = True
        self._grab_local = QPoint()
        self._last_pointer = None
        self.desktop = False
        self._offset = 0
        self._pose_motion = CharacterMotion()
        self._animation = QTimer(self)
        self._animation.setInterval(16)
        self._animation.timeout.connect(self._animate)
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.timeout.connect(self.clicked)
        self.set_character_size(160)

    def set_character_size(self, size):
        """将角色尺寸限制在 100–220 逻辑像素并重算视图和命中区域。"""
        self.character_size = max(100, min(220, int(size)))
        self.setFixedSize(max(210, self.character_size + 30), self.character_size + 105)
        self._update_mask()

    def set_content(self, sprite, text='', motion=False, *, state='idle', token=None):
        """更新素材、截取帧、话术和姿态 token；动效开启时保留上一图用于连续过渡。"""
        if sprite != self._sprite:
            self._previous_image = self._composed_image() if motion and not self._image.isNull() else None
            self._blend = 0 if self._previous_image is not None else 1
            self._blend_started = time.monotonic()
            self._stop_movie()
            self._sprite = sprite
            if sprite.path.suffix.lower() == '.gif':
                self._movie_buffer = QBuffer(self)
                self._movie_buffer.setData(sprite.path.read_bytes())
                self._movie_buffer.open(QIODevice.ReadOnly)
                self._movie = QMovie(self._movie_buffer, parent=self)
                self._movie.setCacheMode(QMovie.CacheNone)
                self._movie.frameChanged.connect(self._movie_frame)
                if not self._movie.jumpToFrame(sprite.frame):
                    self._movie.jumpToFrame(0)
                self._movie_frame()
            else:
                image = QImage(str(sprite.path))
                if sprite.rect:
                    image = image.copy(QRect(*sprite.rect))
                self._image = QPixmap.fromImage(image)
        self._text = text[:160]
        self._pose_motion.set_state(state, token)
        self.set_motion_enabled(motion)
        self._update_mask()
        self.update()

    def _movie_frame(self, *_):
        """GIF 换帧后更新裁切图像、透明命中区域并重绘。"""
        if self._movie:
            image = self._movie.currentPixmap()
            self._image = image.copy(QRect(*self._sprite.rect)) if self._sprite.rect else image
            self._update_mask()
            self.update()

    def _stop_movie(self):
        """停止并解除 GIF 回调，释放缓存设备，避免旧素材继续占用文件。"""
        if self._movie:
            self._movie.stop()
            self._movie.frameChanged.disconnect(self._movie_frame)
            self._movie.deleteLater()
            self._movie = None
        if self._movie_buffer:
            self._movie_buffer.close()
            self._movie_buffer.deleteLater()
            self._movie_buffer = None

    def set_motion_enabled(self, enabled):
        """按可见性和动效设置启停动画/GIF；关闭时恢复静态帧和姿态。"""
        self._motion = bool(enabled)
        active = self._motion and self.isVisible()
        if active:
            self._animation.start()
        else:
            self._animation.stop()
            self._offset = 0
            self._pose_motion.reset()
            self._previous_image = None
            self._blend = 1
        if self._movie:
            if active:
                self._movie.start()
            else:
                self._movie.stop()
                if not self._movie.jumpToFrame(self._sprite.frame):
                    self._movie.jumpToFrame(0)
        self.update()

    def _animate(self):
        """采样连续姿态并推进图片混合，完成过渡后释放上一张图片。"""
        now = time.monotonic()
        self._pose_motion.sample(now)
        if self._previous_image is not None:
            progress = min(1, max(0, (now - self._blend_started) / .20))
            self._blend = progress * progress * (3 - 2 * progress)
            if progress >= 1:
                self._previous_image = None
        self._update_mask()
        self.update()

    def image_rect(self):
        """按角色尺寸等比计算图片在视图中的显示区域。"""
        if self._image.isNull():
            return QRect()
        size = self._image.size().scaled(self.character_size, self.character_size, Qt.KeepAspectRatio)
        return QRect((self.width() - size.width()) // 2,
                     self.height() - size.height() - 8 + round(self._offset), size.width(), size.height())

    def bubble_rect(self):
        """返回话术气泡的固定预留区域，供绘制和命中计算复用。"""
        return QRect(4, 4, self.width() - 8, 77)

    def _composed_image(self):
        """取得当前混合图像副本，让被打断的下一次切换从可见帧继续。"""
        if self._previous_image is None:
            return QPixmap(self._image)
        image = QPixmap(self._image.size())
        image.fill(Qt.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        painter.setOpacity(1 - self._blend)
        painter.drawPixmap(image.rect(), self._previous_image)
        painter.setOpacity(self._blend)
        painter.drawPixmap(image.rect(), self._image)
        painter.end()
        return image

    def _image_transform(self):
        """以角色脚底为基准组合平移、旋转和缩放，返回实际绘制变换。"""
        rect = self.image_rect()
        frame = self._pose_motion.frame
        transform = QTransform()
        transform.translate(rect.center().x() + frame.x, rect.bottom() + frame.y)
        transform.rotate(frame.angle)
        transform.scale(frame.scale_x, frame.scale_y)
        transform.translate(-rect.center().x(), -rect.bottom())
        return transform

    def _update_mask(self):
        """按图片 alpha、姿态变换及气泡区域更新窗口遮罩，透明处保留穿透。"""
        region = QRegion()
        if not self._image.isNull():
            rect = self.image_rect()
            pixmap = self._image.scaled(rect.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            mask = pixmap.mask()
            region = QRegion(mask).translated(rect.topLeft()) if not mask.isNull() else QRegion(rect)
            if self._previous_image is not None:
                previous = self._previous_image.scaled(rect.size(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation).mask()
                region |= QRegion(previous).translated(rect.topLeft()) if not previous.isNull() else QRegion(rect)
            region = self._image_transform().map(region)
        if self._text:
            region |= QRegion(self.bubble_rect())
        if not region.isEmpty():
            self.setMask(region)
        else:
            self.clearMask()

    def paintEvent(self, event):
        """绘制气泡和姿态变换后的角色图像，智能体反馈使用共享纸张颜色。"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        if self._text:
            rect = self.bubble_rect()
            token = self._pose_motion.token
            agent = isinstance(token, tuple) and bool(token) and token[0] == 'agent'
            if agent:
                from .agent_visuals import colors
                c = colors()
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(c.blue if agent else '#f5ebdf'))
            painter.drawRoundedRect(QRectF(rect), 16, 16)
            painter.setPen(QColor(c.ink if agent else '#4f405d'))
            painter.setFont(QFont('Microsoft YaHei UI', 10))
            painter.drawText(rect.adjusted(12, 8, -12, -8), Qt.AlignCenter | Qt.TextWordWrap, self._text)
        if not self._image.isNull():
            painter.setTransform(self._image_transform())
            if self._previous_image is not None:
                painter.setOpacity(1 - self._blend)
                painter.drawPixmap(self.image_rect(), self._previous_image)
            painter.setOpacity(self._blend)
            painter.drawPixmap(self.image_rect(), self._image)

    def mousePressEvent(self, event):
        """记录左键手势起点和局部抓取位置；右键取消待发单击并请求菜单。"""
        if event.button() == Qt.LeftButton:
            self._press = event.globalPosition().toPoint()
            self._origin = self.mapToGlobal(QPoint())
            self._grab_local = event.position().toPoint()
            self._last_pointer = self._press
            self._dragging = False
            event.accept()
        elif event.button() == Qt.RightButton:
            self._click_timer.stop()
            self.menu_requested.emit(event.globalPosition().toPoint())

    def mouseMoveEvent(self, event):
        """超过拖动阈值后发布全球坐标，更新倾斜姿态并保持抓取点不跳变。"""
        if self._press is not None and event.buttons() & Qt.LeftButton and self.draggable:
            delta = event.globalPosition().toPoint() - self._press
            if delta.manhattanLength() >= QApplication.startDragDistance():
                self._dragging = True
                self._click_timer.stop()
            if self._dragging:
                pointer = event.globalPosition().toPoint()
                if self._motion:
                    self._pose_motion.set_drag(pointer.x() - self._last_pointer.x())
                self._last_pointer = pointer
                self.setCursor(Qt.ClosedHandCursor)
                self.dragged.emit(self._origin + delta)

    def mouseReleaseEvent(self, event):
        """非拖动时延后单击以区分双击；拖动结束时回弹、释放抓取并通知保存位置。"""
        if event.button() == Qt.LeftButton and self._press is not None:
            if not self._dragging:
                self._click_timer.start(QApplication.doubleClickInterval())
            else:
                if self._motion:
                    self._pose_motion.release()
                if QWidget.mouseGrabber() is self:
                    self.releaseMouse()
                self.unsetCursor()
                self.drag_finished.emit()
            self._press = None
            self._dragging = False

    def drag_context(self):
        """复制正在拖动的坐标上下文，供跨窗口模式切换时延续同一手势。"""
        return (QPoint(self._press), QPoint(self._origin), QPoint(self._grab_local),
                QPoint(self._last_pointer)) if self._press is not None and self._dragging else None

    def resume_drag(self, context):
        """恢复跨模式拖动上下文；原生平台可见时重新抓取鼠标。"""
        if context is not None:
            self._press, self._origin, self._grab_local, self._last_pointer = context
            self._dragging = True
            if self._motion:
                self._pose_motion.set_drag(0)
            self.setCursor(Qt.ClosedHandCursor)
            if self.isVisible() and QApplication.platformName() != 'offscreen':
                self.grabMouse()

    def mouseDoubleClickEvent(self, event):
        """双击时撤销待发单击，发布独立双击互动信号。"""
        if event.button() == Qt.LeftButton:
            self._click_timer.stop()
            self._press = None
            self.double_clicked.emit()

    def hideEvent(self, event):
        """隐藏时清除未完成手势、待发点击与视觉计时，防止后台误触发。"""
        self._click_timer.stop()
        self._press = None
        self._dragging = False
        if self._pose_motion.dragging:
            self._pose_motion.release()
        self.unsetCursor()
        self._animation.stop()
        if self._movie:
            self._movie.stop()
        super().hideEvent(event)

    def showEvent(self, event):
        """视图再次显示后按现有设置恢复动效。"""
        super().showEvent(event)
        self.set_motion_enabled(self._motion)

    def shutdown(self):
        """停止点击、动画和 GIF，隐藏视图以配合控制器退出。"""
        self._click_timer.stop()
        self._animation.stop()
        self._stop_movie()
        self.hide()
