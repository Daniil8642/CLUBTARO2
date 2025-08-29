import json
import pathlib
import time
from typing import Dict, Tuple

import requests

from mangabuff.config import BASE_URL, CONNECT_TIMEOUT, READ_TIMEOUT, HUGE_LIST_THRESHOLD
from mangabuff.http.http_utils import build_session_from_profile, post
from mangabuff.parsing.cards import parse_trade_cards_html, normalize_card_entry

def fetch_all_cards_by_id(profile_data: Dict, profiles_dir: pathlib.Path, user_id: str, page_size_hint: int = 60, max_pages: int = 500, debug: bool = False) -> Tuple[pathlib.Path, bool]:
    session = build_session_from_profile(profile_data)

    all_cards = []
    offset = 0
    pages = 0

    while True:
        url = f"{BASE_URL}/trades/{user_id}/availableCardsLoad"
        payload = {"offset": offset}
        try:
            resp = post(
                session,
                url,
                headers={
                    "Referer": f"{BASE_URL}/trades/{user_id}",
                    "Origin": BASE_URL,
                    "X-Requested-With": "XMLHttpRequest",
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                },
                data=payload,
            )
        except requests.RequestException as e:
            if debug:
                print(f"[INV] request error offset={offset}: {e}")
            break

        if resp.status_code != 200:
            if debug:
                print(f"[INV] status {resp.status_code} offset={offset}")
            break

        try:
            data = resp.json()
        except ValueError:
            data = {"cards": parse_trade_cards_html(resp.text)}

        cards = data.get("cards", [])
        if not cards:
            break

        if isinstance(cards, list) and len(cards) > HUGE_LIST_THRESHOLD:
            if debug:
                print(f"[INV] too big list {len(cards)} for {user_id}")
            break

        if isinstance(cards, str):
            parsed = parse_trade_cards_html(cards)
            if parsed:
                all_cards.extend(parsed)
            else:
                break
        elif isinstance(cards, list):
            norm = [normalize_card_entry(c) for c in cards]
            all_cards.extend(norm)
        else:
            break

        offset += len(cards) if isinstance(cards, list) else page_size_hint
        pages += 1
        if (isinstance(cards, list) and len(cards) < page_size_hint) or pages >= max_pages:
            break

        time.sleep(0.25)

    cards_path = profiles_dir / f"{user_id}.json"
    with cards_path.open("w", encoding="utf-8") as f:
        json.dump(all_cards, f, ensure_ascii=False, indent=4)
    return cards_path, bool(all_cards)

def ensure_own_inventory(profile_path: pathlib.Path, profile_data: Dict, debug: bool = False) -> pathlib.Path:
    my_id = profile_data.get("id") or profile_data.get("ID") or profile_data.get("user_id")
    if not my_id:
        raise RuntimeError("no user id in profile")
    cards_path, got = fetch_all_cards_by_id(profile_data, profile_path.parent, str(my_id), debug=debug)
    if not got:
        raise RuntimeError("inventory empty")
    return cards_path