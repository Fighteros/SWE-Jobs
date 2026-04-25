export interface Job {
  id: number;
  title: string;
  company: string;
  location: string;
  url: string;
  source: string;
  original_source: string;
  salary_raw: string;
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string;
  job_type: string;
  seniority: string;
  is_remote: boolean;
  country: string;
  tags: string[];
  topics: string[];
  market_salary: string | null;
  posted_at: string | null;
  created_at: string;
}

export interface JobSearchResponse {
  jobs: Job[];
  total: number;
  page: number;
  per_page: number;
  total_pages: number;
}

export interface StatsSummary {
  jobs_today: number;
  jobs_week: number;
  jobs_total: number;
  by_source: { source: string; count: number }[];
  by_topic: { topic: string; count: number }[];
  top_companies: { company: string; count: number }[];
}

export interface SalaryStats {
  currency: string;
  period: string;
  source: string;
  stats: {
    sample_size: number;
    median: number | null;
    p20: number | null;
    p75: number | null;
    p90: number | null;
  } | null;
  buckets: { label: string; count: number }[];
  filters: {
    role: string | null;
    seniority: string | null;
    yoe_from: number | null;
    yoe_to: number | null;
  };
  matched: boolean;
}

export interface TrendItem {
  skill: string;
  count: number;
  previous_count: number;
  change_percent: number;
}

export interface TrendsResponse {
  period: string;
  trends: TrendItem[];
}
