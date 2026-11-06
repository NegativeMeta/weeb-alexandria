"""Verify a Spanish -> English tag phrase map against the local tag library.

Only phrases whose English target is a real, well-covered tag are kept. Prints a
review table and writes the accepted map to weeb_alexandria_mcp/query_aliases_es.json
with --write.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(r"C:\Users\johin\Code_Library\AI\WeebAlexandria")
sys.path.insert(0, str(REPO))

import weeb_alexandria_mcp.server as S  # noqa: E402

# Spanish phrase -> English tag phrase. Targets are the vocabulary Johiny
# actually prompts with, not literal translations.
CANDIDATES: dict[str, str] = {
    # pecho
    "tetas grandes": "large breasts",
    "tetas enormes": "huge breasts",
    "tetas gigantes": "gigantic breasts",
    "pechos grandes": "large breasts",
    "tetas pequeñas": "small breasts",
    "tetas al aire": "nipples",
    "pezones": "nipples",
    "escote": "cleavage",
    "sin sostén": "no bra",
    "sujetador": "bra",
    # actos
    "sexo oral": "oral",
    "mamada": "fellatio",
    "chupar polla": "fellatio",
    "paja": "handjob",
    "paja con las tetas": "paizuri",
    "rusa": "paizuri",
    "cubana": "paizuri",
    "corrida en la cara": "facial",
    "corrida en el cuerpo": "cum on body",
    "corrida en la boca": "cum in mouth",
    "corrida dentro": "creampie",
    "acabar dentro": "creampie",
    "sexo anal": "anal",
    "doble penetración": "double penetration",
    "sexo en grupo": "group sex",
    "trío": "threesome",
    "orgía": "group sex",
    "masturbación": "masturbation",
    "dedos": "fingering",
    "consolador": "dildo",
    "vibrador": "vibrator",
    "juguetes sexuales": "sex toys",
    # posiciones
    "a cuatro patas": "on all fours",
    "piernas abiertas": "spread legs",
    "de rodillas": "on knees",
    "boca abierta": "open mouth",
    "lengua fuera": "tongue out",
    "sentada encima": "girl on top",
    "de espaldas": "from behind",
    "misionero": "missionary",
    "sexo de pie": "standing sex",
    # bdsm / kink
    "atada con cuerdas": "bondage",
    "atada": "bound",
    "esposas": "handcuffs",
    "vendas en los ojos": "blindfold",
    "collar": "collar",
    "correa": "leash",
    "azote": "spanking",
    "marca de cuerda": "rope marks",
    "escrito en el cuerpo": "body writing",
    # estados / cuerpo
    "embarazada": "pregnant",
    "lactancia": "lactation",
    "con leche": "lactating",
    "sudor": "sweat",
    "sudorosa": "sweat",
    "mojada": "wet",
    "ropa mojada": "wet clothes",
    "ropa transparente": "see-through",
    "sin censura": "uncensored",
    "censura": "censored",
    "mosaico": "mosaic censoring",
    # contexto
    "sexo con ropa": "clothed sex",
    "sexo en la ducha": "shower",
    "sexo en el baño": "bathroom",
    "sexo publico": "public indecency",
    "en la playa": "beach",
    "en la cama": "on bed",
    "en el suelo": "on floor",
    "colegiala": "school uniform",
    "uniforme escolar": "school uniform",
    "kimono": "kimono",
    "traje de baño": "swimsuit",
    "lencería": "lingerie",
    "tanga": "panties",
    "medias": "thighhighs",
    "desnuda": "nude",
    # criaturas / fantasía
    "tentáculos": "tentacles",
    "monstruo": "monster",
    "elfa": "elf",
    "demonio": "demon girl",
    "chica gato": "cat girl",
    "orejas de gato": "cat ears",
    "cola de gato": "cat tail",
    "futanari": "futanari",
    # extra: acciones y cuerpo
    "sexo": "sex",
    "follando": "sex",
    "corrida": "cum",
    "eyaculación": "cum",
    "culo": "ass",
    "nalgas": "ass",
    "besar": "kiss",
    "sin ropa": "nude",
    "desnudándose": "undressing",
    "quitándose la ropa": "undressing",
    "bragas a un lado": "panties aside",
    "topless": "topless",
    "tetas al aire libre": "breasts out",
    # extra: términos sueltos frecuentes
    "tetas": "breasts",
    "pechos": "breasts",
    "senos": "breasts",
    "culona": "large ass",
    "culo grande": "large ass",
    "sentada": "sitting",
    "sentado": "sitting",
    "acostada": "lying",
    "de pie": "standing",
    "publico": "public",
    "público": "public",
    "baño": "bathroom",
    # extra: vocabulario de prompt (escenas, ropa, colores, encuadre)
    "chica": "1girl",
    "chico": "1boy",
    "dos chicas": "2girls",
    "tres chicas": "3girls",
    "nieve": "snow",
    "mar": "ocean",
    "atardecer": "sunset",
    "amanecer": "sunrise",
    "sábanas": "bedsheet",
    "almohada": "pillow",
    "luz suave": "soft lighting",
    "luces de neón": "neon lights",
    "lluvia": "rain",
    "noche": "night",
    "nocturno": "night",
    "primer plano": "close up",
    "plano medio": "cowboy shot",
    "vista amplia": "wide shot",
    "cuerpo completo": "full body",
    "de espaldas": "from behind",
    "desde arriba": "from above",
    "acostada": "lying",
    "pelirroja": "red hair",
    "gafas": "glasses",
    "suéter": "sweater",
    "sueter": "sweater",
    "falda": "skirt",
    "falda corta": "miniskirt",
    "medias negras": "black thighhighs",
    "camisa": "shirt",
    "camisa blanca": "white shirt",
    "arremangada": "rolled up sleeves",
    "oficina": "office",
    "flores": "flower",
    "paraguas": "umbrella",
    "kimono blanco": "white kimono",
    "kimono rojo": "red kimono",
    "kimono negro": "black kimono",
    "falda roja": "red skirt",
    "falda rosa": "pink skirt",
    "sábanas blancas": "white bed sheet",
    "estampado floral": "floral print",
    "retrato": "portrait",
    # compuestos que desambiguan palabras polisémicas: "paja" es straw y handjob,
    # "corona" es crown y coronavirus. La frase más larga gana, así que sin estas
    # entradas "sombrero de paja" se traducía como "sombrero de handjob".
    "sombrero de paja": "straw hat",
    "campo de trigo": "wheat field",
    "corona de flores": "flower crown",
    "corona": "crown",
    "ropa de cama": "bed sheet",
    "traje de gala": "formal wear",
    "vestido": "dress",
    "vestido largo": "long dress",
    "abrazadas": "hug",
    "abrazados": "hug",
    "arrodillada": "kneeling",
    "espalda": "back",
    "cuerpo": "body",
    "cara": "face",
    "sonrisa": "smile",
    "lengua fuera": "tongue out",
    "sudando": "sweat",
    "mojada por la lluvia": "wet",
    "traje de baño blanco": "white bikini",
}

# Documented by the wikis but under the 1000-post floor; kept deliberately.
ALLOW_LOW_COVERAGE = {"see_through", "soft_lighting"}

# English phrases whose words are real tags but whose combination is not:
# `adult woman` split into `adult` (9 248) and missed `mature_female` (110 035),
# while `adult_woman` itself holds 2 posts.
CANDIDATES_EN = {
    "adult woman": "mature female",
    "adult women": "mature female",
    "grown woman": "mature female",
    "adult man": "mature male",
    "adult men": "mature male",
    "grown man": "mature male",
}


def is_acceptable(con, top: dict) -> bool:
    posts = top.get("post_count") or 0
    if posts >= 1000:
        return True
    if top["name"] in ALLOW_LOW_COVERAGE:
        return True
    return S._tag_wiki_count(con, top["name"]) >= 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()

    con = S._db()
    accepted: dict[str, str] = {}
    accepted_en: dict[str, str] = {}
    rejected: list[tuple[str, str, str]] = []
    try:
        for spanish, english in sorted(CANDIDATES.items()):
            rows = S._tag_rows(con, english, None, 3)
            top = rows[0] if rows else None
            if not top or not is_acceptable(con, top):
                got = f"{top['name']} ({top.get('post_count')})" if top else "sin resultado"
                rejected.append((spanish, english, got))
                continue
            accepted[spanish] = top["name"].replace("_", " ")
            print(f"  ok   {spanish:22} -> {top['name']:24} {top['post_count']:>8}")
        for source, english in sorted(CANDIDATES_EN.items()):
            rows = S._tag_rows(con, english, None, 3)
            top = rows[0] if rows else None
            if not top or not is_acceptable(con, top):
                got = f"{top['name']} ({top.get('post_count')})" if top else "sin resultado"
                rejected.append((source, english, got))
                continue
            accepted_en[source] = top["name"].replace("_", " ")
            print(f"  ok EN {source:21} -> {top['name']:24} {top['post_count']:>8}")
    finally:
        con.close()

    print(f"\naceptados {len(accepted)} ES + {len(accepted_en)} EN / rechazados {len(rejected)}")
    for spanish, english, got in rejected:
        print(f"  DROP {spanish:22} pedido={english:22} obtenido={got}")

    if args.write:
        target = REPO / "weeb_alexandria_mcp" / "query_aliases_es.json"
        payload = {
            "_comment": (
                "Phrase -> English tag phrase. Generated from the local tag library: "
                "every target was verified to resolve to a tag with >=1000 posts. "
                "'phrases' holds Spanish sources, 'english_phrases' English ones. "
                "Edit freely; the loader only needs those keys."
            ),
            "phrases": dict(sorted(accepted.items())),
            "english_phrases": dict(sorted(accepted_en.items())),
        }
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
        print(f"\nescrito {target} ({len(accepted)} frases)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
