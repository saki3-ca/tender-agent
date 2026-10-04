-- ============================================================================
-- ACNABIN Tender & Opportunity Intelligence Agent — Seed Data
-- ============================================================================

-- 1. Default Allow-listed App Users
INSERT INTO app_users (email, full_name, role, is_active)
VALUES 
    ('admin@acnabin.com', 'ACNABIN Tender Administrator', 'admin', true),
    ('partner.audit@acnabin.com', 'Audit Partner', 'reviewer', true),
    ('consulting@acnabin.com', 'Advisory Services Team', 'reviewer', true)
ON CONFLICT (email) DO NOTHING;

-- 2. Seed 30 Target Banks (Pipeline A)
INSERT INTO organizations (
    organization_id, canonical_name, aliases, organization_type, sector,
    official_domain, is_ifrs9_target, source_status, last_verified, notes
)
VALUES 
    ('bank_01_agrani', 'Agrani Bank PLC', '["Agrani Bank", "ABL", "অগ্রণী ব্যাংক"]'::jsonb, 'STATE_OWNED_COMMERCIAL_BANK', 'banking', 'agranibank.org', true, 'OK', '2026-10-01', 'State-owned commercial bank'),
    ('bank_02_janata', 'Janata Bank PLC', '["Janata Bank", "JBL", "জনতা ব্যাংক"]'::jsonb, 'STATE_OWNED_COMMERCIAL_BANK', 'banking', 'jb.com.bd', true, 'OK', '2026-10-01', 'State-owned commercial bank'),
    ('bank_03_rupali', 'Rupali Bank PLC', '["Rupali Bank", "RBL", "রূপালী ব্যাংক"]'::jsonb, 'STATE_OWNED_COMMERCIAL_BANK', 'banking', 'rupalibank.com.bd', true, 'OK', '2026-10-01', 'State-owned commercial bank'),
    ('bank_04_mercantile', 'Mercantile Bank PLC', '["Mercantile Bank", "MBL", "মার্কেন্টাইল ব্যাংক"]'::jsonb, 'PRIVATE_COMMERCIAL_BANK', 'banking', 'mblbd.com', true, 'OK', '2026-10-01', 'Private commercial bank'),
    ('bank_05_midland', 'Midland Bank PLC', '["Midland Bank", "MDB", "মিডল্যান্ড ব্যাংক"]'::jsonb, 'PRIVATE_COMMERCIAL_BANK', 'banking', 'midlandbankbd.net', true, 'OK', '2026-10-01', 'Private commercial bank'),
    ('bank_06_citizens', 'Citizens Bank PLC', '["Citizens Bank", "CZB", "সিটিজেনস ব্যাংক"]'::jsonb, 'PRIVATE_COMMERCIAL_BANK', 'banking', 'citizensbankbd.com', true, 'OK', '2026-10-01', 'Private commercial bank'),
    ('bank_07_sonali', 'Sonali Bank PLC', '["Sonali Bank", "SBL", "সোনালী ব্যাংক"]'::jsonb, 'STATE_OWNED_COMMERCIAL_BANK', 'banking', 'sonalibank.com.bd', true, 'OK', '2026-10-01', 'Largest state-owned bank'),
    ('bank_08_basic', 'BASIC Bank PLC', '["BASIC Bank", "বেসিক ব্যাংক"]'::jsonb, 'STATE_OWNED_COMMERCIAL_BANK', 'banking', 'basicbank.com.bd', true, 'OK', '2026-10-01', 'State-owned commercial bank'),
    ('bank_09_bdbl', 'Bangladesh Development Bank PLC', '["BDBL", "বাংলাদেশ ডেভেলপমেন্ট ব্যাংক"]'::jsonb, 'STATE_OWNED_DEVELOPMENT_BANK', 'banking', 'bdbl.com.bd', true, 'OK', '2026-10-01', 'State-owned development bank'),
    ('bank_10_sammilito_islami', 'Sammilito Islami Bank PLC', '["Sammilito Islami Bank", "Padma Bank", "The Farmers Bank", "সম্মিলিত ইসলামী ব্যাংক"]'::jsonb, 'ISLAMIC_COMMERCIAL_BANK', 'banking', 'sammilitoislamibank.com.bd', true, 'OK', '2026-10-01', 'Merged bank; includes predecessor aliases'),
    ('bank_11_krishi', 'Bangladesh Krishi Bank', '["BKB", "Krishi Bank", "বাংলাদেশ কৃষি ব্যাংক"]'::jsonb, 'SPECIALIZED_BANK', 'banking', 'krishibank.org.bd', true, 'OK', '2026-10-01', 'Agricultural specialized bank'),
    ('bank_12_rakub', 'Rajshahi Krishi Unnayan Bank', '["RAKUB", "রাজশাহী কৃষি উন্নয়ন ব্যাংক"]'::jsonb, 'SPECIALIZED_BANK', 'banking', 'rakub.org.bd', true, 'OK', '2026-10-01', 'Regional agricultural specialized bank'),
    ('bank_13_city', 'City Bank PLC', '["City Bank", "CBL", "The City Bank", "সিটি ব্যাংক"]'::jsonb, 'PRIVATE_COMMERCIAL_BANK', 'banking', 'thecitybank.com', true, 'OK', '2026-10-01', 'Private commercial bank'),
    ('bank_14_ific', 'IFIC Bank PLC', '["IFIC Bank", "IFIC", "আইএফআইসি ব্যাংক"]'::jsonb, 'PRIVATE_COMMERCIAL_BANK', 'banking', 'ificbank.com.bd', true, 'OK', '2026-10-01', 'Private commercial bank'),
    ('bank_15_pubali', 'Pubali Bank PLC', '["Pubali Bank", "PBL", "পুবালী ব্যাংক"]'::jsonb, 'PRIVATE_COMMERCIAL_BANK', 'banking', 'pubalibangla.com', true, 'OK', '2026-10-01', 'Private commercial bank'),
    ('bank_16_dhaka', 'Dhaka Bank PLC', '["Dhaka Bank", "DBL", "ঢাকা ব্যাংক"]'::jsonb, 'PRIVATE_COMMERCIAL_BANK', 'banking', 'dhakabank.com.bd', true, 'OK', '2026-10-01', 'Private commercial bank'),
    ('bank_17_one', 'ONE Bank PLC', '["ONE Bank", "OBL", "ওয়ান ব্যাংক"]'::jsonb, 'PRIVATE_COMMERCIAL_BANK', 'banking', 'onebank.com.bd', true, 'OK', '2026-10-01', 'Private commercial bank'),
    ('bank_18_mtb', 'Mutual Trust Bank PLC', '["MTB", "Mutual Trust Bank", "মিউচুয়াল ট্রাস্ট ব্যাংক"]'::jsonb, 'PRIVATE_COMMERCIAL_BANK', 'banking', 'mutualtrustbank.com', true, 'OK', '2026-10-01', 'Private commercial bank'),
    ('bank_19_premier', 'The Premier Bank PLC', '["Premier Bank", "প্রিমিয়ার ব্যাংক"]'::jsonb, 'PRIVATE_COMMERCIAL_BANK', 'banking', 'premierbankltd.com', true, 'OK', '2026-10-01', 'Private commercial bank'),
    ('bank_20_trust', 'Trust Bank PLC', '["Trust Bank", "TBL", "ট্রাস্ট ব্যাংক"]'::jsonb, 'PRIVATE_COMMERCIAL_BANK', 'banking', 'trustbank.com.bd', true, 'OK', '2026-10-01', 'Private commercial bank'),
    ('bank_21_meghna', 'Meghna Bank PLC', '["Meghna Bank", "MGBL", "মেঘনা ব্যাংক"]'::jsonb, 'PRIVATE_COMMERCIAL_BANK', 'banking', 'meghnabank.com.bd', true, 'OK', '2026-10-01', 'Private commercial bank'),
    ('bank_22_modhumoti', 'Modhumoti Bank PLC', '["Modhumoti Bank", "MMBL", "মধুমতি ব্যাংক"]'::jsonb, 'PRIVATE_COMMERCIAL_BANK', 'banking', 'modhumotibank.ltd', true, 'OK', '2026-10-01', 'Private commercial bank'),
    ('bank_23_shimanto', 'Shimanto Bank PLC', '["Shimanto Bank", "SHBL", "সীমান্ত ব্যাংক"]'::jsonb, 'PRIVATE_COMMERCIAL_BANK', 'banking', 'shimantobank.com', true, 'OK', '2026-10-01', 'Private commercial bank'),
    ('bank_24_community', 'Community Bank Bangladesh PLC', '["Community Bank", "CBBL", "কমিউনিটি ব্যাংক"]'::jsonb, 'PRIVATE_COMMERCIAL_BANK', 'banking', 'communitybankbd.com', true, 'OK', '2026-10-01', 'Private commercial bank'),
    ('bank_25_bengal', 'Bengal Commercial Bank PLC', '["Bengal Commercial Bank", "BGCB", "বেঙ্গল কমার্শিয়াল ব্যাংক"]'::jsonb, 'PRIVATE_COMMERCIAL_BANK', 'banking', 'bgcb.com.bd', true, 'OK', '2026-10-01', 'Private commercial bank'),
    ('bank_26_islami_bank', 'Islami Bank Bangladesh PLC', '["IBBL", "Islami Bank", "ইসলামী ব্যাংক"]'::jsonb, 'ISLAMIC_COMMERCIAL_BANK', 'banking', 'islamibankbd.com', true, 'OK', '2026-10-01', 'Largest Islamic commercial bank'),
    ('bank_27_icb_islamic', 'ICB Islamic Bank PLC', '["ICB Islamic Bank", "আইসিবি ইসলামিক ব্যাংক"]'::jsonb, 'ISLAMIC_COMMERCIAL_BANK', 'banking', 'icbislamic-bank.com', true, 'OK', '2026-10-01', 'Islamic commercial bank'),
    ('bank_28_al_arafah', 'Al-Arafah Islami Bank PLC', '["AIBL", "Al-Arafah Islami Bank", "আল-আরাফাহ ইসলামী ব্যাংক"]'::jsonb, 'ISLAMIC_COMMERCIAL_BANK', 'banking', 'aibl.com.bd', true, 'OK', '2026-10-01', 'Islamic commercial bank'),
    ('bank_29_combank_ceylon', 'Commercial Bank of Ceylon PLC – Bangladesh', '["Commercial Bank of Ceylon", "CBC Bangladesh", "ComBank"]'::jsonb, 'FOREIGN_COMMERCIAL_BANK', 'banking', 'combankbd.com', true, 'OK', '2026-10-01', 'Foreign commercial bank in Bangladesh'),
    ('bank_30_woori', 'Woori Bank – Bangladesh', '["Woori Bank", "উরি ব্যাংক"]'::jsonb, 'FOREIGN_COMMERCIAL_BANK', 'banking', 'wooribank.com/bd', true, 'OK', '2026-10-01', 'Foreign commercial bank in Bangladesh')
ON CONFLICT (organization_id) DO UPDATE 
SET canonical_name = EXCLUDED.canonical_name,
    aliases = EXCLUDED.aliases,
    is_ifrs9_target = EXCLUDED.is_ifrs9_target,
    official_domain = EXCLUDED.official_domain;
