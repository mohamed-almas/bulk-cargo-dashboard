import { createClient } from '@supabase/supabase-js'

const SUPABASE_URL = 'https://lsyombbeyjokpndczvdj.supabase.co'
const SUPABASE_ANON_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImxzeW9tYmJleWpva3BuZGN6dmRqIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzU4MjkyOTYsImV4cCI6MjA5MTQwNTI5Nn0.lxhMKxXZVLPJX44Hom_X8Ysoz5vclm8IxDkRbQe_oHE'

export const supabase = createClient(SUPABASE_URL, SUPABASE_ANON_KEY)
