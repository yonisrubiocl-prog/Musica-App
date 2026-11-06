"""El título que se enseña de una canción guardada, sin lo que pone YouTube y no es parte del nombre:
'Alexis y Fido - Rompe La Cintura // Letra' -> 'Rompe La Cintura', 'Aqua - Barbie Girl (Official Music Video)' ->
'Barbie Girl'. Solo para enseñar: el catálogo guarda el título de YouTube tal cual (con él se buscan las repetidas y
las versiones de vídeo). Lo que cambia la canción se queda: '(En Vivo)', '(Remix)', '(Cover)', 'ft. X'.
Ver README.md, "Títulos".
"""
import functools
import re
import unicodedata

# palabras de etiquetas de vídeo/letra; un paréntesis o una cola tras ' - ', '|' o '//' hecha solo de estas se quita
JUNK = set("official oficial officiel music musica musical video videoclip clip audio lyric lyrics letra letras con "
           "with hd hq 4k uhd visualizer visualiser animacion sub subs subtitulado subtitulada subtitulos traducida "
           "traducido traduccion traducao legendado lyricvideo full new nuevo estreno exclusivo exclusive".split())
ARTICLES = {"en", "espanol", "ingles", "portugues", "y", "and", "the", "el", "la", "de", "in"}
GROUP = re.compile(r"\s*[\(\[]([^\(\)\[\]]*)[\)\]]")
TAIL = re.compile(r"\s+[-–—]\s+|\s*(?:\|\|?|//)\s*")   # ' - ', ' – ', '|', '||', '//'
DASH = re.compile(r"\s*[-–—]\s+")   # 'Artista - Canción' (también 'DADDY YANKEE-  BOTZ'; 'Ken-Y' no)
NAMES = re.compile(r"\s*(?:,|&|\+|\s(?:y|x|and|ft\.?|feat\.?|featuring|con)\s)\s*", re.I)
# 'BOTZ Official Video': etiquetas sin paréntesis al final (dos o más palabras y una de vídeo/audio/letra)
BARE = re.compile(r"(?:\s+(?:official|oficial|music|musical|video|v[ií]deo|audio|lyrics?|letra|hd|4k)\b\.?){2,}\s*$", re.I)


def norm(text):
    t = unicodedata.normalize("NFKD", (text or "").lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return " ".join(re.findall(r"[a-z0-9]+", t))


def junk(text):
    """Solo etiquetas: '(Official Music Video)', '[4K]', 'Video Letra', '(Tradução)'. Un año también ('(2010)' no:
    eso puede ser el nombre; solo si va con otras etiquetas, 'Official Video 2010')."""
    words = norm(text).split()
    tags = [w for w in words if w in JUNK]
    return bool(tags) and all(w in JUNK or w in ARTICLES or (w.isdigit() and len(w) == 4) for w in words)


def names(text):
    return [n for n in (norm(x) for x in NAMES.split(text or "")) if n]


def is_artist(text, artists):
    """'Amin Martínez & Los Chiches Vallenato' es de 'Los Chiches Vallenatos & Amin Martinez': basta con que el
    primer nombre sea uno de sus artistas (o empiece igual: 'Binomio De Oro De América' / 'Binomio De Oro'). El
    primero, no uno cualquiera: 'Difícil De Igualar, Binomio De Oro De América' es una canción."""
    n = (names(text) or [""])[0]
    return bool(n) and any(n == a or n.startswith(a + " ") or (a.startswith(n + " ") and " " in n)
                           for a in artists)


@functools.lru_cache(maxsize=20000)
def nice(title, artist, credits=(), channel=""):
    t = (title or "").strip()
    if not t:
        return title
    artist_n = {a for x in (artist, *credits) for a in names(x)}
    t = GROUP.sub(lambda m: "" if junk(m.group(1)) else m.group(0), t).strip()
    # lo que queda entre paréntesis no se corta ('Get Lucky (Radio Edit - feat. …)'): se aparta mientras tanto
    kept = []
    t = GROUP.sub(lambda m: kept.append(m.group(0)) or f"\0{len(kept) - 1}\0", t)
    # colas sueltas: ' - Video Oficial', '// Letra', '| Official Audio', '| Discos Fuentes' (el canal)
    # (cada trozo con el separador que llevaba delante, para dejar como estaban los que no se quitan)
    bits = re.split(f"({TAIL.pattern})", t)
    parts = [("", bits[0])] + [(bits[i], bits[i + 1]) for i in range(1, len(bits) - 1, 2)]
    channel_n = norm(channel)
    back = lambda x: re.sub(r"\0(\d+)\0", lambda m: kept[int(m.group(1))], x)
    parts = parts[:1] + [x for x in parts[1:] if x[1].strip() and not junk(back(x[1]))]
    last = norm(parts[-1][1])
    if len(parts) > 1 and channel_n and len(last) >= 4 and (channel_n.startswith(last) or last.startswith(channel_n)):
        parts.pop()
    t = "".join(sep + x for sep, x in parts)
    if BARE.search(t) and BARE.sub("", t).strip():
        t = BARE.sub("", t)
    # 'Artista - Canción' y 'Canción - Artista' (solo si de verdad es su artista; si no, puede ser el nombre)
    if artist_n and DASH.search(t):
        a, b = DASH.split(t, 1)
        if is_artist(a, artist_n) and b.strip():
            t = b
        elif len(DASH.split(t)) == 2 and is_artist(b, artist_n) and a.strip():
            t = a + "".join(" " + x for x in re.findall(r"\0\d+\0", b))   # sin perder un "(Remix)" de detrás
    # 'A Besitos, Los Diablitos', 'Ay Hombe, Jorge Celedón & Jimmy Zambrano': detrás de la coma, solo sus artistas
    # (no en 'Na De Na ft. Gocho, John Eric' ni con más guiones delante)
    if artist_n and "," in t:
        head, tail = t.split(",", 1)
        if (head.strip() and not DASH.search(head) and not NAMES.search(head.replace(",", "")) and names(tail)
                and all(is_artist(n, artist_n) or junk(n) for n in NAMES.split(tail) if norm(n))):
            t = head
    t = back(t)
    t = re.sub(r"^[“\"]([^”\"]+)[”\"]", r"\1", t.strip())   # '“Enemy (Opening Title Version)” (from Arcane)'
    t = re.sub(r"\s{2,}", " ", t).strip(" -–—|/,")
    return t if len(norm(t)) >= 1 else title
