"""A small synthetic company index for agent tests: written to a temporary folder, loaded as a real Index."""

import json
import tempfile
from pathlib import Path
from unittest import mock

from filingroom import config
from filingroom.index import Index

T = "ACME"
K26, K25, Q1, PX, ER = "ACME_10K_FY2026", "ACME_10K_FY2025", "ACME_10Q_Q1FY2027", "ACME_DEF14A_2026", "ACME_8K_Q1FY2027"
URL = {K26: "https://www.sec.gov/a/k26.htm", K25: "https://www.sec.gov/a/k25.htm", Q1: "https://www.sec.gov/a/q1.htm",
       PX: "https://www.sec.gov/a/px.htm", ER: "https://www.sec.gov/a/er.htm"}
META = {K26: ("10-K", "FY2026", "2026-08-20", "2026-06-30"), K25: ("10-K", "FY2025", "2025-08-21", "2025-06-30"),
        Q1: ("10-Q", "Q1 FY2027", "2026-11-05", "2026-09-30"), PX: ("DEF 14A", "2026 annual meeting", "2026-10-01",
                                                                    "2026-06-30"),
        ER: ("8-K", "Q1 FY2027", "2026-11-04", "2026-09-30")}


def chunk(doc, sec, n, text, topic, heading="Item 7. Management's Discussion and Analysis", sub=""):
    form, period, filed, _ = META[doc]
    return {"chunk_id": f"{doc}#{sec}#{n:03d}", "doc_id": doc, "ticker": T, "form": form, "period": period,
            "filing_date": filed, "section": sec, "topic": topic, "heading": heading, "subheading": sub,
            "url": URL[doc], "text": text}


CHUNKS = [
    chunk(K26, "item7", 0, "Overview. Acme sells widgets to small businesses across North America.", "mdna"),
    chunk(K26, "item7", 1, "Total revenue was $1,234.5 million for fiscal 2026, an increase of 12% from fiscal 2025.",
          "mdna"),
    chunk(K26, "item7", 2, "[TABLE]\nItem | 2026 | 2025\nTotal revenue | $ 1,234.5 | $ 1,102.2\n[/TABLE]", "mdna"),
    chunk(K26, "item7", 3, "Liquidity. Cash and cash equivalents were $400 million at year end.", "mdna"),
    chunk(K26, "item1a", 0, "Risk factors. Competition for widgets is intense and revenue may decline.",
          "risk_factors", heading="Item 1A. Risk Factors"),
    chunk(K25, "item7", 0, "Total revenue was $1,102.2 million for fiscal 2025.", "mdna"),
    chunk(Q1, "partI-item2", 0, "Total revenue for the quarter was $330 million.", "mdna",
          heading="Item 2. Management's Discussion and Analysis"),
    chunk(PX, "proxy", 0, "The board has nine directors, eight of whom are independent.", "proxy",
          heading="Proxy Statement"),
    chunk(ER, "ex99", 0, "Acme reports first quarter revenue of $330 million.", "press_release",
          heading="Exhibit 99.1"),
]
MANIFEST = [{"doc_id": d, "ticker": T, "form": f, "period": p, "report_date": rd, "filing_date": fd,
             "url": URL[d]} for d, (f, p, fd, rd) in META.items()]
CO = {"ticker": T, "name": "Acme Corp", "fiscal_year_end": "0630", "split": "tune"}
P = {"latest_periodic": "Q1 FY2027", "latest_periodic_doc": Q1, "latest_periodic_filed": "2026-11-05",
     "latest_release_filed": "2026-11-04", "latest_fy": "FY2026", "latest_fy_end": "2026-06-30", "latest_fy_doc": K26,
     "prior_fy": "FY2025", "prior_fy_end": "2025-06-30", "latest_release": "Q1 FY2027", "latest_release_doc": ER,
     "latest_proxy": "FY2026", "latest_proxy_doc": PX, "latest_filing": "2026-11-05"}


class Corpus:
    """Context manager: temp index on disk, config.company / checklist.periods / edgar.manifest patched."""

    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        d = Path(self.tmp.name)
        (d / f"{T}.jsonl").write_text("".join(json.dumps(c) + "\n" for c in CHUNKS))
        self.patches = [mock.patch.object(config, "INDEX", d), mock.patch.object(config, "company", lambda t: CO),
                        mock.patch("filingroom.checklist.periods", lambda t: P),
                        mock.patch("filingroom.edgar.manifest", lambda t: MANIFEST)]
        for p in self.patches:
            p.start()
        self.ix = Index(T)
        return self

    def __exit__(self, *exc):
        for p in reversed(self.patches):
            p.stop()
        self.tmp.cleanup()
