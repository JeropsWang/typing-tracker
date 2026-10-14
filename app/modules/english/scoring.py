"""Word-aligned sentence accuracy; layout and punctuation do not shift words."""
import re
import unicodedata


def _words(text):
    """规范化 Unicode、大小写和引号，再提取用于一致评分/对齐的单词序列。"""
    text = unicodedata.normalize('NFKC', text).casefold().replace('’', "'").replace('‘', "'")
    return re.findall(r"[^\W_]+(?:['-][^\W_]+)*", text)


def sentence_accuracy(answer, reference):

    """按单词 Levenshtein 距离计算句子错误数和准确率，不使用普通训练逐字评分。"""
    typed, expected = _words(answer), _words(reference)
    previous = list(range(len(expected) + 1))
    for i, word in enumerate(typed, 1):
        current = [i]
        for j, target in enumerate(expected, 1):
            current.append(min(current[-1] + 1, previous[j] + 1,
                               previous[j - 1] + (word != target)))
        previous = current
    errors = previous[-1]
    total = max(len(typed), len(expected), 1)
    return dict(accuracy=max(0, 1 - errors / total) if expected else 0,
                errors=errors, typed_words=len(typed), reference_words=len(expected))


def sentence_alignment(answer, reference):
    """Transient display-only token alignment using the exact existing scoring rules."""
    typed, expected = _words(answer), _words(reference)
    matrix = [list(range(len(expected) + 1))]
    for i, word in enumerate(typed, 1):
        row = [i]
        for j, target in enumerate(expected, 1):
            row.append(min(row[-1] + 1, matrix[-1][j] + 1,
                           matrix[-1][j - 1] + (word != target)))
        matrix.append(row)
    i, j, tokens = len(typed), len(expected), []
    while i or j:
        if i and j and matrix[i][j] == matrix[i-1][j-1] + (typed[i-1] != expected[j-1]):
            tokens.append(dict(kind='equal' if typed[i-1] == expected[j-1] else 'wrong',
                               typed=typed[i-1], expected=expected[j-1]))
            i, j = i-1, j-1
        elif j and matrix[i][j] == matrix[i][j-1] + 1:
            tokens.append(dict(kind='missing', typed='', expected=expected[j-1]))
            j -= 1
        else:
            tokens.append(dict(kind='extra', typed=typed[i-1], expected=''))
            i -= 1
    return tuple(reversed(tokens))
