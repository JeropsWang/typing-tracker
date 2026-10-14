"""窗口布局策略：仅计算逻辑像素，不读取业务数据或修改控件。

页面与导航共享宽度和密度规则，避免各页分别堆积断点与像素补丁。
"""
from dataclasses import dataclass

WINDOW_CHROME_HEIGHT = 140  # 标题栏 42 + 导航最多 82 + 下边距最多 16
FIXED_WINDOW_SIZE = (1440, 1024)  # 设计稿基准，生产窗口不开放缩放


def bounded(value, low, high):
    """把尺寸数值限制在给定区间并四舍五入为整数逻辑像素。"""
    return int(round(max(low, min(high, value))))


def fraction(value, low, high):
    """把尺寸区间映射为 0–1 连续比例，用于响应式插值。"""
    return max(0.0, min(1.0, (value - low) / (high - low)))


def stage_layout_for(widget):
    """窗口预算固定扣除标题栏和导航，避免导航增高反过来触发布局切档。"""
    window = widget.window()
    reserved = window.property('stageChromeHeight')
    if reserved is not None:
        return StageLayout(max(1, window.width()), max(1, window.height() - int(reserved)))
    return StageLayout(max(1, widget.width()), max(1, widget.height()))


@dataclass(frozen=True)
class StageLayout:
    """不可变页面可用宽高模型，统一派生留白、纸张与训练控件尺寸。"""
    width: int
    height: int

    @property
    def compact(self):
        """判断当前可用宽高是否进入紧凑布局。"""
        return self.width <= 1000 or self.height <= 720

    @property
    def openness(self):
        """由宽高余量计算 0–1 开放度，以较紧的方向限制扩张。"""
        return min(fraction(self.width, 1000, 1440), fraction(self.height, 640, 874))

    def blend(self, small, large):
        """依据开放度在紧凑/宽松尺寸间连续插值并限制取值。"""
        return bounded(small + (large - small) * self.openness, small, large)

    @property
    def paper_padding(self):
        """返回纸张内边距的逻辑像素值。"""
        return self.blend(20, 32)

    @property
    def reference_height(self):
        """返回参考正文的响应式预留高度。"""
        return self.blend(57, 76)

    @property
    def margin_x(self):
        """返回页面左右留白，随可用空间连续变化。"""
        return self.blend(24, 48)

    @property
    def margin_top(self):
        """返回页面上方留白的逻辑像素值。"""
        return self.blend(12, 44)

    @property
    def content_width(self):
        # 900→1440 连续过渡；宽屏继续增长，保留右侧人物插画的空间。
        """在可用空间内限制正文纸张宽度，宽屏仍为人物插画留空间。"""
        if self.width <= 1440:
            desired = 760 + (self.width - 900) * 340 / 540
        else:
            desired = 1100 + (self.width - 1440) * .72
        available = max(320, self.width - 2 * self.margin_x - 8)
        return bounded(desired, 320, min(2240, available))

    @property
    def hero_height(self):
        """根据宽高余量计算标题/头图区高度并限制最大值。"""
        wide = min(96, max(0, self.width - 1440) * .09)
        tall = min(1, max(0, (self.height - 874) / 300))
        return bounded(self.blend(98, 220) + wide * tall, 98, 316)

    @property
    def paper_gap(self):
        """计算头图与纸张间距，避免大窗口仍拥挤或无限留白。"""
        return bounded(self.blend(6, 50) + max(0, self.height - 874) * .04, 6, 76)

    @property
    def training_height(self):
        """计算训练纸张目标高度，最终布局还需容纳实际内容。"""
        return bounded(self.blend(324, 448) + max(0, self.height - 874) * .36, 324, 680)

    @property
    def input_height(self):
        """计算主动输入区域高度，受开放度和屏幕高度共同限制。"""
        return bounded(self.blend(64, 120) + max(0, self.height - 900) * .30 * self.openness, 64, 260)

    @property
    def composer_width(self):
        """计算 AI 话题纸张宽度，不越出页面可用区域。"""
        return bounded(self.content_width * 1.15, 600, min(1680, max(600, self.width - 2 * self.margin_x - 8)))


@dataclass(frozen=True)
class NavigationLayout:
    """导航区域的有界布局模型，优先保证全部入口可见，再分配摘要空间。"""
    width: int
    compact: bool
    item_count: int = 5
    openness: float | None = None

    MAX_WIDTH = 1400

    @property
    def show_summary(self):
        # 摘要只占有余量的空间，五个入口必须优先保持可见。
        """仅空间足够且有导航项时显示摘要，五个主入口优先。"""
        return self.width >= 920 and self.item_count > 0

    @property
    def summary_width(self):
        """在有摘要资格时分配有界剩余宽度，否则为零。"""
        return bounded((self.width - 920) * .7, 0, 280) if self.show_summary else 0

    @property
    def expansion(self):
        """取得显式或紧凑标记派生的导航开放度。"""
        return float(not self.compact) if self.openness is None else self.openness

    @property
    def height(self):
        """根据导航开放度计算 62–82 逻辑像素的容器高度。"""
        return bounded(62 + self.expansion * 20, 62, 82)
