"""个人中心：头像（emoji 或上传图片）/ 昵称 / 签名 / 等级徽章 / 称号 / 统计 / 道具。"""
from __future__ import annotations

from datetime import date, timedelta

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import (
    QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
)
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from ..palette import P


class _Avatar(QFrame):
    """圆形头像：上传图片（圆形裁剪）或 emoji 渐变底。"""

    def __init__(self, size: int = 96, parent=None):
        super().__init__(parent)
        self._size = size
        self._emoji = '🐱'
        self._image = None
        self.setFixedSize(size, size)

    def set_emoji(self, emoji: str) -> None:
        self._emoji = emoji
        self.update()

    def set_image(self, path) -> None:
        if path:
            pm = QPixmap(str(path))
            self._image = pm if not pm.isNull() else None
        else:
            self._image = None
        self.update()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        size = self._size - 4
        if self._image is not None:
            # 居中裁剪为正方形再圆形绘制
            scaled = self._image.scaled(
                size, size, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
            x = (scaled.width() - size) // 2
            y = (scaled.height() - size) // 2
            sq = scaled.copy(x, y, size, size)
            path = QPainterPath()
            path.addEllipse(2, 2, size, size)
            p.setClipPath(path)
            p.drawPixmap(2, 2, sq)
            p.setClipping(False)
            p.setPen(QPen(QColor(P.accent), 2))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(2, 2, size, size)
        else:
            grad = QLinearGradient(0, 0, self._size, self._size)
            if P.dark:
                grad.setColorAt(0, QColor('#4FC3F7'))
                grad.setColorAt(1, QColor('#B39DDB'))
            else:
                grad.setColorAt(0, QColor('#FBC2EB'))
                grad.setColorAt(1, QColor('#A6C1EE'))
            p.setPen(Qt.NoPen)
            p.setBrush(grad)
            p.drawEllipse(2, 2, size, size)
            f = QFont()
            f.setPixelSize(int(self._size * 0.52))
            p.setFont(f)
            p.drawText(self.rect(), Qt.AlignCenter, self._emoji)
        p.end()


class ProfilePage(QWidget):
    settings_requested = Signal()

    def __init__(self, repo, balance, engine, ach_service, reward_service,
                 avatar_dir=None, parent=None):
        super().__init__(parent)
        self._repo = repo
        self._balance = balance
        self._engine = engine
        self._ach = ach_service
        self._rewards = reward_service
        self._avatar_dir = avatar_dir

        root = QVBoxLayout(self)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        body.setAttribute(Qt.WA_StyledBackground, True)
        lay = QVBoxLayout(body)

        # ---- 头部卡片：头像 + 昵称 + 签名 + 等级 ----
        head_card = QFrame()
        head_card.setFrameShape(QFrame.StyledPanel)
        h = QHBoxLayout(head_card)
        h.setContentsMargins(20, 18, 20, 18)
        self._avatar = _Avatar(92)
        h.addWidget(self._avatar)
        col = QVBoxLayout()
        self._nick_label = QLabel('')
        self._nick_label.setStyleSheet('font-size:22px; font-weight:800;')
        col.addWidget(self._nick_label)
        self._sig_label = QLabel('')
        self._sig_label.setStyleSheet('font-size:12px;')
        col.addWidget(self._sig_label)
        self._level_label = QLabel('')
        self._level_label.setStyleSheet('font-size:15px; font-weight:700; margin-top:4px;')
        col.addWidget(self._level_label)
        h.addLayout(col, 1)
        self._streak_badge = QLabel('')
        self._streak_badge.setStyleSheet(
            f'font-size:15px; font-weight:800; color:{P.warn};'
            f'background:rgba(255,180,40,36); border-radius:10px;'
            f'padding:8px 14px;')
        h.addWidget(self._streak_badge, 0, Qt.AlignTop)
        lay.addWidget(head_card)

        # ---- 统计卡片 ----
        stat_card = QFrame()
        stat_card.setFrameShape(QFrame.StyledPanel)
        grid = QGridLayout(stat_card)
        grid.setContentsMargins(20, 16, 20, 16)
        self._stat_values = {}
        stats = [
            ('累计输入', 'total_typed'), ('累计有效', 'total_valid'),
            ('累计 tw', 'total_tw'), ('累计活跃', 'total_minutes'),
            ('打卡总天数', 'checkin_days'), ('补签卡', 'makeup_cards'),
            ('经验加成卡', 'boost_cards'), ('AI 训练券', 'ai_passes'),
            ('已获称号', 'titles_count'),
        ]
        for i, (name, key) in enumerate(stats):
            val = QLabel('—')
            val.setStyleSheet('font-size:17px; font-weight:700;')
            n = QLabel(name)
            n.setStyleSheet('font-size:11px;')
            grid.addWidget(n, i // 4, (i % 4) * 2)
            grid.addWidget(val, i // 4, (i % 4) * 2 + 1)
            self._stat_values[key] = val
        lay.addWidget(stat_card)

        # ---- 称号收藏 ----
        title_card = QFrame()
        title_card.setFrameShape(QFrame.StyledPanel)
        tv = QVBoxLayout(title_card)
        tv.setContentsMargins(20, 14, 20, 14)
        tlab = QLabel('🏅 称号收藏（点击佩戴）')
        tlab.setStyleSheet('font-size:14px; font-weight:700;')
        tv.addWidget(tlab)
        self._titles_box = QHBoxLayout()
        tv.addLayout(self._titles_box)
        self._active_title_label = QLabel('')
        self._active_title_label.setStyleSheet('font-size:12px;')
        tv.addWidget(self._active_title_label)
        lay.addWidget(title_card)

        # ---- 简介 + 设置入口 ----
        self._intro = QLabel('')
        self._intro.setWordWrap(True)
        self._intro.setStyleSheet('font-size:12px;')
        lay.addWidget(self._intro)
        self._settings_btn = QPushButton('⚙️ 打开设置（AI 配置 / 主题 / 排除程序…）')
        self._settings_btn.clicked.connect(self.settings_requested)
        lay.addWidget(self._settings_btn)
        lay.addStretch(1)

        scroll.setWidget(body)
        root.addWidget(scroll)
        self.apply_theme()

    # ---------- 主题 ----------
    def apply_theme(self):
        self._avatar.update()

    # ---------- 刷新 ----------
    def refresh(self):
        nickname = self._repo.get_setting('nickname', '打字新星')
        signature = self._repo.get_setting('signature', '键盘上的舞者 ✨')
        emoji = self._repo.get_setting('avatar_emoji', '🐱')
        self._avatar.set_emoji(emoji)
        if self._avatar_dir is not None:
            img = self._avatar_dir / 'avatar.png'
            self._avatar.set_image(img if img.exists() else None)
        self._nick_label.setText(nickname)
        self._sig_label.setText(signature)

        from ...services.exp_service import level_and_progress, band_title
        exp = self._repo.get_exp()
        level, progress, _ = level_and_progress(exp, self._balance)
        band = band_title(level, self._balance)
        self._level_label.setText(f'Lv.{level} · {band}　·　经验 {exp:,}')

        today = date.fromisoformat(self._engine.current_day())
        streak = self._repo.get_streak(today.isoformat()) or self._repo.get_streak(
            (today - timedelta(days=1)).isoformat())
        self._streak_badge.setText(f'🔥 {streak} 天连签')

        life = self._repo.get_lifetime() or {}
        self._stat_values['total_typed'].setText(f'{life.get("total_typed", 0):,}')
        self._stat_values['total_valid'].setText(
            f'{max(0, life.get("total_typed", 0) - life.get("total_deleted", 0)):,}')
        self._stat_values['total_tw'].setText(f'{life.get("total_tw", 0):,}')
        self._stat_values['total_minutes'].setText(f'{life.get("total_active_minutes", 0):,}')
        checkin_days = self._repo.get_checkins('0000-01-01', '9999-12-31')
        self._stat_values['checkin_days'].setText(str(len(checkin_days)))
        self._stat_values['makeup_cards'].setText(str(self._rewards.count('makeup_card')))
        self._stat_values['boost_cards'].setText(str(self._rewards.count('exp_boost')))
        self._stat_values['ai_passes'].setText(str(self._rewards.count('ai_pass')))
        titles = self._rewards.titles()
        self._stat_values['titles_count'].setText(str(len(titles)))

        active = self._repo.get_setting('active_title', '')
        # 称号 chips（含等级段称号 + 获得的特殊称号）
        while self._titles_box.count():
            item = self._titles_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        all_titles = [f'Lv.{level} {band}'] + titles
        for t in all_titles:
            btn = QPushButton(t)
            if t == active or (not active and t.startswith(f'Lv.{level}')):
                btn.setStyleSheet(
                    f'background:{P.accent}; color:white; border-radius:10px;'
                    'padding:6px 12px; font-weight:700;')
            else:
                btn.setStyleSheet(
                    f'background:{P.card_bg}; border:1px solid {P.card_border};'
                    'border-radius:10px; padding:6px 12px;')
            btn.clicked.connect(lambda _=False, tt=t: self._equip_title(tt))
            self._titles_box.addWidget(btn)
        self._titles_box.addStretch(1)
        self._active_title_label.setText(
            f'当前佩戴：{active if active else f"Lv.{level} {band}"}')

        unlocked = sum(1 for a in self._ach.all_achievements() if a['unlocked_at'])
        total = len(self._ach.all_achievements())
        self._intro.setText(
            f'🎮 成就进度 {unlocked}/{total}　·　'
            f'每天打打字，成为键盘上的明星吧 ✨')

    def _equip_title(self, title: str) -> None:
        self._repo.set_setting('active_title', title)
        self.refresh()
