from __future__ import annotations

import os
import json
from typing import Any, Dict, List, Tuple
import re
from urllib.parse import urlparse

from aqt.qt import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QComboBox, QPushButton 
from aqt.qt import qconnect
from aqt import mw
from aqt.utils import showInfo, showWarning, showCritical

from .logger import get_logger
from .anki_util import get_selected_note_ids, get_deck_note_ids, ensure_media_filename_safe, get_field_value, add_audio_to_note, add_image_to_note, add_sentence_to_note, add_sentence_translation_to_note, add_misc_to_note, add_sentence_furigana_to_note
from .nadeshiko_api import NadeshikoApiClient


def _addon_package_name() -> str:
    try:
        return os.path.basename(os.path.dirname(__file__))
    except Exception:
        return ""


def _read_config() -> Dict[str, Any]:
    """
    Read configuration from Anki's add-on config (meta.json),
    falling back to bundled config.json defaults if needed.
    """
    # 1) Try Anki-managed config (user-edited via Config dialog)
    try:
        pkg = _addon_package_name()
        if pkg:
            cfg = mw.addonManager.getConfig(pkg)  # type: ignore[attr-defined]
            if isinstance(cfg, dict) and cfg:
                return cfg
    except Exception:
        pass

    # 2) Fallback to local config.json (defaults)
    try:
        base_dir = os.path.dirname(__file__)
        config_path = os.path.join(base_dir, "config.json")
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

class BackfillImagesDialog(QDialog):
    def __init__(self, mw, mode: str, browser=None) -> None:
        super().__init__(mw)
        self.mw = mw
        self.mode = mode  # "deck" or "browser"
        self.browser = browser
        self.logger = get_logger()
        self.cfg = _read_config()
        self.setWindowTitle("AutoImage")
        self._build_ui()

    def _add_ui_field(self, label: str, layout: QVBoxLayout) -> Tuple[QHBoxLayout, QLabel, QComboBox]:
        row = QHBoxLayout()
        lbl = QLabel(label)
        row.addWidget(lbl)
        field = QComboBox(self)
        row.addWidget(field)
        layout.addLayout(row)
        return row, lbl, field

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # Deck selector (only for deck mode)
        if self.mode == "deck":
            row = QHBoxLayout()
            row.addWidget(QLabel("Deck"))
            self.deck_combo = QComboBox(self)
            # Be compatible with multiple Anki versions
            try:
                items = list(self.mw.col.decks.all_names_and_ids())
            except Exception:
                items = []
            for item in items:
                name = getattr(item, "name", None)
                if not name and isinstance(item, (list, tuple)) and len(item) >= 1:
                    name = item[0] if isinstance(item[0], str) else None
                if name:
                    self.deck_combo.addItem(name)
            row.addWidget(self.deck_combo)
            layout.addLayout(row)

        # Field selectors (dropdowns populated from deck/selection)
        _, _, self.query_field = self._add_ui_field("Query Field", layout)    

        # Nadeshiko fields
        self._row_nade_img, self.lbl_nade_img, self.nade_image_field = self._add_ui_field("Image Field", layout)
        self._row_nade_audio, self.lbl_nade_audio, self.nade_audio_field = self._add_ui_field("Audio Field", layout)
        self._row_nade_sentence, self.lbl_nade_sentence, self.nade_sentence_field = self._add_ui_field("Sentence Field", layout)
        self._row_nade_sentence_furigana, self.lbl_nade_sentence_furigana, self.nade_sentence_furigana_field = self._add_ui_field("Sentence Furigana Field", layout)
        self._row_nade_sentence_translation, self.lbl_nade_sentence_translation, self.nade_sentence_translation_field = self._add_ui_field("Sentence Translation Field", layout)
        self._row_nade_misc, self.lbl_nade_misc, self.nade_misc_field = self._add_ui_field("Misc field", layout)
    
        # Buttons
        row_btn = QHBoxLayout()
        self.run_btn = QPushButton("Run")
        self.cancel_btn = QPushButton("Cancel")
        row_btn.addWidget(self.run_btn)
        row_btn.addWidget(self.cancel_btn)
        layout.addLayout(row_btn)    

        qconnect(self.cancel_btn.clicked, self.reject)
        qconnect(self.run_btn.clicked, lambda: _on_run(self))
        
        # Populate field dropdowns initially and on deck change
        try:
            _refresh_field_dropdowns(self)
        except Exception:
            pass

        if hasattr(self, "deck_combo"):
            try:
                qconnect(self.deck_combo.currentTextChanged, lambda _=None: _refresh_field_dropdowns(self))
            except Exception:
                pass


def _strip_tags(text: str) -> str:
    try:
        return re.sub(r"<[^>]+>", "", text or "")
    except Exception:
        return text or ""


def _nade_format_sentence(seg: Dict[str, Any], lang_code: str) -> str:
    """
    Return sentence text for the requested language, bolding the highlighted term.

    Uses the API's *_highlight field if available (which wraps matches in <em>),
    and converts <em>..</em> to <span class='highlight'>..</span>. Falls back to plain content if highlight
    is missing.
    """
    try:
        lc = (lang_code or "jp").lower()
        plain_key = f"content_{'en' if lc=='en' else ('es' if lc=='es' else 'jp')}"
        hl_key = f"{plain_key}_highlight"
        hl = str(seg.get(hl_key, "") or "").strip()
        if hl:
            return hl.replace("<em>", '<span class="highlight">').replace("</em>", "</span>")
        return str(seg.get(plain_key, "") or "").strip()
    except Exception:
        return str(seg.get("content_jp", "") or "").strip()

def _nade_format_misc(base: Dict[str, Any], seg: Dict[str, Any]) -> str:
    title_jp = str(base.get("name_anime_jp", "")).strip()
    title_en = str(base.get("name_anime_en", "")).strip()

    title = title_jp
    if title_jp and title_en:
        title = f"{title_jp} / {title_en}"

    season = str(base.get("season", "")).strip()
    episode = str(base.get("episode", "")).strip()
    time = str(seg.get("start_time", "")).strip()

    misc = f"{title}"
    if season and episode:
        misc = f"{misc} • Season {season}, Episode {episode}"
    elif episode:
        misc = f"{misc} • Episode {episode}"
    elif season:
        misc = f"{misc} • Season {season}"

    if time:
        time = time.split('.')[0]
        misc = f"{misc} • {time}"

    return misc

def _nade_origin(base_url: str) -> str:
    try:
        p = urlparse(base_url)
        if p.scheme and p.netloc:
            return f"{p.scheme}://{p.netloc}"
    except Exception:
        pass
    # Fallback: strip known '/api/...' suffixes
    base = str(base_url or "").strip()
    idx = base.find("/api/")
    return base[:idx] if idx != -1 else base.rstrip("/")

def _nade_normalize_url(url: str, base_url: str) -> str:
    u = str(url or "").strip()
    if not u:
        return u
    # Replace backslashes with forward slashes (API sometimes returns '\\')
    u = u.replace("\\", "/")
    if u.startswith("http://") or u.startswith("https://"):
        return u
    origin = _nade_origin(base_url)
    if u.startswith("/"):
        return f"{origin}{u}"
    return f"{origin}/{u}"

def _nade_pick_sentences(sentences: List[Dict[str, Any]], count: int = 1) -> List[Dict[str, Any]]:
    """
    Return the top sentence items with the longest text content.

    Ignores the search term and prefers items whose Japanese sentence
    (content_jp or stripped content_jp_highlight) is longest.
    """
    scored = []

    for it in (sentences or []):
        try:
            seg = (it or {}).get("segment_info") or {}
            jp = str(seg.get("content_jp", ""))
            hl = _strip_tags(str(seg.get("content_jp_highlight", "")))
            cand = jp if len(jp) >= len(hl) else hl
            scored.append((len(cand), it))
        except Exception:
            continue

    if not scored:
        return []

    # sort by length descending
    scored.sort(key=lambda x: x[0], reverse=True)

    return [it for _, it in scored[:max(count, 0)]]


def _collect_field_names(self, nids: List[int]) -> List[str]:
    col = self.mw.col
    seen: Dict[str, None] = {}
    for nid in (nids or [])[:1000]:
        try:
            note = col.get_note(nid)
            try:
                for name in list(note.keys()):  # type: ignore[attr-defined]
                    if isinstance(name, str) and name and name not in seen:
                        seen[name] = None
            except Exception:
                try:
                    model = note.note_type()  # type: ignore[attr-defined]
                    for fld in (model or {}).get("flds", []):
                        name = fld.get("name")
                        if isinstance(name, str) and name and name not in seen:
                            seen[name] = None
                except Exception:
                    pass
        except Exception:
            continue
    return list(seen.keys())

def _refresh_field_dropdowns(self) -> None:
    col = self.mw.col
    if self.mode == "browser" and self.browser is not None:
        nids = get_selected_note_ids(self.browser)
    else:
        deck_name = self.deck_combo.currentText() if hasattr(self, "deck_combo") else ""
        nids = get_deck_note_ids(col, deck_name)

    fields = _collect_field_names(self, nids) if nids else []    

    def _pick_default(candidates: List[str], preferred: List[str]) -> int:
        for pref in preferred:
            if pref in candidates:
                return candidates.index(pref)
        return 0

    self.query_field.blockSignals(True)
    self.nade_image_field.blockSignals(True)
    self.nade_audio_field.blockSignals(True)
    self.nade_sentence_field.blockSignals(True)
    self.nade_sentence_furigana_field.blockSignals(True)
    self.nade_sentence_translation_field.blockSignals(True)
    self.nade_misc_field.blockSignals(True)

    self.query_field.clear()
    self.nade_image_field.clear()
    self.nade_audio_field.clear()
    self.nade_sentence_field.clear()
    self.nade_sentence_furigana_field.clear()
    self.nade_sentence_translation_field.clear()
    self.nade_misc_field.clear()

    self.query_field.addItems(fields)
    self.nade_image_field.addItems(fields)
    self.nade_audio_field.addItems(fields)
    self.nade_sentence_field.addItems(fields)
    self.nade_sentence_furigana_field.addItems(fields)
    self.nade_sentence_translation_field.addItems(fields)
    self.nade_misc_field.addItems(fields)

    self.query_field.setCurrentIndex(_pick_default(fields, [self.cfg.get("query_field", "word"), "Expression", "Front", "Word", "Term"]))
    self.nade_image_field.setCurrentIndex(_pick_default(fields, [self.cfg.get("image_field", "picture"), "Picture", "Image", "Images", "Back"]))
    self.nade_audio_field.setCurrentIndex(_pick_default(fields, [self.cfg.get("audio_field", "sentenceAudio"), "Audio", "Sound", "音声"]))
    self.nade_sentence_field.setCurrentIndex(_pick_default(fields, [self.cfg.get("sentence_field", "sentence"), "Sentence", "Text", "Front", "Expression"]))
    self.nade_sentence_furigana_field.setCurrentIndex(_pick_default(fields, [self.cfg.get("sentence_furigana_field", "sentenceFurigana"), "SentenceFurigana", "Furigana"]))
    self.nade_sentence_translation_field.setCurrentIndex(_pick_default(fields, [self.cfg.get("sentence_translation_field", "sentenceTranslation"), "SentenceTranslation", "SentenceEng", "Translation"]))
    self.nade_misc_field.setCurrentIndex(_pick_default(fields, [self.cfg.get("misc_field", "miscInfo"), "Misc", "MiscInfo", "miscellaneous", "Miscellaneous"]))    

    self.query_field.blockSignals(False)
    self.nade_image_field.blockSignals(False)
    self.nade_audio_field.blockSignals(False)
    self.nade_sentence_field.blockSignals(False)
    self.nade_sentence_furigana_field.blockSignals(False)
    self.nade_sentence_translation_field.blockSignals(False)
    self.nade_misc_field.blockSignals(False)

def add_to_note(
    cfg,
    logger,
    client,
    media,
    note,
    query_text: str,
    base_url: str,
    nid: int,
    img_field: str,
    aud_field: str,
    sent_field: str,
    furi_field: str,
    trans_field: str,
    misc_field: str,
    sentence: Dict[str, Any]
) -> bool:
    basic_info = (sentence or {}).get("basic_info") or {}
    segment_info = (sentence or {}).get("segment_info") or {}
    media_info = (sentence or {}).get("media_info") or {}

    text = _nade_format_sentence(segment_info, str(cfg.get("nadeshiko_sentence_lang", "jp")).lower())
    trans = _nade_format_sentence(segment_info, str(cfg.get("nadeshiko_translation_lang", "en")).lower()) 
    misc = _nade_format_misc(basic_info, segment_info)

    if trans_field and trans_field in note:
        if not add_sentence_translation_to_note(note, trans_field, trans, cfg.get("sentence_translation_template", None), sent_field):
            logger.error(f"Nadeshiko adding sentence translation failed for '{query_text}'.")
            return False

    if furi_field and furi_field in note:
        if not add_sentence_furigana_to_note(note, furi_field, text, cfg.get("sentence_furigana_template", None)):
            logger.error(f"Nadeshiko adding sentence furigana failed for '{query_text}'.")
            return False

    if misc_field and misc_field in note:
        if not add_misc_to_note(note, misc_field, misc, cfg.get("misc_template", None), sent_field):
            logger.error(f"Nadeshiko adding misc info failed for '{query_text}'.")
            return False

    if sent_field and sent_field in note:
        if not add_sentence_to_note(note, sent_field, text, cfg.get("sentence_template", None)):
            logger.error(f"Nadeshiko adding sentence failed for '{query_text}'.")
            return False

    # Normalize URLs as done in the reviewer hotkey path
    img_url = _nade_normalize_url(media_info.get("path_image", ""), base_url)
    audio_url = _nade_normalize_url(media_info.get("path_audio", ""), base_url)

    # Download media independently so a failure in one does not prevent sentence-only updates
    if img_url and img_field in note:
        try:
            img_bytes = client.download(img_url)
            tail = img_url.split("/")[-1].split("?")[0] or f"nade_{nid}.jpg"
            media_name_img = media.write_data(ensure_media_filename_safe(tail), img_bytes)
            if not add_image_to_note(note, img_field, media_name_img, cfg.get("image_template", None)):
                logger.error(f"Nadeshiko adding image failed for '{query_text}'.")
                return False
        except Exception as e:
            logger.error(f"Nadeshiko image download failed for '{query_text}': {e}")
            return False

    if audio_url and aud_field in note:
        try:
            aud_bytes = client.download(audio_url)
            tail = audio_url.split("/")[-1].split("?")[0] or f"nade_{nid}.mp3"
            media_name_aud = media.write_data(ensure_media_filename_safe(tail), aud_bytes)
            if not add_audio_to_note(note, aud_field, media_name_aud, cfg.get("audio_template", None)):
                logger.error(f"Nadeshiko adding audio failed for '{query_text}'.")
                return False
        except Exception as e:
            logger.error(f"Nadeshiko audio download failed for '{query_text}': {e}")
            return False

    return True

def _on_run(self) -> None:
    query_field = (self.query_field.currentText().strip() if hasattr(self.query_field, "currentText") else str(self.query_field.text()).strip())

    # Validate provider prerequisites up-front to avoid silent no-ops
    key_check = str(self.cfg.get("nadeshiko_api_key", "")).strip()
    if not key_check:
        showWarning("nadeshiko_api_key is missing in config.json")
        return

    if not query_field:
        showWarning("Please specify a Query Field.")
        return

    col = self.mw.col
    if self.mode == "browser" and self.browser is not None:
        nids = get_selected_note_ids(self.browser)
        if not nids:
            showWarning("No notes selected. Please select notes in the Browser and try again.")
            return
    else:
        deck_name = self.deck_combo.currentText() if hasattr(self, "deck_combo") else ""
        nids = get_deck_note_ids(col, deck_name)
        self.logger.info(f"Searching deck: '{deck_name}' -> found {len(nids)} note ids")

    if not nids:
        showInfo("No notes found to update.")
        self.accept()
        return

    updated = 0
    empty_queries = 0
    nade_no_result = 0

    for nid in nids:
        note = col.get_note(nid)
        query_text = get_field_value(note, query_field).strip()
        if not query_text:
            empty_queries += 1
            continue

        try:
            key = str(self.cfg.get("nadeshiko_api_key", "")).strip()
            if not key:
                continue

            base_url = str(self.cfg.get("nadeshiko_base_url", "https://api.brigadasos.xyz/api/v1")).strip() or "https://api.brigadasos.xyz/api/v1"
            client = NadeshikoApiClient(key, base_url=base_url)
            # Ask API for the longest sentence, with a sensible minimum length
            min_len = int(self.cfg.get("nadeshiko_min_length", 6))
            max_len = int(self.cfg.get("nadeshiko_max_length", 0)) or None
            limit = int(self.cfg.get("count", 1))

            res = client.search_sentences(
                query=query_text,
                limit=limit,
                content_sort="DESC",
                min_length=min_len,
                max_length=max_len,
            )
            sentences = (res or {}).get("sentences") or []
            if not sentences:
                nade_no_result += 1
                continue

            img_field = self.nade_image_field.currentText().strip()
            aud_field = self.nade_audio_field.currentText().strip()
            sent_field = self.nade_sentence_field.currentText().strip()
            furi_field = self.nade_sentence_furigana_field.currentText().strip()
            trans_field = self.nade_sentence_translation_field.currentText().strip()    
            misc_field = self.nade_misc_field.currentText().strip()

            selection = _nade_pick_sentences(sentences, limit)
            selection_success = False
            for sentence in selection:
                success = add_to_note(self.cfg,
                                      self.logger,
                                      client,
                                      self.mw.col.media,
                                      note,
                                      query_text,
                                      base_url,
                                      nid,
                                      img_field,
                                      aud_field,
                                      sent_field,
                                      furi_field,
                                      trans_field,
                                      misc_field,
                                      sentence)
                if not success:
                    continue
                selection_success = True
            
            # Always flush any changes (including sentence-only)
            note.flush()
            if selection_success:
                updated += 1
            continue
        except Exception as e:
            self.logger.error(f"Nadeshiko: {e}")
            continue
    
    col.reset()
    self.mw.reset()
    
    msg = f"Updated {updated} notes."
    if nade_no_result:
        msg += f" No Nadeshiko results for {nade_no_result} note(s)."
    if empty_queries:
        msg += f" Empty query field on {empty_queries} note(s)."
    showInfo(msg)

    self.accept()

class LoggerProxy:
    def __init__(self):
        self.info = showInfo
        self.warning = showWarning
        self.error = showCritical

# Reviewer hotkey quick-add support
def quick_add_nadeshiko_for_current_card(mw) -> None:
    """Add an image and audio from Nadeshiko API to current reviewer card.

    Always overwrites the target image/audio fields. Uses saved query/target/suffix if available.
    Config keys used:
    - nadeshiko_api_key
    - nadeshiko_base_url 
    - image_field 
    - audio_field 
    - sentence_field
    - sentence_translation_field
    - misc_field
    - *_template (for each field) 
    """
    try:
        if getattr(mw, "state", "") != "review" or not getattr(getattr(mw, "reviewer", None), "card", None):
            showWarning("No active card to update.")
            return
        col = mw.col
        card = mw.reviewer.card
        note = col.get_note(card.nid)

        cfg = _read_config()

        def _field_names(n) -> List[str]:
            try:
                return list(n.keys())  # type: ignore[attr-defined]
            except Exception:
                return []
        def _pick_field(candidates: List[str], preferred: List[str]) -> str:
            for pref in preferred:
                if pref in candidates:
                    return candidates[candidates.index(pref)]
            return "" 

        fields = _field_names(note)
        query_field = _pick_field(fields, [cfg.get("query_field", "word"), "Expression", "Front", "Word", "Term"])
        image_field = _pick_field(fields, [cfg.get("image_field", "picture"), "Picture", "Image", "Images", "Back"])
        audio_field = _pick_field(fields, [cfg.get("audio_field", "sentenceAudio"), "Audio", "Sound", "音声"])
        sentence_field = _pick_field(fields, [cfg.get("sentence_field", "sentence"), "Sentence", "Text", "Front", "Expression"])
        sentence_furigana_field = _pick_field(fields, [cfg.get("sentence_furigana_field", "sentenceFurigana"), "SentenceFurigana", "Furigana"])
        sentence_translation_field = _pick_field(fields, [cfg.get("sentence_translation_field", "sentenceTranslation"), "SentenceTranslation", "SentenceEng", "Translation"])
        misc_field = _pick_field(fields, [cfg.get("misc_field", "miscInfo"), "Misc", "MiscInfo", "miscellaneous", "Miscellaneous"])    

        if not query_field or not image_field or not audio_field or not sentence_field or not sentence_translation_field or not misc_field or not sentence_furigana_field:
            showWarning("Could not determine fields to update.")
            return

        query_text = get_field_value(note, query_field).strip()
        if not query_text:
            showInfo(f"Query field '{query_field}' is empty; nothing to do.")
            return

        key = str(cfg.get("nadeshiko_api_key", "")).strip()
        if not key:
            showWarning("Missing nadeshiko_api_key in config.json")
            return
        base_url = str(cfg.get("nadeshiko_base_url", "https://api.brigadasos.xyz/api/v1")).strip() or "https://api.brigadasos.xyz/api/v1"
        client = NadeshikoApiClient(key, base_url=base_url)

        # Ask API for the longest sentence, with a sensible minimum length
        min_len = int(cfg.get("nadeshiko_min_length", 6))
        max_len = int(cfg.get("nadeshiko_max_length", 0)) or None
        limit = int(cfg.get("count", 1))
        data = client.search_sentences(
            query=query_text,
            limit=limit,
            content_sort="DESC",
            min_length=min_len,
            max_length=max_len,
        )
        sentences = (data or {}).get("sentences") or []
        if not sentences:
            showInfo("No Nadeshiko results found.")
            return
    
        selection = _nade_pick_sentences(sentences, limit)
        updated = False

        for item in selection:
            success = add_to_note(cfg,
                                  LoggerProxy(),
                                  client,
                                  col.media,
                                  note,
                                  query_text,
                                  base_url,
                                  card.nid,
                                  image_field,
                                  audio_field,
                                  sentence_field,
                                  sentence_furigana_field,
                                  sentence_translation_field,
                                  misc_field,
                                  item)
            if not success:
                continue
            updated = True

        if updated:
            note.flush()
            col.reset()
            mw.reset()
            showInfo("Nadeshiko media (and sentence) added to current card.")
        else:
            showInfo("Nothing was updated.")
    except Exception as e:
        showWarning(f"Failed to add Nadeshiko media: {e}")

