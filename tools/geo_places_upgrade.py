#!/usr/bin/env python3
"""tools/geo_places_upgrade.py — разовая правка справочника мест.

Что делает (запрос зоны Сайт/Контент от 09.09.2026):

  1. Добавляет `город_en` и `город_ro`. На сайте три языка, а название города
     приходило только по-русски: на английской версии под заголовком стояло
     «ФРАНКФУРТ» кириллицей. Второй справочник у сайта заводить нельзя —
     два списка на проект гарантированно разъедутся, — поэтому имена живут
     здесь, рядом с координатами.

  2. Делит `pattern` на два: топонимы и учреждения остаются в `pattern`,
     национальные прилагательные уезжают в `pattern_weak`.

     🔴 Прилагательное национальности местом события не является.
     «Hungary loses court fight over frozen Russian asset profits» вставало
     в Москву: «Russian» описывает активы, а не место. Это тот же класс
     ошибки, что «Кэпитал Маркетс» → Милан, только не по границам слова,
     а по части речи. Совпадение по слабому выражению теперь даёт отдельный
     ярус `demonym`, а не `headline`: точка не выдумывается и не теряется,
     просто перестаёт называться надёжной.

Скрипт идемпотентен: повторный запуск ничего не меняет.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PLACES = Path(__file__).resolve().parent.parent / "data" / "geo_places.json"

# код: (город_en, город_ro, сильное выражение, слабое выражение)
#
# Сильное — страна, город, центральный банк, орган власти: то, что называет
# место. Слабое — прилагательное национальности: то, что называет
# принадлежность. Пустая строка в слабом = у страны нет отдельной формы
# прилагательного, которую можно отделить (или она совпадает с топонимом).
DATA: dict[str, tuple[str, str, str, str]] = {
    "US": ("New York", "New York",
           r"\bU\.?S\.?A?\b|\bunited states\b|\bamerica\b|\bfederal reserve\b|"
           r"\bthe fed\b|\bfomc\b|\bwall street\b|\bwashington\b|\bwhite house\b|"
           r"\btreasury\b|\bсша\b|\bфрс\b|\bуолл-стрит",
           r"\bamerican\b|\bамерик\w*"),
    "EU": ("Frankfurt", "Frankfurt",
           r"\beurozone\b|\beuro area\b|\becb\b|european central bank|"
           r"\beu\b(?=\s+(economy|inflation|gdp|rate|summit|commission))|"
           r"\bевропейск\w* центральн\w*|\bецб\b|\bеврозон\w*", ""),
    "DE": ("Frankfurt", "Frankfurt",
           r"\bgermany\b|\bbundesbank\b|\bfrankfurt\b|\bгермани[ияю]\b|\bфранкфурт\w*",
           r"\bgerman\b|\bнемецк\w*|\bгерманск\w*"),
    "FR": ("Paris", "Paris",
           r"\bfrance\b|\bparis\b|\bbanque de france\b|\bфранци[ияю]\b|\bпариж\w*",
           r"\bfrench\b(?!\s+fries)|\bфранцузск\w*"),
    "GB": ("London", "Londra",
           r"\buk\b|united kingdom|\bbritain\b|(?<!new )\bengland\b|bank of england|"
           r"\bboe\b|\blondon\b|\bвеликобритани[ияю]\b|\bбанк англии\b|\bлондон\w*",
           r"\bbritish\b|\benglish\b|\bбританск\w*|\bанглийск\w*"),
    "CH": ("Zurich", "Zürich",
           r"\bswitzerland\b|\bsnb\b|\bzurich\b|\bшвейцари[ияю]\b|\bцюрих\w*",
           r"\bswiss\b|\bшвейцарск\w*"),
    "IT": ("Milan", "Milano",
           r"\bitaly\b|\bmilan\b|\brome\b|\bитали[ияю]\b|\bмилан\w*|\bрим\b",
           r"\bitalian\b|\bитальянск\w*"),
    "ES": ("Madrid", "Madrid",
           r"\bspain\b|\bmadrid\b|\bиспани[ияю]\b|\bмадрид\w*",
           r"\bspanish\b|\bиспанск\w*"),
    "NL": ("Amsterdam", "Amsterdam",
           r"\bnetherlands\b|\bamsterdam\b|\bнидерланд\w*|\bамстердам\w*",
           r"\bdutch\b|\bголландск\w*|\bнидерландск\w*"),
    "SE": ("Stockholm", "Stockholm",
           r"\bsweden\b|\briksbank\b|\bstockholm\b|\bшвеци[ияю]\b|\bстокгольм\w*",
           r"\bswedish\b|\bшведск\w*"),
    "NO": ("Oslo", "Oslo",
           r"\bnorway\b|\bnorges bank\b|\boslo\b|\bнорвеги[ияю]\b|\bосло\b",
           r"\bnorwegian\b|\bнорвежск\w*"),
    "PL": ("Warsaw", "Varșovia",
           r"\bpoland\b|\bwarsaw\b|\bпольш[аиеу]\b|\bваршав\w*",
           r"\bpolish\b|\bпольск\w*"),
    "JP": ("Tokyo", "Tokio",
           r"\bjapan\b|bank of japan|\bboj\b|\btokyo\b|\bяпони[ияю]\b|\bбанк японии|\bтоки[ояю]\b",
           r"\bjapanese\b|\bяпонск\w*"),
    "CN": ("Shanghai", "Shanghai",
           r"\bchina\b|\bpboc\b|people'?s bank of china|\bbeijing\b|\bshanghai\b|"
           r"\bкита[йея]\b|\bпекин\w*|\bшанха[йия]\w*",
           r"\bchinese\b|\bкитайск\w*"),
    "HK": ("Hong Kong", "Hong Kong",
           r"\bhong kong\b|\bгонконг\w*", ""),
    "SG": ("Singapore", "Singapore",
           r"\bsingapore\b|\bсингапур\w*", ""),
    "KR": ("Seoul", "Seul",
           r"\bsouth korea\b|bank of korea|\bseoul\b|\bюжн\w* коре[ияю]\b|\bсеул\w*",
           r"\bkorean\b|\bкорейск\w*"),
    "IN": ("Mumbai", "Mumbai",
           r"\bindia\b|reserve bank of india|\bmumbai\b|\bdelhi\b|\bинди[ияю]\b|\bмумба[иия]\w*",
           r"\bindian\b(?!\s+ocean)|\bиндийск\w*"),
    "AU": ("Sydney", "Sydney",
           r"\baustralia\b|\brba\b|reserve bank of australia|\bsydney\b|"
           r"\bавстрали[ияю]\b|\bсидне[йя]\w*",
           r"\baustralian\b|\bавстралийск\w*"),
    "NZ": ("Wellington", "Wellington",
           r"\bnew zealand\b|\brbnz\b|\bwellington\b|\bнов\w* зеланди[ияю]\b", ""),
    "CA": ("Toronto", "Toronto",
           r"\bcanada\b|bank of canada|\btoronto\b|\bканад[аыеу]\b|\bторонто\b",
           r"\bcanadian\b|\bканадск\w*"),
    "BR": ("Sao Paulo", "São Paulo",
           r"\bbrazil\b|\bsao paulo\b|\bбразили[ияю]\b|\bсан-паулу\b",
           r"\bbrazilian\b|\bбразильск\w*"),
    "MX": ("Mexico City", "Ciudad de México",
           r"\bmexico\b|\bbanxico\b|\bмексик[аиеу]\b|\bмехико\b",
           r"\bmexican\b|\bмексиканск\w*"),
    "AR": ("Buenos Aires", "Buenos Aires",
           r"\bargentina\b|\bbuenos aires\b|\bаргентин[аыеу]\b|\bбуэнос-айрес\w*",
           r"\bargentine\b|\bargentinian\b|\bаргентинск\w*"),
    "ZA": ("Johannesburg", "Johannesburg",
           r"\bsouth africa\b|\bjohannesburg\b|\bюжн\w* африк\w*|\bюар\b|\bйоханнесбург\w*",
           r"south african\b|\bюжноафриканск\w*"),
    "TR": ("Istanbul", "Istanbul",
           r"\bturkey'?s\b|central bank of turkey|\bistanbul\b|\bturkiye\b|"
           r"\bтурци[ияю]\b|\bстамбул\w*",
           r"\bturkish\b|\bтурецк\w*"),
    "RU": ("Moscow", "Moscova",
           r"\brussia\b|\bmoscow\b|\bkremlin\b|\bcentral bank of russia\b|"
           r"\bросси[ияю]\b|\bмоскв\w*|\bкремл[ья]\w*|\bбанк россии\b",
           r"\brussian\b|\bросси[йй]ск\w*|\bрусск\w*"),
    "UA": ("Kyiv", "Kiev",
           r"\bukraine\b|\bkyiv\b|\bkiev\b|\bукраин[аыеу]\b|\bкиев\w*",
           r"\bukrainian\b|\bукраинск\w*"),
    "AE": ("Dubai", "Dubai",
           r"\buae\b|united arab emirates|\bdubai\b|\babu dhabi\b|\bоаэ\b|"
           r"\bдубай\w*|\bэмират\w*", ""),
    "SA": ("Riyadh", "Riad",
           r"\bsaudi arabia\b|\baramco\b|\briyadh\b|\bсаудовск\w* арави\w*|"
           r"\bсаудовской аравии\b|\bэр-рияд\w*|\bарамко\b",
           r"\bsaudi\b|\bsaudis\b|\bсаудовск\w*"),
    "IL": ("Tel Aviv", "Tel Aviv",
           r"\bisrael\b|\btel aviv\b|\bbank of israel\b|\bизраил[ья]\w*|\bтель-авив\w*",
           r"\bisraeli\b|\bизраильск\w*"),
    "IR": ("Tehran", "Teheran",
           r"\biran\b|\btehran\b|\bhormuz\b|\bиран[аеу]?\b|\bтегеран\w*|\bормуз\w*",
           r"\biranian\b|\bиранск\w*"),
    "VE": ("Caracas", "Caracas",
           r"\bvenezuela\b|\bcaracas\b|\bвенесуэл\w*|\bкаракас\w*", ""),
    "NG": ("Lagos", "Lagos",
           r"\bnigeria\b|\blagos\b|\bнигери[ияю]\b|\bлагос\w*",
           r"\bnigerian\b|\bнигерийск\w*"),
    "EG": ("Cairo", "Cairo",
           r"\begypt\b|\bsuez\b|\bcairo\b|\bегипт\w*|\bсуэц\w*|\bкаир\w*", ""),
    "CL": ("Santiago", "Santiago",
           r"\bchile\b|\bcodelco\b|\bsantiago\b|\bчили\b|\bкодельк\w*",
           r"\bchilean\b|\bчилийск\w*"),
    "PE": ("Lima", "Lima",
           r"\bperu\b|\bперу\b", r"\bperuvian\b|\bперуанск\w*"),
    "ID": ("Jakarta", "Jakarta",
           r"\bindonesia\b|\bjakarta\b|\bиндонези[ияю]\b|\bджакарт\w*",
           r"\bindonesian\b|\bиндонезийск\w*"),
    "TH": ("Bangkok", "Bangkok",
           r"\bthailand\b|\bbangkok\b|\bтаиланд\w*|\bбангкок\w*",
           r"\bthai\b(?!\s+food)|\bтайск\w*"),
    "VN": ("Hanoi", "Hanoi",
           r"\bvietnam\b|\bhanoi\b|\bвьетнам\w*|\bхано[йия]\b",
           r"\bvietnamese\b|\bвьетнамск\w*"),
    "TW": ("Taipei", "Taipei",
           r"\btaiwan\b|\btsmc\b|\btaipei\b|\bтайван[ья]\w*|\bтайбэ[йия]\b", ""),
    "CI": ("Abidjan", "Abidjan",
           r"ivory coast|c[oô]te d'?ivoire|\babidjan\b|\bкот-д'?ивуар\w*", ""),
    "GH": ("Accra", "Accra",
           r"\bghana\b|\baccra\b|\bгана\b|\bаккр[аыеу]\b",
           r"\bghanaian\b|\bганск\w*"),
    "AT": ("Vienna", "Viena",
           r"\bopec\b|\bopec\+|\bvienna\b|\bопек\b|\bвен\w* саммит", ""),
    # Страны, которых в справочнике не было вовсе. Отсутствие в списке — не
    # «нет точки», а точка в чужом месте: «Hungary loses court fight over
    # frozen Russian asset profits» уезжала в Москву в том числе потому, что
    # Венгрии в справочнике не существовало и перебивать слово Russian было
    # нечем. Берём те, что реально встречаются в рыночной ленте.
    "HU": ("Budapest", "Budapesta",
           r"\bhungary\b|\bbudapest\b|\bвенгри[ияю]\b|\bбудапешт\w*",
           r"\bhungarian\b|\bвенгерск\w*"),
    "CZ": ("Prague", "Praga",
           r"\bczechia\b|\bczech republic\b|\bprague\b|\bчехи[ияю]\b|\bпраг[аеу]\b",
           r"\bczech\b|\bчешск\w*"),
    "RO": ("Bucharest", "București",
           r"\bromania\b|\bbucharest\b|\bрумыни[ияю]\b|\bбухарест\w*",
           r"\bromanian\b|\bрумынск\w*"),
    "GR": ("Athens", "Atena",
           r"\bgreece\b|\bathens\b|\bгреци[ияю]\b|\bафин\w*",
           r"\bgreek\b|\bгреческ\w*"),
    "PT": ("Lisbon", "Lisabona",
           r"\bportugal\b|\blisbon\b|\bпортугали[ияю]\b|\bлиссабон\w*",
           r"\bportuguese\b|\bпортугальск\w*"),
    "BE": ("Brussels", "Bruxelles",
           r"\bbelgium\b|\bbrussels\b|\bбельги[ияю]\b|\bбрюссел\w*",
           r"\bbelgian\b|\bбельгийск\w*"),
    "DK": ("Copenhagen", "Copenhaga",
           r"\bdenmark\b|\bcopenhagen\b|\bmaersk\b|\bдани[ияю]\b|\bкопенгаген\w*",
           r"\bdanish\b|\bдатск\w*"),
    "FI": ("Helsinki", "Helsinki",
           r"\bfinland\b|\bhelsinki\b|\bфинлянди[ияю]\b|\bхельсинки\b",
           r"\bfinnish\b|\bфинск\w*"),
    "IE": ("Dublin", "Dublin",
           r"(?<!northern )\bireland\b|\bdublin\b|\bирланди[ияю]\b|\bдублин\w*",
           r"\birish\b|\bирландск\w*"),
    "MD": ("Chisinau", "Chișinău",
           r"\bmoldova\b|\bchisinau\b|\bмолдов\w*|\bкишинёв\w*|\bкишинев\w*",
           r"\bmoldovan\b|\bмолдавск\w*"),
}


# Координаты и русское имя для стран, которых в справочнике ещё нет.
NEW: dict[str, tuple[float, float, str]] = {
    "HU": (19.04, 47.50, "Будапешт"),
    "CZ": (14.42, 50.09, "Прага"),
    "RO": (26.10, 44.43, "Бухарест"),
    "GR": (23.73, 37.98, "Афины"),
    "PT": (-9.14, 38.72, "Лиссабон"),
    "BE": (4.35, 50.85, "Брюссель"),
    "DK": (12.57, 55.68, "Копенгаген"),
    "FI": (24.94, 60.17, "Хельсинки"),
    "IE": (-6.26, 53.35, "Дублин"),
}


def main() -> int:
    raw = json.loads(PLACES.read_text(encoding="utf-8"))
    missing = [c for c in raw
               if not c.startswith("_") and isinstance(raw[c], dict) and c not in DATA]
    if missing:
        print(f"нет данных для стран: {missing}", file=sys.stderr)
        return 1

    changed = 0
    for code, (en, ro, strong, weak) in DATA.items():
        meta = raw.get(code)
        if not isinstance(meta, dict):
            if code not in NEW:
                print(f"страна {code} отсутствует в справочнике — пропущена", file=sys.stderr)
                continue
            lon, lat, city = NEW[code]
            meta = raw[code] = {"lon": lon, "lat": lat, "город": city}
        for expr in (strong, weak):
            if expr:
                re.compile(expr, re.I)  # падаем громко на кривом выражении
        before = json.dumps(meta, ensure_ascii=False, sort_keys=True)
        meta["город_en"] = en
        meta["город_ro"] = ro
        meta["pattern"] = strong
        if weak:
            meta["pattern_weak"] = weak
        else:
            meta.pop("pattern_weak", None)
        if json.dumps(meta, ensure_ascii=False, sort_keys=True) != before:
            changed += 1

    PLACES.write_text(json.dumps(raw, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print(f"обновлено стран: {changed} из {len(DATA)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
