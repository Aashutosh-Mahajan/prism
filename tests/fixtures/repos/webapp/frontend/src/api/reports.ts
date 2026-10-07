export type KpiKind = 'money' | 'count' | 'score';

export interface Kpi {
  value: number | null;
  previous: number | null;
  kind: KpiKind;
}

export interface Summary {
  window: { range: string };
  kpis: Record<string, Kpi>;
}
