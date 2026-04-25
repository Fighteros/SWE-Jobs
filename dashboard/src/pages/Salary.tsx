import { useState, useEffect } from 'react';
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts';
import { api } from '../api';
import type { SalaryStats } from '../types';

const ROLE_OPTIONS = [
  '', 'backend', 'frontend', 'fullstack', 'mobile', 'devops', 'qa',
  'security', 'data engineer', 'data scientist', 'data analytics',
  'embedded', 'ui ux', 'product manager', 'engineering manager',
];

const SENIORITY_OPTIONS = ['', 'intern', 'junior', 'mid', 'senior', 'lead', 'executive'];

const fmtEgp = (n: number | null | undefined): string =>
  n == null ? '—' : `EGP ${n.toLocaleString()}/mo`;

export default function Salary() {
  const [stats, setStats] = useState<SalaryStats | null>(null);
  const [loading, setLoading] = useState(false);
  const [role, setRole] = useState('backend');
  const [seniority, setSeniority] = useState('');
  const [yoeFrom, setYoeFrom] = useState('');
  const [yoeTo, setYoeTo] = useState('');

  const fetchSalary = () => {
    setLoading(true);
    const params: Record<string, string> = {};
    if (role) params.role = role;
    if (seniority) params.seniority = seniority;
    if (yoeFrom) params.yoe_from = yoeFrom;
    if (yoeTo) params.yoe_to = yoeTo;
    api.getSalaryStats(params)
      .then(setStats)
      .catch(console.error)
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    fetchSalary();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div>
      <h1 className="text-2xl font-bold text-gray-900 mb-1">Egyptian Tech Salaries</h1>
      <p className="text-xs text-gray-500 mb-6">
        Source: <a href="https://egytech.fyi" target="_blank" rel="noopener noreferrer" className="underline">egytech.fyi</a> — April 2024 survey, ~2,100 responses. All values are monthly EGP, excluding relocated and remote-abroad participants.
      </p>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-3 mb-6">
        <div>
          <label className="block text-xs text-gray-600 mb-1">Role</label>
          <select
            value={role}
            onChange={(e) => setRole(e.target.value)}
            className="border border-gray-300 rounded px-3 py-1.5 text-sm w-full"
          >
            {ROLE_OPTIONS.map((r) => (
              <option key={r} value={r}>{r || 'Any'}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs text-gray-600 mb-1">Seniority</label>
          <select
            value={seniority}
            onChange={(e) => setSeniority(e.target.value)}
            className="border border-gray-300 rounded px-3 py-1.5 text-sm w-full"
          >
            {SENIORITY_OPTIONS.map((s) => (
              <option key={s} value={s}>{s || 'Any'}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs text-gray-600 mb-1">YoE from</label>
          <input
            type="number"
            min={0}
            max={20}
            value={yoeFrom}
            onChange={(e) => setYoeFrom(e.target.value)}
            className="border border-gray-300 rounded px-3 py-1.5 text-sm w-full"
          />
        </div>
        <div>
          <label className="block text-xs text-gray-600 mb-1">YoE to (excl.)</label>
          <input
            type="number"
            min={1}
            max={26}
            value={yoeTo}
            onChange={(e) => setYoeTo(e.target.value)}
            className="border border-gray-300 rounded px-3 py-1.5 text-sm w-full"
          />
        </div>
      </div>

      <button
        onClick={fetchSalary}
        className="bg-blue-600 text-white px-4 py-1.5 rounded text-sm hover:bg-blue-700 mb-6"
      >
        Update
      </button>

      {loading && <p className="text-gray-500 py-8">Loading...</p>}

      {!loading && stats && !stats.matched && (
        <div className="bg-yellow-50 border border-yellow-200 rounded p-4 text-sm text-yellow-900">
          No data for this combination. Try a broader filter (e.g. clear seniority or YoE).
        </div>
      )}

      {!loading && stats && stats.matched && stats.stats && (
        <>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-8">
            <div className="bg-white rounded-lg border p-4 text-center">
              <p className="text-2xl font-bold text-gray-700">{stats.stats.sample_size}</p>
              <p className="text-xs text-gray-500">Sample Size</p>
            </div>
            <div className="bg-white rounded-lg border p-4 text-center">
              <p className="text-2xl font-bold text-blue-600">{fmtEgp(stats.stats.median)}</p>
              <p className="text-xs text-gray-500">Median</p>
            </div>
            <div className="bg-white rounded-lg border p-4 text-center">
              <p className="text-lg font-bold text-green-600">
                {fmtEgp(stats.stats.p20)} – {fmtEgp(stats.stats.p75)}
              </p>
              <p className="text-xs text-gray-500">P20 – P75</p>
            </div>
            <div className="bg-white rounded-lg border p-4 text-center">
              <p className="text-2xl font-bold text-orange-600">{fmtEgp(stats.stats.p90)}</p>
              <p className="text-xs text-gray-500">P90</p>
            </div>
          </div>

          {stats.buckets.length > 0 && (
            <div className="bg-white rounded-lg border p-4">
              <h2 className="font-semibold text-gray-900 mb-4">Distribution</h2>
              <ResponsiveContainer width="100%" height={350}>
                <BarChart data={stats.buckets}>
                  <XAxis dataKey="label" />
                  <YAxis />
                  <Tooltip />
                  <Bar dataKey="count" fill="#3b82f6" name="Participants" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </>
      )}
    </div>
  );
}
