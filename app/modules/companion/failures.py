"""桌宠纯规则层的错误词表；只允许固定阶段／类别进入来信任务和用户提示。"""

FAILURE_STAGES = {'agent': '智能体', 'model': '模型服务', 'search': '联网搜索'}
FAILURE_REASONS = {
    'unknown': '出现未分类故障，请检查配置后明确重试。',
    'connection': '暂时连接不上，请检查网络和服务是否启动。',
    'auth': '鉴权失败，请检查 API Key 和访问权限。',
    'rate_limit': '请求受限或额度不足，请稍后明确重试。',
    'timeout': '处理超时，请稍后重试或缩小兴趣范围。',
    'protocol': '返回格式或工具调用不兼容，请检查服务与模型。',
    'no_sources': '没有取得可引用的资料，请调整兴趣或搜索服务。',
    'configuration': '配置不完整或不受支持，请检查服务地址和模型名称。',
}
LEGACY_FAILURES = {
    'network': '历史失败原因未细分；请检查模型和搜索连接后明确重试。',
    'cancelled': '这封来信已取消。',
    'configuration_changed': '配置已改变，旧来信已取消。',
    'configuration': '来信配置不正确，请检查模型和搜索设置。',
    'timeout': '来信处理超时，请稍后明确重试。',
    'invalid_report': '来信内容格式不符合保存要求，请检查模型输出。',
    'interrupted': '上次运行中断，未自动重新请求模型。',
    'expired': '这封来信已过期，请现在准备一封。',
}
FAILURE_CODES = frozenset(LEGACY_FAILURES) | frozenset(
    stage + '.' + code for stage in FAILURE_STAGES for code in FAILURE_REASONS)


def normalize_failure_code(code):
    """只保留白名单码，未知输入回退历史通用值；不解析或保存异常原文。"""
    return code if isinstance(code, str) and code in FAILURE_CODES else 'network'


def agent_failure_code(error):
    """从兼容异常的显式属性提取类别，未知异常不依赖文字猜测阶段。"""
    stage, code = getattr(error, 'stage', 'agent'), getattr(error, 'code', 'unknown')
    stage = stage if isinstance(stage, str) and stage in FAILURE_STAGES else 'agent'
    code = code if isinstance(code, str) and code in FAILURE_REASONS else 'unknown'
    return stage + '.' + code


def failure_message(code):
    """把已提交错误码映射为固定中文说明，旧数据不猜写成新的细分原因。"""
    code = normalize_failure_code(code)
    if code in LEGACY_FAILURES:
        return LEGACY_FAILURES[code]
    stage, reason = code.split('.')
    return FAILURE_STAGES[stage] + '：' + FAILURE_REASONS[reason]
