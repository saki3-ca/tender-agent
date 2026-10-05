import json
import re
import urllib.parse
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = BASE_DIR / "config"

RAW_DATA = """1	BRAC	https://tender.brac.net/tender/liveTenderTemplate
2	Palli Karma-Sahayak Foundation (PKSF)	https://pksf.org.bd/procurement/
3	icddr,b	https://www.icddrb.org/tender-notices
4	ActionAid Bangladesh	https://actionaidbd.org/category/tender-notice
5	UCEP Bangladesh	https://tender.ucepbd.org/
6	Caritas Bangladesh	https://caritasbd.org/notice/tender/
7	Eco-Social Development Organization (ESDO)	https://esdo.net.bd/notice/
8	TMSS (Thengamara Mohila Sabuj Sangha)	https://tmss-bd.org/category/tender-notice/
9	Bangladesh Red Crescent Society (BDRCS)	https://bdrcs.org/tenders/
10	Friendship NGO	https://friendship.ngo/procurement/
11	Sajida Foundation	https://sajidafoundation.org/tenders-notices/
12	BURO Bangladesh	https://burobd.org/tender-notice/
13	Jagorani Chakra Foundation (JCF)	https://jcf.org.bd/tender-notice/
14	Dhaka Ahsania Mission (DAM)	https://ahsaniamission.org.bd/tender/
15	Centre for the Rehabilitation of the Paralysed (CRP)	https://crp-bangladesh.org/tender-notices/
16	RDRS Bangladesh	https://rdrsbangladesh.org/tender-notices/
17	Save the Children Bangladesh	https://bangladesh.savethechildren.net/tenders
18	Oxfam in Bangladesh	https://bangladesh.oxfam.org/latest/tenders
19	CARE Bangladesh	https://carebangladesh.org/procurement/
20	Plan International Bangladesh	https://plan-international.org/bangladesh/tenders-and-procurement/
21	World Vision Bangladesh	https://www.wvi.org/bangladesh/procurement-and-tenders
22	Swisscontact Bangladesh	https://www.swisscontact.org/en/countries/bangladesh/procurement
23	Solidarites International Bangladesh	https://www.solidarites.org/en/calls-for-tenders/
24	Action Against Hunger (ACF) Bangladesh	https://www.actionagainsthunger.org/procurement/
25	Christian Commission for Development in Bangladesh (CCDB)	https://ccdb-bd.org/tender-procurement/
26	Muslim Aid Bangladesh	https://muslimaid.org.bd/tenders/
27	Islamic Relief Bangladesh	https://islamicrelief.org.bd/tenders/
28	Voluntary Service Overseas (VSO) Bangladesh	https://www.vsointernational.org/about/procurement
29	Practical Action Bangladesh	https://practicalaction.org/procurement/
30	Concern Worldwide Bangladesh	https://www.concern.net/tenders
31	Helvetas Bangladesh	https://www.helvetas.org/en/bangladesh/who-we-are/jobs-tenders
32	Handicap International (Humanity & Inclusion) Bangladesh	https://www.hi.org/en/calls-for-tenders
33	Sightsavers Bangladesh	https://www.sightsavers.org/procurement/
34	Danish Refugee Council (DRC) Bangladesh	https://drc.ngo/tenders/
35	Norwegian Refugee Council (NRC) Bangladesh	https://www.nrc.no/tenders/
36	International Rescue Committee (IRC) Bangladesh	https://www.rescue.org/procurement
37	Relief International Bangladesh	https://www.ri.org/procurement/
38	Medecins du Monde (MdM) Bangladesh	https://www.medecinsdumonde.org/en/calls-for-tenders/
39	Malteser International Bangladesh	https://www.malteser-international.org/en/procurement.html
40	Room to Read Bangladesh	https://www.roomtoread.org/procurement/
41	Marie Stopes Bangladesh	https://mariestopes-bd.org/tender-notice/
42	EngenderHealth Bangladesh	https://www.engenderhealth.org/procurement
43	Pathfinder International Bangladesh	https://www.pathfinder.org/requests-for-proposals/
44	Nutrition International Bangladesh	https://www.nutritionintl.org/work-with-us/procurement-rfps/
45	Jhpiego Bangladesh	https://www.jhpiego.org/procurement-portal/
46	Chemonics International (Bangladesh Operations)	https://chemonics.com/procurement-opportunities/
47	DAI (Development Alternatives Inc. - Bangladesh)	https://www.dai.com/work-with-us/procurement-opportunities
48	RTI International Bangladesh	https://www.rti.org/procurement-opportunities
49	FHI 360 Bangladesh	https://www.fhi360.org/working-with-fhi-360/procurement/
50	Winrock International Bangladesh	https://winrock.org/procurement-opportunities/
51	iDE (International Development Enterprises) Bangladesh	https://www.ideglobal.org/tenders
52	Land O'Lakes Venture37 Bangladesh	https://www.venture37.org/procurement
53	ACDI/VOCA Bangladesh	https://www.acdivoca.org/work-with-us/procurement/
54	Habitat for Humanity Bangladesh	https://www.habitatbangladesh.org/procurement-tender/
55	WaterAid Bangladesh	https://www.wateraid.org/bd/procurement-and-tender-notices
56	ORBIS International Bangladesh	https://www.orbis.org/en/procurement-opportunities
57	Fred Hollows Foundation Bangladesh	https://www.hollows.org/procurement
58	Lepra Bangladesh	https://www.lepra.org.uk/work-with-us/tenders
59	HEKS/EPER Bangladesh	https://en.heks.ch/tenders
60	Stromme Foundation Bangladesh	https://strommefoundation.org/tenders
61	Terre des Hommes (TdH) Foundation Bangladesh	https://www.tdh.org/en/calls-for-tenders
62	Educo Bangladesh	https://educo.org/bangladesh-tender/
63	SOS Children's Villages Bangladesh	https://www.sos-childrensvillages.org/procurement
64	Good Neighbors Bangladesh	https://gnbangladesh.org/tender/
65	ChildFund Bangladesh	https://www.childfund.org/procurement/
66	World Fish Bangladesh	https://worldfishcenter.org/procurement-tenders
67	CIMMYT Bangladesh	https://www.cimmyt.org/about-cimmyt/procurement/
68	IRRI (International Rice Research Institute) Bangladesh	https://www.irri.org/procurement
69	Association for Land Reform and Development (ALRD)	https://www.alrd.org/notice/
70	Ain o Salish Kendra (ASK)	https://www.askbd.org/ask/notices/
71	Bangladesh Legal Aid and Services Trust (BLAST)	https://www.blast.org.bd/notices/
72	Transparency International Bangladesh (TIB)	https://www.ti-bangladesh.org/procurement
73	Centre for Policy Dialogue (CPD)	https://cpd.org.bd/procurement/
74	Bangladesh Rural Advanced Committee - Ultra Poor Graduation (BRAC UPG)	https://tender.brac.net/
75	COAST Foundation	https://coastbd.net/tenders/
76	CODEC (Community Development Centre)	https://codec.org.bd/notice-board/
77	WAVE Foundation	https://wavefoundationbd.org/tender-notice/
78	Padakhep Manabik Unnayan Kendra	https://padakhep.org/tender-notices/
79	SKS Foundation	https://sks-bd.org/tender-notice/
80	Ghashful	https://ghashful-bd.org/tenders/
81	Shakti Foundation for Disadvantaged Women	https://shakti.org.bd/tenders
82	Dushtha Shasthya Kendra (DSK)	https://dskbangladesh.org/tender-notices/
83	Manabik Shahajya Sangstha (MSS)	https://mssbd.org/tender/
84	POPI (People's Oriented Program Implementation)	https://popibd.org/procurement/
85	RIC (Resource Integration Centre)	https://ric-bd.org/notice-board/
86	YPSA (Young Power in Social Action)	https://ypsa.org/tender-notice/
87	HEED Bangladesh	https://heed-bangladesh.com/notice/
88	Ashrai	https://ashrai.org/notice/
89	Gram Bikash Kendra (GBK)	https://gbk-bd.org/notice-tender/
90	IDEA (Institute of Development Affairs)	https://ideabd.org/notice/
91	CNRS (Center for Natural Resource Studies)	https://cnrs.org.bd/tenders-and-vacancies/
92	BCAS (Bangladesh Centre for Advanced Studies)	https://bcas.net/tenders/
93	CDD (Centre for Disability in Development)	https://cdd.org.bd/procurement-notice/
94	Prodipan	https://prodipan-bd.org/tender-notice/
95	Uttaran	https://uttaran.net/tender-notice/
96	Banchte Shekha	https://banckteshekha.org/notice/
97	VARD (Voluntary Association for Rural Development)	https://vardbd.org/procurement/
98	JAAGO Foundation	https://jaago.com.bd/request-for-proposals"""

def clean_org_id(name, num):
    # Extract clean short slug
    slug = re.sub(r'[^a-zA-Z0-9]+', '_', name.lower()).strip('_')
    # Truncate
    short_slug = '_'.join(slug.split('_')[:3])
    return f"ngo_{int(num):02d}_{short_slug}"

def main():
    lines = [l.strip() for l in RAW_DATA.strip().split("\n") if l.strip()]
    
    # Load existing
    with open(CONFIG_DIR / "organizations.json", "r", encoding="utf-8") as f:
        existing_orgs = json.load(f)
    
    with open(CONFIG_DIR / "sources.json", "r", encoding="utf-8") as f:
        existing_sources = json.load(f)

    # Filter out previous non-bank NGO items to ensure clean canonical list
    base_orgs = [o for o in existing_orgs if not o["organization_id"].startswith("ngo_")]
    base_sources = [s for s in existing_sources if not s["id"].startswith("src_ngo_")]

    new_orgs = []
    new_sources = []

    for line in lines:
        parts = line.split("\t")
        if len(parts) < 3:
            # try splitting by multiple spaces
            parts = re.split(r'\s{2,}|\t', line)
        if len(parts) >= 3:
            num = parts[0].strip()
            name = parts[1].strip()
            url = parts[2].strip()
        elif len(parts) == 2:
            num_match = re.match(r'^(\d+)\s+(.*)$', parts[0].strip())
            if num_match:
                num = num_match.group(1)
                name = num_match.group(2)
                url = parts[1].strip()
            else:
                continue
        else:
            continue

        org_id = clean_org_id(name, num)
        source_id = f"src_{org_id}"

        # Extract domain
        parsed = urllib.parse.urlparse(url)
        domain = parsed.netloc

        # Determine org type
        is_ingo = any(k in name.lower() for k in [
            "international", "oxfam", "care", "save the children", "world vision",
            "swisscontact", "solidarites", "action against hunger", "muslim aid", "islamic relief",
            "vso", "practical action", "concern", "helvetas", "handicap", "sightsavers",
            "drc", "danish", "norwegian", "nrc", "rescue", "relief international", "medecins",
            "malteser", "room to read", "marie stopes", "engenderhealth", "pathfinder",
            "nutrition international", "jhpiego", "chemonics", "dai", "rti", "fhi 360",
            "winrock", "ide", "land o'lakes", "acdi", "habitat", "wateraid", "orbis", "fred hollows",
            "lepra", "heks", "stromme", "terre des hommes", "educo", "sos children", "good neighbors",
            "childfund", "world fish", "cimmyt", "irri"
        ])
        org_type = "INGO" if is_ingo else "NGO"
        if "pksf" in name.lower():
            org_type = "DEVELOPMENT_PARTNER"

        # Generate aliases
        aliases = [name]
        # Acronym inside parentheses
        paren_match = re.search(r'\((.*?)\)', name)
        if paren_match:
            aliases.append(paren_match.group(1).strip())
        short_name = re.sub(r'\(.*?\)', '', name).strip()
        if short_name != name:
            aliases.append(short_name)

        org_entry = {
            "organization_id": org_id,
            "canonical_name": name,
            "aliases": list(set(aliases)),
            "organization_type": org_type,
            "sector": "ngos",
            "official_domain": domain,
            "procurement_url": url,
            "tender_url": url,
            "notice_url": url,
            "is_ifrs9_target": False,
            "source_status": "OK",
            "last_verified": "2026-10-05",
            "last_checked": None,
            "notes": f"Bangladesh NGO/INGO procurement source #{num}"
        }
        new_orgs.append(org_entry)

        source_entry = {
            "id": source_id,
            "url": url,
            "organization_id": org_id,
            "tier": 2 if int(num) > 20 else 1,
            "requires_js": False,
            "verify_ssl": True,
            "rate_limit_seconds": 3,
            "enabled": True
        }
        new_sources.append(source_entry)

    final_orgs = base_orgs + new_orgs
    final_sources = base_sources + new_sources

    with open(CONFIG_DIR / "organizations.json", "w", encoding="utf-8") as f:
        json.dump(final_orgs, f, indent=2, ensure_ascii=False)

    with open(CONFIG_DIR / "sources.json", "w", encoding="utf-8") as f:
        json.dump(final_sources, f, indent=2, ensure_ascii=False)

    print(f"Successfully processed {len(new_orgs)} NGO organizations and {len(new_sources)} procurement sources!")
    print(f"Total organizations in config: {len(final_orgs)}")
    print(f"Total sources in config: {len(final_sources)}")

if __name__ == "__main__":
    main()
