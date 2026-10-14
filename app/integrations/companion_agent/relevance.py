"""Pure query splitting and conservative topic relevance for browser evidence."""
import re
import unicodedata

QUALIFIERS = re.compile(r'(最新|今天|今日|最近|近期|目前|现在|当前|有哪些|有什么|是什么|怎么样|怎么|如何|请问|帮我|给我|搜索|查找|介绍一下|了解|新闻|热点|的|与|和)')
ENGLISH_GENERIC = {'latest', 'today', 'recent', 'news', 'official', 'website', 'what', 'about', 'the', 'and', 'how'}
INTENT_ALIASES = {
    '省钱': ('节约开支', '节省开支', '减少开支', '节省支出', '减少支出', '节省费用', '消费预算', 'save money', 'saving money'),
    '减肥': ('减重', '体重管理', 'weight loss'),
    '找工作': ('求职', '招聘', 'job search'),
}


def split_query(topic):
    """把中文时间/请求修饰词分隔，减少整句检索失败，保持实际主题。"""
    return ' '.join(QUALIFIERS.sub(r' \1 ', topic).split())


def topic_terms(topic):
    """规范化主题，保留最长中文实体及非泛化英文词，避免类别词放行相似但不同话题。"""
    cleaned = QUALIFIERS.sub(' ', unicodedata.normalize('NFKC', topic).lower())
    chinese = re.findall(r'[\u4e00-\u9fff]{2,}', cleaned)
    # The longest Chinese phrase is the subject. Shorter request/category terms
    # must not allow 明日之后 to stand in for 明日方舟 merely by matching 干员.
    if chinese:
        longest = max(map(len, chinese))
        chinese = [word for word in chinese if len(word) == longest]
    english = [word for word in re.findall(r'[a-z][a-z0-9+.-]{1,}', cleaned)
               if word not in ENGLISH_GENERIC]
    return tuple(chinese + english)


def focused_query(topic):
    """生成备用核心词查询，无可提取实体时保留原规范化查询。"""
    terms = topic_terms(topic)
    return ' '.join(terms) if terms else split_query(topic)


def relevance(topic, source):
    """按实体/常用意图别名及中文连续词片评分，用于保守词面过滤而非语义真实性判断。"""
    terms = topic_terms(topic)
    if not terms:
        return 1.0  # broad requests such as 今日新闻 have no specific entity
    text = unicodedata.normalize('NFKC', source.title + ' ' + source.snippet).lower()
    scores = []
    for word in terms:
        if word in text or any(alias in text for alias in INTENT_ALIASES.get(word, ())):
            scores.append(1.0)
        elif re.fullmatch(r'[\u4e00-\u9fff]{4,}', word):
            pairs = {word[i:i+2] for i in range(len(word)-1)}
            scores.append(sum(pair in text for pair in pairs) / len(pairs))
        else:
            scores.append(0.0)
    return max(scores)
