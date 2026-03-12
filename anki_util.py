from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple

from aqt import mw
from anki.notes import Note
from anki.collection import Collection


@dataclass
class NoteTarget:
    nid: int
    note_type_name: str

def get_selected_note_ids(browser) -> List[int]:
    # Try modern attribute first
    try:
        if hasattr(browser, "selected_notes"):
            nids = browser.selected_notes()
            return list(nids)
    except Exception:
        pass

    # Legacy API
    try:
        return list(browser.selectedNotes())
    except Exception:
        pass

    # Fallback via selected cards mapping to notes
    try:
        cids = []
        if hasattr(browser, "selected_cards"):
            cids = list(browser.selected_cards())
        elif hasattr(browser, "selectedCards"):
            cids = list(browser.selectedCards())
        nids: List[int] = []
        col = mw.col  # type: ignore
        for cid in cids:
            try:
                card = col.get_card(cid)
                nids.append(card.nid)
            except Exception:
                continue
        return nids
    except Exception:
        return []

def get_deck_note_ids(col: Collection, deck_name: str) -> List[int]:
    # Include deck and its subdecks
    name = deck_name or ""
    name_escaped = name.replace('"', '\\"')
    queries: List[str] = []

    if name_escaped:
        queries.append(f"deck:\"{name_escaped}\"")
        queries.append(f"deck:\"{name_escaped}::*\"")
    else:
        # Fallback: all notes
        queries.append("")

    query = " or ".join(q for q in queries if q)
    nids = col.find_notes(query)
    return list(nids)

def ensure_media_filename_safe(name: str) -> str:
    # Keep it ASCII-ish and Anki-safe
    name = name.strip().replace(" ", "_")
    name = re.sub(r"[^A-Za-z0-9_.-]", "", name)
    return name or f"image_{int(time.time())}.jpg"

def get_next_note_group(note: Note, field_name: str) -> Optional[int]:
    numbers = re.findall(r'class="group(\d*)"', note[field_name])
    numbers = [int(n) if n else 1 for n in numbers]

    max_number = max(numbers, default=0)
    detection_count = len(numbers)

    return max(max_number, detection_count) + 1

def add_to_note_field(note: Note, field_name: str, template: str, value: str, group: bool = False) -> bool:
    if field_name not in note:
        return False

    if not group:
        template = template.replace('##GROUP##', '')
    else:
        template = template.replace('##GROUP##', str(get_next_note_group(note, field_name)))
    
    if not note[field_name]:
        note[field_name] = template.replace('##OLD##', '').replace('##NEW##', value)
    else:
        note[field_name] = template.replace('##OLD##', note[field_name]).replace('##NEW##', value)

    return True

def add_image_to_note(note: Note, field_name: str, media_filename: str, tempalte: Optional[str] = None) -> bool:
    img_tag = f"<img src=\"{media_filename}\">"

    if template is None:
        template = '##OLD##</br>##NEW##'

    return add_to_note_field(note, field_name, template, img_tag)
    
def add_audio_to_note(note: Note, field_name: str, media_filename: str, template: Optional[str] = None) -> bool:
    audio_tag = f"[sound:{media_filename}]"

    if template is None:
        template = '##OLD##\n##NEW##'

    return add_to_note_field(note, field_name, template, audio_tag)

def add_sentence_to_note(note: Note, field_name: str, value: str, template: Optional[str] = None) -> bool:
    if template is None:
        template = '##OLD##<span class="group">##NEW##</span>'
    return add_to_note_field(note, field_name, template, value)

def add_sentence_translation_to_note(note: Note, field_name: str, value: str, template: Optional[str] = None) -> bool:
    if template is None:
        template = '##OLD##<span class="group##GROUP##">##NEW##</span>'
    return add_to_note_field(note, field_name, template, value, True)

def add_misc_to_note(note: Note, field_name: str, value: str, template: Optional[str] = None) -> bool:
    if template is None:
        template = '##OLD##<span class="group##GROUP##">##NEW##</span>'
    return add_to_note_field(note, field_name, template, value, True)

def get_field_value(note: Note, field_name: str) -> str:
    try:
        return note[field_name]
    except Exception:
        return ""


