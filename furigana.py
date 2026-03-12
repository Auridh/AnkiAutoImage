from fugashi import Tagger
import jaconv
import re
import unidic_lite

tagger = Tagger(f"{unidic_lite.DICDIR}")

kanji_re = re.compile(r"[一-龯]")

def ruby_for_word(surface, reading):
    """Return surface with furigana in ruby if it contains kanji, otherwise plain."""
    if not reading:  # no reading available
        return f"<span>{surface}</span>"

    reading = jaconv.kata2hira(reading)
    if kanji_re.search(surface):
        return f"<ruby>{surface}<rt>{reading}</rt></ruby>"
    else:
        return f"<span>{surface}</span>"

def furigana_html(text):
    """
    Convert text into HTML with furigana.
    Highlight spans are preserved and furigana is applied inside them.
    Other text is split into <span> blocks per token.
    """
    # Split input by highlight spans
    parts = re.split(r'(<span class="highlight">.*?</span>)', text)
    out = []

    for part in parts:
        if part.startswith('<span class="highlight">'):
            # Extract inner text
            inner = re.sub(r'^<span class="highlight">|</span>$', '', part)
            processed = "".join(
                ruby_for_word(word.surface, word.feature.kana)
                for word in tagger(inner)
            )
            out.append(f'<span class="highlight">{processed}</span>')
        else:
            # Regular text
            processed = "".join(
                ruby_for_word(word.surface, word.feature.kana)
                for word in tagger(part)
            )
            out.append(processed)

    return "".join(out)
