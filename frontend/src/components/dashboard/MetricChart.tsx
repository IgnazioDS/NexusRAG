"use client";

import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

interface DataPoint {
  label: string;
  value: number;
}

interface MetricChartProps {
  data: DataPoint[];
  height?: number;
  /** stroke + gradient stop colour. Default uses brand. */
  color?: string;
  yAxisFormatter?: (value: number) => string;
}

/**
 * MetricChart — recharts-based area chart calibrated for the dashboard
 * aesthetic. Tight axes, neutral grid, brand-tinted gradient fill.
 */
export function MetricChart({
  data,
  height = 220,
  color = "hsl(238 84% 67%)",
  yAxisFormatter,
}: MetricChartProps) {
  return (
    <div className="w-full" style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
          <defs>
            <linearGradient id="metric-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={color} stopOpacity={0.32} />
              <stop offset="100%" stopColor={color} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid
            strokeDasharray="2 4"
            stroke="hsl(240 6% 14%)"
            vertical={false}
          />
          <XAxis
            dataKey="label"
            stroke="hsl(240 5% 32%)"
            fontSize={10}
            tickLine={false}
            axisLine={false}
          />
          <YAxis
            stroke="hsl(240 5% 32%)"
            fontSize={10}
            tickLine={false}
            axisLine={false}
            tickFormatter={yAxisFormatter}
            width={40}
          />
          <Tooltip
            cursor={{ stroke: "hsl(240 6% 22%)", strokeWidth: 1 }}
            content={({ active, payload, label }) => {
              if (!active || !payload?.length) return null;
              const value = payload[0].value as number;
              return (
                <div className="rounded-md border border-border-strong bg-surface-2 px-2.5 py-1.5 shadow-popover">
                  <p className="text-2xs uppercase tracking-wider text-foreground-faint">
                    {label}
                  </p>
                  <p className="text-sm font-semibold tabular-nums text-foreground">
                    {yAxisFormatter ? yAxisFormatter(value) : value}
                  </p>
                </div>
              );
            }}
          />
          <Area
            type="monotone"
            dataKey="value"
            stroke={color}
            strokeWidth={1.5}
            fill="url(#metric-fill)"
            isAnimationActive
            animationDuration={400}
          />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}
