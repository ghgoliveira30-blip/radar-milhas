#!/usr/bin/env python3
"""Radar de Milhas — coletor + baldes diarios (arquivo unico).

Subcomandos, na ordem em que a rodada de hora em hora os usa:

  python3 radar_run.py known   --dir dump                     -> known.json
  python3 radar_run.py collect --known known.json --hours 30  -> novos.json
  python3 radar_run.py merge   --dir dump --new novos.json    -> hoje.json + resumo.json
  python3 radar_run.py prune   --dir dump --keep 21           -> ids de dias a apagar

`dump` e a pasta onde o ArtifactData salvou os documentos da colecao `days`.
Um documento por dia mantem o banco pequeno (teto de 5.000 documentos).
"""
import argparse, concurrent.futures as cf, hashlib, html, json, re, sys
from datetime import datetime, timezone, timedelta

import feedparser, requests

UA = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36",
    "Accept": "application/rss+xml,application/xml,text/html;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,pt-BR;q=0.8,de;q=0.7,es;q=0.7",
}

# nome, url, tipo, idioma, regiao
SOURCES = [
    # --- alemao: o ecossistema mais rapido ---
    ("meilenoptimieren",     "https://meilenoptimieren.com/feed/",                    "rss", "de", "DE"),
    ("Travel-Dealz",         "https://travel-dealz.de/feed/",                         "rss", "de", "DE"),
    ("reisetopia",           "https://reisetopia.de/feed/",                           "rss", "de", "DE"),
    ("Frankfurtflyer",       "https://frankfurtflyer.de/?feed=rss2",                  "rss", "de", "DE"),
    ("InsideFlyer DE",       "https://insideflyer.de/feed/",                          "rss", "de", "DE"),
    ("YouHaveBeenUpgraded",  "https://youhavebeenupgraded.boardingarea.com/feed/",    "rss", "en", "DE"),
    # --- espanhol: chave para Iberia / Avios ---
    ("Ultima Llamada",       "https://ultimallamada.com/feed/",                       "rss", "es", "ES"),
    ("Exprime Viajes",       "https://exprimeviajes.com/feed/",                       "rss", "es", "ES"),
    ("TarifasError",         "https://tarifaserror.es/feed/",                         "rss", "es", "ES"),
    # --- leste europeu: cacadores de error fare ---
    ("Fly4free",             "https://www.fly4free.com/feed/",                        "rss", "en", "EU"),
    ("Fly4free PL",          "https://www.fly4free.pl/feed/",                         "rss", "pl", "EU"),
    ("Fly4free Telegram",    "https://t.me/s/fly4free_com",                           "tg",  "en", "EU"),
    # --- franca / holanda ---
    ("VolPromo",             "https://www.volpromo.net/blog/feed/",                   "rss", "fr", "FR"),
    ("InsideFlyer NL",       "https://insideflyer.nl/feed/",                          "rss", "nl", "NL"),
    # --- ingles ---
    ("Secret Flying",        "https://www.secretflying.com/",                         "sf",  "en", "GLOBAL"),
    ("The Flight Deal",      "https://www.theflightdeal.com/feed/",                   "rss", "en", "US"),
    ("LoyaltyLobby",         "https://loyaltylobby.com/feed/",                        "rss", "en", "GLOBAL"),
    ("View from the Wing",   "https://viewfromthewing.com/feed/",                     "rss", "en", "US"),
    ("Thrifty Traveler",     "https://thriftytraveler.com/feed/",                     "rss", "en", "US"),
    ("Head for Points",      "https://www.headforpoints.com/feed/",                   "rss", "en", "UK"),
    ("God Save the Points",  "https://godsavethepoints.com/feed/",                    "rss", "en", "GLOBAL"),
    ("Frequent Miler",       "https://frequentmiler.com/feed/",                       "rss", "en", "US"),
    ("One Mile at a Time",   "https://onemileatatime.com/feed/",                      "rss", "en", "GLOBAL"),
    ("The Points Guy",       "https://thepointsguy.com/feed/",                        "rss", "en", "US"),
    ("Live and Let's Fly",   "https://liveandletsfly.com/feed/",                      "rss", "en", "US"),
    ("Prince of Travel",     "https://princeoftravel.com/feed/",                      "rss", "en", "CA"),
    ("Frugal Flyer",         "https://frugalflyer.ca/feed/",                          "rss", "en", "CA"),
    ("Milesopedia",          "https://milesopedia.com/feed/",                         "rss", "fr", "CA"),
    ("Point Hacks",          "https://www.pointhacks.com.au/feed/",                   "rss", "en", "AU"),
    # --- brasil ---
    ("Passageiro de Primeira", "https://passageirodeprimeira.com/feed/",              "rss", "pt", "BR"),
    ("Melhores Destinos",    "https://www.melhoresdestinos.com.br/feed",              "rss", "pt", "BR"),
    ("Mestre das Milhas",    "https://mestredasmilhas.com/feed/",                     "rss", "pt", "BR"),
    ("Pontos pra Voar",      "https://pontospravoar.com/feed/",                       "rss", "pt", "BR"),
    ("Melhores Cartões",     "https://www.melhorescartoes.com.br/feed/",              "rss", "pt", "BR"),
    ("PP Telegram",          "https://t.me/s/passageirodeprimeira",                   "tg",  "pt", "BR"),
    ("MD Telegram",          "https://t.me/s/melhoresdestinos",                       "tg",  "pt", "BR"),
    # --- reddit ---
    ("r/awardtravel",        "https://www.reddit.com/r/awardtravel/new/.rss",          "rss", "en", "GLOBAL"),
    ("r/Flights",            "https://www.reddit.com/r/Flights/new/.rss",              "rss", "en", "GLOBAL"),
    ("r/travelhacking",      "https://www.reddit.com/r/travelhacking/new/.rss",        "rss", "en", "GLOBAL"),
]

# ---------------------------------------------------------------- classificacao
ERROR_FARE = [
    r"error\s*fare", r"mistake\s*fare", r"fehlerpreis", r"preisfehler", r"fehler[- ]?tarif",
    r"tarifa\s*error", r"tarifas\s*error", r"erro\s*de\s*tarifa", r"erro\s*de\s*pre[çc]o",
    r"erreur\s*de\s*(prix|tarif)", r"b[łl][ąa]d\s*cenow", r"glitch", r"pricing\s*(error|bug)",
    r"\bbug\b", r"prijsfout",
]
TRANSFER_BONUS = [
    r"b[oô]nus\s*(de|na|em|para)?\s*transfer[eê]nci",   # "bônus de/na transferência"
    r"transfer[eê]nci\w*[^.;]{0,40}b[oô]nus",            # "transferência ... com bônus"
    r"b[oô]nus[^.;]{0,40}transfer[eê]nci",
    r"transfir[ao][^.;]{0,50}b[oô]nus",                   # "transfira ... com 80% de bônus"
    r"transfer\s*bonus", r"transferbonus", r"bonus\s*(de\s*)?transferencia",
    r"bonus\s*transfert", r"transfer(ir|a)\s*com\s*b[oô]nus", r"pontos?\s*com\s*b[oô]nus",
]

# par programa-origem + programa-destino e sinal forte de bonus de transferencia,
# mesmo quando a manchete nao usa a palavra "transferencia"
ORIGEM = re.compile(r"\blivelo\b|\besfera\b|\bip[êe]\b|it[aá]u\s*points|\bdotz\b|\bcaixa\b", re.I)
DESTINO = re.compile(r"smiles|latam\s*pass|azul\s*fidelidade|tudoazul|iberia\s*plus|\bavios\b|"
                     r"tap\s*miles|flying\s*blue|qatar|aeroplan|lifemiles|connectmiles|aadvantage|"
                     r"miles\s*&\s*(more|smiles)", re.I)
PCT_QUALQUER = re.compile(r"(\d{2,3})\s?%")
# =============================================================================
# REGUA DE BONUS POR PROGRAMA DE DESTINO
# Fonte: Super Mapa Mental do Vitão (base milhas-conhecimento, "quando transferir
# pontos — bonus minimo para valer"). Um percentual so significa alguma coisa
# depois de saber PARA ONDE vai: 25% na Iberia e raro e otimo; 80% na Smiles e
# rotina. Mexa nos numeros aqui.
# =============================================================================
LIMIAR_BONUS = {
    "LATAM Pass":   25,   # 25% e o normal hoje; acima disso e festa
    "Iberia/Avios": 25,   # idem — via Esfera 2:1
    "Smiles":       80,
    "Azul":         80,
    "ConnectMiles": 65,
    "TAP":           1,   # praticamente nunca tem bonus — qualquer um ja e noticia
}
LIMIAR_PADRAO = 80        # programa nao reconhecido

PROGRAMAS_DESTINO = [
    ("LATAM Pass",   r"latam\s*pass|\blatam\b"),
    ("Smiles",       r"\bsmiles\b|\bgol\b"),
    ("Azul",         r"azul\s*fidelidade|tudoazul|\bazul\b"),
    ("ConnectMiles", r"connect\s*miles|\bcopa\b"),
    ("Iberia/Avios", r"iberia|\bavios\b|british\s*airways"),
    ("TAP",          r"\btap\b|miles\s*&\s*go|miles\s*and\s*go"),
]
PROGRAMAS_RX = [(nome, re.compile(rx, re.I)) for nome, rx in PROGRAMAS_DESTINO]


def programa_destino(text):
    for nome, rx in PROGRAMAS_RX:
        if rx.search(text):
            return nome
    return None


def limiar_de(text):
    nome = programa_destino(text)
    return nome, (LIMIAR_BONUS.get(nome, LIMIAR_PADRAO) if nome else LIMIAR_PADRAO)
AWARD_PROMO = [
    r"award\s*sale", r"promo\s*(award|reward)", r"pr[äa]mien(flug|meilen).{0,12}(aktion|sale|rabatt)",
    r"meilenschn[äa]ppchen", r"descuento.{0,20}avios", r"avios.{0,20}descuento",
    r"promo[çc][ãa]o\s*de\s*resgate", r"resgate\s*com\s*desconto", r"redemption\s*sale",
    r"points?\s*sale", r"milhas?\s*em\s*promo[çc][ãa]o", r"flash\s*sale",
]
BUY_POINTS = [
    r"buy\s*(points|miles)", r"compre?\s*(pontos|milhas)", r"punkte\s*kaufen", r"meilen\s*kaufen",
    r"comprar\s*(puntos|millas|avios)", r"acheter\s*des\s*(points|miles)",
]
BIZ = [
    r"business\s*class", r"first\s*class", r"classe\s*executiva", r"executiva",
    r"la\s*premi[eè]re", r"qsuite", r"business\s*ab\s*\d", r"biznes", r"premium\s*cabin",
]
STATUS_HOTEL = [
    r"status\s*match", r"statusmatch", r"elite\s*status", r"hilton|marriott|hyatt|accor|ihg",
    r"b[oô]nus\s*de\s*(pontos|noites)", r"double\s*points",
]

MONEY = re.compile(r"(?:R\$|US?\$|€|£|EUR|USD|BRL|PLN)\s?([\d\.,]{2,9})")
# % so conta quando esta perto de uma palavra de bonus/desconto e longe de reembolso
BONUS_WORD = r"(?:b[oô]nus|bonus|bonificad|transfer|transferencia|transfer[eê]ncia|desconto|descuento|rabatt|discount|off|sale)"
PCT_NEAR_BONUS = re.compile(rf"(?:{BONUS_WORD}[^.;]{{0,60}}?(\d{{2,3}})\s?%|(\d{{2,3}})\s?%[^.;]{{0,60}}?{BONUS_WORD})", re.I)
REFUND_PCT = re.compile(r"(?:reembols|refund|cashback|devoluc|garantia)[^.;]{0,40}\d{2,3}\s?%|\d{2,3}\s?%[^.;]{0,40}(?:reembols|refund|cashback)", re.I)

# rodape que os feeds WordPress grudam no resumo e polui a classificacao
BOILER = re.compile(
    r"(?:La entrada|The post|O post|Der Beitrag|Het bericht|L'article|Wpis)\b.*$",
    re.I | re.S)


DEAL_SOURCES = {'MD Telegram', 'Secret Flying', 'Travel-Dealz', 'The Flight Deal', 'Exprime Viajes', 'Fly4free', 'Fly4free Telegram', 'VolPromo', 'TarifasError', 'Fly4free PL', 'Thrifty Traveler', 'Melhores Destinos'}

FLIGHT_WORDS = [r"\bvoos?\b", r"\bvuelos?\b", r"\bfl[üu]ge?\b", r"\bflights?\b",
                r"\bloty?\b", r"\bvols?\b", r"passagens?", r"roundtrip", r"ida y vuelta",
                r"hin[- ]?und[- ]?r[üu]ck", r"\bnon[- ]?stop\b", r"\br/t\b"]


def _has(patterns, text):
    return any(re.search(p, text, re.I) for p in patterns)


def _pct(text):
    if REFUND_PCT.search(text):
        return 0
    vals = [int(g) for m in PCT_NEAR_BONUS.finditer(text) for g in m.groups() if g]
    vals = [v for v in vals if v <= 300]
    return max(vals) if vals else 0


def _signals(text, allow_hot):
    """Retorna (categoria, calor, motivos) para um trecho de texto."""
    cat, heat, why = None, 1, []
    pct = _pct(text)

    if _has(STATUS_HOTEL, text):
        cat, heat = "hotel/status", max(heat, 1)
    if _has(BIZ, text) and MONEY.search(text):
        cat, heat = "executiva barata", max(heat, 2)
        why.append("cabine premium com preco")
    if _has(BUY_POINTS, text):
        cat, heat = "compra de pontos", max(heat, 2)
        why.append("compra de pontos")
    if _has(AWARD_PROMO, text):
        cat, heat = "promo award", max(heat, 2)
        why.append("promocao de resgate")
    if _has(TRANSFER_BONUS, text) or (ORIGEM.search(text) and DESTINO.search(text) and pct):
        cat = "bonus de transferencia"
        heat = max(heat, 3 if (allow_hot and pct >= 100) else 2)
        why.append(f"bonus {pct}%" if pct else "bonus de transferencia")
    elif pct >= 100:
        cat = cat or "bonus/desconto alto"
        heat = max(heat, 3 if allow_hot else 2)
        why.append(f"{pct}%")
    if _has(ERROR_FARE, text):
        cat = "ERRO DE TARIFA"
        heat = 3 if allow_hot else max(heat, 2)
        why.append("erro de tarifa" if allow_hot else "possivel erro de tarifa")

    return cat, heat, why


ERRO_NA_URL = re.compile(r"error[-_]?fare|mistake[-_]?fare|tarifa[s]?[-_]?error|fehlerpreis|preisfehler", re.I)


def classify(title, summary, source=""):
    """O calor 3 so pode vir do titulo; o resumo sustenta no maximo calor 2.

    Isso evita que o rodape do feed ("...aparece primero en ... tarifas error")
    transforme qualquer oferta comum em alerta vermelho.
    """
    t_cat, t_heat, t_why = _signals(title, allow_hot=True)
    s_cat, s_heat, s_why = _signals(summary, allow_hot=False)

    heat = max(t_heat, min(s_heat, 2))
    cat = t_cat if (t_cat and t_heat >= 2) else (s_cat or t_cat or "noticia")
    why = t_why or s_why

    # fonte de garimpo + preco + palavra de voo = oferta de tarifa, mesmo sem gatilho
    if heat < 2 and source in DEAL_SOURCES and MONEY.search(title) and _has(FLIGHT_WORDS, title):
        cat, heat = "oferta de tarifa", 2
        why = why or ["tarifa promocional"]

    return cat, heat, ", ".join(dict.fromkeys(why)) or "noticia do setor"


def clean(s, limit=300):
    s = re.sub(r"<[^>]+>", " ", s or "")
    s = html.unescape(s)
    s = re.sub(r"\s+", " ", s).strip()
    s = BOILER.sub("", s).strip()
    return s[:limit]


TRACK = re.compile(r"^(utm_[a-z_]+|fbclid|gclid|mc_cid|mc_eid|ref|source|amp)$", re.I)


def norm_link(u):
    """Mesma noticia chega com sufixo de rastreio ou barra final; a chave ignora isso."""
    try:
        from urllib.parse import urlsplit, parse_qsl, urlencode
        p = urlsplit(u)
        host = p.netloc.lower().removeprefix("www.")
        path = p.path.rstrip("/")
        qs = urlencode(sorted((k, v) for k, v in parse_qsl(p.query) if not TRACK.match(k)))
        frag = p.fragment if host == "t.me" and p.fragment else ""
        return host + path + (("?" + qs) if qs else "") + (("#" + frag) if frag else "")
    except Exception:
        return (u or "").strip().lower().rstrip("/")


def mkid(link):
    return hashlib.sha1(norm_link(link).encode("utf-8")).hexdigest()[:16]


def title_key(t):
    """Titulo reduzido ao essencial, para pegar a mesma materia vinda de duas fontes."""
    t = re.sub(r"https?://\S+", " ", (t or "").lower())
    t = re.sub(r"[^0-9a-zà-ÿ]+", " ", t, flags=re.I).strip()
    return " ".join(t.split()[:9])


# ------------------------------------------------- lugares, preco e "boa promo"
PLACES = {
    "Brasil": r"brasil|brazil|brasilien|\bGRU\b|\bGIG\b|\bCGH\b|\bBSB\b|\bVCP\b|\bCNF\b|\bREC\b|\bSSA\b|\bFOR\b|\bPOA\b|\bCWB\b|s[ãa]o paulo|rio de janeiro|guarulhos|congonhas|campinas|bras[íi]lia|salvador|recife|fortaleza|porto alegre|florian[óo]polis|belo horizonte|nordeste",
    "Europa": r"europ[ae]|madri[dt]?|barcelona|lisbo[an]|lisbon|\bporto\b|oporto|paris|london|londres|frankfurt|m[üu]nchen|munich|munique|berlin|berlim|amsterd[ãa]?m|\broma\b|\brome\b|mil[ãa]o|milan|viena|vienna|wien|z[üu]rich|zurique|warsaw|warszawa|vars[óo]via|krak[óo]w|cracovia|budape|prag|copenhag|stockholm|estocolmo|oslo|helsin|dublin|brussel|bruxelas|atenas|athens|istanbul|alicante|m[áa]laga|sevilla|bilbao|can[áa]rias|canarias|tenerife|gran canaria|ibiza|mallorca|sic[íi]lia|split|dubrovnik|riga|tallinn|vilnius|bucareste|sof[íi]a|reykjav|spitzbergen|noruega|norway|su[íi][çc]a|escandin",
    "EUA e Canadá": r"\bUSA\b|united states|estados unidos|\bEUA\b|new york|nova york|\bNYC\b|\bJFK\b|\bEWR\b|miami|\bMIA\b|los angeles|\bLAX\b|san francisco|\bSFO\b|chicago|\bORD\b|boston|orlando|washington|seattle|denver|atlanta|dallas|houston|las vegas|hawaii|hava[íi]|toronto|\bYYZ\b|vancouver|montreal|canad[áa]|canada",
    "Ásia e Oriente Médio": r"\b[áa]sia\b|asien|tokyo|t[óo]quio|\bNRT\b|\bHND\b|jap[ãa]o|japan|seoul|seul|coreia|korea|bangkok|\bBKK\b|tail[âa]ndia|thailand|singapor|hong kong|\bHKG\b|dubai|\bDXB\b|doha|\bDOH\b|abu dhabi|\bAUH\b|catar|qatar|delhi|mumbai|[íi]ndia|beijing|pequim|shanghai|xangai|taipei|taiwan|kuala lumpur|mal[áa]sia|malaysia|manila|filipinas|philippines|vietn[ãa]|vietnam|bali|indon[ée]sia|maldiv|sri lanka|colombo|om[ãa]|\boman\b|israel|tel aviv|amman|uzbek|cazaquist",
    "América Latina": r"buenos aires|\bEZE\b|argentina|santiago|\bSCL\b|chile|\blima\b|\bLIM\b|peru|bogot[áa]|colombia|col[ôo]mbia|cartagena|medell[íi]n|canc[úu]n|m[ée]xico|mexico|montevid|uruguai|punta cana|rep[úu]blica dominicana|costa rica|panam[áa]|cusco|patag[ôo]nia|bariloche|paraguai|bol[íi]via|equador|gal[áa]pagos",
    "Caribe": r"caribe|caribbean|aruba|cura[çc]ao|jamaica|barbados|guadeloupe|guadalupe|martinica|martinique|bahamas|turks|santa l[úu]cia|trinidad|cabo verde|cape verde",
    "África": r"[áa]frica|africa|cape town|cidade do cabo|johannesburg|joanesburgo|nairobi|qu[êe]nia|kenya|marrakech|marrocos|morocco|cairo|egito|egypt|dakar|senegal|zanzibar|tanz[âa]nia|maur[íi]cio|mauritius|seychelles|namib|eti[óo]pia|ethiopia",
    "Oceania": r"austr[áa]lia|australia|sydney|melbourne|brisbane|perth|nova zel[âa]ndia|new zealand|auckland|fiji|tahiti|polin[ée]sia",
}
PLACE_RX = {k: re.compile(v, re.I) for k, v in PLACES.items()}

FX = {"R$": 1, "BRL": 1, "US$": 5.4, "$": 5.4, "USD": 5.4, "€": 5.9, "EUR": 5.9, "£": 7.0, "GBP": 7.0,
      "CA$": 3.9, "C$": 3.9, "CAD": 3.9, "A$": 3.6, "AUD": 3.6, "CHF": 6.3, "PLN": 1.35,
      "SEK": 0.52, "NOK": 0.50, "DKK": 0.79, "€": 5.9, "£": 7.0, "ZŁ": 1.35, "ZL": 1.35}
MONEY_PRE = re.compile(r"(R\$|CA\$|C\$|A\$|US\$|\$|€|£|CHF|EUR|USD|BRL|GBP|CAD|AUD|PLN|SEK|NOK|DKK)\s?([\d.,]{2,9})", re.I)
MONEY_SUF = re.compile(r"([\d.,]{2,9})\s?(CAD|AUD|USD|EUR|GBP|CHF|PLN|SEK|NOK|DKK|BRL|€|£|z[łl])", re.I)

TETO_EXECUTIVA_BRL = 6000   # mesmo teto padrao do painel


def _num(raw):
    try:
        return float(re.sub(r"[.,](\d{3})\b", r"\1", raw).replace(",", "."))
    except Exception:
        return 0.0


def preco_brl(text):
    vals = []
    for m in MONEY_PRE.finditer(text):
        v = _num(m.group(2))
        if v >= 10:
            vals.append(v * FX.get(m.group(1), FX.get(m.group(1).upper(), 1)))
    for m in MONEY_SUF.finditer(text):
        v = _num(m.group(1))
        if v >= 10:
            vals.append(v * FX.get(m.group(2).upper(), 1))
    return round(min(vals)) if vals else 0


def lugares(text):
    return [k for k, rx in PLACE_RX.items() if rx.search(text)]


def bonus_pct(text):
    """Maior percentual citado, quando o texto e sobre bonus/transferencia."""
    if not (_has(TRANSFER_BONUS, text)
            or (ORIGEM.search(text) and (DESTINO.search(text) or programa_destino(text)))):
        return 0
    vals = [int(v) for v in PCT_QUALQUER.findall(text) if int(v) <= 300]
    return max(vals) if vals else 0


def eh_boa_promo(it):
    """O que merece notificacao."""
    return bool(
        it.get("erro_tarifa")
        or it.get("heat") == 3
        or it.get("category") == "promo award"
        or (it.get("pct", 0) and it.get("pct", 0) >= it.get("limiar", LIMIAR_PADRAO))
        or (it.get("category") == "executiva barata"
            and 0 < it.get("preco", 0) <= TETO_EXECUTIVA_BRL)
    )


# ---------------------------------------------------------------- coletores
def _get(url, tries=2):
    last = None
    for _ in range(tries):
        try:
            r = requests.get(url, headers=UA, timeout=25)
            r.raise_for_status()
            return r
        except Exception as exc:
            last = exc
    raise last


def fetch_rss(name, url, lang, region, cutoff):
    out = []
    r = _get(url)
    feed = feedparser.parse(r.content)
    for e in feed.entries[:40]:
        link = (e.get("link") or "").strip()
        if not link:
            continue
        pub = None
        for key in ("published_parsed", "updated_parsed"):
            if e.get(key):
                pub = datetime(*e[key][:6], tzinfo=timezone.utc)
                break
        if pub and pub < cutoff:
            continue
        out.append(dict(
            source=name, lang=lang, region=region, link=link,
            title=clean(e.get("title", ""), 220),
            summary=clean(e.get("summary", ""), 170),
            published=(pub or datetime.now(timezone.utc)).isoformat(),
        ))
    return out


def fetch_tg(name, url, lang, region, cutoff):
    out = []
    r = _get(url)
    blocks = re.findall(
        r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>.*?'
        r'<time datetime="([^"]+)"', r.text, re.S)
    base = url.rstrip("/").split("/s/")[-1]
    for i, (body, ts) in enumerate(blocks[-25:]):
        text = clean(body, 300)
        if len(text) < 25:
            continue
        try:
            pub = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except Exception:
            pub = datetime.now(timezone.utc)
        if pub < cutoff:
            continue
        m = re.search(r'href="(https?://[^"]+)"', body)
        link = html.unescape(m.group(1)) if m else f"https://t.me/{base}"
        out.append(dict(
            source=name, lang=lang, region=region,
            link=link if m else f"{link}#{mkid(text)}",
            title=text[:170], summary=text[:170],
            published=pub.astimezone(timezone.utc).isoformat(),
        ))
    return out


def fetch_secretflying(name, url, lang, region, cutoff):
    r = _get(url)
    seen, out = set(), []
    for m in re.finditer(r'<a[^>]+href="(https://www\.secretflying\.com/posts/[^"#]+)"[^>]*>(.*?)</a>',
                         r.text, re.S):
        link, title = m.group(1), clean(m.group(2), 220)
        if "/category/" in link or len(title) < 20 or link in seen:
            continue
        seen.add(link)
        out.append(dict(source=name, lang=lang, region=region, link=link,
                        title=title, summary=title,
                        published=datetime.now(timezone.utc).isoformat()))
    return out[:25]


FETCHERS = {"rss": fetch_rss, "tg": fetch_tg, "sf": fetch_secretflying}


# O Reddit bloqueia os IPs de datacenter do GitHub (403/429 em toda rodada).
# No navegador do usuario eles funcionam, entao ficam so no app e saem do robo.
SO_NO_NAVEGADOR = {"r/awardtravel", "r/Flights", "r/travelhacking"}


def run(hours, known):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    items, errors = [], []

    def one(src):
        name, url, kind, lang, region = src
        try:
            return name, FETCHERS[kind](name, url, lang, region, cutoff), None
        except Exception as exc:
            return name, [], f"{type(exc).__name__}: {exc}"[:120]

    fontes = [f for f in SOURCES if f[0] not in SO_NO_NAVEGADOR]
    with cf.ThreadPoolExecutor(max_workers=12) as ex:
        for name, got, err in ex.map(one, fontes):
            if err:
                errors.append({"source": name, "error": err})
            items.extend(got)

    seen, seen_titles, new = set(), set(), []
    for it in items:
        iid = mkid(it["link"])
        if iid in known or iid in seen:
            continue
        tk = title_key(it["title"])
        if len(tk) > 12 and tk in seen_titles:
            continue          # mesma materia, outra fonte
        seen.add(iid)
        if len(tk) > 12:
            seen_titles.add(tk)
        cat, heat, why = classify(it["title"], it["summary"], it["source"])
        texto = it["title"] + " " + it["summary"]
        bp = bonus_pct(it["title"]) or bonus_pct(texto)
        prog, limiar = limiar_de(it["title"]) if bp else (None, LIMIAR_PADRAO)
        erro = bool(ERRO_NA_URL.search(it["link"])) or cat == "ERRO DE TARIFA"

        it.update(id=iid, category=cat, heat=heat, why=why, pct=bp,
                  programa=prog, limiar=limiar, erro_tarifa=erro,
                  places=lugares(texto), preco=preco_brl(it["title"]) or preco_brl(texto))

        if erro:
            it["category"] = "ERRO DE TARIFA"
            it["heat"] = 3
            it["why"] = "erro de tarifa"
        elif bp and bp >= limiar:
            it["heat"] = 3
            it["category"] = "bonus de transferencia"
            it["why"] = f"bônus de {bp}%" + (f" para {prog}" if prog else "")
        it["alert"] = eh_boa_promo(it)
        new.append(it)

    new.sort(key=lambda x: (-x["heat"], x["published"]), reverse=False)
    new.sort(key=lambda x: (-x["heat"], x["published"]))
    return new, errors

# =================================================================== baldes
import os

MAX_ITEMS_PER_DAY = 800
MAX_BYTES = 230_000          # folga sobre o teto de 256 KiB por documento


def load_days(d):
    """Le os arquivos JSON que o ArtifactData salvou (um por documento)."""
    out = {}
    if not d or not os.path.isdir(d):
        return out
    for root, _, files in os.walk(d):
        for fn in files:
            if not fn.endswith(".json"):
                continue
            try:
                with open(os.path.join(root, fn)) as fh:
                    body = json.load(fh)
            except Exception:
                continue
            if isinstance(body, dict) and "items" in body:
                out[body.get("date") or fn[:-5]] = body
    return out


def cmd_known(a):
    ids = set()
    for body in load_days(a.dir).values():
        for it in body.get("items", []):
            if it.get("id"):
                ids.add(it["id"])
    json.dump(sorted(ids), open("known.json", "w"))
    print(f"known.json com {len(ids)} ids de {len(load_days(a.dir))} dias")


def cmd_collect(a):
    known = set()
    if a.known:
        try:
            known = set(json.load(open(a.known)))
        except Exception:
            pass
    new, errors = run(a.hours, known)
    json.dump(new, open(a.out, "w"), ensure_ascii=False, indent=1)
    hot = [i for i in new if i.get("alert")]
    print(f"novos: {len(new)} | boas promos: {len(hot)} | fontes com erro: {len(errors)}")
    for e in errors:
        print("  ! ", e["source"], e["error"])


def cmd_merge(a):
    today = a.date or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    dias = load_days(a.dir)
    bucket = dias.get(today) or {"date": today, "items": []}

    new = json.load(open(a.new))
    have = {i["id"] for i in bucket["items"] if i.get("id")}
    have_titles = {title_key(i.get("title", "")) for d in dias.values() for i in d.get("items", [])}
    have_titles.discard("")
    added = [i for i in new
             if i.get("id") and i["id"] not in have
             and not (len(title_key(i.get("title", ""))) > 12
                      and title_key(i.get("title", "")) in have_titles)]

    merged = added + bucket["items"]
    # ordena por calor e depois por data: o corte tira sempre o menos valioso
    merged.sort(key=lambda i: (-int(i.get("heat", 1)), i.get("published", "")), reverse=False)
    merged.sort(key=lambda i: (-int(i.get("heat", 1)), i.get("published", "")))
    bucket["items"] = merged[:MAX_ITEMS_PER_DAY]
    while len(json.dumps(bucket, ensure_ascii=False).encode()) > MAX_BYTES and len(bucket["items"]) > 20:
        bucket["items"] = bucket["items"][:-10]

    bucket["updated"] = datetime.now(timezone.utc).isoformat()
    bucket["count"] = len(bucket["items"])
    json.dump(bucket, open(a.out, "w"), ensure_ascii=False)

    hot = [i for i in added if i.get("alert")]
    warm = [i for i in added if not i.get("alert") and i.get("heat") == 2]
    resumo = {
        "date": today,
        "added": len(added),
        "hot": [{"titulo": i["title"][:150], "fonte": i["source"], "link": i["link"],
                 "motivo": i.get("why", ""), "preco_brl": i.get("preco", 0),
                 "regioes": i.get("places", [])} for i in hot],
        "warm_count": len(warm),
        "warm_sample": [{"titulo": i["title"][:110], "fonte": i["source"]} for i in warm[:8]],
        "bucket_items": bucket["count"],
    }
    json.dump(resumo, open("resumo.json", "w"), ensure_ascii=False, indent=1)
    print(json.dumps(resumo, ensure_ascii=False, indent=1))


def cmd_prune(a):
    limite = (datetime.now(timezone.utc) - timedelta(days=a.keep)).strftime("%Y-%m-%d")
    print(json.dumps(sorted(d for d in load_days(a.dir) if d < limite)))




# =========================================================== publicacao (GitHub Actions)
import os as _os


MAX_POR_RODADA = 6   # teto de mensagens por rodada, para nao virar spam


def _tg(texto):
    """Manda uma mensagem no Telegram. Sem segredo configurado, nao faz nada."""
    token = _os.environ.get("TELEGRAM_TOKEN", "").strip()
    chat = _os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat:
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": texto, "parse_mode": "HTML",
                  "disable_web_page_preview": False},
            timeout=20)
        if r.status_code != 200:
            print("  ! telegram:", r.status_code, r.text[:160])
        return r.status_code == 200
    except Exception as exc:
        print("  ! telegram:", type(exc).__name__)
        return False


def _escapa(t):
    return (t or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def cmd_publish(a):
    """Varre, atualiza dados.json e avisa no Telegram o que for boa promocao."""
    # ping de teste: prova que token e chat_id estao certos, mesmo sem promocao nova
    if _os.environ.get("TELEGRAM_PING", "").lower() == "true":
        ok = _tg("✅ Radar de Milhas: teste de conexão. Se você recebeu isto, "
                 "o bot está configurado corretamente.")
        print("ping de teste:", "enviado" if ok else "FALHOU (veja a linha ! telegram acima)")
    # 1. o que ja existe
    try:
        atual = json.load(open(a.dados))
    except Exception:
        atual = {"items": []}
    antigos = atual.get("items", [])

    try:
        estado = json.load(open(a.estado))
    except Exception:
        estado = {"enviados": []}
    enviados = set(estado.get("enviados", []))

    # 2. coleta
    known = {i["id"] for i in antigos if i.get("id")}
    novos, errors = run(a.hours, known)

    # 3. junta, corta pelo tempo e pelo teto
    corte = (datetime.now(timezone.utc) - timedelta(days=a.keep)).isoformat()
    juntos = novos + [i for i in antigos if i.get("published", "") > corte]

    vistos, titulos, final = set(), set(), []
    for i in juntos:
        if not i.get("id") or i["id"] in vistos:
            continue
        tk = title_key(i.get("title", ""))
        if len(tk) > 12 and tk in titulos:
            continue
        vistos.add(i["id"])
        if len(tk) > 12:
            titulos.add(tk)
        final.append(i)

    final.sort(key=lambda i: i.get("published", ""), reverse=True)
    final = final[:a.max_items]

    ativas = len(SOURCES) - len(SO_NO_NAVEGADOR)
    saida = {
        "atualizado": datetime.now(timezone.utc).isoformat(),
        "fontes_ok": ativas - len(errors),
        "fontes_total": ativas,
        "falhas": [e["source"] for e in errors],
        "items": final,
    }
    json.dump(saida, open(a.dados, "w"), ensure_ascii=False, separators=(",", ":"))

    # 4. avisa so o que e boa promocao e ainda nao foi avisado
    # Candidato a alerta = qualquer item ativo e recente que ainda nao foi avisado,
    # mesmo que ja estivesse no dados.json de rodadas anteriores. Assim, se uma
    # rodada falhar ou o estado for zerado, o radar se recupera sozinho.
    janela = (datetime.now(timezone.utc) - timedelta(hours=a.alert_hours)).isoformat()
    alertas = [i for i in final
               if i.get("alert") and i.get("published", "") > janela
               and i["id"] not in enviados]
    alertas.sort(key=lambda i: (0 if i.get("erro_tarifa") else 1, i.get("published", "")),
                 reverse=False)

    # A mesma promocao sai em 3 ou 4 blogs. Para bonus, a identidade e
    # programa + percentual: avisa uma vez e ignora as repetições por 48h.
    assuntos = estado.get("assuntos", {})
    limite = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    assuntos = {k: v for k, v in assuntos.items() if v > limite}

    def assunto(i):
        if i.get("erro_tarifa"):
            return None                      # erro de tarifa nunca e agrupado
        if i.get("pct") and i.get("programa"):
            return f"bonus:{i['programa']}:{i['pct']}"
        return None

    unicos, repetidos = [], 0
    for i in alertas:
        ch = assunto(i)
        if ch and ch in assuntos:
            enviados.add(i["id"])            # ja avisado por outra fonte
            repetidos += 1
            continue
        if ch:
            assuntos[ch] = datetime.now(timezone.utc).isoformat()
        unicos.append(i)
    alertas = unicos
    estado["assuntos"] = assuntos
    for i in alertas[:MAX_POR_RODADA]:
        marca = "🚨 ERRO DE TARIFA" if i.get("erro_tarifa") else "🔥"
        linhas = [f"{marca} <b>{_escapa(i['title'][:180])}</b>"]
        det = [i["source"]]
        if i.get("preco"):
            det.append(f"~R$ {i['preco']:,}".replace(",", "."))
        if i.get("places"):
            det.append(" / ".join(i["places"]))
        linhas.append(" · ".join(det))
        if i.get("why"):
            linhas.append(f"<i>{_escapa(i['why'])}</i>")
        linhas.append(i["link"])
        _tg("\n".join(linhas))
        enviados.add(i["id"])

    if len(alertas) > MAX_POR_RODADA:
        _tg(f"… e mais {len(alertas) - MAX_POR_RODADA} promoções ativas no radar — "
            f"abra o app para ver a lista completa.")
        for i in alertas[MAX_POR_RODADA:]:
            enviados.add(i["id"])

    estado["enviados"] = list(enviados)[-3000:]
    estado["ultima_rodada"] = saida["atualizado"]
    json.dump(estado, open(a.estado, "w"), ensure_ascii=False)

    print(f"novos: {len(novos)} | alertas enviados: {len(alertas)} "
          f"(+{repetidos} repetições agrupadas) | "
          f"total no dados.json: {len(final)} | fontes com erro: {len(errors)}")
    for e in errors:
        print("  !", e["source"], e["error"][:70])

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("known"); s.add_argument("--dir", required=True); s.set_defaults(fn=cmd_known)

    s = sub.add_parser("collect")
    s.add_argument("--known", default=None); s.add_argument("--out", default="novos.json")
    s.add_argument("--hours", type=int, default=30); s.set_defaults(fn=cmd_collect)

    s = sub.add_parser("merge")
    s.add_argument("--dir", required=True); s.add_argument("--new", required=True)
    s.add_argument("--out", default="hoje.json"); s.add_argument("--date")
    s.set_defaults(fn=cmd_merge)

    s = sub.add_parser("prune")
    s.add_argument("--dir", required=True); s.add_argument("--keep", type=int, default=21)
    s.set_defaults(fn=cmd_prune)


    s = sub.add_parser("publish")
    s.add_argument("--dados", default="dados.json")
    s.add_argument("--estado", default="estado.json")
    s.add_argument("--hours", type=int, default=36)
    s.add_argument("--keep", type=int, default=14)
    s.add_argument("--max-items", type=int, default=700, dest="max_items")
    s.add_argument("--alert-hours", type=int, default=48, dest="alert_hours")
    s.set_defaults(fn=cmd_publish)

    args = p.parse_args()
    args.fn(args)
