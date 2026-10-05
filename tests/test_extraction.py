from datetime import date

from app.parsers.html_parser import HtmlNoticeExtractor, is_weak_title

TODAY = date(2026, 10, 5)
BASE = "https://bank.example/tender"


def extract(html):
    return HtmlNoticeExtractor(BASE, today=TODAY).extract(html)


def test_header_mapped_tender_table():
    html = """<table>
      <tr><th>SL</th><th>Tender Name</th><th>Publishing Date</th><th>Closing Date</th><th>Download</th></tr>
      <tr><td>1</td><td>Supply of laptops</td><td>September 30, 2026; 6:05 PM</td>
          <td>October 12, 2026; 11:00 AM</td><td><a href="/docs/laptop.pdf">Download</a></td></tr>
    </table>"""
    [item] = extract(html)
    assert item.title == "Supply of laptops"
    assert item.published == date(2026, 9, 30)
    assert item.deadline.date() == date(2026, 10, 12) and item.deadline.hour == 11
    assert item.document_url == "https://bank.example/docs/laptop.pdf"


def test_header_in_separate_table_is_carried_over():
    html = """<table><tr><td>SL.</td><td>Title</td><td>Closing Date</td><td>Files</td></tr></table>
      <table>
        <tr><td>1</td><td>Invitation for Quotation of VAPT tools</td><td>02 August, 2026</td>
            <td><a href="/a.pdf">Download Now</a></td></tr>
      </table>"""
    [item] = extract(html)
    assert item.deadline.date() == date(2026, 8, 2)
    assert item.published is None


def test_non_tender_tables_and_page_furniture_are_ignored():
    html = """<header><a href="/brand.pdf">Download Brand Kit</a></header>
      <nav><a href="/login">Forgot Password?</a></nav>
      <table><tr><th>Currency</th><th>Buying</th><th>Selling</th></tr><tr><td>USD</td><td>124.00</td><td>125.00</td></tr></table>
      <div class="site-footer"><a href="/rates.pdf">Interest Rate on Lending tender</a></div>
      <main><p>No tenders at the moment.</p></main>"""
    assert extract(html) == []


def test_key_value_detail_tables():
    html = """<div class="card"><h5>Tender for construction of regional office</h5><div>
      <table><tr><td>Tender ID:</td><td>2026/10/04-Tender-Admin-132</td></tr>
             <tr><td>Publishing date:</td><td>4, October 2026</td></tr>
             <tr><td>Closing date:</td><td>25, October 2026 2:30 PM</td></tr>
             <tr><td>Tender opening date:</td><td>26, October 2026 2:30 PM</td></tr></table></div></div>"""
    [item] = extract(html)
    assert item.title == "Tender for construction of regional office"
    assert item.reference == "2026/10/04-Tender-Admin-132"
    assert item.published == date(2026, 10, 4)
    assert item.deadline.date() == date(2026, 10, 25)


def test_link_listing_prefers_descriptive_title_and_reads_posting_date():
    html = """<main><ul>
      <li><a href="/tender/rfp-external-audit">Tender Notice</a>
          <h3><a href="/tender/rfp-external-audit">RFP for External Audit of Project Accounts</a></h3>
          <span>28 Sep 2026</span></li>
      <li><a href="/about">About us</a></li></ul></main>"""
    [item] = extract(html)
    assert item.title == "RFP for External Audit of Project Accounts"
    assert item.link == "https://bank.example/tender/rfp-external-audit"
    assert item.published == date(2026, 9, 28)


def test_generic_download_link_takes_title_from_accordion_header():
    html = """<main><div class="acc-item">
      <div class="acc-title"><a href="#">Tender Schedule for Supply of Construction Materials</a></div>
      <div class="acc-content"><div class="row">
        <div class="col"><h6>Tender Details:</h6><ul><li>Reference: 0001</li><li>Deadline Date: October 07, 2026</li></ul></div>
        <div class="col"><h6>Methods of Application:</h6><a href="/pdf/0001.pdf">Download Notice</a></div>
      </div></div></div>
      <p><a href="/about">About us</a></p></main>"""
    [item] = extract(html)
    assert item.title == "Tender Schedule for Supply of Construction Materials"
    assert item.document_url == "https://bank.example/pdf/0001.pdf"


def test_weak_titles():
    assert is_weak_title("SBPLC/EED/ED/Godown/2026/140")
    assert is_weak_title("SBPLC.PO-Mirpur.IT.LTM.03")
    assert is_weak_title("Invitation for Tender")
    assert is_weak_title("Download Notice")
    assert not is_weak_title("Supply of 3 KVA Online UPS for ATM Booth")
