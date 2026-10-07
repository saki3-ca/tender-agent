-- IT Services: tenders of IT organizations (government ICT bodies, IT companies) use sector 'IT'.
-- (Organizations are configured in config/organizations.json; the legacy organizations table is not used.)
ALTER TABLE tenders DROP CONSTRAINT IF EXISTS tenders_sector_check;
ALTER TABLE tenders ADD CONSTRAINT tenders_sector_check CHECK (sector IN ('BANK', 'NGO', 'IT'));

ALTER TABLE source_status DROP CONSTRAINT IF EXISTS source_status_sector_check;
ALTER TABLE source_status ADD CONSTRAINT source_status_sector_check CHECK (sector IN ('BANK', 'NGO', 'IT'));
