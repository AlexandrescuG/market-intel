"""Тесты extract.py — критерии приёмки из спеки."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from analyze.extract import (
    tier, signature, cluster, extract_facts, classify, rollup, run, parse_feed,
    CLUSTER_WINDOW_H,
)

# ─── Фикстуры: базовые unix-метки (06:39 и 09:05 17 июня 2026) ───────────────

from datetime import datetime
TS_0639 = int(datetime(2026, 6, 17, 6, 39).timestamp())   # Kobeissi
TS_0905 = int(datetime(2026, 6, 17, 9,  5).timestamp())   # WallStreetMav
TS_0728 = int(datetime(2026, 6, 17, 7, 28).timestamp())   # naiivememe
TS_0817 = int(datetime(2026, 6, 17, 8, 17).timestamp())   # WatcherGuru
TS_0700 = int(datetime(2026, 6, 17, 7,  0).timestamp())   # NiohBerg и пр.


# ══════════════════════════════════════════════════════════════════════════════
# tier()
# ══════════════════════════════════════════════════════════════════════════════

def test_tier_t1():
    assert tier("KobeissiLetter") == 1

def test_tier_t2():
    assert tier("WallStreetMav") == 2

def test_tier_t3():
    assert tier("NiohBerg") == 3

def test_tier_unknown():
    assert tier("some_rando_account") == 3

def test_tier_at_prefix_stripped():
    assert tier("@KobeissiLetter") == 1

def test_tier_domain():
    assert tier("investing.com") == 1

def test_tier_domain_normalized():
    assert tier("https://www.rbc.ru/story/abc") == 1


# ══════════════════════════════════════════════════════════════════════════════
# signature()
# ══════════════════════════════════════════════════════════════════════════════

def test_signature_tickers():
    sig = signature("$BTC falls -7% to $76")
    assert "$BTC" in sig

def test_signature_numbers():
    sig = signature("$BTC falls -7% to $76")
    assert "76" in sig
    assert "7" in sig

def test_signature_empty():
    assert signature("nothing to see here") == set()

def test_signature_no_translate_dependency():
    # числа и тикеры одинаковы в оригинале и переводе
    en = signature("Oil drops to $76, down -7%")
    ru = signature("Нефть упала до $76, минус -7%")
    assert en & ru  # есть общие токены


# ══════════════════════════════════════════════════════════════════════════════
# cluster()
# ══════════════════════════════════════════════════════════════════════════════

def _post(src, text, ts, url=""):
    return {"src": src, "text": text, "ts": ts, "url": url}

# Критерий 1: Kobeissi + WallStreetMav → один кластер (нефть)
def test_cluster_oil_kobeissi_wallstreetmav():
    """Оба поста содержат '76' и '$WTI' — Jaccard >= 0.3."""
    p1 = _post("KobeissiLetter", "Oil $WTI crashes -7%, from $108 to $76", TS_0639)
    p2 = _post("WallStreetMav",  "$WTI: $108 → $75. Iran deal risk off.",  TS_0905)
    groups = cluster([p1, p2])
    assert len(groups) == 1
    assert len(groups[0]) == 2

# Критерий 3: lead_sec > 0 (первый в 06:39, второй в 09:05)
def test_cluster_lead_sec():
    p1 = _post("KobeissiLetter", "Oil $WTI -7% $76 $108", TS_0639)
    p2 = _post("WallStreetMav",  "Oil $WTI $76 down $108", TS_0905)
    ev = rollup(cluster([p1, p2])[0])
    assert ev["lead_sec"] > 0
    assert ev["first_ts"] == TS_0639

# Критерий 5: «Илон дороже биткойна» — два поста → один кластер size>=2
def test_cluster_elon_btc():
    p1 = _post("naiivememe",  "Elon Musk surpasses $BTC $1 trillion net worth",  TS_0728)
    p2 = _post("WatcherGuru", "Elon Musk now worth more than $BTC at $1 trillion", TS_0817)
    groups = cluster([p1, p2])
    # Должны попасть в один кластер (общий $BTC и "1")
    flat = [p for g in groups for p in g]
    merged = [g for g in groups if len(g) >= 2]
    assert len(merged) >= 1 and len(merged[0]) >= 2

# Критерий 2: "$300B deal" от T3-источников — отдельный кластер (не с нефтью)
def test_cluster_300b_separate_from_oil():
    oil_p = _post("KobeissiLetter", "Oil $WTI -7% $76", TS_0639)
    deal_p1 = _post("NiohBerg",       "$300B Iran deal signed", TS_0700)
    deal_p2 = _post("ImBreckWorsham", "Iran $300B agreement reached", TS_0700)
    groups = cluster([oil_p, deal_p1, deal_p2])
    # Нефтяной и deal-кластеры не должны слиться
    assert len(groups) >= 2

# Пустые сигнатуры не сливаются между собой
def test_cluster_empty_sig_singletons():
    p1 = _post("x", "hello world",  TS_0639)
    p2 = _post("y", "hey there",    TS_0639)
    groups = cluster([p1, p2])
    assert len(groups) == 2   # каждый в своём синглтоне


# ══════════════════════════════════════════════════════════════════════════════
# classify()
# ══════════════════════════════════════════════════════════════════════════════

def test_classify_promo_russian():
    p = _post("saylor", "деньги на битах — купить сейчас!", TS_0639)
    assert classify(p) == "promo"

def test_classify_promo_hodl():
    p = _post("saylor", "Just HODL your Bitcoin forever", TS_0639)
    assert classify(p) == "promo"

def test_classify_price_data_t1():
    p = _post("KobeissiLetter", "Oil down -7% to $76 today", TS_0639)
    assert classify(p) == "price_data"

def test_classify_price_data_t2():
    p = _post("WallStreetMav", "$WTI hits $75, down from $108", TS_0905)
    assert classify(p) == "price_data"

def test_classify_news_claim_t3_with_numbers():
    p = _post("NiohBerg", "Iran demands $300 billion advance", TS_0700)
    assert classify(p) == "news_claim"

def test_classify_news_claim_t1_no_numbers():
    p = _post("KobeissiLetter", "Iran deal talks breaking down", TS_0639)
    assert classify(p) == "news_claim"

def test_classify_opinion_t3_no_numbers():
    p = _post("X22Report", "The deep state is collapsing as planned", TS_0700)
    assert classify(p) == "opinion"


# ══════════════════════════════════════════════════════════════════════════════
# rollup() — flag и t1_sources
# ══════════════════════════════════════════════════════════════════════════════

# Критерий 1 (полный): Kobeissi=T1, WallStreetMav=T2 → t1=1 → SINGLE-SOURCE
def test_rollup_oil_single_source():
    p1 = _post("KobeissiLetter", "Oil $WTI -7% $76 $108", TS_0639)
    p2 = _post("WallStreetMav",  "Oil $WTI $76 down $108", TS_0905)
    ev = rollup([p1, p2])
    assert ev["t1_sources"] == 1
    assert ev["flag"] == "SINGLE-SOURCE"

# Критерий 2: NiohBerg + ImBreckWorsham (оба T3) → UNVERIFIED
def test_rollup_300b_unverified():
    p1 = _post("NiohBerg",       "Iran $300B deal", TS_0700)
    p2 = _post("ImBreckWorsham", "Iran $300 billion agreement", TS_0700)
    ev = rollup([p1, p2])
    assert ev["t1_sources"] == 0
    assert ev["flag"] == "UNVERIFIED"

def test_rollup_corroborated_two_t1():
    p1 = _post("KobeissiLetter", "$WTI $76 -7%", TS_0639)
    p2 = _post("rbc.ru",         "$WTI $76 oil falls", TS_0700)
    ev = rollup([p1, p2])
    assert ev["t1_sources"] == 2
    assert ev["flag"] == "CORROBORATED"

def test_rollup_cluster_id_stable():
    p1 = _post("KobeissiLetter", "Oil $WTI $76", TS_0639)
    p2 = _post("WallStreetMav",  "Oil $WTI $76", TS_0905)
    ev1 = rollup([p1, p2])
    ev2 = rollup([p2, p1])   # порядок другой
    assert ev1["cluster_id"] == ev2["cluster_id"]


# ══════════════════════════════════════════════════════════════════════════════
# run() — фильтрация promo и пустых singleton-opinion
# ══════════════════════════════════════════════════════════════════════════════

SAMPLE_FEED = """\
[6/17/26 6:39 AM] Markgandonbon: 💰 @KobeissiLetter Oil $WTI crashes -7%, from $108 to $76. Iran deal risk off. https://x.com/KobeissiLetter/status/1
[6/17/26 9:05 AM] Markgandonbon: 📉 @WallStreetMav $WTI: $108 → $76. Oil risk off on Iran deal. https://x.com/WallStreetMav/status/2
[6/17/26 7:00 AM] Markgandonbon: 🔴 @NiohBerg Iran demands $300B advance payment for deal https://x.com/NiohBerg/status/3
[6/17/26 7:00 AM] Markgandonbon: 📢 @ImBreckWorsham $300 billion Iran agreement terms leaked https://x.com/ImBreckWorsham/status/4
[6/17/26 7:28 AM] Markgandonbon: 💡 naiivememe Elon Musk surpasses $BTC $1 trillion net worth https://x.com/naiivememe/status/5
[6/17/26 8:17 AM] Markgandonbon: 🚀 @WatcherGuru Elon Musk now worth more than $BTC market cap $1 trillion https://x.com/WatcherGuru/status/6
[6/17/26 7:30 AM] Markgandonbon: 💸 @saylor деньги на битах HODL forever https://x.com/saylor/status/7
"""

def test_run_promo_filtered():
    events = run(SAMPLE_FEED)
    for ev in events:
        assert ev["post_type"] != "promo"

def test_run_oil_cluster_present():
    events = run(SAMPLE_FEED)
    oil_ev = [e for e in events if any("WTI" in a or "76" in sig
              for a in e["assets"]
              for sig in [str(e["assets"])])]
    # нефтяной кластер должен быть
    assert any("76" in str(e["facts"]) or "$WTI" in e["assets"] for e in events)

def test_run_oil_cluster_single_source():
    events = run(SAMPLE_FEED)
    oil = next(
        (e for e in events if "$WTI" in e["assets"] and e["size"] >= 2), None
    )
    assert oil is not None
    assert oil["flag"] == "SINGLE-SOURCE"
    assert oil["lead_sec"] > 0

def test_run_300b_cluster_unverified():
    events = run(SAMPLE_FEED)
    deal = next(
        (e for e in events if any("300" in str(f["value"]) for f in e["facts"])
         and "$WTI" not in e["assets"]), None
    )
    assert deal is not None
    assert deal["flag"] == "UNVERIFIED"

def test_run_elon_btc_clustered():
    events = run(SAMPLE_FEED)
    elon = next((e for e in events if "$BTC" in e["assets"] and e["size"] >= 2), None)
    assert elon is not None


# ══════════════════════════════════════════════════════════════════════════════
# parse_feed()
# ══════════════════════════════════════════════════════════════════════════════

def test_parse_feed_basic():
    raw = "[6/17/26 6:39 AM] Markgandonbon: 💰 @KobeissiLetter Oil falls -7% https://x.com/k/1"
    posts = parse_feed(raw)
    assert len(posts) == 1
    assert posts[0]["src"] == "KobeissiLetter"
    assert "Oil falls" in posts[0]["text"]
    assert posts[0]["url"] == "https://x.com/k/1"

def test_parse_feed_ts_am_pm():
    raw = "[6/17/26 9:05 AM] Bot: @WallStreetMav text https://x.com/w/1"
    posts = parse_feed(raw)
    dt = datetime.fromtimestamp(posts[0]["ts"])
    assert dt.hour == 9 and dt.minute == 5

def test_parse_feed_pm():
    raw = "[6/17/26 2:30 PM] Bot: @Someone text https://x.com/s/1"
    posts = parse_feed(raw)
    dt = datetime.fromtimestamp(posts[0]["ts"])
    assert dt.hour == 14

def test_parse_feed_domain_src():
    raw = "[6/17/26 8:00 AM] Bot: some news https://investing.com/news/123"
    posts = parse_feed(raw)
    assert posts[0]["src"] == "investing.com"
