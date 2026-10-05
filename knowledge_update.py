from __future__ import annotations

import hashlib
import html as html_lib
import json
import os
import threading
import re
import time
from datetime import date, datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from rulepack_manager import configured_manifest_url, load_rulepack, update_from_manifest
from update_storage import write_json


# Stable primary sources that underpin the shared European baseline and the
# currently implemented national overlays. A changed fingerprint means the
# built-in legal rules need evidence-based review. Opt-in subscription review
# prepares candidates; only tested signed rules can resolve findings.
def _effective_eu_versions(today: date | None = None) -> dict[str, str]:
    """Return only versions already in force, never a future consolidation."""
    today = today or date.today()
    return {
        "EU Consumer Rights Directive": "2026-09-27" if today >= date(2026, 9, 27) else "2022-05-28",
        "EU Sale of Goods Directive": "2026-07-31",
    }


def _scheduled_legal_versions(rulepack: dict[str, object], today: date | None = None) -> dict[str, str]:
    """Return national versions only after their stated effective date.

    Future national transpositions are recorded in the rulepack so that they
    are not lost, but they must not block generation or change policy text
    before the law actually applies. On the effective date this function
    makes the pending version reviewable by the normal startup gate.
    """
    scheduled = rulepack.get("future_legal_versions", {})
    if not isinstance(scheduled, dict):
        return {}
    effective: dict[str, str] = {}
    for name, details in scheduled.items():
        if not isinstance(details, dict):
            continue
        try:
            effective_on = date.fromisoformat(str(details.get("effective_on", "")))
        except ValueError:
            continue
        version = str(details.get("version", "")).strip()
        if today is None and details.get("effective_timezone"):
            from datetime import timezone
            from zoneinfo import ZoneInfo
            country_today = datetime.now(timezone.utc).astimezone(ZoneInfo(str(details["effective_timezone"]))).date()
        else:
            country_today = today or date.today()
        if version and country_today >= effective_on:
            effective[str(name)] = version
    return effective


_EU_VERSIONS = _effective_eu_versions()
SOURCES = {
    # Each tuple is ordered by preference. EUR-Lex can return a successful but
    # empty anti-bot page on one route while another official representation of
    # the same act remains available.
    "EU Consumer Rights Directive": (
        f"https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:02011L0083-{_EU_VERSIONS['EU Consumer Rights Directive'].replace('-', '')}",
        f"https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:02011L0083-{_EU_VERSIONS['EU Consumer Rights Directive'].replace('-', '')}",
        f"https://eur-lex.europa.eu/legal-content/EN/TXT/XML/?uri=CELEX:02011L0083-{_EU_VERSIONS['EU Consumer Rights Directive'].replace('-', '')}",
        f"https://publications.europa.eu/resource/celex/02011L0083-{_EU_VERSIONS['EU Consumer Rights Directive'].replace('-', '')}",
    ),
    "EU Sale of Goods Directive": (
        f"https://eur-lex.europa.eu/legal-content/EN/TXT/HTML/?uri=CELEX:02019L0771-{_EU_VERSIONS['EU Sale of Goods Directive'].replace('-', '')}",
        f"https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:02019L0771-{_EU_VERSIONS['EU Sale of Goods Directive'].replace('-', '')}",
        f"https://eur-lex.europa.eu/legal-content/EN/TXT/XML/?uri=CELEX:02019L0771-{_EU_VERSIONS['EU Sale of Goods Directive'].replace('-', '')}",
        f"https://publications.europa.eu/resource/celex/02019L0771-{_EU_VERSIONS['EU Sale of Goods Directive'].replace('-', '')}",
    ),
    "EU GDPR obligations": ("https://commission.europa.eu/law/law-topic/data-protection/information-business-and-organisations/obligations_en",),
    "Germany BGB": ("https://www.gesetze-im-internet.de/bgb/",),
    "UK distance selling": ("https://www.gov.uk/online-and-distance-selling-for-businesses/distance-selling",),
    "Swiss ecommerce obligations": (
        "https://www.seco.admin.ch/en/onlinehandel",
        "https://www.seco.admin.ch/de/onlinehandel",
        "https://www.seco.admin.ch/fr/commerce-electronique",
        "https://www.kmu.admin.ch/en/statutory-obligations-swiss-and-european-e-commerce-laws",
        # Fedlex is the Swiss Confederation's official legal database. This
        # current Federal Act Against Unfair Competition is the principal
        # federal statute behind the SECO e-commerce guidance.
        "https://www.fedlex.admin.ch/eli/cc/241/en",
    ),
    "Turkey distance contracts": ("https://tuketici.ticaret.gov.tr/yayinlar/tuketici-bilgi-rehberi/mesafeli-sozlesmeler-hakkinda-bilgilendirme",),
}

# One authoritative national entry point for every selectable market. These
# are deliberately kept separate from the shared EU sources above: a common
# EU directive is not a substitute for checking each country's implementing
# law, consumer authority guidance, or official legal publication. A source
# that is temporarily unavailable is reported as such and never treated as a
# legal change.
COUNTRY_OFFICIAL_SOURCES: dict[str, tuple[str, ...]] = {
    "Germany": ("https://www.gesetze-im-internet.de/bgb/",),
    # The official XML representation excludes most presentation/navigation
    # churn while retaining the consolidated instrument and its status data.
    "United Kingdom": ("https://www.legislation.gov.uk/uksi/2013/3134/data.xml",),
    "France": (
        "https://www.legifrance.gouv.fr/loda/id/LEGISCTA000006114381",
        "https://www.legifrance.gouv.fr/codes/texte_lc/LEGITEXT000006069565",
        "https://www.legifrance.gouv.fr/codes/id/LEGITEXT000006069565",
        # Official French government consumer guidance (Service-Public,
        # published by the Prime Minister's legal-information directorate).
        "https://www.service-public.gouv.fr/particuliers/vosdroits/N10515",
        "https://www.service-public.gouv.fr/particuliers/vosdroits/F10488",
    ),
    "Italy": (
        "https://www.normattiva.it/uri-res/N2Ls?urn:nir:stato:decreto.legislativo:2005-09-06;206!vig=",
        "https://www.normattiva.it/atto/caricaDettaglioAtto?atto.codiceRedazionale=26G00002&atto.dataPubblicazioneGazzetta=2026-01-08&classica=true",
        "https://www.normattiva.it/atto/caricaDettaglioAtto?atto.codiceRedazionale=26G00047&atto.dataPubblicazioneGazzetta=2026-03-09&dataVigenza=24%2F04%2F2026&classica=true",
        "https://www.normattiva.it/atto/caricaDettaglioAtto?atto.codiceRedazionale=26G00093&atto.dataPubblicazioneGazzetta=2026-05-15&dataVigenza=08%2F07%2F2026&classica=true",
    ),
    "Russia": (
        "https://publication.pravo.gov.ru/",
        # Federal Rospotrebnadzor guidance dated 21 May 2026 confirms the
        # current distance-sale return and refund rules. Regional pages often
        # rewrite navigation or timestamps without changing the guidance.
        "https://zpp.rospotrebnadzor.ru/news/federal/574244",
    ),
    "Spain": ("https://www.boe.es/buscar/act.php?id=BOE-A-2007-20555",),
    "Turkey": ("https://tuketici.ticaret.gov.tr/yayinlar/tuketici-bilgi-rehberi/mesafeli-sozlesmeler-hakkinda-bilgilendirme",),
    "Netherlands": ("https://wetten.overheid.nl/BWBR0005289/",),
    "Switzerland": ("https://www.fedlex.admin.ch/eli/cc/27/317_321_377/en",),
    "Poland": (
        "https://eli.gov.pl/api/acts/DU/2024/1796/text.html",
        "https://api.sejm.gov.pl/eli/acts/DU/2024/1796/text.html",
        "https://isap.sejm.gov.pl/isap.nsf/download.xsp/WDU20140000827",
        "https://isap.sejm.gov.pl/isap.nsf/DocDetails.xsp?id=WDU20140000827",
    ),
    "Belgium": (
        "https://economie.fgov.be/fr/themes/ventes/formes-de-vente/ventes-distance",
        "https://economie.fgov.be/nl/themas/verkoop/vormen-van-verkoop/verkoop-op-afstand",
        "https://economie.fgov.be/en/themes/consumer-protection",
    ),
    "Sweden": (
        "https://www.konsumentverket.se/lagar/lagen-om-distansavtal-och-avtal-utanfor-affarslokaler-konsument/",
        "https://www.hallakonsument.se/om-oss/lagar/",
    ),
    "Austria": (
        "https://www.ris.bka.gv.at/eli/bgbl/i/2014/33/P0/NOR40162350",
    ),
    "Norway": ("https://lovdata.no/dokument/NL/lov/2014-06-20-27",),
    "Denmark": (
        "https://www.retsinformation.dk/eli/lta/2025/1184/pdf",
        "https://www.retsinformation.dk/eli/lta/2013/1457/pdf",
        "https://www.retsinformation.dk/eli/lta/2025/1184",
        "https://www.retsinformation.dk/eli/lta/2013/1457",
    ),
    "Ireland": ("https://www.irishstatutebook.ie/eli/2013/si/484/made/en/print",),
    # The consolidated (ajantasa) statute is the legally binding text; the
    # collection/metadata pages carry no statutory wording and only mirror
    # site chrome, so they are not monitored.
    "Finland": (
        "https://www.finlex.fi/fi/lainsaadanto/1978/38",
        "https://www.finlex.fi/fi/laki/ajantasa/1978/19780038",
    ),
    "Romania": ("https://legislatie.just.ro/Public/DetaliiDocument/140083",),
    "Czechia": (
        "https://www.cnb.cz/export/sites/cnb/cs/legislativa/.galleries/zakony/zakon_89_2012.pdf",
        "https://www.e-sbirka.cz/sb/2012/89",
    ),
    "Portugal": (
        "https://files.diariodarepublica.pt/1s/2021/10/20200/0000400029.pdf",
        "https://diariodarepublica.pt/dr/detalhe/decreto-lei/84-2008-249259",
        "https://diariodarepublica.pt/dr/legislacao-consolidada/decreto-lei/2003-34409475",
    ),
    "Greece": ("https://www.et.gr/",),
    # Current consolidated Consumer Protection Act (the old 2013-5 route was
    # not the consumer statute and is no longer a valid page).
    "Hungary": (
        "https://njt.hu/jogszabaly/1997-155-00-00",
        "https://njt.hu/jogszabaly/en/1997-155-00-00",
        # Official National Authority for Trade and Consumer Protection
        # guidance on online shops and prior-information duties.
        "https://nkfh.gov.hu/en/useful/electronic-commerce/online-commerce-web-stores",
    ),
    "Ukraine": (
        "https://zakon.rada.gov.ua/laws/show/1023-12",
        "https://zakon.rada.gov.ua/laws/show/en/1023-12/comp20121119",
        "https://zakon.rada.gov.ua/go/1023-12",
    ),
    "Slovakia": (
        # Act 108/2024 is the current general Consumer Protection Act; the
        # older Act 102/2014 endpoint is retained only in historical records.
        "https://static.slov-lex.sk/static/SK/ZZ/2024/108/20260731.print.html",
        "https://static.slov-lex.sk/static/SK/ZZ/2024/108/vyhlasene_znenie.print.html",
    ),
    # The old laws-list shell now returns 404.  Monitor an official State
    # Gazette publication page first; keep the list route as a fallback for
    # when the portal restores it.
    "Bulgaria": (
        "https://dv.parliament.bg/DVWeb/showMaterialDV.jsp?idMat=240866",
        "https://dv.parliament.bg/DVWeb/lawsList.faces",
    ),
    "Croatia": ("https://narodne-novine.nn.hr/clanci/sluzbeni/2014_06_76_1443.html",),
    "Serbia": (
        "https://www.pravno-informacioni-sistem.rs/",
        "https://slgl.pravno-informacioni-sistem.rs/api/prins/viewdoc?uuid=5e1627a4-81c0-452d-9f5c-d8c3ab84ddd1",
    ),
    "Lithuania": ("https://e-seimas.lrs.lt/portal/legalAct/lt/TAD/TAIS.163482",),
    "Slovenia": (
        "https://pisrs.si/api/datoteke/integracije/356439411",
        "https://pisrs.si/pregledPredpisa?id=ZAKO7054&tab=analiticni",
        "https://pisrs.si/Pis.web/pregledPredpisa?id=ZAKO1263",
    ),
    "Latvia": ("https://likumi.lv/ta/id/23309",),
    # Riigi Teataja's browser route is an Angular shell.  Its official public
    # XML API returns the actual consolidated statute and is stable enough for
    # fingerprinting; retain the browser route as a human-readable fallback.
    "Estonia": (
        "https://www.riigiteataja.ee/public-api/api/v1/akt/108072025032/blob-xml",
        "https://www.riigiteataja.ee/en/eli/ee/530102013016/consolide",
    ),
    "Cyprus": (
        "https://www.cylaw.org/nomoi/enop/non-ind/2021_1_112/full.html",
        "https://www.cylaw.org/nomoi/enop/non-ind/1996_1_93/full.html",
        "https://www.olc.gov.cy/OLC/OLC.NSF/5F1BAED14FE3DF2BC2258A2F00404247/%24file/The%20Consumer%20Law.pdf",
        "https://consumer.gov.cy/en/consumer-rights",
        # Server-rendered official Consumer Protection Service guidance. The
        # modern landing page is a JavaScript shell, while these pages carry
        # the actual withdrawal and guarantee text.
        "https://www.consumer.gov.cy/meci/cyco/cyconsumer.nsf/All/9EF29C3192873F25C2257FD5004000C9",
        "https://www.consumer.gov.cy/meci/cyco/cyconsumer.nsf/All/058B4ACC04925FEEC2257FD500318BCC",
    ),
    "Iceland": ("https://www.althingi.is/lagas/nuna/2000046.html",),
    "Bosnia and Herzegovina": (
        # The ministry's page is a dynamic document wrapper; this stable
        # official file endpoint returns the underlying gazette PDF directly.
        "https://fmt.gov.ba/preuzimanja-download-2/dokumenti/ured-za-zastitu-potrosaca/163-zakon-o-zastiti-potrosaca-u-bih/file.html",
        "https://www.mpr.gov.ba/organizacija_nadleznosti/zakonodavstvo/default.aspx?id=1023&langTag=en-US",
    ),
    "Albania": (
        "https://qbz.gov.al/eli/ligj/2008/04/17/9902",
        "https://www.avokatipopullit.gov.al/sq/article/legislation",
        "https://ishmt.gov.al/mbi-zbatimin-e-ligjit-per-mbrojtjen-e-konsumatoreve/",
    ),
    "North Macedonia": (
        "https://slvesnik.com.mk/Issues/c4ef6c06718f4fe18ff615a5877f73f4.pdf",
        "https://www.slvesnik.com.mk/Issues/c4ef6c06718f4fe18ff615a5877f73f4.pdf",
        "https://www.slvesnik.com.mk/",
        "https://dpi.gov.mk/index.php/en/",
        "https://www.economy.gov.mk/en-GB/ministerstvo/drzaven-pazaren-inspektorat",
    ),
    "Moldova": (
        "https://www.legis.md/cautare/downloadpdf/137809",
        "https://www.legis.md/cautare/downloadpdf/137809?lang=ro",
        "https://www.legis.md/cautare/getResults?doc_id=137809&lang=ro",
        "https://www.legis.md/cautare/getResults?doc_id=110702&lang=ro",
        "https://consumator.gov.md/en/node/575",
    ),
    "Georgia": (
        "https://matsne.gov.ge/en/document/view/5420598?publication=0",
        "https://www.matsne.gov.ge/en/document/download/5420598/0/en/pdf",
        "https://gcca.gov.ge/uploads_script/legislation/tmp/phpvesun3.pdf",
        "https://matsne.gov.ge/en/document/view/1659417",
    ),
    "Armenia": ("https://www.arlis.am/DocumentView.aspx?DocID=172223",),
    "Belarus": (
        "https://pravo.by/document/?guid=3871&p0=H11000262",
        "https://etalonline.by/document/?regnum=H11000262",
        # Government fallback: the Belarusian tax authority publishes current
        # rules for electronic distance sales; the EAEU's official legal
        # repository hosts the consumer-protection statute text.
        "https://nalog.gov.by/clarifications/clarifications/28487/",
        "https://nalog.gov.by/electronic_vat/e-vat/online_test/distance_selling/",
        "https://nalog.gov.by/news/29815/",
        "https://eec.eaeunion.org/upload/medialibrary/90d/Zakon-RB-O-zashchite-prav-potrebiteley.pdf",
    ),
    "Azerbaijan": (
        "https://e-qanun.az/framework/46944",
        "https://taxes.gov.az/az/post/180",
        "https://competition.gov.az/en/page/qanunvericilik/qanunlar",
    ),
    # Current Consumer Protection Act (published 06.02.2026).  The service is
    # intermittently returning HTTP 500; retaining the exact official record
    # lets the checker recover automatically without replacing it by a mirror.
    "Montenegro": (
        "https://www.sluzbenilist.me/propisi/390427",
        # Official Government consumer-protection directorate summary of the
        # enacted 2026 Act, used while the Gazette/PIS record intermittently
        # returns HTTP 500.
        "https://wapi.gov.me/download/49d8cec5-9723-461b-9297-d3a6a5c2c7a8?version=1.0",
    ),
    "Luxembourg": (
        "https://mpc.gouvernement.lu/en/actualites.gouvernement2024%2Bfr%2Bactualites%2Btoutes_actualites%2Bcommuniques%2B2026%2B06-juin%2B10-dpc-nouvelle-loi.html",
        "https://data.legilux.public.lu/filestore/eli/etat/leg/code/consommation/20170101/fr/html/eli-etat-leg-code-consommation-20170101-fr-html.html",
        "https://data.legilux.public.lu/filestore/eli/etat/leg/code/consommation/20170101/fr/xml/eli-etat-leg-code-consommation-20170101-fr-xml.xml",
        "https://legilux.public.lu/eli/etat/leg/code/consommation/20170101/fr",
        "https://legilux.public.lu/eli/etat/leg/loi/2014/04/23/n1/jo",
        "https://guichet.public.lu/fr/entreprises/commerce/pratiques-commerciales/vente/a-distance-b2c.html",
    ),
    "Malta": ("https://legislation.mt/eli/cap/378/eng/pdf",),
    "Kosovo": ("https://gzk.rks-gov.net/",),
    "Liechtenstein": ("https://www.gesetze.li/konso/",),
    "Monaco": ("https://legimonaco.mc/",),
    # Monitor the consolidated consumer-protection statute rather than the
    # portal home page, whose list of recently updated laws changes often and
    # is unrelated to ecommerce rules.
    "Andorra": (
        "https://portaljuridicandorra.ad/L2013013",
        "https://www.govern.ad/ca/tematiques/comerc-i-consum/consum/legislacio-consum",
    ),
    # The Council's official PDF record is the primary source; the streaming
    # page is an official HTML record of the same consumer decree.
    "San Marino": (
        "https://www.consigliograndeegenerale.sm/on-line/home/documento17148431.html",
        "https://www.consigliograndeegenerale.sm/on-line/home/streaming-video-consiglio/scheda17187245.html",
        "https://www.consigliograndeegenerale.sm/on-line/home/leggi-e-decreti.html",
    ),
    # Correct Holy See path/date for the official Pastor Bonus document; the
    # previous 18-Dec path was a permanent 404.
    "Vatican City": (
        "https://www.vatican.va/content/john-paul-ii/en/apost_constitutions/documents/hf_jp-ii_apc_19880628_pastor-bonus.html",
    ),
}
SOURCES.update({f"Country — {country}": urls for country, urls in COUNTRY_OFFICIAL_SOURCES.items()})
# Schema 15 records the tag-safe body normalizer, embedded-data/PDF fallback,
# plus the official fallback endpoints (including national PDF/API mirrors).
# Schema 16 adds volatile-marker scrubbing: legislation.gov.uk and
# normattiva.it stamp the CURRENT DATE into every page, legimonaco.mc and
# legislation.mt embed latest-publication tickers, and finlex embeds a
# per-deployment build id. Those churn daily or per deploy and must never
# read as a change in the law itself.
# Schema 17 extends hydration-stream scrubbing for finlex.fi: the statute
# only exists inside React Flight chunks, so publishing any unrelated law
# renumbers chunk ids, component references and scss-module hashes, and the
# "latest legislation" sidebar churns on every publication.
FINGERPRINT_SCHEMA = 17
MIN_VISIBLE_SOURCE_CHARS = 1000

_LOCK = threading.Lock()
_READY = threading.Event()
_STATUS: dict[str, object] = {
    "state": "checking",
    "message": "正在检查政策知识库更新……",
    "changed": [],
    "unreachable": [],
}


def _cache_path() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Policy Amadeus"
    base.mkdir(parents=True, exist_ok=True)
    return base / "knowledge_source_state.json"


_VOLATILE_MARKERS: tuple[tuple[re.Pattern[str], str], ...] = (
    # legislation.gov.uk stamps today's date into its up-to-date statement.
    (re.compile(r"in force on or before \d{1,2} \w+ \d{4}", re.I), "in force on or before"),
    # normattiva.it renders the as-of date of the version being viewed.
    (re.compile(r"vigente al \d{1,2}/\d{1,2}/\d{4}", re.I), "vigente al"),
    # legimonaco.mc lists the latest published journal issue number and date.
    # The degree sign may arrive mojibake ("nÂ°") when the page is mis-decoded.
    (re.compile(r"Journal n(?:\u00c2)?\u00b0 ?\d+ +\d{1,2} \w+ \d{4}", re.I), "Journal n°"),
    # legislation.mt lists newly published laws ahead of the act metadata.
    (re.compile(r"L-AĦĦAR AĠĠORNAMENTI.*?FAQs", re.I | re.S), " "),
    # wetten.overheid.nl prints the retrieval date on every consolidated-law
    # page. It is a page-view timestamp, not an amendment to the statute.
    (re.compile(r"Geraadpleegd op \d{1,2}-\d{1,2}-\d{4}", re.I), "Geraadpleegd op"),
    # RIS puts the current viewing date into the title/header of the
    # consolidated Austrian text. Keep effective dates in the legal body;
    # only this standalone page marker is volatile.
    (re.compile(r"Fassung vom \d{1,2}\.\d{1,2}\.\d{4}", re.I), "Fassung vom"),
    # React hydration streams (finlex.fi) carry the statute inside
    # self.__next_f.push chunks. A push boundary can split the payload at any
    # byte, so the wrappers are stitched back together first; afterwards the
    # per-deployment build identifier is scrubbed from the joined stream.
    (re.compile(r'self\.__next_f\.push\(\[1,"[0-9a-z]{1,6}:'), 'self.__next_f.push([1,"'),
    (re.compile(r'"\]\)self\.__next_f\.push\(\[1,"'), ""),
    (re.compile(r"20\d\d-\d\d-[a-z0-9-]*frontend-prod", re.I), "finlex-build"),
    # Publishing any unrelated law renumbers every later chunk, component
    # reference, scss-module hash and webpack module id. Neutralize the
    # build-dependent identifiers, never the payload they carry.
    (re.compile(r'\\n[0-9a-z]{1,6}:(?=[\[IE"])'), "\\n"),
    (re.compile(r"\$L[0-9a-z]{1,6}"), "$L"),
    (re.compile(r"styles-module-scss-module__[0-9A-Za-z_]{2,12}__"), "styles-module-scss-module__"),
    (re.compile(r"/_next/static/[0-9A-Za-z._/-]+"), "next-asset"),
    (re.compile(r"I\[\d{1,9},"), "I[0,"),
    # Finlex appends revision/timestamp query parameters to correction-PDF
    # links in the hydration payload. They identify a rendered asset, not a
    # change to the consolidated statute; preserve the link path itself.
    (re.compile(r"(?:[?&]|\\u0026)revision=\d+", re.I), ""),
    (re.compile(r"(?:\\u0026|&)timestamp=20\d{2}-\d{2}-\d{2}T[^&\" ]+Z", re.I), ""),
    # The finlex "latest legislation" sidebar lists every newly published
    # act. Scrub whole entries (separator included) so the entry count can
    # never shift the fingerprint; only the monitored statute remains.
    (
        re.compile(
            r'(?:\\n)?\[\\"\$\\",\\"li\\",\\"[0-9]+\\",\{\\"className\\":\\"[^"]*documentListItem[^"]*\\"'
            r'.{0,8000}?\\"--markerColor\\":\\"[^"\\]*\\"\}\}\]\]',
            re.S,
        ),
        "",
    ),
)


def _normalized_legal_text(html: str) -> str:
    # Restrict monitoring to the document body. Government sites frequently
    # change global navigation, cookie banners and recommendation cards even
    # when the legal guidance itself is unchanged.
    original_html = html
    found_container = False
    # The Turkish ministry places the stable dated guidance in __zone, while
    # <main> also wraps volatile site navigation and promotional cards.
    zone = re.search(
        r'<div\b[^>]*class=["\'][^"\']*\b__zone\b[^"\']*["\'][^>]*>(.*?)</section>',
        html, flags=re.I | re.S,
    )
    if zone:
        html = zone.group(1)
        found_container = True

    for tag in (() if found_container else ("main", "article")):
        match = re.search(rf"<{tag}\b[^>]*>(.*)</{tag}>", html, flags=re.I | re.S)
        if match:
            html = match.group(1)
            found_container = True
            break

    # A number of official legacy portals (notably the Cyprus Consumer
    # Protection Service's Domino pages) place the substantive text in a
    # `<div id="content">` wrapper inside one large POST form.  The generic
    # form scrubber below would otherwise remove the entire document and
    # leave only the page title, falsely reporting the source as unreachable.
    if not found_container:
        content = re.search(
            r'<div\b[^>]*\bid=["\']content["\'][^>]*>(.*)</body>',
            html,
            flags=re.I | re.S,
        )
        if content:
            html = content.group(1)
            found_container = True

    def clean(fragment: str) -> str:
        # Match each volatile element with its own closing tag. A loose
        # "any opener/any closer" expression can consume the legal body when
        # government pages nest scripts or forms inside a header/navigation
        # wrapper, producing false "source unreachable" results.
        volatile = re.compile(
            r"<(?P<volatile>script|style|nav|header|footer|aside|form)\b[^>]*>.*?</(?P=volatile)>",
            flags=re.I | re.S,
        )

        def remove_layout(match: re.Match[str]) -> str:
            # Some legal portals wrap the entire document in one POST form.
            # Removing that form would remove the law itself and leave only a
            # navigation shell (the Dutch wetten.nl page is one example).
            # Keep unusually large wrappers, while still removing ordinary
            # search, newsletter and cookie forms.
            if match.group("volatile").lower() == "form" and len(match.group(0)) > 100_000:
                return match.group(0)
            return " "

        visible = volatile.sub(remove_layout, fragment)
        visible = re.sub(r"<[^>]+>", " ", visible)
        return " ".join(visible.split())

    normalized = clean(html)
    if len(normalized) < MIN_VISIBLE_SOURCE_CHARS:
        # Modern official portals often server-render only a shell and put the
        # actual statute in inline hydration data (for example Next.js
        # `self.__next_f.push(...)`). Keep data-bearing inline scripts only as
        # a last-resort fallback; ordinary JavaScript bundles are discarded.
        script = re.compile(r"<script(?P<attrs>[^>]*)>(?P<body>.*?)</script>", flags=re.I | re.S)

        def keep_embedded_data(match: re.Match[str]) -> str:
            attrs = match.group("attrs").lower()
            body = match.group("body")
            if "src=" in attrs:
                return " "
            if "self.__next_f.push" in body or "application/ld+json" in attrs:
                return html_lib.unescape(body)
            # Other inline state containers are retained only when they look
            # substantial and contain legal/consumer wording, avoiding hashes
            # dominated by analytics and UI telemetry.
            if len(body) >= 500 and re.search(
                r"consumer|consument|kuluttaja|forbruger|consumidor|consommateur|consumat|consumator|spotrebit|potroša|consumator",
                body, flags=re.I,
            ):
                return html_lib.unescape(body)
            return " "

        embedded = script.sub(keep_embedded_data, original_html)
        embedded_normalized = clean(embedded)
        if len(embedded_normalized) > len(normalized):
            normalized = embedded_normalized
    # EUR-Lex does not always place consolidated document text inside its
    # standard <main> element. Fall back to a navigation-stripped full page
    # only when the selected container is clearly too small to be the law.
    if found_container and len(normalized) < MIN_VISIBLE_SOURCE_CHARS:
        normalized = clean(original_html)
    for pattern, replacement in _VOLATILE_MARKERS:
        normalized = pattern.sub(replacement, normalized)
    return normalized


def _fingerprint(url: str) -> str:
    from io import BytesIO
    import requests

    # EUR-Lex pages are relatively large and occasionally take longer than
    # eight seconds even when healthy.  A short timeout incorrectly classified
    # that latency as an unavailable legal source and made startup checks
    # needlessly incomplete.
    headers = {"User-Agent": "Policy-Amadeus/1.3"}
    if "publications.europa.eu/resource/celex/" in url:
        headers["Accept"] = "application/rdf+xml"
    # Some official portals sit behind a slow government CDN or occasionally
    # reset the first TLS connection. Keep a bounded connect/read split so a
    # transient edge failure is retried by _fingerprint_source instead of
    # being reported as a legal-source outage.
    request_timeout = (30, 90) if "eec.eaeunion.org" in url else (12, 45)
    try:
        response = requests.get(url, timeout=request_timeout, allow_redirects=True, headers=headers)
    except Exception:
        # The EEC file host is reachable directly on some Windows networks
        # but its TLS handshake can stall through the system proxy. Retry this
        # one official endpoint without inherited proxy variables before
        # classifying Belarus as temporarily unavailable.
        if "eec.eaeunion.org" not in url:
            raise
        direct = requests.Session()
        direct.trust_env = False
        response = direct.get(url, timeout=(20, 60), allow_redirects=True, headers=headers)
    response.raise_for_status()
    # PDF-only official portals (notably Denmark's Retsinformation) return a
    # binary response, so extract text before applying the same normalizer.
    content_type = (getattr(response, "headers", {}) or {}).get("content-type", "").lower()
    pdf_magic = response.content.lstrip().startswith(b'%PDF-')
    expected_malta_pdf = url.lower().startswith('https://legislation.mt/eli/') and url.lower().split('?', 1)[0].endswith('/pdf')
    is_pdf = pdf_magic or "application/pdf" in content_type or url.lower().split("?", 1)[0].endswith(".pdf") or expected_malta_pdf
    if is_pdf and not pdf_magic:
        raise RuntimeError('官方 PDF 入口返回网站外壳，未获取法律文档')
    if is_pdf:
        try:
            from pypdf import PdfReader

            normalized_input = "\n".join(page.extract_text() or "" for page in PdfReader(BytesIO(response.content)).pages)
        except Exception as exc:
            raise RuntimeError("官方 PDF 正文无法提取") from exc
    else:
        normalized_input = response.text
    # Hash only normalized legal-body text. This is stronger than
    # Last-Modified, which many government sites omit or change for templates.
    from official_document import extract_official_document
    extracted = None if is_pdf else extract_official_document(normalized_input, url)
    normalized = ' '.join(extracted.split()) if extracted is not None else _normalized_legal_text(normalized_input)
    # A successful HTTP status is not proof that the legal document was
    # returned. EUR-Lex and other government sites can temporarily return an
    # empty/bot/interstitial page. Never store such a response as a baseline;
    # otherwise recovery from the outage looks like a change in the law.
    if len(normalized) < MIN_VISIBLE_SOURCE_CHARS and is_pdf and len(response.content) >= 10_000:
        # Some official gazette PDFs are scanned images and contain no
        # extractable text. The complete PDF bytes are still a valid document
        # integrity signal; hashing them prevents a dynamic HTML wrapper from
        # causing false positives while still detecting a replaced PDF.
        return hashlib.sha256(response.content).hexdigest()
    if len(normalized) < MIN_VISIBLE_SOURCE_CHARS:
        raise RuntimeError("官方来源正文为空或异常短")
    digest = hashlib.sha256(normalized.encode("utf-8", "ignore")).hexdigest()
    evidence = os.environ.get("POLICY_AMADEUS_EVIDENCE_DIR", "")
    if evidence:
        # Only public official-law text; never licence or merchant data.
        folder = Path(evidence)
        folder.mkdir(parents=True, exist_ok=True)
        write_json(folder / f"{digest}.json", {"url": url, "sha256": digest,
                   "observed_at": datetime.now().astimezone().isoformat(), "normalized_text": normalized})
    return digest


def _fingerprint_source(urls: tuple[str, ...]) -> dict[str, str]:
    """Try every official representation before declaring a source offline.

    Candidates are fetched concurrently so a slow primary route does not hold
    startup hostage. If the first pass fails, one delayed pass handles brief
    edge/CDN failures. The preferred valid candidate always wins, preserving a
    stable baseline when more than one route is healthy.
    """
    errors: list[Exception] = []
    for attempt in range(3):
        results: dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=len(urls)) as pool:
            jobs = {pool.submit(_fingerprint, url): url for url in urls}
            for job in as_completed(jobs):
                url = jobs[job]
                try:
                    results[url] = job.result()
                except Exception as exc:
                    errors.append(exc)
        if results:
            # Keep every healthy representation. Cache comparisons are made
            # per URL, so switching between HTML and RDF can never masquerade
            # as a change in the underlying law.
            return results
        if attempt < 2:
            time.sleep(1.0 + attempt * 0.75)
    if errors:
        raise RuntimeError("所有官方入口均暂时不可达") from errors[-1]
    raise RuntimeError("官方来源未配置可用入口")


def run_startup_check(incremental: bool = False) -> dict[str, object]:
    global _STATUS
    try:
        try:
            cache = json.loads(_cache_path().read_text(encoding="utf-8"))
            previous = cache.get("sources", {}) if cache.get("schema") == FINGERPRINT_SCHEMA else {}
        except (OSError, ValueError):
            previous = {}
        try:
            previous_report = json.loads((_cache_path().parent / "knowledge_coverage_latest.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            previous_report = {}
        selected_sources = dict(SOURCES)
        if incremental and previous_report:
            flagged = set(previous_report.get("changed", [])) | set(previous_report.get("unreachable", []))
            selected_sources = {name: urls for name, urls in SOURCES.items() if name in flagged or not name.startswith("Country — ")}
        else:
            incremental = False
        current: dict[str, dict[str, str]] = {}
        unreachable: list[str] = []
        with ThreadPoolExecutor(max_workers=5) as pool:
            jobs = {pool.submit(_fingerprint_source, urls): name for name, urls in selected_sources.items()}
            for job in as_completed(jobs):
                name = jobs[job]
                try:
                    current[name] = job.result()
                except Exception:
                    unreachable.append(name)
        # A failed fetch is not a resolution. Carry pending document evidence
        # across full scans, incremental scans and temporary source outages.
        changed: list[str] = []
        pending = {name: dict(endpoints) for name, endpoints in previous_report.get("pending_source_fingerprints", {}).items() if isinstance(endpoints, dict)}
        for name in previous_report.get("changed", []):
            if name in SOURCES or name.startswith("Country — "):
                changed.append(name)
                if name not in pending:
                    pending[name] = {url: digest for url, digest in previous_report.get("observed_source_fingerprints", {}).get(name, {}).items()
                                     if previous.get(name, {}).get(url) != digest}
        try:
            update_result = update_from_manifest(configured_manifest_url())
            update_error = ""
        except Exception as exc:
            update_result = {"state": "failed", "message": "规则包自动更新失败"}
            update_error = str(exc)
        # Version dates are authoritative. A page hash is only a secondary
        # integrity signal and a future consolidation must not be treated as
        # current before its effective date.
        try:
            reviewed_rulepack = load_rulepack()
            reviewed_versions = reviewed_rulepack.get("legal_versions", {})
        except Exception:
            reviewed_rulepack = {}
            reviewed_versions = {}
        for name, effective_version in _effective_eu_versions().items():
            if reviewed_versions.get(name) != effective_version:
                changed.append(name)
        for name, effective_version in _scheduled_legal_versions(reviewed_rulepack).items():
            if reviewed_versions.get(name) != effective_version:
                changed.append(name)
        for name, endpoints in current.items():
            old_endpoints = previous.get(name, {})
            if not isinstance(old_endpoints, dict):
                continue
            approvals = reviewed_rulepack.get("reviewed_source_fingerprints", {}).get(name, {})
            differences = {url: digest for url, digest in endpoints.items() if url in old_endpoints and old_endpoints[url] != digest and approvals.get(url) != digest}
            if differences:
                pending.setdefault(name, {}).update(differences)
                if name not in changed:
                    changed.append(name)
        resolved_pending = []
        for name in list(changed):
            evidence = pending.get(name, {})
            approvals = reviewed_rulepack.get("reviewed_source_fingerprints", {}).get(name, {})
            if evidence and all(approvals.get(url) == digest or (
                    url in current.get(name, {}) and approvals.get(url) == current[name][url])
                    for url, digest in evidence.items()):
                changed.remove(name)
                pending.pop(name, None)
                resolved_pending.append(name)
        # Add newly reachable sources to an existing partial baseline without
        # treating them as changes. Existing fingerprints remain immutable
        # until a verified rulepack update is installed.
        baseline = {name: dict(value) for name, value in previous.items() if isinstance(value, dict)}
        for name, endpoints in current.items():
            baseline.setdefault(name, {}).update({url: digest for url, digest in endpoints.items() if url not in baseline.get(name, {})})
            approvals = reviewed_rulepack.get("reviewed_source_fingerprints", {}).get(name, {})
            baseline[name].update({url: digest for url, digest in endpoints.items() if approvals.get(url) == digest})
        if baseline != previous:
            write_json(_cache_path(), {"schema": FINGERPRINT_SCHEMA, "sources": baseline})
        if update_result.get("state") == "updated":
            # Installing a signed package is not evidence that every observed
            # source-body change was reviewed. Never erase pending findings.
            reviewed_rulepack = load_rulepack()
        if changed:
            state = "review_required"
            message = "官方法律来源发生变化，知识库需要人工复核，已暂停政策生成。"
            from codex_review_worker import enabled as auto_review_enabled
            if auto_review_enabled():
                message = "检测到官方来源变化，正在自动审查与修复；测试和签名安装通过后恢复生成。"
        elif not current:
            state = "offline"
            message = "无法连接官方来源；将使用已核验的本地规则库，并显示离线警告。"
        elif update_error:
            state = "update_failed"
            message = f"规则包自动更新失败：{update_error}；继续使用已核验的本地规则包。"
        elif unreachable:
            state = "partial"
            message = f"部分官方来源暂时无法连接（{len(unreachable)}项）；使用已核验本地规则并显示警告。"
        else:
            state = "current"
            if update_result.get("state") == "updated":
                message = str(update_result.get("message"))
            elif update_result.get("state") == "not_configured":
                message = "未发现官方来源变化；规则包自动更新通道尚未配置。"
            else:
                message = "政策知识库检查完成：未发现官方来源变化。"
        coverage = {
            country: {
                "status": (
                    "temporarily_unreachable" if f"Country — {country}" in unreachable else
                    "source_changed" if f"Country — {country}" in changed else
                    "source_fingerprint_no_change" if f"Country — {country}" in current and
                    any(url in previous.get(f"Country — {country}", {}) for url in current[f"Country — {country}"]) else
                    "baseline_requires_review" if f"Country — {country}" in current else
                    "not_verified"
                ),
                "official_sources_reached": sorted(current.get(f"Country — {country}", {})),
                "verification_method": "configured_source_fingerprint_and_scheduled_effective_dates",
                "full_national_legal_review_completed": False,
                "checked_at": datetime.now().astimezone().isoformat(),
            }
            for country in COUNTRY_OFFICIAL_SOURCES
        }
        if incremental:
            for country in coverage:
                if f"Country — {country}" not in selected_sources:
                    coverage[country] = previous_report.get("countries", {}).get(country, coverage[country])
        report = {
            "pending_source_fingerprints": pending,
            "checked_at": datetime.now().astimezone().isoformat(),
            "state": state,
            "message": message,
            "changed": changed,
            "unreachable": unreachable,
            "countries": coverage,
            "rulepack_version": reviewed_rulepack.get("rulepack_version", "unavailable"),
            "update_result": update_result,
            "mode": "incremental" if incremental else "full",
            "last_full_checked_at": previous_report.get("last_full_checked_at", previous_report.get("checked_at")) if incremental else datetime.now().astimezone().isoformat(),
            "observed_source_fingerprints": current,
            "reviewed_resolutions": list(dict.fromkeys(resolved_pending + [name for name, endpoints in current.items() if name not in changed
                and any(reviewed_rulepack.get("reviewed_source_fingerprints", {}).get(name, {}).get(url) == digest
                        for url, digest in endpoints.items())])),
        }
        report_error = ""
        try:
            write_json(_cache_path().parent / "knowledge_coverage_latest.json", report)
        except OSError as exc:
            report_error = str(exc)
        with _LOCK:
            _STATUS = {"state": state, "message": message, "changed": changed, "checked_at": report["checked_at"],
                       "unreachable": unreachable, "report_error": report_error}
    finally:
        _READY.set()
    from codex_review_worker import launch_if_needed
    launch_if_needed()
    return get_status()


def start_startup_check() -> None:
    threading.Thread(target=run_startup_check, daemon=True).start()


def get_status(wait_seconds: float = 0) -> dict[str, object]:
    if wait_seconds:
        _READY.wait(wait_seconds)
    # A scheduled updater can resolve a finding while this GUI is still open.
    # Adopt only a newer completed report using the currently active rulepack.
    # This changes no baseline and performs no network request on the UI thread.
    try:
        report = json.loads((_cache_path().parent / "knowledge_coverage_latest.json").read_text(encoding="utf-8"))
        if report.get("message") and report.get("rulepack_version") == load_rulepack()["rulepack_version"]:
            with _LOCK:
                if _STATUS.get("state") != "checking" and datetime.fromisoformat(report["checked_at"]) > datetime.fromisoformat(str(_STATUS.get("checked_at", "1970-01-01T00:00:00+00:00"))):
                    _STATUS.update({key: report[key] for key in ("state", "message", "changed", "unreachable", "checked_at")})
    except (OSError, ValueError, KeyError, RuntimeError):
        pass
    with _LOCK:
        return dict(_STATUS)


def require_no_detected_change() -> dict[str, object]:
    status = get_status(20)
    if status.get("state") == "checking":
        raise RuntimeError("政策知识库更新检查尚未完成，请稍后重试。")
    if status.get("state") == "review_required":
        changed = "、".join(str(item) for item in status.get("changed", []))
        from codex_review_worker import enabled as auto_review_enabled
        if auto_review_enabled():
            raise RuntimeError(f"正在自动审查并修复官方来源变化（{changed}）；通过测试及签名安装后自动恢复生成。")
        raise RuntimeError(f"检测到官方法律来源发生变化（{changed}）。规则库人工复核前已禁止生成政策。")
    return status
