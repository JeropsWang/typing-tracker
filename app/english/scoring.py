"""Word-aligned sentence accuracy; layout and punctuation do not shift words."""
import re
import unicodedata


def sentence_accuracy(answer, reference):
    def words(text):
        text = unicodedata.normalize('NFKC', text).casefold().replace('’', "'").replace('‘', "'")
        return re.findall(r"[^\W_]+(?:['-][^\W_]+)*", text)

    typed, expected = words(answer), words(reference)
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
