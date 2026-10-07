"""IT Services: IT subject detection, IT Priority (ACNABIN and its MoU IT partners), IT sources."""

import pytest

from app.classification.relevance import ItClassifier, RelevanceClassifier
from app.crawler.alltender import AlltenderItem, organization_name, sector

it = ItClassifier()

ACNABIN, CIPHERSHIELD, BRAIN_STATION = "ACNABIN", "CipherShield", "Brain Station 23"


@pytest.mark.parametrize("title,partner,category", [
    ("Information Systems Audit of core banking system", ACNABIN, "IT / IS Audit & Assurance"),
    ("Appointment of firm for SWIFT CSP independent assessment", ACNABIN, "IT / IS Audit & Assurance"),
    ("ISO 27001 certification readiness and gap assessment", ACNABIN, "IT / IS Audit & Assurance"),
    ("Request for Expressions of Interest Consultancy Service for Review and Update of existing ICT based "
     "Monitoring billing software of DPHE", ACNABIN, "IT Advisory & Digital Transformation"),
    ("Consultancy for ICT strategy and digital transformation roadmap", ACNABIN, "IT Advisory & Digital Transformation"),
    ("Vulnerability Assessment and Penetration Testing (VAPT) of IT infrastructure", CIPHERSHIELD, "Cyber Security Services"),
    ("Security Operations Center (SOC) as a service for 3 years", CIPHERSHIELD, "Cyber Security Services"),
    ("Supply a Customized Hostel Management Software with related service for BIAM Foundation", BRAIN_STATION,
     "Software Development & Implementation"),
    ("RFP for Development of Digital Data Collection Application and Impact Monitoring Dashboard", BRAIN_STATION,
     "Software Development & Implementation"),
    ("Development and Implementation of Digital lending Solution", BRAIN_STATION, "Software Development & Implementation"),
    ("REQUEST FOR PROPOSAL (RFP) for Contracting a Firm for AI Use Case Design, Testing and Deployment", BRAIN_STATION,
     "Software Development & Implementation"),
    ("RAB Case Management System (RCMS) Software Maintenance", BRAIN_STATION, "Software Development & Implementation"),
])
def test_it_priority(title, partner, category):
    r = it.classify(title)
    assert r.is_it and r.is_priority
    assert partner in r.partners and category in r.categories


@pytest.mark.parametrize("title", [
    "Open Tender Notice for IT Equipment Procurement 2026",
    "Supply of Desktop Computers and Printers",
    "Procurement of Internet Bandwidth",
    "Supply and installation of network switches and routers",
    "Enlistment for the Procurement of IT Products and Services (Server, laptop, Cyber Security appliance and software)",
    "Procurement of physical services for Web- Based Toll Collection, Operation and Management for Bridge",
])
def test_it_general_but_not_priority(title):
    r = it.classify(title)
    assert r.is_it and not r.is_priority


@pytest.mark.parametrize("title,description", [
    ("Tender Notice - Construction of Solar Operated Water Distribution Network", ""),
    ("Selection of external auditor for the year 2026", ""),
    ("Consultant - Business Development Support Consultancy", ""),
    ("Supply of office furniture", "Details are available on our website www.example.org. Procurement Nature: Goods, non-e-GP"),
])
def test_not_it(title, description):
    assert not it.classify(title, description).is_it


def test_it_source_marks_every_tender_as_it():
    r = it.classify("Supply of office furniture", it_source=True)
    assert r.is_it and not r.is_priority


def test_bank_ngo_priority_is_still_acnabin_services_only():
    rc = RelevanceClassifier()
    assert not rc.classify("Development of a Souvenir Sales Management Software Application").is_priority
    assert not rc.classify("Supply, installation of primary data center network equipment").is_priority
    assert rc.classify("Information Systems Audit of core banking").is_priority


def test_alltender_category_organization_from_caller():
    item = AlltenderItem("1", {"Ministry/Division": "Bank/Insurance/Finance Company", "Department": "Private Bank",
                               "Tender Caller": "Head of Procurement, IFIC Bank PLC, IFIC Tower, 61 Purana Paltan, Dhaka"})
    assert organization_name(item) == "IFIC Bank PLC"
    assert sector(item) == "BANK"
    gov = AlltenderItem("2", {"Ministry/Division": "Ministry of Religious Affairs", "Department": "Islamic Foundation"})
    assert organization_name(gov) == "Islamic Foundation" and sector(gov) is None
