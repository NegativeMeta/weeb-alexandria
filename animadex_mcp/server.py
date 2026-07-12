"""
AnimaDex MCP server (stdio).

Expone la galeria AnimaDex (Flask + SQLite) como un Model Context Protocol
server para que cualquier modelo/agente pueda buscar y consultar personajes,
artistas y copyrights de anime sin tocar HTML.

Se comunica con el backend AnimaDex por HTTP (por defecto
http://127.0.0.1:5000). No necesita la DB local: solo el server corriendo.

Config:
  ANIMADEX_BASE_URL   URL base del backend (default http://127.0.0.1:5000)

Tools:
  search_characters / search_artists / search_copyrights
  get_character_facets / get_artist_facets
  get_facet_values
  get_character (detalle por slug)

Uso:
  python -m mcp.server          (stdio, para MCP clients)
  o el run.bat incluido.
"""

from __future__ import annotations

import os
import urllib.parse
import urllib.request
import json
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

BASE_URL = os.environ.get("ANIMADEX_BASE_URL", "http://127.0.0.1:5000").rstrip("/")

mcp = FastMCP("AnimaDex")


# --------------------------------------------------------------------------
# HTTP helper
# --------------------------------------------------------------------------
def _get(path: str, params: Optional[dict] = None) -> dict:
    """GET JSON from the AnimaDex API. Raises on HTTP errors."""
    url = BASE_URL + path
    if params:
        clean = {k: v for k, v in params.items() if v is not None}
        if clean:
            url += "?" + urllib.parse.urlencode(clean, doseq=True)
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _absolute(url: str) -> str:
    """Turn a relative /thumb/... or /img/... URL into an absolute one."""
    if url.startswith("http://") or url.startswith("https://"):
        return url
    return BASE_URL + url


# Facetas validas por modo (las que expone /api/<mode>/facets)
CHARACTER_FACETS = ["character", "copyright", "hair_color", "hair_length",
                    "eye_color", "gender"]
ARTIST_FACETS = ["artist"]  # el backend define las suyas; lo dejamos abierto


# --------------------------------------------------------------------------
# Tools
# --------------------------------------------------------------------------
@mcp.tool()
def search_characters(
    q: str = "",
    copyright: Optional[str] = None,
    hair_color: Optional[str] = None,
    hair_length: Optional[str] = None,
    eye_color: Optional[str] = None,
    gender: Optional[str] = None,
    sort: str = "count",
    page: int = 1,
) -> dict:
    """Busca personajes de anime en AnimaDex.

    Args:
        q: texto libre (nombre, trigger, tags). Vacio = sin filtro de texto.
        copyright: serie/franchise (ej. 'vocaloid', 'touhou').
        hair_color: color de pelo (ej. 'blue', 'aqua').
        hair_length: largo de pelo (ej. 'long', 'short').
        eye_color: color de ojos (ej. 'blue', 'red').
        gender: 'female' | 'male' | 'other'.
        sort: 'count' (popularidad) | 'name' | 'random'.
        page: numero de pagina (empieza en 1).

    Returns: total, page, page_size, pages y lista de resultados con
        slug, name, copyright, trigger, tags, count, thumb_url e img_url
        (estas dos ultimas como URLs absolutas).
    """
    params: dict[str, Any] = {"q": q, "sort": sort, "page": page}
    if copyright:
        params["copyright"] = copyright
    if hair_color:
        params["hair_color"] = hair_color
    if hair_length:
        params["hair_length"] = hair_length
    if eye_color:
        params["eye_color"] = eye_color
    if gender:
        params["gender"] = gender
    data = _get("/api/characters/search", params)
    for r in data.get("results", []):
        if r.get("thumb_url"):
            r["thumb_url"] = _absolute(r["thumb_url"])
        if r.get("img_url"):
            r["img_url"] = _absolute(r["img_url"])
    return data


@mcp.tool()
def search_artists(q: str = "", sort: str = "count", page: int = 1) -> dict:
    """Busca artistas en AnimaDex.

    Args:
        q: texto libre (nombre del artista).
        sort: 'count' | 'name' | 'random'.
        page: numero de pagina.

    Returns: resultados con slug, name, trigger, count, score,
        thumb_url e img_url absolutos.
    """
    data = _get("/api/artists/search", {"q": q, "sort": sort, "page": page})
    for r in data.get("results", []):
        if r.get("thumb_url"):
            r["thumb_url"] = _absolute(r["thumb_url"])
        if r.get("img_url"):
            r["img_url"] = _absolute(r["img_url"])
    return data


@mcp.tool()
def search_copyrights(q: str = "", sort: str = "count", page: int = 1) -> dict:
    """Busca series/franchises (copyrights) en AnimaDex.

    Args:
        q: texto libre (nombre de la serie).
        sort: 'count' | 'name' | 'random'.
        page: numero de pagina.

    Returns: resultados con slug, name, count y thumb_url absoluto
        (collage 2x2 de la serie).
    """
    data = _get("/api/copyrights/search", {"q": q, "sort": sort, "page": page})
    for r in data.get("results", []):
        if r.get("thumb_url"):
            r["thumb_url"] = _absolute(r["thumb_url"])
    return data


@mcp.tool()
def get_character_facets() -> dict:
    """Devuelve las facetas disponibles para filtrar personajes y sus
    valores mas comunes (character, copyright, hair_color, hair_length,
    eye_color, gender). Util para que el modelo sepa que valores pasar a
    search_characters."""
    return _get("/api/characters/facets")


@mcp.tool()
def get_artist_facets() -> dict:
    """Devuelve las facetas disponibles para artistas."""
    return _get("/api/artists/facets")


@mcp.tool()
def get_facet_values(mode: str, facet: str, q: str = "") -> dict:
    """Lista los valores posibles de una faceta concreta.

    Args:
        mode: 'characters' | 'artists'.
        facet: nombre de la faceta (ej. 'hair_color', 'copyright',
            'gender'). En characters tambien: 'character', 'hair_length',
            'eye_color'.
        q: filtra los valores por texto (opcional).

    Returns: diccionario con los valores y su conteo.
    """
    if mode not in ("characters", "artists"):
        raise ValueError("mode debe ser 'characters' o 'artists'")
    return _get(f"/api/{mode}/facet/{facet}", {"q": q})


@mcp.tool()
def get_character(slug: str) -> dict:
    """Devuelve el detalle completo de un personaje por su slug.

    Args:
        slug: identificador unico (ej. 'hatsune_miku'). Obtenelo de
            search_characters o get_facet_values.

    Returns: el objeto personaje completo (name, copyright, trigger, tags,
        count, url, loras, thumb_url e img_url absolutos).
    """
    # El backend no tiene GET /api/characters/<slug>; usamos search con
    # el slug exacto y devolvemos el primer match.
    data = _get("/api/characters/search", {"q": slug, "page": 1})
    for r in data.get("results", []):
        if r.get("thumb_url"):
            r["thumb_url"] = _absolute(r["thumb_url"])
        if r.get("img_url"):
            r["img_url"] = _absolute(r["img_url"])
    match = next((r for r in data.get("results", []) if r.get("slug") == slug), None)
    return match if match is not None else {
        "error": f"personaje '{slug}' no encontrado",
        "candidates": [r.get("slug") for r in data.get("results", [])[:10]],
    }


if __name__ == "__main__":
    mcp.run()  # stdio por defecto
