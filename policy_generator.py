from __future__ import annotations

import re
import time
from datetime import date
from pathlib import Path

from policy_validator import enforce_market, validate_combined
from policy_validator import validate_localized_output
from policy_ai_assist import audit_policies
from rulepack_manager import load_rulepack
from knowledge_update import COUNTRY_OFFICIAL_SOURCES


COUNTRIES = {
    "德国|germany|deutschland": ("Germany", "de", True, "German and European Union consumer law, the BGB, GDPR and German data-protection law"),
    "奥地利|austria|österreich": ("Austria", "de", True, "Austrian and European Union consumer law and GDPR"),
    "瑞士|switzerland|schweiz": ("Switzerland", "de", False, "Swiss consumer law and the Swiss Federal Act on Data Protection"),
    "法国|france": ("France", "fr", True, "French and European Union consumer law, the French Consumer Code and GDPR"),
    "意大利|italy|italia": ("Italy", "it", True, "Italian and European Union consumer law, the Italian Consumer Code and GDPR"),
    "西班牙|spain|españa": ("Spain", "es", True, "Spanish and European Union consumer law and GDPR"),
    "葡萄牙|portugal": ("Portugal", "pt", True, "Portuguese and European Union consumer law and GDPR"),
    "荷兰|netherlands|nederland": ("Netherlands", "nl", True, "Dutch and European Union consumer law, the Dutch Civil Code and GDPR"),
    "比利时|belgium|belgië|belgique": ("Belgium", "nl", True, "Belgian and European Union consumer law and GDPR"),
    "丹麦|denmark|danmark": ("Denmark", "da", True, "Danish and European Union consumer law, the Danish Sale of Goods Act and GDPR"),
    "瑞典|sweden|sverige": ("Sweden", "sv", True, "Swedish and European Union consumer law and GDPR"),
    "挪威|norway|norge": ("Norway", "no", False, "Norwegian consumer law, EEA rules and Norwegian data-protection law"),
    "芬兰|finland|suomi": ("Finland", "fi", True, "Finnish and European Union consumer law and GDPR"),
    "波兰|poland|polska": ("Poland", "pl", True, "Polish and European Union consumer law and GDPR"),
    "捷克|捷克共和国|czechia|czech republic": ("Czechia", "cs", True, "Czech and European Union consumer law and GDPR"),
    "匈牙利|hungary": ("Hungary", "hu", True, "Hungarian and European Union consumer law and GDPR"),
    "罗马尼亚|romania": ("Romania", "ro", True, "Romanian and European Union consumer law and GDPR"),
    "保加利亚|bulgaria": ("Bulgaria", "bg", True, "Bulgarian and European Union consumer law and GDPR"),
    "希腊|greece": ("Greece", "el", True, "Greek and European Union consumer law and GDPR"),
    "克罗地亚|croatia": ("Croatia", "hr", True, "Croatian and European Union consumer law and GDPR"),
    "斯洛伐克|slovakia": ("Slovakia", "sk", True, "Slovak and European Union consumer law and GDPR"),
    "斯洛文尼亚|slovenia": ("Slovenia", "sl", True, "Slovenian and European Union consumer law and GDPR"),
    "爱沙尼亚|estonia": ("Estonia", "et", True, "Estonian and European Union consumer law and GDPR"),
    "拉脱维亚|latvia": ("Latvia", "lv", True, "Latvian and European Union consumer law and GDPR"),
    "立陶宛|lithuania": ("Lithuania", "lt", True, "Lithuanian and European Union consumer law and GDPR"),
    "英国|uk|united kingdom|great britain": ("United Kingdom", "en", False, "UK consumer law, the Consumer Rights Act and UK GDPR"),
    "爱尔兰|ireland": ("Ireland", "en", True, "Irish and European Union consumer law and GDPR"),
    "卢森堡|luxembourg": ("Luxembourg", "fr", True, "Luxembourg and European Union consumer law and GDPR"),
    "冰岛|iceland": ("Iceland", "is", False, "Icelandic consumer law, EEA rules and data-protection law"),
    "马耳他|malta": ("Malta", "mt", True, "Maltese and European Union consumer law and GDPR"),
    "塞浦路斯|cyprus|κύπρος": ("Cyprus", "el", True, "Cypriot and European Union consumer law and GDPR"),
    "列支敦士登|liechtenstein": ("Liechtenstein", "de", False, "Liechtenstein consumer law, EEA rules and data-protection law"),
    "阿尔巴尼亚|albania|shqipëri": ("Albania", "sq", False, "Albanian consumer and data-protection law"),
    "塞尔维亚|serbia|srbija": ("Serbia", "sr", False, "Serbian consumer and data-protection law"),
    "波斯尼亚和黑塞哥维那|bosnia and herzegovina|bosnia": ("Bosnia and Herzegovina", "bs", False, "Bosnia and Herzegovina consumer and data-protection law"),
    "黑山|montenegro|crna gora": ("Montenegro", "sr", False, "Montenegrin consumer and data-protection law"),
    "北马其顿|north macedonia|macedonia": ("North Macedonia", "mk", False, "North Macedonian consumer and data-protection law"),
    "摩尔多瓦|moldova": ("Moldova", "ro", False, "Moldovan consumer and data-protection law"),
    "乌克兰|ukraine|україна": ("Ukraine", "uk", False, "Ukrainian consumer and data-protection law"),
    "白俄罗斯|belarus|беларусь": ("Belarus", "be", False, "Belarusian consumer and data-protection law"),
    "科索沃|kosovo": ("Kosovo", "sq", False, "Kosovo consumer and data-protection law"),
    "土耳其|turkey|türkiye": ("Turkey", "tr", False, "Turkish consumer and personal-data protection law"),
    "俄罗斯|russia|россия": ("Russia", "ru", False, "Russian consumer and personal-data protection law"),
    "格鲁吉亚|georgia|საქართველო": ("Georgia", "ka", False, "Georgian consumer and data-protection law"),
    "亚美尼亚|armenia|հայաստան": ("Armenia", "hy", False, "Armenian consumer and data-protection law"),
    "阿塞拜疆|azerbaijan|azərbaycan": ("Azerbaijan", "az", False, "Azerbaijani consumer and data-protection law"),
    "安道尔|andorra": ("Andorra", "ca", False, "Andorran consumer and data-protection law"),
    "摩纳哥|monaco": ("Monaco", "fr", False, "Monegasque consumer and data-protection law"),
    "圣马力诺|san marino": ("San Marino", "it", False, "San Marino consumer and data-protection law"),
    "梵蒂冈|vatican city|vatican": ("Vatican City", "it", False, "Vatican City applicable consumer and data rules"),
}

# Consumer-law rules used by the generator.  EU/EEA countries inherit the
# harmonised distance-selling baseline; only genuine national differences are
# kept here.  Commercial promises (30-day returns, prepaid labels and 10-day
# operational refunds) are intentionally stored separately from statutory law.
EU_COUNTRIES = {profile[0] for profile in COUNTRIES.values() if profile[2]}
EEA_COUNTRIES = EU_COUNTRIES | {"Norway", "Iceland", "Liechtenstein"}
LEGAL_GUARANTEE = {
    "Spain": "at least 3 years for new goods",
    "Portugal": "3 years for movable goods, subject to the remedies and conditions of Portuguese law",
    "Sweden": "a 3-year statutory complaint period",
    "Ireland": "statutory remedies for faulty goods that may remain available for up to 6 years, depending on the goods and circumstances",
    "Netherlands": "a conformity period based on the product's reasonably expected lifetime rather than a fixed two-year cap",
    "Finland": "a conformity period based on the product's reasonably expected lifetime rather than a fixed two-year cap",
    "Norway": "2 years, or 5 years for goods intended to last substantially longer",
    "Iceland": "2 years, or 5 years for goods intended to last substantially longer",
    "United Kingdom": "statutory remedies under the Consumer Rights Act 2015; limitation is generally 6 years in England/Wales/Northern Ireland and 5 years in Scotland",
    "Switzerland": "the statutory warranty rights and limitation period applicable under Swiss law",
}

LEGAL_GUARANTEE_CN = {
    "Spain": "新商品至少3年法定质量保证",
    "Portugal": "动产3年法定质量保证，具体救济依葡萄牙法律",
    "Sweden": "3年法定投诉期",
    "Ireland": "瑕疵商品的法定救济视商品和具体情况最长可达6年",
    "Netherlands": "按商品合理预期寿命确定，不设统一两年上限",
    "Finland": "按商品合理预期寿命确定，不设统一两年上限",
    "Norway": "通常2年；预期使用寿命明显更长的商品为5年",
    "Iceland": "通常2年；预期使用寿命明显更长的商品为5年",
}

REGISTER_AUTHORITIES = {
    "Denmark": ("CVR No.", "Det Centrale Virksomhedsregister (CVR), Erhvervsstyrelsen"),
    "United Kingdom": ("Company Registration Number", "Companies House"),
    "Germany": ("Register number", "The competent German commercial register"),
    "Austria": ("Company register number", "The competent Austrian Firmenbuch court"),
    "France": ("Registration number", "Registre national des entreprises (RNE)"),
    "Italy": ("Registration number", "Registro delle Imprese"),
    "Netherlands": ("KVK number", "Kamer van Koophandel (KVK)"),
    "Belgium": ("Enterprise number", "Crossroads Bank for Enterprises (CBE/KBO/BCE)"),
}

OFFICIAL_SOURCES = {
    "EU": (
        "Directive 2011/83/EU (current effective consolidation): https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:02011L0083-20260927",
        "Directive (EU) 2019/771 (current effective consolidation): https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:02019L0771-20260731",
        "Rome I Article 6: https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32008R0593",
        "European Commission GDPR obligations: https://commission.europa.eu/law/law-topic/data-protection/information-business-and-organisations/obligations_en",
    ),
    "EEA": ("EFTA EEA-Lex / JCD 181/2012: https://www.efta.int/eea-lex/32011l0083",),
    "UK": (
        "UK Government distance selling: https://www.gov.uk/online-and-distance-selling-for-businesses/distance-selling",
        "UK Government returns/refunds: https://www.gov.uk/accepting-returns-and-giving-refunds",
    ),
    "CH": ("Swiss SME Portal: https://www.kmu.admin.ch/en/statutory-obligations-swiss-and-european-e-commerce-laws",),
    "TR": ("Turkish Ministry of Trade: https://tuketici.ticaret.gov.tr/yayinlar/tuketici-bilgi-rehberi/mesafeli-sozlesmeler-hakkinda-bilgilendirme",),
}


def legal_coverage(country: str, is_eu: bool) -> tuple[str, tuple[str, ...]]:
    if is_eu:
        return "EU", OFFICIAL_SOURCES["EU"]
    if country in {"Norway", "Iceland", "Liechtenstein"}:
        return "EEA", OFFICIAL_SOURCES["EU"] + OFFICIAL_SOURCES["EEA"]
    key = {"United Kingdom": "UK", "Switzerland": "CH", "Turkey": "TR"}.get(country)
    if key:
        return key, OFFICIAL_SOURCES[key]
    raise RuntimeError(
        f"{country} 的普通实体商品 B2C 网店规则尚未完成官方来源复核。为避免生成不严谨政策，程序已停止输出该国家。"
    )

LANGUAGES = {
    "中文|简体中文|chinese|zh|zh-cn": ("Chinese", "zh-CN"),
    "英语|英文|english|en": ("English", "en"),
    "德语|德文|german|deutsch|de": ("German", "de"),
    "法语|法文|french|français|fr": ("French", "fr"),
    "意大利语|italian|italiano|it": ("Italian", "it"),
    "西班牙语|spanish|español|es": ("Spanish", "es"),
    "葡萄牙语|portuguese|português|pt": ("Portuguese", "pt"),
    "荷兰语|dutch|nederlands|nl": ("Dutch", "nl"),
    "丹麦语|danish|dansk|da": ("Danish", "da"),
    "瑞典语|swedish|svenska|sv": ("Swedish", "sv"),
    "挪威语|norwegian|norsk|no": ("Norwegian", "no"),
    "芬兰语|finnish|suomi|fi": ("Finnish", "fi"),
    "波兰语|polish|polski|pl": ("Polish", "pl"),
    "罗马尼亚语|romanian|română|ro": ("Romanian", "ro"),
    "捷克语|czech|čeština|cs": ("Czech", "cs"),
    "希腊语|greek|ελληνικά|el": ("Greek", "el"),
    "匈牙利语|hungarian|magyar|hu": ("Hungarian", "hu"),
    "保加利亚语|bulgarian|български|bg": ("Bulgarian", "bg"),
    "克罗地亚语|croatian|hrvatski|hr": ("Croatian", "hr"),
    "斯洛伐克语|slovak|slovenčina|sk": ("Slovak", "sk"),
    "斯洛文尼亚语|slovenian|slovenščina|sl": ("Slovenian", "sl"),
    "爱沙尼亚语|estonian|eesti|et": ("Estonian", "et"),
    "拉脱维亚语|latvian|latviešu|lv": ("Latvian", "lv"),
    "立陶宛语|lithuanian|lietuvių|lt": ("Lithuanian", "lt"),
    "冰岛语|icelandic|íslenska|is": ("Icelandic", "is"),
    "马耳他语|maltese|malti|mt": ("Maltese", "mt"),
    "土耳其语|turkish|türkçe|tr": ("Turkish", "tr"),
    "俄语|russian|русский|ru": ("Russian", "ru"),
    "乌克兰语|ukrainian|українська|uk": ("Ukrainian", "uk"),
    "塞尔维亚语|serbian|srpski|sr": ("Serbian", "sr"),
    "波斯尼亚语|bosnian|bosanski|bs": ("Bosnian", "bs"),
    "阿尔巴尼亚语|albanian|shqip|sq": ("Albanian", "sq"),
    "马其顿语|macedonian|македонски|mk": ("Macedonian", "mk"),
    "白俄罗斯语|belarusian|беларуская|be": ("Belarusian", "be"),
    "格鲁吉亚语|georgian|ქართული|ka": ("Georgian", "ka"),
    "亚美尼亚语|armenian|հայերեն|hy": ("Armenian", "hy"),
    "阿塞拜疆语|azerbaijani|azərbaycan|az": ("Azerbaijani", "az"),
    "加泰罗尼亚语|catalan|català|ca": ("Catalan", "ca"),
    "爱尔兰语|irish|gaeilge|ga": ("Irish", "ga"),
    "卢森堡语|luxembourgish|lëtzebuergesch|lb": ("Luxembourgish", "lb"),
    "威尔士语|welsh|cymraeg|cy": ("Welsh", "cy"),
    "苏格兰盖尔语|scottish gaelic|gàidhlig|gd": ("Scottish Gaelic", "gd"),
    "巴斯克语|basque|euskara|eu": ("Basque", "eu"),
    "加利西亚语|galician|galego|gl": ("Galician", "gl"),
    "罗曼什语|romansh|rumantsch|rm": ("Romansh", "rm"),
    "黑山语|montenegrin|crnogorski|cnr": ("Montenegrin", "sr"),
    "拉丁语|latin|latina|la": ("Latin", "la"),
}


def country_profile(value: str) -> tuple[str, str, bool, str]:
    key = value.strip().lower()
    for aliases, profile in COUNTRIES.items():
        if key in aliases.split("|"):
            return profile
    raise RuntimeError(f"暂不支持国家“{value}”，请使用完整的欧洲国家名称。")


def output_language_profile(value: str) -> tuple[str, str]:
    key = value.strip().casefold()
    for aliases, profile in LANGUAGES.items():
        if key in [item.casefold() for item in aliases.split("|")]:
            return profile
    raise RuntimeError(f"暂不支持输出语言“{value}”，请填写完整语言名称，例如中文、英语、德语或法语。")


def extract_license_data(pdf_path: str) -> tuple[str, str]:
    try:
        from pypdf import PdfReader
        text = "\n".join((page.extract_text() or "") for page in PdfReader(pdf_path).pages[:5])
    except Exception:
        return Path(pdf_path).name, ""
    lines = [" ".join(line.split()) for line in text.splitlines() if line.strip()]
    summary = " | ".join(lines[:20])[:2500] or Path(pdf_path).name
    phone_lines = [line for line in lines if re.search(r"\b(?:tel|telephone|phone|mobile|mobil|telefon|tlf)\b|电话|联系电话", line, re.I)]
    if not phone_lines:
        return summary, ""
    search_text = "\n".join(phone_lines)
    for candidate in re.findall(r"(?<!\w)(?:\+|00)?\d[\d\s()./-]{6,}\d(?!\w)", search_text):
        cleaned = candidate.strip()
        if re.fullmatch(r"\d{1,2}[./-]\d{1,2}[./-]\d{2,4}", cleaned):
            continue
        digits = re.sub(r"\D", "", candidate)
        if 7 <= len(digits) <= 15:
            return summary, " ".join(candidate.split())
    return summary, ""


def _split_address_fields(street: str, unit: str) -> tuple[str, str]:
    """Split Danish C/O, house number and apartment text conservatively."""
    if not street:
        return street, unit
    address_match = None
    if re.match(r"^C/O\s+", street, re.I):
        remainder = re.sub(r"^C/O\s+", "", street, flags=re.I)
        tokens = remainder.split()
        road_index = next((i for i, token in enumerate(tokens)
                           if re.search(r"(?:gade|vej|all[eé]|stræde|boulevard|plads|torv)$", token, re.I)), -1)
        has_road_suffix = road_index >= 0
        if road_index < 0:
            road_index = next((i for i, token in enumerate(tokens) if re.search(r"\d", token)), -1)
        if road_index > 0:
            street_start = max(0, road_index - 2) if has_road_suffix and re.fullmatch(
                r"vej|gade|all[eé]|stræde|boulevard|plads|torv", tokens[road_index], re.I
            ) else (max(0, road_index - 1) if not has_road_suffix else road_index)
            care_of = "C/O " + " ".join(tokens[:street_start])
            road_and_unit = " ".join(tokens[street_start:])
            road_match = re.match(r"^(.+?\s+\d+[A-Za-z]?)(?:,\s*(.+))?$", road_and_unit)
            if road_match:
                street = road_match.group(1).strip()
                extras = [item.strip() for item in (care_of if street_start else "", road_match.group(2), unit) if item and item.strip()]
                unit = ", ".join(dict.fromkeys(extras))
    if not re.match(r"^C/O\s+", street, re.I):
        address_match = re.match(
            r"^(.+?(?:gade|vej|all[eé]|stræde|boulevard|plads|torv)\s+\d+[A-Za-z]?)(?:,\s*(.+))?$",
            street, re.I,
        )
        if not address_match:
            address_match = re.match(r"^(.+?\s+\d+[A-Za-z]?)(?:,\s*(.+))?$", street, re.I)
    if address_match:
        street_part, address_unit = address_match.groups()
        street = street_part.strip()
        extras = [item.strip() for item in (address_unit, unit) if item and item.strip()]
        unit = ", ".join(dict.fromkeys(extras))
    return street, unit


def extract_license_fields(pdf_path: str) -> dict[str, str]:
    """Extract conservative, platform-ready business fields from a licence PDF."""
    try:
        from pypdf import PdfReader
        text = "\n".join((page.extract_text() or "") for page in PdfReader(pdf_path).pages[:8])
    except Exception:
        text = ""
    # Some Companies House PDF text layers contain literal escaped newlines;
    # restore them before applying line-based labels.
    text = text.replace("\\n", "\n")
    lines = [" ".join(line.split()).strip(" |") for line in text.splitlines() if line.strip()]
    joined = "\n".join(lines)

    def labelled(labels: str) -> str:
        pattern = re.compile(rf"^(?:{labels})\s*[:：-]?\s*(.+)$", re.I)
        for index, line in enumerate(lines):
            match = pattern.match(line)
            if match and match.group(1).strip():
                return match.group(1).strip()
            if re.fullmatch(rf"(?:{labels})\s*[:：-]?", line, re.I) and index + 1 < len(lines):
                return lines[index + 1]
        return ""

    def plausible_person(value: str) -> bool:
        value = value.strip(" ,;:-")
        if not value or re.search(r"\d|@|https?://", value, re.I):
            return False
        if re.search(
            r"\b(?:dato|date|side|page|erhvervsstyrelsen|register|adresse|address|postnummer|"
            r"kommune|direktion|director|stiftere|ejerforhold|regnskab|cvr|telefon|mail|brug|data)\b",
            value, re.I,
        ):
            return False
        words = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ'’-]+", value)
        return (2 <= len(words) <= 6 and sum(len(word) for word in words) >= 5
                and words[0][0].isupper())

    # Danish CVR full-view documents identify the current legal entity
    # immediately after "Side 1". Resolve it before generic "Navn" labels,
    # because later pages use "Navn" for P-units, former businesses and owners.
    legal_name = ""
    for index, line in enumerate(lines[:-1]):
        if re.fullmatch(r"Side\s+1", line, re.I):
            candidate = lines[index + 1]
            if not re.search(r"dato|cvr|adresse|erhvervsstyrelsen", candidate, re.I):
                legal_name = candidate
            break
    if not legal_name:
        legal_name = labelled(
            r"company name(?: in full)?|legal name|registered name|organisation name|organization name|"
            r"virksomhedsnavn|firmanavn|navn|unternehmensname|firmenname|raison sociale|denominazione sociale"
        )
    if legal_name.casefold() == "in":
        for index, line in enumerate(lines[:-2]):
            if re.fullmatch(r"Company Name in", line, re.I) and re.fullmatch(r"full:?", lines[index + 1], re.I):
                legal_name = lines[index + 2]
                break
    registration_number = labelled(
        r"cvr(?:[- ]?nummer|-?nr\.?)?|company number|company registration number|registration number|"
        r"register number|handelsregisternummer|siret|siren|partita iva"
    )
    legal_form = labelled(r"legal form|company type|entity type|virksomhedsform|rechtsform|forme juridique|forma giuridica")
    vat_id = labelled(r"vat(?: identification)?(?: number| id)?|ust-?id(?:nr\.)?|umsatzsteuer-id|momsnummer|tva intracommunautaire")
    register_name = labelled(r"register|registration authority|registrar|registergericht|register court|registreringsmyndighed")
    duns_number = labelled(r"d-?u-?n-?s(?: number| nummer| 编码)?|duns")
    street = labelled(r"street address|registered address|business address|adresse|anschrift|indirizzo|dirección")
    unit = labelled(r"apartment|suite|unit|floor|building|door|lejl(?:ighed)?|etage|wohnungsnummer")
    postal_code = labelled(r"postal code|postcode|zip code|postnummer(?: og by)?|postnr\.?(?: og by)?|postleitzahl|code postal|cap")
    city = labelled(r"city|town|municipality|by|kommune|stadt|ville|città|ciudad")
    person = labelled(
        r"director|owner|proprietor|indehaver|geschäftsführer|representative|legal representative|"
        r"fuldt ansvarlig deltager"
    )
    if not person:
        for index, line in enumerate(lines):
            inline = re.match(r"Full Forename\(s\)\s*:\s*(.+)$", line, re.I)
            if inline:
                given = inline.group(1)
                surname = ""
                if index + 1 < len(lines):
                    surname_match = re.match(r"Surname\s*:\s*(.+)$", lines[index + 1], re.I)
                    surname = surname_match.group(1) if surname_match else ""
                candidate = " ".join(item for item in (given, surname) if item)
                if plausible_person(candidate):
                    person = candidate.strip(" ,;:-")
                    break
            if re.fullmatch(r"Full Forename\(s\)", line, re.I) and index + 1 < len(lines):
                given = lines[index + 1]
                surname = ""
                if index + 3 < len(lines) and re.fullmatch(r"Surname", lines[index + 2], re.I):
                    surname = lines[index + 3]
                candidate = " ".join(item for item in (given, surname) if item)
                if plausible_person(candidate):
                    person = candidate.strip(" ,;:-")
                    break
    if person and not plausible_person(person):
        person = ""
    if not person:
        for index, line in enumerate(lines):
            if re.match(r"direktion\b", line, re.I):
                # CVR director sections may cross a page boundary. Skip the
                # repeated date, authority disclaimer and page heading until a
                # genuine human name appears.
                for candidate in lines[index + 1:index + 24]:
                    if plausible_person(candidate):
                        person = candidate.strip(" ,;:-")
                        break
                if person:
                    break

    # UK Companies House documents use an alphanumeric postcode and place the
    # registered-office lines immediately above it.
    uk_postal = re.search(r"\b([A-Z]{1,2}\d[A-Z\d]?\s*\d[A-Z]{2})\b", joined, re.I)
    uk_postal_index = -1
    if uk_postal:
        postal_code = postal_code or re.sub(r"\s+", " ", uk_postal.group(1).upper())
        for index, line in enumerate(lines):
            if re.search(re.escape(uk_postal.group(1).strip()), line, re.I):
                uk_postal_index = index
                break
        if uk_postal_index > 0:
            preceding = lines[max(0, uk_postal_index - 3):uk_postal_index]
            city = next((item for item in reversed(preceding) if re.fullmatch(r"[A-Za-z .'-]+", item) and item.casefold() not in {"england", "wales", "scotland", "northern ireland"}), "")
            if not street:
                street = next((item for item in preceding if re.search(r"\d|flat|house|road|street|court", item, re.I)), "")

    combined_postal = re.search(r"(?:[A-Z]{1,2}[- ]?)?(\d{4,6})\s+(.+)", postal_code)
    if combined_postal:
        postal_code = combined_postal.group(1)
        city = combined_postal.group(2).strip(" ,-.")

    postal_index = uk_postal_index if uk_postal_index >= 0 else -1
    if not postal_code or not city:
        postal_pattern = re.compile(r"^(?:[A-Z]{1,2}[- ]?)?(\d{4,6})\s+(.+)$", re.I)
        for index, line in enumerate(lines):
            match = postal_pattern.match(line)
            if match:
                postal_code = postal_code or match.group(1)
                city = city or match.group(2).strip(" ,-.")
                postal_index = index
                break
    if not street and postal_index > 0:
        for candidate in reversed(lines[max(0, postal_index - 4):postal_index]):
            if re.search(r"\d", candidate) and not re.search(r"cvr|registration|nummer|number", candidate, re.I):
                street = candidate
                break

    # Split common Danish CVR address lines into the fields expected by
    # Shopify/Google payment profiles while preserving C/O information.
    street, unit = _split_address_fields(street, unit)

    if not registration_number:
        match = re.search(r"\bCVR(?:[- ]?(?:nummer|nr\.?)?)?\s*[:：-]?\s*(\d{8})\b", joined, re.I)
        registration_number = match.group(1) if match else ""
    if not legal_name:
        # Prefer a nearby uppercase business line, but never invent one from a filename.
        candidates = [line for line in lines[:25] if 2 <= len(line) <= 100 and re.search(r"[A-Za-zÆØÅÄÖÜ]", line)]
        candidates = [line for line in candidates if not re.search(r"register|certificate|authority|cvr|date|adresse", line, re.I)]
        legal_name = next((line for line in candidates if line.upper() == line), "")

    country = detect_license_country(" | ".join(lines), "")
    first_name = last_name = ""
    if person:
        name_parts = person.split()
        if len(name_parts) >= 2:
            first_name, last_name = name_parts[0], " ".join(name_parts[1:])

    if re.search(r"\bApS\b|Anpartsselskab", legal_form or legal_name, re.I):
        legal_form = "Anpartsselskab (ApS)"
    elif not legal_form and re.search(r"\bLtd\b|Limited", legal_name, re.I):
        legal_form = "Private company limited by shares"
    register_label, default_register = REGISTER_AUTHORITIES.get(country, ("Registration number", ""))
    vat_id = vat_id.strip()
    # A CVR/company number is not automatically a VAT ID. Include VAT only when
    # the licence explicitly labels it as VAT/USt/Moms.
    if vat_id and not re.search(r"[A-Za-z]{2}|\d{8,12}", vat_id):
        vat_id = ""
    return {
        "profile_type": "组织",
        "organization_name": legal_name,
        "legal_name": legal_name,
        "registration_number": registration_number,
        "registration_label": register_label,
        "legal_form": legal_form,
        "authorized_representative": person,
        "register_name": register_name or default_register,
        "vat_id": vat_id,
        "duns_number": re.sub(r"\D", "", duns_number)[:9] if duns_number else "",
        "street_address": street,
        "unit": unit,
        "postal_code": postal_code,
        "city": city,
        "country": country,
        "first_name": first_name,
        "last_name": last_name,
    }


def detect_license_country(text: str, fallback: str) -> str:
    """Detect the registered country from licence text, independently of the sales market."""
    lowered = text.casefold()
    # CVR is Denmark's Central Business Register identifier and is often the
    # only explicit country clue printed on Danish registration documents.
    if re.search(r"(?<!\w)cvr(?:[-\s]?nr\.?|\s*number|\s*nummer|\b)", lowered):
        return "Denmark"
    if re.search(r"companies house|england and wales|northern ireland|scotland", lowered):
        return "United Kingdom"
    matches = []
    for aliases, profile in COUNTRIES.items():
        score = sum(len(re.findall(rf"(?<!\w){re.escape(alias.casefold())}(?!\w)", lowered))
                    for alias in aliases.split("|"))
        if score:
            matches.append((score, profile[0]))
    return max(matches)[1] if matches else fallback


def sanitize_licence_identity(text: str) -> str:
    """Keep registration details but remove conflicting licence contact fields."""
    parts = [part.strip() for part in text.split(" | ") if part.strip()]
    contact_label = re.compile(
        r"\b(?:e-?mail|email|phone|telephone|tel\.?|mobile|mobil|telefon|tlf)\b|邮箱|电话|联系电话",
        re.I,
    )
    safe = [part for part in parts if not contact_label.search(part)]
    return "\n".join(safe) if safe else "Registered business details are stated in the imported company licence."


def _translate(text: str, language: str) -> str:
    if language == "en":
        return text
    from deep_translator import GoogleTranslator
    try:
        from translatepy import Translator as MultiTranslator
        multi_translator = MultiTranslator()
    except Exception:
        multi_translator = None

    def translate_piece(piece: str) -> str:
        last_error = None
        for attempt in range(3):
            try:
                result = GoogleTranslator(source="en", target=language).translate(piece)
                if result and not re.search(r"no translation was found|try another translator|翻译.*失败", str(result), re.I):
                    return result
            except Exception as exc:
                last_error = exc
            if multi_translator is not None:
                try:
                    result = str(multi_translator.translate(piece, destination_language=language))
                    if result and not re.search(r"no translation was found|try another translator|翻译.*失败", str(result), re.I):
                        return result
                except Exception as exc:
                    last_error = exc
            if attempt < 2:
                time.sleep(0.6 * (attempt + 1))
        # Large pieces are divided again before giving up.
        if len(piece) > 220:
            lines = piece.splitlines()
            if len(lines) > 1:
                return "\n".join(translate_piece(line) if line.strip() else "" for line in lines)
            midpoint = len(piece) // 2
            split_at = piece.rfind(". ", 0, midpoint)
            if split_at < 80:
                split_at = piece.find(". ", midpoint)
            if split_at > 0:
                return translate_piece(piece[:split_at + 1]) + " " + translate_piece(piece[split_at + 2:])
        raise last_error or RuntimeError("翻译服务没有返回内容")

    translated, chunk = [], ""
    for paragraph in text.split("\n\n"):
        candidate = f"{chunk}\n\n{paragraph}" if chunk else paragraph
        if len(candidate) > 800 and chunk:
            translated.append(translate_piece(chunk))
            chunk = paragraph
        else:
            chunk = candidate
    if chunk:
        translated.append(translate_piece(chunk))
    return "\n\n".join(translated)


def _generate_single_bundle(
    country: str, email: str, phone: str, pdf_path: str, target_language: str,
    store_name: str = "", website: str = "", customs_mode: str = "卖家承担（客户收货时不另付）",
) -> tuple[list[tuple[str, str]], dict[str, str]]:
    canonical, _native_language, is_eu, law = country_profile(country)
    rulepack = load_rulepack()
    coverage_group, official_sources = legal_coverage(canonical, is_eu)
    official_sources = official_sources + (
        "Google Merchant Center return-policy requirements: https://support.google.com/merchants/answer/14011730",
    )
    # Every selectable market is checked against a country-specific official
    # legal publication in addition to the shared EU/EEA baseline. Surface
    # that exact source in the generated settings so reviewers can trace the
    # jurisdiction-specific rule without relying on a common directive alone.
    country_sources = COUNTRY_OFFICIAL_SOURCES.get(canonical, ())
    official_sources += tuple(
        f"{canonical} official legal source: {url}" for url in country_sources
    )
    if canonical == "Germany":
        official_sources += (
            "German BGB §356a electronic withdrawal function: https://www.gesetze-im-internet.de/bgb/",
            "EGBGB Annex 2 model withdrawal form: https://www.gesetze-im-internet.de/bgbeg/",
        )
    language = target_language
    licence, _ = extract_license_data(pdf_path)
    licence_fields = extract_license_fields(pdf_path)
    registered_country = licence_fields["country"] or detect_license_country(licence, canonical)
    structured_identity = [
        licence_fields["legal_name"],
        licence_fields["street_address"],
        licence_fields["unit"],
        " ".join(filter(None, (licence_fields["postal_code"], licence_fields["city"]))),
        registered_country,
        f"Registration Number: {licence_fields['registration_number']}" if licence_fields["registration_number"] else "",
    ]
    licence = "\n".join(item for item in structured_identity if item) or sanitize_licence_identity(licence)
    today = date.today().isoformat()
    # Fulfilment and carrier times are merchant operations, not legal facts.
    # Keep them uniform unless the user later supplies market-specific operations.
    processing_min, processing_max, transit_min, transit_max = 1, 2, 5, 10
    if is_eu:
        jurisdiction_group = "EU"
    elif canonical == "United Kingdom":
        jurisdiction_group = "UK"
    elif canonical in {"Norway", "Iceland", "Liechtenstein"}:
        jurisdiction_group = "EEA"
    elif canonical == "Switzerland":
        jurisdiction_group = "CH"
    elif canonical == "Turkey":
        jurisdiction_group = "TR"
    else:
        jurisdiction_group = f"LOCAL:{canonical}"
    group_rules = rulepack["coverage_groups"].get(jurisdiction_group)
    if not group_rules:
        raise RuntimeError(f"规则包缺少 {jurisdiction_group} 的法定参数，已停止生成。")
    statutory_days = group_rules.get("statutory_withdrawal_days")
    has_withdrawal = isinstance(statutory_days, int)
    commercial_return_days = int(group_rules["commercial_return_days"])
    refund_days = int(group_rules["refund_deadline_days"])
    refund_unit = str(group_rules["refund_deadline_unit"])
    country_overlay = rulepack.get("country_overlays", {}).get(canonical, {})
    national_product_marketing_clause = str(
        country_overlay.get("national_product_marketing_clause", "")
    ).strip()
    withdrawal = f"{statutory_days} calendar days after delivery" if has_withdrawal else "the mandatory period provided by local law"
    withdrawal_clause = (
        f"For eligible distance purchases, customers may withdraw without giving a reason within {withdrawal}. "
        f"Send a clear statement to the customer service email {email} before the deadline."
        if has_withdrawal else
        "No general change-of-mind withdrawal right is stated unless mandatory local law provides one. "
        "Rights concerning defective, damaged or incorrectly supplied goods remain fully available."
    )
    # Store-wide commercial policy used consistently in the policy text and in
    # the Merchant Center values shown by the UI.
    return_window = f"收货后{commercial_return_days}个自然日"
    # The licence text is customer-facing company data.  Do not expose internal
    # workflow wording such as "extracted from licence" in a published policy.
    identity = f"{licence}\nCountry: {registered_country}\nCustomer Service Email: {email}\nCustomer Service Phone: {phone}"
    common_contact = f"Contact customer service by email at {email} or by phone at {phone}."
    return_shipping_clause = (
        "For a non-defective change-of-mind return, the customer bears the direct return cost where the law permits "
        "this and the obligation was disclosed before purchase. We provide a prepaid label and bear required costs "
        "for defective, damaged or incorrectly supplied goods. No restocking fee is charged for exercising a "
        "statutory withdrawal right. Any stronger local right prevails."
    )
    if group_rules.get("return_shipping_mode") == "free_designated_carrier":
        return_shipping_clause = (
            "When the consumer uses the return carrier identified before purchase, or no return carrier was "
            "identified and the consumer therefore uses a carrier, the consumer is not charged return shipping as "
            "required by Turkish distance-contract rules. Defective, damaged or incorrect goods are handled without "
            "cost to the consumer. No restocking fee is charged for exercising the statutory withdrawal right."
        )
    guarantee = country_overlay.get("legal_guarantee") or LEGAL_GUARANTEE.get(
        canonical,
        "a minimum 2-year legal guarantee for lack of conformity" if canonical in EEA_COUNTRIES
        else f"the mandatory conformity and warranty rights applicable in {canonical}",
    )
    repair_extension_months = int(group_rules.get("repair_remedy_liability_extension_months", 0) or 0)
    if canonical == "Austria" and date.today() < date(2026, 10, 1):
        repair_extension_months = 0
    repairability_clause = (
        "For EEA consumer sales, the objective conformity assessment also includes the repairability a consumer "
        "may reasonably expect from goods of that type. "
        if group_rules.get("objective_conformity_includes_repairability") else ""
    )
    repair_extension_clause = (
        f"Where repair is performed as the statutory remedy, the applicable seller-liability period is extended "
        f"once by **{repair_extension_months} months**, subject to the national law implementing Directive (EU) "
        "2024/1799 and any stronger local protection."
        if repair_extension_months else ""
    )
    statutory_refund = (
        f"For a statutory EEA withdrawal, reimbursement is made without undue delay and no later than {refund_days} {refund_unit} "
        "after we are informed of the withdrawal; where lawful, reimbursement may be withheld until the goods "
        "or evidence of return are received."
        if canonical in EEA_COUNTRIES else
        (f"For an online cancellation, reimbursement is made within {refund_days} {refund_unit} after the returned goods or evidence of "
         "return are received, subject to the Consumer Contracts Regulations."
         if canonical == "United Kingdom" else
         "Any shorter mandatory reimbursement deadline under local law prevails over this voluntary operational target.")
    )
    seller_name = store_name.strip() or licence_fields["legal_name"] or "this online store"
    site_text = website.strip() or "this website"
    if customs_mode == "消费者承担（结账前明确披露）":
        customs_summary = "Customer is responsible, with the obligation disclosed before checkout"
        customs_clause = (
            f"For deliveries to {canonical} that are subject to import formalities, the customer is the importer "
            "and bears the applicable customs duties and import taxes. This responsibility and any amount that can "
            "reasonably be calculated by us are clearly disclosed before the order is submitted. We do not add "
            "undisclosed shipping or handling charges after checkout."
        )
    elif customs_mode == "不适用（境内或关税同盟内配送）":
        customs_summary = "No import customs duty applies to the configured domestic/customs-union delivery"
        customs_clause = (
            f"The configured fulfilment route for deliveries to {canonical} is domestic or within the applicable "
            "customs union, so the customer is not charged import customs duty on delivery. All taxes and mandatory "
            "charges collected by us are included or displayed before the order is submitted."
        )
    else:
        customs_summary = "Seller bears customs duties and import charges; customer pays no extra amount on delivery"
        customs_clause = (
            f"For standard deliveries to {canonical}, the seller bears any applicable customs duties and import "
            "charges. All taxes and mandatory charges collected by us are included or displayed before the order "
            "is submitted. The customer is not charged additional customs duties, import taxes or handling fees on "
            "delivery that were not disclosed before checkout."
        )
    model_withdrawal_form = ""
    if has_withdrawal:
        model_withdrawal_form = f"""
## Model Withdrawal Form
(Complete and return this form only if you wish to withdraw from the contract. Use of this form is optional; any other clear withdrawal statement is also valid.)

To: {licence_fields['legal_name']}, {licence_fields['street_address']}, {licence_fields['postal_code']} {licence_fields['city']}, {registered_country}; customer service email: {email}

I/We hereby give notice that I/We withdraw from my/our contract of sale for the following goods:

- Goods ordered: ______________________________
- Order number: ______________________________
- Ordered on / received on: ___________________
- Consumer name: _____________________________
- Consumer address: __________________________
- Date: ______________________________________
- Signature (only if submitted on paper): _____
"""
    electronic_withdrawal_notice = ""
    if country_overlay.get("electronic_withdrawal_function"):
        start_label = str(country_overlay.get("withdrawal_start_label", "Vertrag widerrufen"))
        confirm_label = str(country_overlay.get("withdrawal_confirm_label", "Widerruf bestätigen"))
        electronic_withdrawal_notice = f"""
## Electronic Withdrawal Function for {canonical}
During the statutory withdrawal period, {site_text} must keep a prominent and easily accessible online function labelled **“{start_label}”** (or an equally unambiguous expression). The confirmation action must be labelled **“{confirm_label}”** (or equivalent), and an electronic receipt containing the withdrawal details, date and time must be sent immediately on a durable medium. Email and the model form remain additional ways to withdraw.
"""

    raw = [
        ("Refund and Return Policy", f"""# Refund and Return Policy
**Last updated: {today}**

## 1. Scope and Mandatory Rights
This policy applies to consumer orders in {canonical} under {law}. Mandatory consumer rights are not limited by this policy.

## 2. Right of Withdrawal
{withdrawal_clause}

The applicable return window used by this store is **{commercial_return_days} calendar days after delivery**. Where this is a voluntary commercial period rather than a statutory right, it is additional to and does not replace mandatory remedies.

For orders containing several goods delivered separately, or goods delivered in several lots or pieces, the statutory period begins from receipt of the last applicable good, lot or piece where the governing law so provides. For EU and EEA withdrawals, after giving a valid withdrawal notice the customer must send the goods back without undue delay and no later than **14 calendar days after sending the notice**. Any stronger national rule prevails.

## 3. Return Eligibility and Product Condition
For a statutory withdrawal, customers may inspect goods only to the extent necessary to establish their nature, characteristics and functioning, as they could reasonably do in a shop. Opening the original packaging does not by itself remove the statutory right. Where legally permitted and after proper pre-contract information, the customer may be responsible for diminished value caused by handling beyond what is necessary for that inspection. Stricter unused, tag and original-packaging conditions apply only to any separately identified voluntary commercial return benefit and never restrict statutory rights.

## 4. Return Procedure
Please contact the customer service email before returning goods so that we can provide practical return instructions. Include the order number and item; photographs may be requested for damaged or incorrect goods. **Prior authorization is not required to exercise a statutory right of withdrawal.** A clear statement sent within the deadline is sufficient. Goods should then be returned by mail to the address below within the applicable return period.

Refusing delivery or failing to collect a parcel does not by itself constitute an unambiguous statutory withdrawal notice. Customers should send a clear withdrawal statement through an available channel. Any return reference or label we provide is intended to identify and process the parcel efficiently and does not restrict a mandatory right.

**Return address and business details:**
{identity}

## 5. Return Shipping Costs
{return_shipping_clause}

Where we issue a prepaid label, it must be used in accordance with the supplied instructions. The policy shown before purchase determines whether a change-of-mind return label is free or whether its disclosed direct cost may be deducted. We do not impose a restocking fee for a valid statutory withdrawal.

## 6. Refunds and Payment Method
After receiving the returned goods, we inspect them and confirm the refund. This inspection does not limit the statutory right of withdrawal. Any legally permitted deduction for diminished value will be explained to the customer. Refunds are processed within **{refund_days} {refund_unit}** to the **original payment method**. {statutory_refund} Standard outbound delivery is reimbursed where statutory withdrawal law requires it; premium delivery upgrades need not be reimbursed beyond the standard-delivery amount. Banks and card providers may need additional processing time after we issue the refund.

## 7. Exchanges
Exchanges are accepted subject to stock availability. The fastest method is to complete the eligible return and place a new order. A refund is provided where a replacement is unavailable.

## 8. Damaged, Defective or Incorrect Goods
Report problems promptly with the order number and evidence. Remedies may include repair, replacement, price reduction or refund under applicable law.

## 9. Exceptions
Statutory exceptions are interpreted narrowly. They may include perishable goods; genuinely custom-made or personalised goods; sealed goods which are not suitable for return for reasons of health protection or hygiene and which were unsealed after delivery; and other specific exceptions provided by applicable law. A discount or sale price does not by itself remove statutory withdrawal or legal-guarantee rights.

## 10. Cancellation and Withdrawal Effects
Orders may be cancelled before dispatch by contacting customer service. Once dispatched, an order cannot normally be cancelled through shipping, but the customer may use this return policy and all statutory withdrawal rights.

## 11. Statutory Guarantee
Customers retain {guarantee}. The applicable statutory hierarchy of repair, replacement, price reduction, termination and refund remains unaffected.

{repairability_clause}{repair_extension_clause}

## 12. Contact
{common_contact}

We aim to respond to customer-service enquiries within **1–2 business days**, Monday through Friday excluding applicable public holidays. This service target does not shorten or suspend any statutory deadline.

## 13. Return Address
Returns should be sent only to the return address confirmed in the instructions so that they can be identified correctly. Unless a different lawful return facility is communicated for the order, the business return address is:

{identity}
{model_withdrawal_form}
{electronic_withdrawal_notice}
"""),
        ("Privacy Policy", f"""# Privacy Policy
**Last updated: {today}**

## 1. Scope and Data Controller
This Privacy Policy explains how the online store collects, uses, discloses and retains personal data when customers visit the website, create an account, place an order, request support, return goods or otherwise interact with the store.

{identity}

## 2. Categories of Personal Data
Depending on the interaction, we may process identity and contact data; account credentials; billing and delivery addresses; order, product and transaction data; payment status and limited payment metadata; customer-service communications; return, complaint and refund data; device, browser, IP address and log data; cookie, consent, analytics and advertising data; and fraud-prevention or security signals.

We do not normally receive complete payment-card credentials when an independent payment provider processes the transaction.

## 3. Sources of Personal Data
Data may be collected directly from the customer, automatically from the website or device, and from Shopify, payment providers, fraud-prevention providers, carriers, fulfilment providers, marketing partners or other service providers involved in the transaction.

## 4. Purposes of Processing
We use data to provide and administer the website and customer accounts; process orders and payments; arrange dispatch, tracking and delivery; manage returns, refunds, complaints and warranties; provide customer support; authenticate users; prevent fraud and protect security; maintain business, tax and accounting records; measure and improve store performance; send permitted marketing; personalize content or advertising where lawful; establish or defend legal claims; and comply with legal obligations.

## 5. Legal Bases
Where GDPR or equivalent law applies, processing necessary for an order, delivery, return or requested service relies on performance of a contract or pre-contractual steps. Tax, accounting, product-safety and authority requests may rely on legal obligations. Security, fraud prevention, service improvement and legal claims may rely on legitimate interests after balancing the interests involved. Non-essential cookies, personalized advertising and marketing rely on consent where required. Consent can be withdrawn prospectively at any time.

## 6. Orders, Payments and Fraud Prevention
Shopify, payment processors, acquiring banks and fraud-prevention services may receive the identity, order, billing, device and payment-status information necessary to authorize and administer a transaction, detect misuse and issue refunds. Their own privacy notices may also apply when they act as independent controllers.

## 7. Fulfilment, Shipping and Returns
Warehouses, fulfilment providers and carriers receive only the recipient, address, contact, order and shipment information reasonably required to prepare, deliver, track, recover or return a parcel and resolve delivery problems.

## 8. Customer Service and Communications
When a customer contacts us, we process the message, contact details, order number and any photographs or documents supplied to answer the request, investigate a problem and retain an appropriate support record.

## 9. Technical Logs and Security
The website and its providers may automatically process IP address, browser, device, operating system, timestamps, requested pages, referrer and security events to deliver the service, diagnose faults, prevent abuse and maintain security.

## 10. Cookies and Consent Choices
Essential cookies and similar technologies support login, cart, checkout, security, language and consent preferences. Analytics, advertising or personalization technologies are activated only after valid consent where required. Customers can use the website's cookie settings to give, refuse or withdraw non-essential consent without disabling essential shopping functions.

## 11. Analytics, Advertising and Marketing
If enabled, analytics measure store usage and campaign performance, while advertising services may measure conversions or personalize advertising. The store must identify the services actually enabled in its cookie interface or supplementary disclosures. Marketing messages are sent only where permitted, and customers can unsubscribe or withdraw consent at any time.

## 12. How We Disclose Personal Data
Personal data may be disclosed as necessary to Shopify and ecommerce hosts; payment and fraud providers; fulfilment and shipping providers; IT, cloud, security and customer-support providers; analytics and advertising providers used with a lawful basis; accountants, auditors, insurers and legal advisers; corporate affiliates; prospective parties to a business transaction; and courts, regulators or authorities where legally required. We do not sell personal data in the ordinary meaning of selling customer lists for money.

## 13. Relationship with Shopify
The store is powered by Shopify. Shopify processes personal data to host and provide ecommerce services and may process certain data for its own legally described purposes. Customers should review the applicable Shopify consumer privacy information and use any Shopify privacy portal made available for relevant rights. Shopify is not the seller of the store's products.

## 14. International Transfers
Where personal data is transferred outside the EEA, United Kingdom, Switzerland or another protected jurisdiction, the responsible party uses an applicable adequacy decision, approved contractual clauses or another lawful transfer mechanism, together with supplementary safeguards where required.

## 15. Retention
Personal data is retained only for as long as necessary for the stated purpose and applicable contractual, tax, accounting, product-safety, fraud-prevention, limitation, dispute and legal-record periods. Criteria include the duration of the customer relationship, the sensitivity of the data and potential legal claims. Data is deleted or anonymized when no lawful reason for retention remains.

## 16. Security
We and our providers use proportionate technical and organisational safeguards designed to protect confidentiality, integrity and availability. No internet transmission or storage system can be guaranteed completely secure, and customers should protect account credentials and notify us of suspected unauthorized use.

## 17. Data Protection Rights
Subject to legal conditions and exceptions, an individual may request access, correction, deletion, restriction, portability or information about processing; object to processing based on legitimate interests or direct marketing; withdraw consent prospectively; and lodge a complaint with a competent supervisory authority. Identity verification may be required before fulfilling a request.

## 18. Automated Decisions
The store does not make a decision producing legal or similarly significant effects based solely on automated processing unless this is disclosed and permitted by law. Automated fraud signals may assist human review of a transaction.

## 19. Children
The store is not directed to children below the age at which they may independently consent or contract under applicable law, and we do not knowingly process children's data unlawfully.

## 20. Third-Party Websites
Links, social widgets and third-party platforms are governed by their own privacy and security practices. Customers should review those notices before providing data to an independent third party.

## 21. Required Information and Consequences
Information marked as required at checkout is necessary to enter into or perform the purchase contract. Without the required identity, address, contact and payment information, we may be unable to accept, fulfil or support an order.

## 22. Changes to This Policy
Material updates are published with a revised date. Where law requires additional notice or consent, it will be provided before the relevant change takes effect.

## 23. Privacy Contact and Complaints
{common_contact}
Privacy requests should describe the requested right and provide enough information to locate the relevant records. Individuals may also complain to the competent data-protection authority in their habitual residence, place of work or place of the alleged infringement.
"""),
        ("Terms of Service", f"""# Terms of Service
**Last updated: {today}**

## 1. Company and About Us
{identity}

## 2. Online Store
These terms govern website use and purchases in {canonical} under {law}.

Customers must provide accurate, current and complete account, billing, contact and delivery information and protect their account credentials. Suspected unauthorized use should be reported promptly. Products are intended for lawful personal or household use unless expressly agreed otherwise.

## 3. Products
We take reasonable care with descriptions, images, specifications and availability. Display settings, photography, packaging and non-material manufacturing variations may affect appearance without limiting rights where goods are defective, unsafe or not as described. We may lawfully limit quantities, discontinue products or restrict sales where disclosed and permitted.

{national_product_marketing_clause}

## 4. Prices and Taxes
The total price, applicable taxes, delivery charges and other mandatory charges collected by us are displayed before checkout. Promotions may have separate disclosed terms. Obvious pricing or availability errors are handled only as permitted by applicable consumer law.

## 5. Orders and Acceptance
An order is an offer to buy. An automated receipt acknowledgment does not necessarily constitute acceptance; the contract is formed when accepted under the checkout information and an electronic confirmation is provided. We may reject or cancel an order for unavailable goods, failed payment, legal restrictions, suspected fraud or a material pricing error where law permits. Amounts already collected for a rejected order are refunded appropriately.

## 6. Payment Information
Available payment methods appear at checkout. Customers authorize the selected method. Independent processors may handle payments. Failed authorization may prevent acceptance. Refunds use the original method unless agreed otherwise.

## 7. Shipping and Risk
Shipping follows our Shipping Policy. Risk remains with us until delivery where required by consumer law.

## 8. Returns, Refunds and Withdrawal
Our Refund and Return Policy contains the complete procedure and does not limit statutory rights.

## 9. Defective Goods
Customers receive remedies required under applicable conformity and guarantee law.

## 10. Acceptable Use
The website must not be used unlawfully, fraudulently, to infringe rights, submit false information, spread malware, scrape protected content without permission, evade security, interfere with operation, harass others or conduct prohibited commercial activity.

## 11. Intellectual Property
Original text, graphics, design, logos and descriptions may be legally protected.

## 12. Third-Party Services
Payment, delivery and other providers may have their own terms and privacy policies.

Optional third-party tools are provided subject to their own terms and availability. We do not promise that every third-party service will remain continuously available, but nothing in this clause excludes responsibility that cannot lawfully be excluded.

## 13. Relationship with Shopify
The store is powered by Shopify, which provides the technical ecommerce platform. Purchases are made directly between the customer and the seller identified in these Terms. Shopify is not the seller and is not responsible for the seller's products, fulfilment, delivery, returns, refunds or customer support, except for obligations Shopify separately assumes under applicable law.

## 14. Data Protection
Personal information is handled under our Privacy Policy and applicable law.

## 15. Liability
Nothing excludes or limits liability where doing so is prohibited, including mandatory product, consumer, fraud, intentional misconduct, gross-negligence, death or personal-injury liability where applicable. Any permitted limitation is interpreted narrowly and does not remove statutory remedies for non-conforming goods.

## 16. Force Majeure
We are not responsible for delays caused by events outside reasonable control, subject to mandatory rights.

## 17. Feedback, Reviews and Submissions
Customers must have the necessary rights to content they submit and must not provide unlawful, misleading or infringing material. Any licence needed to display a review or feedback is limited by applicable law and our Privacy Policy. Incentivized reviews must be disclosed.

## 18. Errors and Service Availability
We may correct website typographical errors, inaccuracies or omissions where permitted. Temporary maintenance, security work or technical interruption may affect access. Corrections do not remove mandatory rights or authorize undisclosed post-contract price changes.

## 19. Suspension and Termination
We may restrict access for material unlawful use, fraud or security threats where proportionate and lawful. Termination does not affect accrued payment obligations, accepted orders, returns, warranties, privacy rights or provisions intended to survive.

## 20. Severability, Waiver and Assignment
If a provision is unenforceable, the remaining provisions continue to the extent legally possible. A failure to enforce a term is not a waiver. We do not assign a consumer contract in a way that reduces mandatory rights; customers may not transfer obligations where restriction is lawful and reasonably necessary.

## 21. Entire Agreement and Policy Priority
These Terms and the policies incorporated by reference form the applicable store agreement, subject to mandatory pre-contract information and the order confirmation. The Privacy Policy governs personal-data processing; the Refund and Return Policy governs withdrawals and returns; and the Shipping Policy governs delivery details.

## 22. Changes and Governing Law
The version presented when an order is placed normally applies to that order. The seller's governing law and forum are subject to applicable conflict-of-law rules and do not deprive consumers of non-derogable protections or available courts in their country of habitual residence.

## 23. Frequently Asked Questions
**How do I track an order?** Use the dispatch email or contact support.  
**Can I change an address or cancel?** Contact us immediately; changes may be impossible after dispatch.  
**How do I return an item?** Contact us before sending it.  
**When is my refund issued?** Within the period stated in our Refund Policy.  
**What if goods arrive damaged?** Send the order number and photographs.  
**How do I contact support?** Customer service email: {email}. Customer service phone: {phone}.

## 24. Contact
{common_contact}
"""),
        ("Shipping Policy", f"""# Shipping Policy
**Last updated: {today}**

## Shipping Summary — {canonical}
**Shipping method:** Tracked standard shipping  
**Shipping cost:** Free for all orders delivered within {canonical}  
**Order processing time:** {processing_min}–{processing_max} business days, Monday through Friday  
**Shipping transit time:** {transit_min}–{transit_max} business days after dispatch  
**Estimated total delivery time:** {processing_min + transit_min}–{processing_max + transit_max} business days  
**Tracking:** Carrier, tracking number and tracking link after dispatch  
**Taxes and customs:** {customs_summary}

## 1. Scope and Shipping Destinations
This policy explains the delivery areas, shipping method, charges, processing and transit times, tracking, customs, delays, failed delivery, loss, damage and returned parcels for orders delivered throughout **{canonical}**. Available destinations are displayed before checkout; an order cannot be placed for an unavailable destination.

## 2. Shipping Method
Orders are normally sent using tracked standard shipping. The carrier may vary with the delivery address, product, parcel size and weight, fulfilment location and carrier availability. The assigned carrier is normally identified in the dispatch confirmation or tracking information.

## 3. Order Processing Time
Orders are normally processed within **{processing_min}–{processing_max} business days**, Monday through Friday, excluding public holidays. Processing is separate from transit time. Orders placed after the daily carrier cut-off begin processing on the next business day.

Processing may include payment and fraud checks, address verification, product preparation, packaging and handover to the carrier. A displayed cut-off time determines when processing can begin but does not guarantee same-day dispatch.

## 4. Shipping Transit and Total Delivery Time
Standard shipping transit is normally **{transit_min}–{transit_max} business days** after dispatch. Estimated total delivery time is **{processing_min + transit_min}–{processing_max + transit_max} business days**, combining processing and transit. Estimates are not guaranteed appointments unless expressly agreed.

The estimate may be affected by the destination, carrier, customs processing, public holidays, severe weather, transport disruption and exceptional demand. Any more specific estimate shown at checkout for the order applies to that order.

## 5. Shipping Costs
Standard shipping is **free for all orders delivered within {canonical}**. Any optional express, premium or special-handling charge is displayed before payment and applies only when selected. We do not add undisclosed shipping or handling charges after purchase.

Product pages, the cart, checkout, order confirmation and any merchant listing must display shipping charges and delivery estimates consistently. All mandatory taxes, customs duties or import charges collected by us are disclosed before purchase where required.

## 6. Order Confirmation, Dispatch and Tracking
Customers receive an order confirmation showing the order number, products, delivery address, order value, shipping method, applicable shipping fee and available delivery estimate. Receipt of an order is not necessarily confirmation of dispatch.

After dispatch, we normally provide the carrier, tracking number and tracking link. Tracking may require **24–72 hours** to become active and carrier events may not appear in real time. A temporary tracking delay does not necessarily mean that the parcel has stopped moving.

## 7. Accurate Address and Address Changes
Customers must provide the recipient name, street and building number, unit where applicable, postal code, city, country, reachable email address and telephone number. Contact customer service immediately after discovering an error. We may update an address before dispatch but cannot guarantee a change after processing or carrier handover. Lawful carrier redirection or reshipping costs may apply where caused by customer-supplied incorrect information and properly disclosed.

## 8. Delivery Attempts, Collection and Failed Delivery
The carrier may deliver to the recipient, an agreed safe place, a neighbour where permitted, a parcel shop, post office or collection point, or make another attempt. Customers must collect parcels within the carrier's stated period. Uncollected, refused or incorrectly addressed parcels may be returned to us. Refusal or non-collection does not by itself constitute a clear statutory withdrawal notice.

## 9. Delivery Delays and Consumer Rights
Carrier disruption, customs, weather, holidays, industrial action, transport interruption, government restrictions and exceptional demand may affect estimates. If a significant delay becomes known, we make reasonable efforts to notify the customer. Mandatory late-delivery rights remain unaffected, including any right to set an additional reasonable delivery deadline and cancel when the legal conditions are met.

## 10. Lost Packages
Customers should check tracking, the delivery address, household members, neighbours and collection points before reporting a missing parcel. We investigate with the carrier and provide a replacement at no extra cost or a refund to the original payment method when loss is confirmed.

## 11. Damaged Packages
Report damage promptly with the order number, outer-packaging photos, shipping-label photos and product photos. Retain the item and packaging until instructions are provided. Confirmed damage receives a replacement, prepaid return or refund as appropriate.

## 12. Incorrect, Missing or Incomplete Items
Report an incorrect product, quantity or missing item promptly with the order number and photographs where useful. After review, we arrange the correct or missing item, a replacement, a prepaid return or a refund as appropriate without limiting statutory remedies.

## 13. Split Shipments
An order may arrive in several parcels because products use different fulfilment locations, become ready at different times or are subject to parcel limits. Separate tracking numbers may be provided. Customers are not charged an undisclosed additional standard shipping fee solely because we split an order.

## 14. Customs, Duties and Taxes
{customs_clause} Customs processing can affect delivery estimates without removing mandatory rights.

## 15. Risk of Loss or Damage
Risk transfers only at the time required by applicable consumer law.

## 16. Returned Parcels and Returns
If a parcel is returned because it was unclaimed, refused, incorrectly addressed or could not be delivered, we contact the customer where reasonably possible and apply the disclosed lawful reshipping or refund procedure. Deductions are made only where legally permitted and transparently explained.

Shipping-related returns follow our Refund and Return Policy. Return-shipping responsibility depends on the reason for return and the mandatory rules applicable in the customer's market. We bear required return costs for defective, damaged or incorrectly supplied goods; change-of-mind return costs are handled exactly as disclosed in the Refund and Return Policy.

## 17. Contact
{common_contact}
Please include the order number, delivery address and tracking number where available. We aim to respond within **1–2 business days** during normal business days.
"""),
        ("Contact Information", f"""# Contact Information
**Last updated: {today}**

## About Us
The legal business identified below operates this online store.

## Company Information
{identity}

## Customer Service
Customer service email: {email}. Customer service phone: {phone}. Use these details for orders, shipping, products, payments and website questions. Include the order number where relevant.

We aim to respond within **1–2 business days**, Monday through Friday excluding applicable public holidays. This is a service target and does not suspend statutory deadlines.

## Order and Product Questions
For an existing order, include the order number, customer name and checkout email where possible. Customer service can assist with pre-purchase product information, order status, address corrections before dispatch, payment questions, tracking, incorrect or missing products and cancellations where still possible.

## Returns and Refunds
Contact us before returning goods so we can provide practical instructions and the applicable return address. This contact request does not make prior authorization a condition of a statutory withdrawal. For damaged, defective or incorrect goods, include useful photographs where reasonably available.

## Shipping Questions
The Shipping Policy contains the delivery area, method, charges, processing and transit estimates, tracking and delay procedures. For an individual shipment enquiry, include the order and tracking numbers.

## Privacy Requests
Requests for access, correction or deletion may be sent to the customer service email: {email}.

## Business Address and Support
The company address stated above is the registered business address. Customers should follow the confirmed return instructions before sending a parcel so that the correct return facility and reference are used. The legal company name, registration number, brand, website, email and telephone must remain consistent across the footer, checkout, order communications and merchant-account records.
"""),
        ("Legal Notice / Imprint", f"""# Legal Notice / Imprint
**Last updated: {today}**

## Service Provider and Website Operator
**Legal company name:** {licence_fields['legal_name']}
**Registered address:** {licence_fields['street_address']}{(', ' + licence_fields['unit']) if licence_fields['unit'] else ''}, {licence_fields['postal_code']} {licence_fields['city']}, {registered_country}
{f"**Legal form:** {licence_fields['legal_form']}" if licence_fields['legal_form'] else ''}
{f"**{licence_fields['registration_label']}:** {licence_fields['registration_number']}" if licence_fields['registration_number'] else ''}
{f"**Register / registration authority:** {licence_fields['register_name']}" if licence_fields['register_name'] else ''}
{f"**Authorized representative / director:** {licence_fields['authorized_representative']}" if licence_fields['authorized_representative'] else ''}

## Contact
{common_contact}

{f"## VAT Identification\n**VAT ID:** {licence_fields['vat_id']}" if licence_fields['vat_id'] else ''}

## Online Store, Seller and Platform
**{seller_name}** at **{site_text}** is operated by the legal company identified above. All purchases are made directly between the customer and that company, which is the seller responsible for products, orders, delivery, returns and refunds. Shopify supplies the technical ecommerce platform and is not the seller.

## Responsible for Website Content
The website operator identified above is responsible for the commercial and editorial content of the store. Customer-service and privacy requests may be sent to {email}.

## Product, Pricing and Availability Information
We take reasonable care to keep product descriptions, prices, availability and delivery information accurate and current. Obvious errors or omissions may be corrected where law permits. Display, photography or packaging differences do not restrict rights where goods are defective, unsafe or not as described.

{national_product_marketing_clause}

## Liability for Website Content
General website information is maintained with reasonable care, but continuous availability and absolute freedom from immaterial errors cannot be guaranteed. Nothing excludes or limits liability for fraud, intentional misconduct, gross negligence, death, personal injury or another matter where limitation is prohibited, and mandatory consumer remedies remain unaffected.

## External Links
Independent third-party websites control their own content, availability, security and privacy practices. Their inclusion does not transfer responsibility to the store operator. If we become aware of an unlawful link, we take appropriate steps within our control.

## Intellectual Property
Unless otherwise stated, original store text, logos, graphics, photographs, videos, product images, designs and page layouts are owned by or licensed to the operator and may be protected by copyright, trademark or other rights. Lawful exceptions and third-party rights remain unaffected.

## Consumer Information
Mandatory consumer protections applicable in {canonical} remain unaffected. Customers should also review the Refund and Return Policy, Privacy Policy, Terms of Service and Shipping Policy. Nothing in this notice deprives a consumer of mandatory protections in the country of habitual residence.

## Governing Law
The website operator's applicable governing law is subject to mandatory conflict-of-law and consumer-protection rules. Consumers retain any non-derogable protections and competent courts available in their country of habitual residence.

## Direct Contact
Questions about this Legal Notice may be sent to {email} or raised by telephone at {phone}. We aim to respond within **1–2 business days** during normal business days.
"""),
    ]

    clauses = country_overlay.get("additional_legal_clauses", {})
    if clauses:
        if not isinstance(clauses, dict) or any(not isinstance(text, str) for text in clauses.values()):
            raise RuntimeError("国家附加法律条款格式错误，已停止生成。")
        raw = [(title, body + ("\n\n## Additional Mandatory Consumer Information\n" + clauses[title]
                               if clauses.get(title) else "")) for title, body in raw]

    try:
        # UI buttons already provide localized Chinese labels. Translating short standalone
        # titles can return "No translation was found" on some network translators, so only
        # translate the complete document (which already contains its H1 title).
        policies = [(title, _translate(body, language)) for title, body in raw]
    except Exception as exc:
        raise RuntimeError(f"网络翻译失败：{exc}\n\n请检查网络连接后重试。") from exc

    settings = {
        "country": canonical,
        "jurisdiction_group": jurisdiction_group,
        "language": language.upper(),
        "processing_time": f"{processing_min}–{processing_max}个工作日",
        "processing_days": "周一至周五",
        "shipping_scope": f"{canonical} 全境",
        "shipping_time": f"{transit_min}–{transit_max}个工作日",
        "shipping_days": "周一至周五",
        "shipping_cost": f"{canonical} 全境所有订单标准运输免费",
        "customs_responsibility": customs_mode,
        "returns": "接受瑕疵品及非瑕疵品退货",
        "exchanges": "接受换货（视库存及法定权利而定）",
        "refund_time": f"收到并检查退货后{refund_days}{'个自然日' if has_withdrawal else '个工作日'}内",
        "refund_days_value": str(refund_days),
        "condition": "全新及仅为检查性质使用的商品",
        "return_window": return_window,
        "return_method": "邮寄退货",
        "return_shipping_mode": str(group_rules.get("return_shipping_mode")),
        "return_shipping_cost": (
            "无理由撤回：消费者承担直接退货运费（须在购买前告知）；瑕疵、损坏或错发：商家承担"
            if group_rules.get("return_shipping_mode") != "free_designated_carrier" else
            "使用购买前指定的承运人退货：消费者不承担退货运费；瑕疵、损坏或错发：商家承担"
        ),
        "restocking_fee": ("不收取重新入库费；法定价值减损不属于重新入库费"
                           if not group_rules.get("restocking_fee") else "收取重新入库费（须另行核验合法性）"),
        "withdrawal_function": (
            f"必须在网站持续提供“{country_overlay.get('withdrawal_start_label')}”及“{country_overlay.get('withdrawal_confirm_label')}”电子撤回功能，并即时发送持久载体确认"
            if country_overlay.get("electronic_withdrawal_function") else "该国家规则库未要求德国式电子撤回按钮；仍须提供有效撤回声明渠道"
        ),
        "withdrawal_function_required": bool(country_overlay.get("electronic_withdrawal_function")),
        "withdrawal_start_label": str(country_overlay.get("withdrawal_start_label", "")),
        "withdrawal_confirm_label": str(country_overlay.get("withdrawal_confirm_label", "")),
        "language_consistency": "政策语言必须与网站落地页、商品数据源及 Merchant Center 所选语言一致",
        "statutory_withdrawal": withdrawal if has_withdrawal else "按当地强制法律（未设定统一撤回期）",
        "legal_guarantee": guarantee,
        "legal_guarantee_cn": LEGAL_GUARANTEE_CN.get(
            canonical,
            "至少2年瑕疵不符合约定的法定质量保证" if canonical in EEA_COUNTRIES else guarantee,
        ),
        "legal_basis": law,
        "coverage_status": "已由官方来源规则覆盖",
        "coverage_group": coverage_group,
        "official_sources": official_sources,
        "verified_on": str(rulepack["verified_on"]),
        "review_due": str(rulepack["review_due"]),
        "ruleset_version": str(rulepack["rulepack_version"]),
        "license_fields": licence_fields,
    }
    # Validate the canonical English templates before translation so localized
    # output cannot hide a forbidden clause from the hard consistency gate.
    settings.update(enforce_market(raw, settings, email, phone, website))
    validate_localized_output(policies, email, phone)
    settings.update(audit_policies(policies, settings))
    return policies, settings


def generate_translated_bundle(
    countries: str, email: str, phone: str, pdf_path: str, output_language: str,
    store_name: str = "", website: str = "", customs_mode: str = "卖家承担（客户收货时不另付）",
) -> tuple[list[tuple[str, str]], dict[str, object]]:
    """Generate six combined policies covering every requested sales market."""
    requested = [item.strip() for item in re.split(r"[,，、;；\n]+", countries) if item.strip()]
    if not requested:
        raise RuntimeError("请至少输入一个销售国家。")
    canonical_requested = [country_profile(item)[0] for item in requested]
    duplicates = sorted({name for name in canonical_requested if canonical_requested.count(name) > 1})
    if duplicates:
        raise RuntimeError(f"销售国家存在重复项：{'、'.join(duplicates)}。请每个国家只选择一次。")
    language_name, language_code = output_language_profile(output_language)
    bundles = [_generate_single_bundle(item, email, phone, pdf_path, language_code, store_name, website, customs_mode) for item in requested]
    combined: list[tuple[str, str]] = []
    for policy_index in range(6):
        title = bundles[0][0][policy_index][0]
        # Contact details and the legal notice describe the same legal
        # operator, irrespective of sales market. Publish one identity page,
        # not artificial country-by-country duplicates.
        if policy_index in {4, 5}:
            market_names = ", ".join(str(bundle[1]["country"]) for bundle in bundles)
            body = bundles[0][0][policy_index][1]
            if policy_index == 5:
                first_market = str(bundles[0][1]["country"])
                body = body.replace(
                    f"Mandatory consumer protections applicable in {first_market}",
                    f"Mandatory consumer protections applicable in the selected sales markets ({market_names})",
                )
            combined.append((title, body))
            continue
        sections = []
        for (_policies, settings) in bundles:
            market = settings["country"]
            sections.append(f"# {market}\n\n{_policies[policy_index][1]}")
        combined.append((title, "\n\n---\n\n".join(sections)))
    first = dict(bundles[0][1])
    first["country"] = "、".join(str(bundle[1]["country"]) for bundle in bundles)
    first["language"] = language_name
    first["markets"] = [bundle[1] for bundle in bundles]
    generated_markets = [str(market["country"]) for market in first["markets"]]
    if generated_markets != canonical_requested:
        raise RuntimeError("生成结果未完整保留全部所选国家，已停止输出，请重新选择。")
    first["bundle_validation_status"] = validate_combined(first["markets"], len(combined))
    return combined, first
