from fugashi import Tagger
import jaconv
import re
import unidic_lite

tagger = Tagger(f"{unidic_lite.DICDIR}")

kanji_re = re.compile(r"[一-龯]")

def align_furigana(surface, reading):
    reading = jaconv.kata2hira(reading)

    result = ""
    i = 0

    for char in surface:
        if kanji_re.match(char):
            # find kana until next surface kana
            kana = ""
            while i < len(reading):
                kana += reading[i]
                i += 1
                if i >= len(reading) or reading[i] not in surface:
                    break

            result += f"<ruby>{char}<rt>{kana}</rt></ruby>"
        else:
            result += char
            if i < len(reading):
                i += 1

    return result


def furigana_html(text):
    out = []

    for word in tagger(text):
        surface = word.surface
        reading = word.feature.kana

        if reading:
            out.append(align_furigana(surface, reading))
        else:
            out.append(surface)

    html = "".join(out)
    return f'<span class="group"><span class="term">{html}</span></span>'
