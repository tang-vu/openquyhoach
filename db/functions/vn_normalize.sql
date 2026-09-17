-- Vietnamese-aware search normalization for PostgreSQL.
-- unaccent handles most combining marks but NOT đ/Đ (it is a distinct letter,
-- not d + diacritic), so we translate it first, then unaccent + lowercase.
CREATE OR REPLACE FUNCTION vn_normalize(input text)
RETURNS text
LANGUAGE sql
IMMUTABLE
PARALLEL SAFE
AS $$
  SELECT regexp_replace(lower(unaccent(translate(coalesce(input, ''), 'đĐ', 'dd'))), '\s+', ' ', 'g');
$$;

COMMENT ON FUNCTION vn_normalize(text) IS
  'Case/diacritic-insensitive Vietnamese normalization used by search indexes.';
