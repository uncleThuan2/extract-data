-- Run this in Supabase SQL Editor (https://supabase.com/dashboard → SQL Editor)
-- This enables the pgvector extension needed for vector search

-- 1. Enable pgvector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- That's it! The `vecs` library will auto-create tables when the bot runs.
-- The table `vecs.pdf_documents` will be created automatically.

-- Optional: If you want to give READ access to others via Supabase REST API,
-- you can create a view:

-- CREATE OR REPLACE VIEW public.pdf_search_documents AS
-- SELECT
--     id,
--     metadata->>'text' as text,
--     metadata->>'filename' as filename,
--     (metadata->>'page_number')::int as page_number
-- FROM vecs.pdf_documents;

-- GRANT SELECT ON public.pdf_search_documents TO anon;
