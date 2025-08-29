import re
import time
from typing import List, Generator, Tuple, Dict

import requests
from bs4 import BeautifulSoup

from mangabuff.config import BASE_URL
from mangabuff.http.http_utils import build_session_from_profile, get
from mangabuff.utils.text import safe_int
from mangabuff.utils.html import with_page, extract_last_page_number


def parse_online_unlocked_owners(html: str) -> List[int]:
    """
    Возвращает список user_id владельцев карты, которые:
      - помечены как онлайн (маркер может быть в классе ссылки, родителя или рядом),
      - и у которых нет признака «замка» на обмен.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    user_ids: List[int] = []
    seen = set()

    def cls_list(n):
        try:
            return [c.lower() for c in (n.get("class") or [])]
        except Exception:
            return []

    def online_here(n) -> bool:
        classes = cls_list(n)
        # Точные классы
        if any(c in ("online", "is-online", "owner--online") for c in classes):
            return True
        # Модификаторы вида card-show_owner--online и т.п.
        if any("online" in c for c in classes):
            return True
        # Частые маркеры в потомках
        return bool(n.select_one(".online, .is-online, .user-online, .avatar__online, .status--online, .badge--online"))

    def has_online_marker(node) -> bool:
        # Сам узел
        if online_here(node):
            return True
        # Родители (до 4 уровней)
        p = node
        for _ in range(4):
            p = getattr(p, "parent", None)
            if not p:
                break
            if online_here(p):
                return True
        # Несколько соседей справа (индикатор рядом со ссылкой)
        sib = getattr(node, "next_sibling", None)
        for _ in range(4):
            if not sib:
                break
            try:
                if hasattr(sib, "select_one") and online_here(sib):
                    return True
            except Exception:
                pass
            sib = getattr(sib, "next_sibling", None)
        return False

    def lock_here(n) -> bool:
        classes = cls_list(n)
        # Типичные варианты классов «замка»
        if any(c in ("lock", "locked", "trade-lock") for c in classes):
            return True
        if any(c.endswith("-lock") or c.endswith("__lock") or "-lock" in c for c in classes):
            return True
        # data-locked
        if n.has_attr("data-locked") and str(n.get("data-locked")).strip() == "1":
            return True
        # Иконки/элементы-замки среди потомков
        if n.select_one(".card-show__owner-icon--trade-lock, .trade-lock, .icon-lock, .icon--lock, .locked"):
            return True
        return False

    def is_locked(node) -> bool:
        # Проверяем у самой ссылки и у нескольких родителей
        if lock_here(node):
            return True
        p = node
        for _ in range(3):
            p = getattr(p, "parent", None)
            if not p:
                break
            if lock_here(p):
                return True
        return False

    # Берём все ссылки на пользователей
    for a in soup.select('a[href^="/users/"]'):
        href = a.get("href") or ""
        m = re.search(r"/users/(\d+)", href)
        if not m:
            continue
        uid = safe_int(m.group(1))
        if not uid or uid in seen:
            continue

        # Онлайн?
        if not has_online_marker(a):
            continue
        # Не «под замком»?
        if is_locked(a):
            continue

        seen.add(uid)
        user_ids.append(uid)

    return user_ids


def iter_online_owners_by_pages(
    profile_data: Dict,
    card_id: int,
    max_pages: int = 0,
    debug: bool = False
) -> Generator[Tuple[int, List[int]], None, None]:
    """
    Итератор по страницам владельцев: на каждой странице отдаёт список user_id,
    которые онлайн и без замка.
    """
    session = build_session_from_profile(profile_data)
    owners_url = f"{BASE_URL}/cards/{card_id}/users"

    try:
        r1 = get(session, with_page(owners_url, 1))
    except requests.RequestException:
        return
    if r1.status_code != 200:
        return

    soup1 = BeautifulSoup(r1.text or "", "html.parser")
    last_page = extract_last_page_number(soup1)
    if max_pages and max_pages > 0:
        last_page = min(last_page, max_pages)

    owners1 = parse_online_unlocked_owners(r1.text)
    if debug:
        print(f"[OWNERS] page 1: {len(owners1)} online unlocked, last_page={last_page}")
    yield 1, owners1

    for p in range(2, last_page + 1):
        try:
            rp = get(session, with_page(owners_url, p))
        except requests.RequestException:
            break
        if rp.status_code != 200:
            break
        owners_p = parse_online_unlocked_owners(rp.text)
        if debug:
            print(f"[OWNERS] page {p}: {len(owners_p)} online unlocked")
        yield p, owners_p
        time.sleep(0.2)