import { Kpi } from '../../api/reports';

export const describeDelta = (kpi: Kpi): string => {
  if (kpi.previous === null || kpi.value === null || kpi.previous === 0) return '';
  const pct = ((kpi.value - kpi.previous) / kpi.previous) * 100;
  return `${pct >= 0 ? '+' : ''}${pct.toFixed(1)}% vs previous period`;
};

export function KpiGrid({ kpis }: { kpis: Record<string, Kpi> }) {
  return (
    <div className="kpi-grid">
      {Object.entries(kpis).map(([name, kpi]) => (
        <div key={name}>
          <span>{name}</span>
          <strong>{kpi.value ?? '-'}</strong>
          <small>{describeDelta(kpi)}</small>
        </div>
      ))}
    </div>
  );
}
