/**
 * ChartRenderer - Renders charts using Plotly.
 */

import React, { useMemo } from 'react';
import type { ChartConfig } from '../../types/message';
import { chartConfigToPlotly, type PlotlyConfig } from '../../types/visualization';

// Lazy load Plotly for better initial load time
const Plot = React.lazy(() => import('react-plotly.js'));

interface ChartRendererProps {
  config: ChartConfig;
  height?: number;
  className?: string;
}

const PLOTLY_CONFIG: PlotlyConfig = {
  responsive: true,
  displayModeBar: true,
  displaylogo: false,
  modeBarButtonsToRemove: ['lasso2d', 'select2d', 'autoScale2d']
};

export function ChartRenderer({
  config,
  height = 300,
  className = ''
}: ChartRendererProps) {
  const { data, layout } = useMemo(() => {
    const plotlyData = chartConfigToPlotly(config);
    return {
      data: plotlyData.data,
      layout: {
        ...plotlyData.layout,
        height,
        paper_bgcolor: 'transparent',
        plot_bgcolor: 'transparent',
        font: {
          family: 'system-ui, -apple-system, sans-serif',
          size: 12,
          color: '#374151'
        }
      }
    };
  }, [config, height]);

  return (
    <div className={`w-full ${className}`}>
      <React.Suspense
        fallback={
          <div className="flex items-center justify-center h-64 bg-gray-50 rounded-lg">
            <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-600" />
          </div>
        }
      >
        <Plot
          data={data as any}
          layout={layout as any}
          config={PLOTLY_CONFIG as any}
          style={{ width: '100%' }}
          useResizeHandler
        />
      </React.Suspense>
    </div>
  );
}

export default ChartRenderer;
