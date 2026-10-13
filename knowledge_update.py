"""Offline official-source references and manual-review safety gate. No updater."""
import json,os
from pathlib import Path

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
        "https://zakon.rada.gov.ua/laws/show/1023-12/print",
        # Retained for diagnostic history only. The review worker explicitly
        # refuses to approve this historical comparison as a current statute.
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
        # Adopted 23 April 2026, gazette 35/26: full single-act text. The
        # gazette fallback contains other acts and advertising as well.
        "https://www.parlament.gov.rs/upload/archive/files/lat/pdf/zakoni/14_saziv/1317-26-lat..pdf",
        "https://www.pravno-informacioni-sistem.rs/",
        "https://slgl.pravno-informacioni-sistem.rs/api/prins/viewdoc?uuid=5e1627a4-81c0-452d-9f5c-d8c3ab84ddd1",
    ),
    "Lithuania": ("https://e-seimas.lrs.lt/portal/legalAct/lt/TAD/TAIS.6020/asr",
                  "https://e-seimas.lrs.lt/portal/legalAct/lt/TAD/TAIS.6020",
                  "https://vvtat.lrv.lt/lt/DUK/"),
    "Slovenia": (
        "https://pisrs.si/api/datoteke/integracije/356439411",
        "https://pisrs.si/pregledPredpisa?id=ZAKO7054&tab=analiticni",
        "https://pisrs.si/Pis.web/pregledPredpisa?id=ZAKO1263",
    ),
    "Latvia": (
        "https://likumi.lv/ta/id/23309",
        "https://likumi.lv/ta/id/266462",
        "https://likumi.lv/ta/id/96619",
        "https://likumi.lv/ta/id/300099",
    ),
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
    "Iceland": ("https://www.althingi.is/lagas/nuna/2016016.html",
                "https://www.althingi.is/altext/lagasofn/nuna/2016016.html",
                "https://www.althingi.is/lagas/nuna/2003048.html",
                "https://www.althingi.is/lagas/nuna/2002030.html",
                "https://www.althingi.is/lagas/nuna/2018090.html"),
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
        # Historical diagnostic endpoint: this is the ministry's annual work
        # report, NOT statute text. Retain its provenance, never use it as a
        # legal-body replacement; the review worker explicitly rejects it.
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


def require_no_detected_change(markets=None):
    """Preserve known unresolved findings without fetching or updating anything."""
    from rulepack_manager import load_rulepack
    path=Path(os.environ.get('LOCALAPPDATA',Path.home()))/'Policy Amadeus'/'knowledge_coverage_latest.json'
    try:
        report=json.loads(path.read_text(encoding='utf-8'))
    except (OSError,ValueError):
        report={}
    names=set(markets or [])
    load_rulepack()  # Preserve expiry and structural checks before drafting.
    changed=list(report.get('changed',[]))
    relevant=[s for s in changed if not s.startswith('Country — ') or not names or s.removeprefix('Country — ') in names]
    if relevant:
        return {'state':'draft_pending_review','message':'仅生成待法律复核草稿，不可直接发布：'+', '.join(relevant),
                'unresolved_findings':relevant,'unrelated_findings':[s for s in changed if s not in relevant]}
    return {'state':'manual_maintenance','message':'使用本地规则；未自动检查法律最新状态',
            'unrelated_findings':changed}
