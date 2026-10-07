"""
Tests for IT Services sources, Alltender subcategory scraper, and IT classification.
"""

from datetime import date
import pytest
from app.classification.relevance import RelevanceClassifier
from app.crawler import alltender
from app.crawler.alltender import AlltenderItem, parse_list_page, organization_name, sector
from app.parsers.date_cleaner import parse_first_date


SAMPLE_SUBCAT_HTML = """
<div class="my_tender_title">
    <p style="font-size:15px;">ICT Support/Consultancy (Total tender: 2)</p>
</div>
<div class="my_tender">
    <div class="col-md-12">
        <div class="tender_info">
            <div class="tender_id">
                <p>Tender ID 1647357</p>
            </div>
            <div class="tender_description">
                <div class="tender_infoo">
                    <div class="row">
                        <div class="col-md-4"><p class="tender_des_title">Name of Work</p></div>
                        <div class="col-md-8"><p class="tender_des">: Enlistment of Schedule for ICT Equipment, Accessories and Services ( Server, laptop, projector, printer, scanner Printer, Cyber Security appliance and software )</p></div>
                    </div>
                </div>
                <div class="tender_infoo">
                    <div class="row">
                        <div class="col-md-4"><p class="tender_des_title">Caller District</p></div>
                        <div class="col-md-8"><p class="tender_des">: Dhaka</p></div>
                    </div>
                </div>
                <div class="tender_infoo">
                    <div class="row">
                        <div class="col-md-4"><p class="tender_des_title">Closing date</p></div>
                        <div class="col-md-8"><p class="tender_des">: Oct 14, 2026</p></div>
                    </div>
                </div>
            </div>
            <div class="share_button_div">
                <a href="https://www.alltender.com/user/tender_detail/1647357">Tender Details</a>
            </div>
        </div>
    </div>
    <div class="col-md-12">
        <div class="tender_info">
            <div class="tender_id">
                <p>Tender ID 1645989</p>
            </div>
            <div class="tender_description">
                <div class="tender_infoo">
                    <div class="row">
                        <div class="col-md-4"><p class="tender_des_title">Name of Work</p></div>
                        <div class="col-md-8"><p class="tender_des">: REQUEST FOR PROPOSAL (RFP) for Contracting a Firm for AI Use Case Design, Testing and Deployment for BRAC.</p></div>
                    </div>
                </div>
                <div class="tender_infoo">
                    <div class="row">
                        <div class="col-md-4"><p class="tender_des_title">Closing date</p></div>
                        <div class="col-md-8"><p class="tender_des">: Oct 13, 2026</p></div>
                    </div>
                </div>
            </div>
        </div>
    </div>
</div>
"""


def test_parse_subcategory_page():
    items, total, _ = parse_list_page(SAMPLE_SUBCAT_HTML)
    assert len(items) == 2
    assert items[0].tender_id == "1647357"
    assert "ICT Equipment" in items[0].fields["Name of Work"]
    assert items[0].fields["Closing date"] == "Oct 14, 2026"
    assert items[0].fields["Caller District"] == "Dhaka"
    assert items[0].link == "https://www.alltender.com/user/tender_detail/1647357"

    assert items[1].tender_id == "1645989"
    assert "AI Use Case Design" in items[1].fields["Name of Work"]


def test_it_organization_name_and_sector():
    item1 = AlltenderItem(
        tender_id="1647357",
        fields={
            "Name of Work": "Enlistment of Schedule for ICT Equipment",
            "Caller District": "Dhaka",
        }
    )
    assert organization_name(item1) == "Procuring Entity (Dhaka)"
    assert sector(item1, default="IT") == "IT"

    item2 = AlltenderItem(
        tender_id="1645989",
        fields={
            "Name of Work": "REQUEST FOR PROPOSAL (RFP) for Contracting a Firm for AI Use Case Design for BRAC.",
        }
    )
    assert organization_name(item2) == "BRAC"
    assert sector(item2, default="IT") == "IT"


def test_it_relevance_classification():
    classifier = RelevanceClassifier()

    # Software dev
    rel1 = classifier.classify("Development and Deployment of Souvenir Sales Management Software Application")
    assert rel1.is_priority is True
    assert "Software & Web Development" in rel1.categories

    # Cyber security & IT Infra
    rel2 = classifier.classify("National Cloud Security Assessment and SOC Vulnerability Assessment Penetration Testing VAPT")
    assert rel2.is_priority is True
    assert "Cyber Security & Information Protection" in rel2.categories

    # IT Equipment & Networking
    rel3 = classifier.classify("Open Tender Notice for IT Equipment Procurement, Server and Managed Network Services")
    assert rel3.is_priority is True
    assert "IT Infrastructure & Networking" in rel3.categories

    # IT Consulting & Digital Transformation
    rel4 = classifier.classify("Consultancy Services for ICT Digital Transformation and Enterprise Architecture")
    assert rel4.is_priority is True
    assert "IT Consulting & Digital Transformation" in rel4.categories


@pytest.mark.asyncio
async def test_live_alltender_subcategory_64_fetch():
    # Test live fetch of subcategory 64 (ICT Support/Consultancy)
    status, error, items = await alltender.fetch_subcategory_tenders(subcategory_id=64, max_pages=1)
    assert status == 200
    assert error is None
    assert len(items) > 0
    assert any("164" in it.tender_id for it in items)
