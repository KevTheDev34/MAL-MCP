"""Sanitized MAL API v2 HTTP fixtures for contract tests."""

from __future__ import annotations

from backend.tests.fixtures.mal_oauth_responses import MAL_USER_RESPONSE

ANIME_NODE = {
    "id": 9253,
    "title": "Steins;Gate",
    "alternative_titles": {
        "synonyms": ["Steins Gate"],
        "en": "Steins;Gate",
        "ja": "シュタインズ・ゲート",
    },
    "media_type": "tv",
    "start_date": "2011-04-06",
    "num_episodes": 24,
    "status": "finished_airing",
}

MANGA_NODE = {
    "id": 642,
    "title": "Monster",
    "alternative_titles": {
        "synonyms": [],
        "en": "Monster",
        "ja": "モンスター",
    },
    "media_type": "manga",
    "start_date": "1994-12-05",
    "num_chapters": 162,
    "num_volumes": 18,
    "status": "finished",
}

ANIME_SEARCH_RESPONSE = {
    "data": [{"node": ANIME_NODE}],
    "paging": {},
}

EMPTY_SEARCH_RESPONSE = {
    "data": [],
    "paging": {},
}

MANGA_SEARCH_RESPONSE = {
    "data": [{"node": MANGA_NODE}],
    "paging": {},
}

ANIME_LIST_STATUS = {
    "status": "completed",
    "score": 9,
    "num_episodes_watched": 24,
    "is_rewatching": False,
    "updated_at": "2024-01-15T12:00:00+00:00",
    "start_date": "2024-01-01",
    "finish_date": "2024-01-10",
}

ANIME_DETAILS_WITH_LIST_STATUS = {
    **ANIME_NODE,
    "my_list_status": ANIME_LIST_STATUS,
}

ANIME_DETAILS_WITHOUT_LIST_STATUS = {
    **ANIME_NODE,
}

MANGA_LIST_STATUS = {
    "status": "completed",
    "score": 10,
    "num_chapters_read": 162,
    "num_volumes_read": 18,
    "is_rereading": False,
    "updated_at": "2024-02-01T12:00:00+00:00",
}

MANGA_DETAILS_WITH_LIST_STATUS = {
    **MANGA_NODE,
    "my_list_status": MANGA_LIST_STATUS,
}

MANGA_DETAILS_WITHOUT_LIST_STATUS = {
    **MANGA_NODE,
}

ANIME_LIST_PAGE_ONE = {
    "data": [
        {
            "node": ANIME_NODE,
            "list_status": ANIME_LIST_STATUS,
        }
    ],
    "paging": {
        "next": "https://api.myanimelist.net/v2/users/@me/animelist?offset=1&limit=1"
    },
}

ANIME_LIST_PAGE_TWO = {
    "data": [
        {
            "node": {
                "id": 1,
                "title": "Cowboy Bebop",
                "alternative_titles": {
                    "synonyms": [],
                    "en": "Cowboy Bebop",
                    "ja": None,
                },
                "media_type": "tv",
                "start_date": "1998-04-03",
                "num_episodes": 26,
            },
            "list_status": {
                "status": "completed",
                "score": 10,
                "num_episodes_watched": 26,
                "is_rewatching": False,
            },
        }
    ],
    "paging": {},
}

EMPTY_ANIME_LIST = {
    "data": [],
    "paging": {},
}

MAL_USER = MAL_USER_RESPONSE
